"""
Stage 10e — Management commentary vs this filing's actuals.

Guidance is read from commentary / MD&A in the OCR markdown.
History is read from JSON years that also appear in that markdown.
No comparison → empty report, not a fake "consistent" stamp.
"""
import importlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass, field


_ANNUAL_ACTUAL_RE = re.compile(r"^fy\d{2,4}a?$", re.IGNORECASE)
_REVENUE_KEYS = (
    "revenue", "nii", "net_interest_income", "total_income",
    "net_sales", "operating_revenue", "gmv",
)
_EBITDA_KEYS = ("ebitda", "operating_profit", "ppop")
_CAPEX_KEYS = ("capex", "capital_expenditure", "capital_outlay")

_MD_HEADING_RE = re.compile(
    r"(management\s+discussion|md\s*&\s*a|outlook|guidance|"
    r"director'?s?\s+report|letter\s+to\s+shareholders|"
    r"chairman'?s?\s+(?:message|statement)|business\s+review)",
    re.IGNORECASE,
)

_MARGIN_PHRASES = (
    "margin improvement", "margin expansion", "cost optimisation",
    "cost optimization", "operating efficiency", "better margins",
    "higher margins", "margin expansion",
)
_EXPANSION_PHRASES = (
    "capacity addition", "new plant", "new facility", "greenfield",
    "brownfield", "capex plan", "investment plan", "capacity expansion",
)


@dataclass
class MgmtRealityGap:
    claim: str
    evidence: str
    gap: str  # optimistic / pessimistic / consistent
    confidence: str


@dataclass
class MgmtRealityReport:
    gaps: List[MgmtRealityGap] = field(default_factory=list)
    overall_assessment: str = ""
    narrative_brief: str = ""
    checks_run: List[str] = field(default_factory=list)


class MgmtRealityCrossReferencer:
    @staticmethod
    def analyze(
        management_text: str,
        annual_data: Dict[str, Any],
        sector: str = "",
        llm_client=None,
        ocr_text: str = "",
        historical_data: Optional[Dict[str, Any]] = None,
    ) -> MgmtRealityReport:
        ocr = (ocr_text or "").strip()
        commentary = MgmtRealityCrossReferencer._commentary(
            management_text or "", ocr
        )
        if len(commentary) < 40:
            return MgmtRealityReport()

        payload = dict(historical_data or annual_data or {})
        if ocr:
            payload, _dropped = MgmtRealityCrossReferencer._keep_ocr_values(
                payload, ocr
            )
        else:
            return MgmtRealityReport()

        gaps: List[MgmtRealityGap] = []
        checks: List[str] = []

        MgmtRealityCrossReferencer._check_growth_guidance(
            commentary, payload, gaps, checks
        )
        MgmtRealityCrossReferencer._check_margin_talk(
            commentary, payload, gaps, checks
        )
        MgmtRealityCrossReferencer._check_expansion_talk(
            commentary, payload, gaps, checks
        )

        if not checks:
            return MgmtRealityReport(checks_run=checks)

        report = MgmtRealityReport(gaps=gaps, checks_run=checks)
        optimistic = [g for g in gaps if g.gap == "optimistic"]
        pessimistic = [g for g in gaps if g.gap == "pessimistic"]
        if optimistic:
            report.overall_assessment = (
                f"Management commentary is optimistic versus reported actuals "
                f"on {len(optimistic)} item(s)."
            )
        elif pessimistic:
            report.overall_assessment = (
                f"Management commentary is conservative versus reported actuals "
                f"on {len(pessimistic)} item(s)."
            )
        else:
            report.overall_assessment = (
                "On the items that could be compared, management commentary "
                "is consistent with reported actuals."
            )
        report.narrative_brief = MgmtRealityCrossReferencer._build_narrative(report)
        return report

    @staticmethod
    def _commentary(outlook: str, ocr: str) -> str:
        parts: List[str] = []
        if outlook and len(outlook.strip()) >= 20:
            parts.append(outlook.strip())
        if ocr:
            for match in _MD_HEADING_RE.finditer(ocr):
                window = ocr[match.start(): match.start() + 1600]
                parts.append(window)
                if len(parts) >= 3:
                    break
        return "\n".join(parts).strip()

    @staticmethod
    def _number_in_markdown(value: float, ocr_text: str) -> bool:
        fact = importlib.import_module("pipeline.12b_source_verifier.fact_checker")
        found, _, _ = fact._search_ocr(value, ocr_text)
        return found

    @staticmethod
    def _keep_ocr_values(
        payload: Dict[str, Any], ocr_text: str
    ) -> Tuple[Dict[str, Any], int]:
        kept: Dict[str, Any] = {}
        dropped = 0
        for key, series in (payload or {}).items():
            if not isinstance(series, dict):
                kept[key] = series
                continue
            filtered: Dict[str, Any] = {}
            for year, val in series.items():
                num = MgmtRealityCrossReferencer._safe_float(val)
                if num is None:
                    continue
                if MgmtRealityCrossReferencer._number_in_markdown(num, ocr_text):
                    filtered[str(year)] = val
                else:
                    dropped += 1
            kept[key] = filtered
        return kept, dropped

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            if hasattr(val, "value"):
                val = val.value
            if val in (None, "[N/A]", "", "—", "None", "null"):
                return None
            return float(str(val).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _is_actual_fy(key: str) -> bool:
        return bool(_ANNUAL_ACTUAL_RE.match(str(key).strip()))

    @staticmethod
    def _year_num(key: str) -> int:
        nums = re.findall(r"\d+", str(key or ""))
        if not nums:
            return -1
        num = int(nums[0])
        return num % 100 if num > 100 else num

    @staticmethod
    def _actual_years(series: Dict[str, Any]) -> List[str]:
        years = [
            str(k) for k, v in (series or {}).items()
            if MgmtRealityCrossReferencer._is_actual_fy(str(k))
            and MgmtRealityCrossReferencer._safe_float(v) is not None
        ]
        return sorted(years, key=lambda y: (MgmtRealityCrossReferencer._year_num(y), y))

    @staticmethod
    def _pick(data: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
        for key in keys:
            series = data.get(key)
            if isinstance(series, dict) and MgmtRealityCrossReferencer._actual_years(series):
                return series
        return {}

    @staticmethod
    def _compute_cagr(series: Dict[str, Any]) -> Optional[float]:
        years = MgmtRealityCrossReferencer._actual_years(series)
        if len(years) < 2:
            return None
        first = MgmtRealityCrossReferencer._safe_float(series.get(years[0]))
        last = MgmtRealityCrossReferencer._safe_float(series.get(years[-1]))
        if first in (None, 0, 0.0) or last is None:
            return None
        n = len(years) - 1
        return round(((last / first) ** (1 / n) - 1) * 100, 1)

    @staticmethod
    def _extract_growth_guidance(text: str) -> Optional[float]:
        patterns = [
            r"(\d+\.?\d*)\s*%\s*(?:revenue|topline|sales|nii)\s*growth",
            r"(?:revenue|topline|sales|nii)\s*growth\s*(?:of|at)?\s*(\d+\.?\d*)\s*%",
            r"grow\s*(?:revenue|topline|sales|nii)\s*(?:by|at)?\s*(\d+\.?\d*)\s*%",
            r"(?:guidance|guide|expect|target)\s*(?:of|at)?\s*(\d+\.?\d*)\s*%\s*(?:revenue|growth)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "", re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    @staticmethod
    def _growth_pct(current: Any, previous: Any) -> Optional[float]:
        cur = MgmtRealityCrossReferencer._safe_float(current)
        prev = MgmtRealityCrossReferencer._safe_float(previous)
        if cur is None or prev in (None, 0, 0.0):
            return None
        return round((cur - prev) / abs(prev) * 100, 1)

    @staticmethod
    def _check_growth_guidance(
        commentary: str,
        data: Dict[str, Any],
        gaps: List[MgmtRealityGap],
        checks: List[str],
    ) -> None:
        guided = MgmtRealityCrossReferencer._extract_growth_guidance(commentary)
        revenue = MgmtRealityCrossReferencer._pick(data, _REVENUE_KEYS)
        hist = MgmtRealityCrossReferencer._compute_cagr(revenue)
        if guided is None or hist is None:
            return
        checks.append("growth guidance")
        gap = guided - hist
        if gap > 8:
            gaps.append(MgmtRealityGap(
                claim=f"Management guides ~{guided:g}% top-line growth",
                evidence=f"Reported actual CAGR is {hist}%",
                gap="optimistic",
                confidence="high" if gap > 15 else "medium",
            ))
        elif gap < -5:
            gaps.append(MgmtRealityGap(
                claim=f"Management guides ~{guided:g}% top-line growth",
                evidence=f"Reported actual CAGR is {hist}%",
                gap="pessimistic",
                confidence="medium",
            ))

    @staticmethod
    def _check_margin_talk(
        commentary: str,
        data: Dict[str, Any],
        gaps: List[MgmtRealityGap],
        checks: List[str],
    ) -> None:
        low = commentary.lower()
        if not any(phrase in low for phrase in _MARGIN_PHRASES):
            return
        ebitda = MgmtRealityCrossReferencer._pick(data, _EBITDA_KEYS)
        revenue = MgmtRealityCrossReferencer._pick(data, _REVENUE_KEYS)
        years = [
            y for y in MgmtRealityCrossReferencer._actual_years(revenue)
            if y in MgmtRealityCrossReferencer._actual_years(ebitda)
        ]
        if len(years) < 2:
            return
        margins = []
        for year in years:
            e = MgmtRealityCrossReferencer._safe_float(ebitda.get(year))
            r = MgmtRealityCrossReferencer._safe_float(revenue.get(year))
            if e is None or r in (None, 0, 0.0):
                continue
            margins.append((year, e / r))
        if len(margins) < 2:
            return
        checks.append("margin commentary")
        first, last = margins[0][1], margins[-1][1]
        if last - first < -0.005:
            gaps.append(MgmtRealityGap(
                claim="Management discusses margin improvement",
                evidence=(
                    f"EBITDA margin declined from {first * 100:.1f}% "
                    f"to {last * 100:.1f}% on reported actuals"
                ),
                gap="optimistic",
                confidence="high",
            ))

    @staticmethod
    def _check_expansion_talk(
        commentary: str,
        data: Dict[str, Any],
        gaps: List[MgmtRealityGap],
        checks: List[str],
    ) -> None:
        low = commentary.lower()
        if not any(phrase in low for phrase in _EXPANSION_PHRASES):
            return
        capex = MgmtRealityCrossReferencer._pick(data, _CAPEX_KEYS)
        years = MgmtRealityCrossReferencer._actual_years(capex)
        if len(years) < 2:
            return
        growth = MgmtRealityCrossReferencer._growth_pct(
            capex.get(years[-1]), capex.get(years[-2])
        )
        if growth is None:
            return
        checks.append("expansion commentary")
        if growth < 2:
            gaps.append(MgmtRealityGap(
                claim="Management discusses expansion / capacity addition",
                evidence=f"Reported capex is flat ({growth:+.1f}% YoY)",
                gap="optimistic",
                confidence="medium",
            ))

    @staticmethod
    def _build_narrative(report: MgmtRealityReport) -> str:
        parts = [report.overall_assessment] if report.overall_assessment else []
        for item in report.gaps[:3]:
            parts.append(
                f"{item.claim}. However, {item.evidence} ({item.gap})."
            )
        return " ".join(parts)
