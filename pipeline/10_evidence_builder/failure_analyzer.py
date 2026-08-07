"""
failure_analyzer.py - Self-Improving Extraction Pipelines

FIX: score_extraction was hardcoded to check 'revenue' + 'pat'.
     Banking/NBFC sectors don't have 'revenue' — they have 'nii'.
     Result was a false failure score of 0.0 on every bank report.

New logic:
  - Score based on ANY of the key financial presence fields
  - Banks: nii OR net_interest_income OR pat
  - NBFC:  aum OR pat
  - All other sectors: revenue OR pat
  - Also accepts 'total_income', 'operating_revenue' as revenue aliases
"""
import json
import os
from typing import Dict, Any


# Fields that count as "revenue" depending on sector
_REVENUE_ALIASES = [
    "revenue", "total_income", "operating_revenue", "net_revenue",
    "nii", "net_interest_income",           # Banking / NBFC
    "aum", "disbursements",                  # NBFC
    "gross_premium", "net_premium",          # Insurance
]

_PAT_ALIASES = ["pat", "net_profit", "profit_after_tax", "net_income"]


class FailureAnalyzerAgent:
    MEMORY_FILE = "pipeline_memory.json"

    @classmethod
    def load_memory(cls) -> Dict[str, Any]:
        if os.path.exists(cls.MEMORY_FILE):
            try:
                with open(cls.MEMORY_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"known_issues": {}, "learned_strategies": {}}

    @classmethod
    def save_memory(cls, memory: Dict[str, Any]):
        with open(cls.MEMORY_FILE, "w") as f:
            json.dump(memory, f, indent=4)

    @classmethod
    def _has_numeric_data(cls, field_dict: Any) -> bool:
        """Return True if the dict contains at least one non-null numeric value."""
        if not isinstance(field_dict, dict):
            return False
        for v in field_dict.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0:
                return True
            if isinstance(v, str):
                try:
                    if float(v.replace(",", "").strip()) != 0:
                        return True
                except ValueError:
                    pass
        return False

    @classmethod
    def score_extraction(cls, raw_data: Dict[str, Any]) -> float:
        """
        Auto-Scorer: Evaluates completeness of extracted data.
        Checks sector-agnostic aliases — does NOT fail banks for missing 'revenue'.
        Returns 1.0 if at least one revenue-alias AND one PAT-alias have numeric data.
        Returns 0.5 if only one of the two is present.
        Returns 0.0 if neither is present.
        """
        has_revenue = any(
            cls._has_numeric_data(raw_data.get(alias))
            for alias in _REVENUE_ALIASES
            if alias in raw_data
        )
        has_pat = any(
            cls._has_numeric_data(raw_data.get(alias))
            for alias in _PAT_ALIASES
            if alias in raw_data
        )

        if has_revenue and has_pat:
            return 1.0
        if has_revenue or has_pat:
            return 0.5   # partial data — allow it through
        return 0.0

    @classmethod
    def analyze_and_retry(cls, raw_data: Dict[str, Any], attempt: int) -> Dict[str, Any]:
        """
        Failure Analyzer: Only called when score < 1.0.
        Tries to fix missing fields by re-running Mistral Large 3 with a targeted prompt.
        Falls back to returning original data rather than corrupting it.
        """
        memory = cls.load_memory()
        print(f"     [Failure Analyzer] Attempt {attempt} Failed (Score < 1.0). Analyzing root cause...")

        # Identify which alias buckets are missing
        missing_revenue = not any(
            cls._has_numeric_data(raw_data.get(alias))
            for alias in _REVENUE_ALIASES if alias in raw_data
        )
        missing_pat = not any(
            cls._has_numeric_data(raw_data.get(alias))
            for alias in _PAT_ALIASES if alias in raw_data
        )

        issues = []
        if missing_revenue:
            issues.append("revenue / NII / net_interest_income")
        if missing_pat:
            issues.append("PAT / net_profit")

        issue_str = " and ".join(issues) if issues else "incomplete financial data"
        print(f"     [Failure Analyzer] Identified Issue: Missing — {issue_str}")
        memory["known_issues"][f"missing_data_attempt_{attempt}"] = issue_str
        cls.save_memory(memory)

        # Do NOT re-call LLM with a vague prompt — it returns garbage.
        # Instead, just return the existing raw_data (Mistral already did its best).
        # The pipeline will proceed with degraded data rather than corrupt data.
        print(f"     [Failure Analyzer] Partial data accepted (attempt {attempt}). "
              f"Pipeline continues with available fields.")
        return raw_data
