"""
engine.py - Quant Engine

Deterministic math only. No LLM.
Works on whatever years this filing has (fy23, fy26a, fy24e, …).
Does not assume FY25 / FY26E.
"""
import re
from typing import Any, Dict, Optional

from .evidence_packets import FinancialLineItem, VerifiedNumber

_ANNUAL_KEY_RE = re.compile(r"^fy\d{2,4}[ae]?$", re.IGNORECASE)


def _wrap(val: Any) -> VerifiedNumber:
    if val is None or val == "":
        return VerifiedNumber(value="[N/A]")
    try:
        return VerifiedNumber(value=float(str(val).replace(",", "")))
    except ValueError:
        return VerifiedNumber(value=val)


class QuantEngine:
    QUARTERLY_KEYS = {"q_prev_year", "q_prev_qtr", "q_current"}

    @staticmethod
    def calculate_growth(current: float, previous: float) -> Optional[float]:
        if current is None or previous in (None, 0, 0.0):
            return None
        return ((float(current) - float(previous)) / float(previous)) * 100.0

    @staticmethod
    def calculate_margin(profit: float, revenue: float) -> Optional[float]:
        if profit is None or revenue in (None, 0, 0.0):
            return None
        return (float(profit) / float(revenue)) * 100.0

    @staticmethod
    def _is_annual_key(key: str) -> bool:
        return bool(_ANNUAL_KEY_RE.match(str(key).lower().strip()))

    @staticmethod
    def _is_period_dict(raw_data: Any) -> bool:
        if not isinstance(raw_data, dict) or not raw_data:
            return False
        for key in raw_data:
            low = str(key).lower().strip()
            if low in QuantEngine.QUARTERLY_KEYS or QuantEngine._is_annual_key(low):
                return True
        return False

    @staticmethod
    def build_financial_line_item(raw_data: Dict[str, Any], field_name: str) -> FinancialLineItem:
        if QuantEngine._is_period_dict(raw_data):
            data = raw_data
        else:
            data = raw_data.get(field_name, {}) if isinstance(raw_data, dict) else {}

        normalized_data: Dict[str, Any] = {}
        if isinstance(data, dict):
            for key, val in data.items():
                if not isinstance(val, dict):
                    normalized_data[key] = val
            for key, val in data.items():
                if isinstance(val, dict):
                    for sub_k, sub_v in val.items():
                        if sub_v not in (None, "") and normalized_data.get(sub_k) in (None, ""):
                            normalized_data[sub_k] = sub_v

        annual_dict = {}
        for key, val in normalized_data.items():
            key_lower = str(key).lower().strip()
            if QuantEngine._is_annual_key(key_lower):
                wrapped = _wrap(val)
                if key_lower.endswith("e"):
                    wrapped.is_estimate = True
                annual_dict[key_lower] = wrapped

        def pick(name: str) -> VerifiedNumber:
            if name in normalized_data:
                vn = _wrap(normalized_data.get(name))
                if name.endswith("e"):
                    vn.is_estimate = True
                return vn
            if name in annual_dict:
                return annual_dict[name]
            return _wrap(None)

        return FinancialLineItem(
            annual=annual_dict,
            fy22=pick("fy22"),
            fy23=pick("fy23"),
            fy24=pick("fy24"),
            fy25=pick("fy25"),
            fy26e=pick("fy26e"),
            fy27e=pick("fy27e"),
            q_prev_year=pick("q_prev_year"),
            q_prev_qtr=pick("q_prev_qtr"),
            q_current=pick("q_current"),
        )
