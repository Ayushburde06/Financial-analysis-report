"""
failure_analyzer.py — Stage 10 coverage check.

Scores whether this filing produced any usable P&L numbers.
Does not invent fields. Does not re-call the LLM.
"""
from typing import Any, Dict, Iterable, Optional, Sequence


_REVENUE_ALIASES = (
    "revenue", "total_income", "operating_revenue", "net_revenue", "net_sales",
    "nii", "net_interest_income",
    "aum", "disbursements",
    "gross_premium", "net_premium", "gross_written_premium",
    "gmv", "gross_merchandise_value",
)

_PAT_ALIASES = ("pat", "net_profit", "profit_after_tax", "net_income")


class FailureAnalyzerAgent:
    @classmethod
    def _has_numeric_data(cls, field_dict: Any) -> bool:
        if not isinstance(field_dict, dict):
            return False
        for val in field_dict.values():
            if isinstance(val, bool):
                continue
            if isinstance(val, (int, float)):
                return True
            if isinstance(val, str):
                try:
                    float(val.replace(",", "").strip())
                    return val.strip() not in ("", "—", "None", "null")
                except ValueError:
                    continue
        return False

    @classmethod
    def score_extraction(
        cls,
        raw_data: Dict[str, Any],
        extra_keys: Optional[Sequence[str]] = None,
    ) -> float:
        raw = raw_data if isinstance(raw_data, dict) else {}
        keys: Iterable[str] = list(_REVENUE_ALIASES) + list(extra_keys or [])
        has_revenue = any(cls._has_numeric_data(raw.get(alias)) for alias in keys)
        has_pat = any(cls._has_numeric_data(raw.get(alias)) for alias in _PAT_ALIASES)
        if has_revenue and has_pat:
            return 1.0
        if has_revenue or has_pat:
            return 0.5
        return 0.0

    @classmethod
    def analyze_and_retry(cls, raw_data: Dict[str, Any], attempt: int) -> Dict[str, Any]:
        print(f"     [Failure Analyzer] Coverage still thin (attempt {attempt}); "
              "keeping source fields as extracted.")
        return raw_data
