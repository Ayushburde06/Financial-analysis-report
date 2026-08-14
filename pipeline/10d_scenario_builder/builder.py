"""
Stage 10d — Scenarios from this filing.

JSON supplies CMP / target / estimate years.
OCR markdown confirms the target and any estimate figures.
Python computes upside vs CMP.

Does not invent ±15% bull/bear bands, 30/50/20 probabilities,
FY26E, or generic catalysts. No target in the markdown → empty report.
"""
import importlib
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


_RANGE_RE = re.compile(
    r"(?:target|fair\s*value|tp)\s*(?:price)?[^\d]{0,24}"
    r"(?:rs\.?|inr|₹)?\s*"
    r"([\d][\d,]*(?:\.\d+)?)\s*"
    r"(?:[-–—]|to)\s*"
    r"(?:rs\.?|inr|₹)?\s*"
    r"([\d][\d,]*(?:\.\d+)?)",
    re.IGNORECASE,
)

_DOWNSIDE_HINTS = (
    "risk", "headwind", "challenge", "delay", "pressure", "decline",
    "weak", "uncertain", "volatility", "competition",
)
_UPSIDE_HINTS = (
    "guidance", "outlook", "expansion", "capacity", "demand",
    "order", "pipeline", "win", "growth", "ramp",
)


@dataclass
class Scenario:
    label: str
    probability_pct: Optional[int] = None
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None
    revenue_estimate: Optional[float] = None
    pat_estimate: Optional[float] = None
    estimate_year: str = ""
    catalysts: List[str] = field(default_factory=list)
    narrative: str = ""
    # Alias kept so older callers still read the first estimate slot.
    revenue_fy26e: Optional[float] = None
    pat_fy26e: Optional[float] = None


@dataclass
class ScenarioReport:
    scenarios: List[Scenario] = field(default_factory=list)
    expected_value: Optional[float] = None
    narrative_brief: str = ""
    estimate_year: str = ""


class ScenarioBuilder:
    @staticmethod
    def build(
        base_target: Optional[float],
        cmp: Optional[float],
        base_revenue_fy26e: Optional[float] = None,
        base_pat_fy26e: Optional[float] = None,
        base_eps_fy26e: Optional[float] = None,
        ocr_text: str = "",
        management_commentary: str = "",
        sector: str = "",
        llm_client=None,
        revenue_estimates: Optional[Dict[str, Any]] = None,
        pat_estimates: Optional[Dict[str, Any]] = None,
        source_value_factor: float = 1.0,
    ) -> ScenarioReport:
        ocr = (ocr_text or "").strip()
        if not ocr:
            return ScenarioReport()
        if cmp in (None, 0, 0.0):
            return ScenarioReport()

        cmp_f = float(cmp)
        lo, hi = ScenarioBuilder._target_range(ocr, source_value_factor)
        target_f = ScenarioBuilder._safe_float(base_target)
        target_in_md = (
            target_f is not None
            and ScenarioBuilder._number_in_markdown(target_f, ocr, source_value_factor)
        )
        if not target_in_md:
            if lo is None or hi is None:
                return ScenarioReport()
            target_f = round((lo + hi) / 2.0, 2)

        rev_map = dict(revenue_estimates or {})
        pat_map = dict(pat_estimates or {})
        if base_revenue_fy26e is not None and rev_map:
            rev_map.setdefault(sorted(rev_map, key=ScenarioBuilder._year_num)[0], base_revenue_fy26e)
        if base_pat_fy26e is not None and pat_map:
            pat_map.setdefault(sorted(pat_map, key=ScenarioBuilder._year_num)[0], base_pat_fy26e)

        est_year, rev_est, pat_est = ScenarioBuilder._pick_estimate(
            rev_map, pat_map, ocr, source_value_factor
        )
        upside, down = ScenarioBuilder._catalysts_from_source(
            ocr, management_commentary or ""
        )

        scenarios: List[Scenario] = []
        if lo is not None and hi is not None and hi > lo:
            scenarios.append(ScenarioBuilder._case(
                "Bear Case", lo, cmp_f, rev_est, pat_est, est_year, down
            ))
            scenarios.append(ScenarioBuilder._case(
                "Base Case", target_f, cmp_f, rev_est, pat_est, est_year, []
            ))
            scenarios.append(ScenarioBuilder._case(
                "Bull Case", hi, cmp_f, rev_est, pat_est, est_year, upside
            ))
        else:
            scenarios.append(ScenarioBuilder._case(
                "Base Case", target_f, cmp_f, rev_est, pat_est, est_year,
                upside or down,
            ))

        ev = target_f
        narrative = ScenarioBuilder._build_narrative(scenarios, ev, cmp_f, est_year)
        return ScenarioReport(
            scenarios=scenarios,
            expected_value=round(ev, 2),
            narrative_brief=narrative,
            estimate_year=est_year,
        )

    @staticmethod
    def _case(
        label: str,
        target: float,
        cmp: float,
        rev: Optional[float],
        pat: Optional[float],
        year: str,
        catalysts: List[str],
    ) -> Scenario:
        upside = round((target - cmp) / cmp * 100, 1) if cmp else None
        return Scenario(
            label=label,
            target_price=round(target, 2),
            upside_pct=upside,
            revenue_estimate=rev,
            pat_estimate=pat,
            estimate_year=year,
            catalysts=list(catalysts or []),
            revenue_fy26e=rev,
            pat_fy26e=pat,
        )

    @staticmethod
    def _number_in_markdown(
        value: float, ocr_text: str, source_value_factor: float = 1.0
    ) -> bool:
        fact = importlib.import_module("pipeline.12b_source_verifier.fact_checker")
        found, _, _ = fact._search_ocr(value, ocr_text)
        if found:
            return True
        factor = float(source_value_factor or 1.0)
        if factor not in (0.0, 1.0):
            found, _, _ = fact._search_ocr(value / factor, ocr_text)
            return found
        return False

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        if val is None or val in ("", "—", "[N/A]", "None", "null"):
            return None
        try:
            if hasattr(val, "value"):
                val = val.value
            return float(str(val).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _year_num(label: str) -> int:
        nums = re.findall(r"\d+", str(label or ""))
        if not nums:
            return 99
        num = int(nums[0])
        return num % 100 if num > 100 else num

    @staticmethod
    def _pick_estimate(
        rev_map: Dict[str, Any],
        pat_map: Dict[str, Any],
        ocr: str,
        factor: float,
    ) -> Tuple[str, Optional[float], Optional[float]]:
        years = set(rev_map) | set(pat_map)
        ordered = sorted(years, key=lambda y: (ScenarioBuilder._year_num(y), str(y)))
        for year in ordered:
            rev = ScenarioBuilder._safe_float(rev_map.get(year))
            pat = ScenarioBuilder._safe_float(pat_map.get(year))
            rev_ok = rev is None or ScenarioBuilder._number_in_markdown(rev, ocr, factor)
            pat_ok = pat is None or ScenarioBuilder._number_in_markdown(pat, ocr, factor)
            if (rev is not None or pat is not None) and rev_ok and pat_ok:
                return str(year), rev, pat
        return "", None, None

    @staticmethod
    def _target_range(
        ocr: str, factor: float
    ) -> Tuple[Optional[float], Optional[float]]:
        match = _RANGE_RE.search(ocr or "")
        if not match:
            return None, None
        lo = ScenarioBuilder._safe_float(match.group(1))
        hi = ScenarioBuilder._safe_float(match.group(2))
        if lo is None or hi is None or lo == hi:
            return None, None
        if lo > hi:
            lo, hi = hi, lo
        if not (
            ScenarioBuilder._number_in_markdown(lo, ocr, factor)
            and ScenarioBuilder._number_in_markdown(hi, ocr, factor)
        ):
            return None, None
        return lo, hi

    @staticmethod
    def _catalysts_from_source(
        ocr: str, commentary: str
    ) -> Tuple[List[str], List[str]]:
        text = f"{commentary}\n{ocr}"
        upside: List[str] = []
        downside: List[str] = []
        for raw in re.split(r"(?<=[.!?])\s+", text):
            sentence = " ".join(raw.split())
            if len(sentence) < 40 or len(sentence) > 220:
                continue
            low = sentence.lower()
            if any(h in low for h in _DOWNSIDE_HINTS) and len(downside) < 2:
                if sentence not in downside:
                    downside.append(sentence)
            elif any(h in low for h in _UPSIDE_HINTS) and len(upside) < 2:
                if sentence not in upside:
                    upside.append(sentence)
        return upside, downside

    @staticmethod
    def _build_narrative(
        scenarios: List[Scenario], ev: float, cmp: float, estimate_year: str
    ) -> str:
        parts = []
        year_bit = f" {estimate_year} estimates from the filing." if estimate_year else ""
        for s in scenarios:
            cat = f" Source: {'; '.join(s.catalysts)}" if s.catalysts else ""
            upside = (
                f" ({s.upside_pct:+.1f}% vs CMP)"
                if s.upside_pct is not None else ""
            )
            parts.append(
                f"{s.label}: target Rs. {s.target_price:,.0f}{upside}.{cat}"
            )
        if ev and cmp:
            parts.append(
                f"Source target expected value Rs. {ev:,.0f} "
                f"({round((ev - cmp) / cmp * 100, 1):+.1f}% vs CMP).{year_bit}"
            )
        return " ".join(parts)
