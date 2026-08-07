"""Quality gates that prevent empty or misleading research reports."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

_YEAR_RE = re.compile(r"^FY\d{2}[AE]?$", re.IGNORECASE)

FORBIDDEN_BULLET_PATTERNS = [
    "grew + YoY",
    "stood at in",
    "rose + YoY to,",
    "expanded + YoY to,",
    "improved to of",
    "+% YoY",
    "[VERIFIED]",
    "[N/A]",
    "KEY_HIGHLIGHTS",
]

# Dot-paths checked on GeojitReportData (blocking if empty/missing)
REQUIRED_FOR_PDF = [
    "company.name",
    "recommendation.action",
]


def _numeric(value: Any) -> bool:
    if isinstance(value, bool) or value in (None, "", "[N/A]", "--", "—"):
        return False
    try:
        float(str(value).replace(",", "").strip())
        return True
    except (TypeError, ValueError):
        return False


def _has_numeric(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_numeric(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_numeric(child) for child in value)
    return _numeric(value)


def deep_get(obj: Any, path: str) -> Any:
    """Read nested attribute/dict path like 'financials.annual.revenue'."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def build_all_columns(financials: Dict[str, Any]) -> List[str]:
    """
    Collect year columns from ALL financial sections (annual, forecasts, BS, CF, ratios).
    Fixes the bug where balance-sheet FY25 data was omitted when P&L only had FY26E/FY27E.
    """
    seen: set[str] = set()
    cols: List[str] = []

    sections = [
        financials.get("annual", {}),
        financials.get("forecasts", {}),
        financials.get("balance_sheet", {}),
        financials.get("cash_flow", {}),
        financials.get("ratios", {}),
    ]

    for section in sections:
        if not isinstance(section, dict):
            continue
        for val in section.values():
            if not isinstance(val, dict):
                continue
            for year in val.keys():
                y = str(year)
                if _YEAR_RE.match(y) and y not in seen:
                    cols.append(y)
                    seen.add(y)

    def _sort_key(y: str) -> Tuple[int, int]:
        num = int(y[2:4])
        suffix = 0 if y.upper().endswith("A") else 1
        return (num, suffix)

    cols.sort(key=_sort_key)
    return cols


def validate_bullets(bullets: List[str]) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for highlight bullets."""
    errors: List[str] = []
    warnings: List[str] = []
    for b in bullets or []:
        text = (b or "").strip()
        if not text:
            errors.append("EMPTY BULLET")
            continue
        if not re.search(r"\d", text):
            warnings.append(f"NO NUMBER: {text[:60]}")
        for pattern in FORBIDDEN_BULLET_PATTERNS:
            if pattern in text:
                errors.append(f"PLACEHOLDER ({pattern}): {text[:60]}")
    return errors, warnings


def validate_rom(report: Any) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for required ROM fields."""
    errors: List[str] = []
    warnings: List[str] = []

    for path in REQUIRED_FOR_PDF:
        val = deep_get(report, path)
        if val is None or str(val).strip() in ("", "None"):
            errors.append(f"MISSING REQUIRED: {path}")

    financials = getattr(report, "financials", {}) or {}
    if not isinstance(financials, dict):
        financials = {}

    has_quarterly = _has_numeric(financials.get("quarterly"))
    has_annual = _has_numeric(financials.get("annual"))
    if not has_quarterly and not has_annual:
        errors.append("MISSING REQUIRED: financials.quarterly OR financials.annual")

    bullets = getattr(report, "key_highlights", []) or []
    b_errs, b_warns = validate_bullets(bullets)
    errors.extend(b_errs)
    warnings.extend(b_warns)

    all_cols = financials.get("all_columns") or build_all_columns(financials)
    if not all_cols:
        warnings.append("No year columns collected for page-3 tables")

    return errors, warnings


class ReportQualityGate:
    """Validates source extraction and final ROM before allowing PDF generation."""

    @staticmethod
    def validate_raw_financials(raw_data: Dict[str, Any], sector: str = "") -> None:
        if not isinstance(raw_data, dict):
            raise ValueError("Financial extractor did not return a JSON object.")

        sector_lower = (sector or "").lower()
        is_banking = any(kw in sector_lower for kw in ("bank", "nbfc", "financial services", "insurance"))

        if is_banking:
            required = ["nii", "advances", "deposits"]
        else:
            required = ["revenue", "ebitda", "pat"]

        missing = [
            metric for metric in required
            if not _has_numeric(raw_data.get(metric))
        ]
        if missing:
            raise ValueError(
                "Verified financial extraction is incomplete; missing numeric metrics: "
                + ", ".join(missing)
            )

    @staticmethod
    def validate_report(report: Any) -> None:
        financials = getattr(report, "financials", {}) or {}
        has_data = (
            _has_numeric(financials.get("annual"))
            or _has_numeric(financials.get("quarterly"))
            or _has_numeric(financials.get("extra_metrics"))
            or _has_numeric(financials.get("balance_sheet"))
        )
        if not has_data:
            raise ValueError("Report contains no numeric financial data.")

        errors, warnings = validate_rom(report)
        if warnings:
            appendix = getattr(report, "appendix", None)
            if isinstance(appendix, dict):
                appendix["validation_warnings"] = warnings
            elif appendix is not None and hasattr(appendix, "__dict__"):
                appendix.__dict__["validation_warnings"] = warnings
            print(f"     [Quality Gate] {len(warnings)} warning(s):")
            for w in warnings[:5]:
                print(f"       ⚠ {w}")

        if errors:
            detail = "; ".join(errors[:8])
            raise ValueError(f"Report quality gate failed: {detail}")
