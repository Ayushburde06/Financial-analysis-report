"""
Stage 06: Adaptive Analysis Planner
Determines which analysis modules to run and which to skip.
"""
from typing import Dict, Any

class ExecutionPlan:
    def __init__(self, run_esg: bool, run_segments: bool, sector_module: str,
                 sector: str = "Other"):
        self.run_esg = run_esg
        self.run_segments = run_segments
        self.sector_module = sector_module
        self.sector = sector  # Passed to Stage 08 for sector-aware extraction

class AdaptiveAnalysisPlanner:
    @staticmethod
    def run(industry: str, coverage: Any) -> ExecutionPlan:
        print(f"     [Analysis Planner] Generating execution plan for {industry}...")
        return ExecutionPlan(
            run_esg=True,
            run_segments=True,
            sector_module=f"{industry}_Metrics",
            sector=industry,  # Pass detected sector downstream
        )
