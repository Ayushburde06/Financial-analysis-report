"""
Stage 06: Adaptive Analysis Planner

Maps the detected sector onto the extractor config and forwards
the source KPIs. Does not enable extra modules to fill a template.
"""

from typing import Any, List, Optional


class ExecutionPlan:
    def __init__(
        self,
        run_esg: bool,
        run_segments: bool,
        sector_module: str,
        sector: str = "",
        discovered_kpis: Optional[List[str]] = None,
        missing_metrics: Optional[List[str]] = None,
        has_full_history: bool = False,
    ):
        self.run_esg = run_esg
        self.run_segments = run_segments
        self.sector_module = sector_module
        self.sector = sector
        self.discovered_kpis = list(discovered_kpis or [])
        self.missing_metrics = list(missing_metrics or [])
        self.has_full_history = has_full_history


class AdaptiveAnalysisPlanner:
    @staticmethod
    def run(industry: str, coverage: Any, kpis: Optional[List[str]] = None) -> ExecutionPlan:
        from pipeline.sectors import get_sector_config

        kpis = list(kpis or [])
        missing = list(getattr(coverage, "missing_metrics", None) or [])
        has_history = bool(getattr(coverage, "has_full_history", False))
        cfg = get_sector_config(industry or "")
        label = (industry or "").strip() or cfg.sector_name
        print(
            f"     [Analysis Planner] {label}: "
            f"{len(kpis)} source KPIs, {len(missing)} missing, "
            f"history={'yes' if has_history else 'limited'}"
        )
        return ExecutionPlan(
            run_esg=False,
            run_segments=False,
            sector_module=cfg.sector_name,
            sector=label,
            discovered_kpis=kpis,
            missing_metrics=missing,
            has_full_history=has_history,
        )
