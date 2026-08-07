"""
Stage 04: Coverage Analyzer
Determines evidence availability (e.g. missing 5-year historicals) without reasoning.
"""
from typing import Dict, Any

class CoverageReport:
    def __init__(self, has_full_history: bool, missing_metrics: list):
        self.has_full_history = has_full_history
        self.missing_metrics = missing_metrics

class CoverageAnalyzer:
    @staticmethod
    def run(master_doc: Any, kpis: list) -> CoverageReport:
        print("     [Coverage Analyzer] Checking data availability for historical modeling...")
        full_text = master_doc.get_full_text().lower()
        missing = []
        for kpi in kpis:
            if kpi.lower() not in full_text:
                missing.append(kpi)
        
        has_full = len(missing) == 0
        return CoverageReport(has_full_history=has_full, missing_metrics=missing)
