"""
engine.py - Quant Engine
Computes derived metrics deterministically. LLMs are forbidden from doing math here.
"""
from typing import Dict, Any
from .evidence_packets import VerifiedNumber, FinancialLineItem

class QuantEngine:
    """
    Computes YoY, QoQ, Margins, and Return metrics.
    All logic is pure Python. No LLMs.
    """
    
    @staticmethod
    def calculate_growth(current: float, previous: float) -> float:
        if not previous or previous == 0:
            return 0.0
        return ((current - previous) / previous) * 100.0
        
    @staticmethod
    def calculate_margin(profit: float, revenue: float) -> float:
        if not revenue or revenue == 0:
            return 0.0
        return (profit / revenue) * 100.0

    @staticmethod
    def build_financial_line_item(raw_data: Dict[str, Any], field_name: str) -> FinancialLineItem:
        """
        Given either:
          - a full raw_data dict (will extract field_name from it), OR
          - an already-resolved sub-dict (has period keys like fy22, q_current etc.)
        Builds a typed FinancialLineItem.
        """
        # If raw_data already looks like a period dict (has period keys), use it directly.
        # Otherwise look up field_name inside it (legacy path).
        PERIOD_KEYS = {"fy22", "fy23", "fy24", "fy25", "fy26e", "fy27e",
                       "q_prev_year", "q_prev_qtr", "q_current"}
        if raw_data and PERIOD_KEYS.intersection(raw_data.keys()):
            data = raw_data  # already a period-keyed dict
        else:
            data = raw_data.get(field_name, {}) if isinstance(raw_data, dict) else {}
        
        # Normalize data to flatten any nested dictionaries that LLMs occasionally return
        normalized_data = {}
        if isinstance(data, dict):
            # First, copy non-dict items
            for k, v in data.items():
                if not isinstance(v, dict):
                    normalized_data[k] = v
            # Then, merge keys from any nested dicts
            for k, v in data.items():
                if isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        if sub_v is not None and sub_v != "":
                            if normalized_data.get(sub_k) is None or normalized_data.get(sub_k) == "":
                                normalized_data[sub_k] = sub_v
        else:
            normalized_data = {}
            
        # Helper to safely wrap values
        def wrap(val) -> VerifiedNumber:
            if val is None or val == "":
                return VerifiedNumber(value="[N/A]")
            
            # In a full implementation, the raw extractor would provide source_page and source_table
            # For v1, we simulate passing the raw extracted float/int
            try:
                numeric_val = float(str(val).replace(",", ""))
                return VerifiedNumber(value=numeric_val)
            except ValueError:
                return VerifiedNumber(value=val)

        return FinancialLineItem(
            fy22=wrap(normalized_data.get("fy22")),
            fy23=wrap(normalized_data.get("fy23")),
            fy24=wrap(normalized_data.get("fy24")),
            fy25=wrap(normalized_data.get("fy25")),
            q_prev_year=wrap(normalized_data.get("q_prev_year")),
            q_prev_qtr=wrap(normalized_data.get("q_prev_qtr")),
            q_current=wrap(normalized_data.get("q_current"))
        )
