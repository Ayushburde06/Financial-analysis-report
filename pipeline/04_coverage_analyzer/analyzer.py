"""
Stage 04: Coverage Analyzer

Checks whether each Stage 03 metric still has a number in the source.
Also notes how many fiscal-year labels the filing carries. Does not guess.
"""

from __future__ import annotations

import importlib
import re
from typing import Any, List

_disc = importlib.import_module("pipeline.03_kpi_discovery_engine.discoverer")
KPI_LABELS = _disc.KPI_LABELS
label_for = _disc.label_for
metric_has_number = _disc.metric_has_number


class CoverageReport:
    def __init__(self, has_full_history: bool, missing_metrics: list):
        self.has_full_history = has_full_history
        self.missing_metrics = missing_metrics


class CoverageAnalyzer:
    @staticmethod
    def run(master_doc: Any, kpis: list) -> CoverageReport:
        print("     [Coverage Analyzer] Checking numbered evidence for discovered KPIs...")
        text = (master_doc.get_full_text() if master_doc else "") or ""
        missing: List[str] = []
        for kpi in kpis or []:
            if not metric_has_number(text, str(kpi)):
                missing.append(str(kpi))

        years = set(re.findall(r"\bfy\s*'?(\d{2,4})\b", text, re.I))
        quarters = set(re.findall(r"\bq[1-4]\s*fy\s*\d{2,4}", text, re.I))
        has_full_history = len(years) >= 3 or (len(years) >= 2 and len(quarters) >= 2)

        missing_labels = ", ".join(label_for(k) for k in missing) or "none"
        print(
            f"     [Coverage Analyzer] {len(kpis or []) - len(missing)}/"
            f"{len(kpis or [])} evidenced; FY labels={len(years)}; "
            f"missing: {missing_labels}"
        )
        return CoverageReport(has_full_history=has_full_history, missing_metrics=missing)
