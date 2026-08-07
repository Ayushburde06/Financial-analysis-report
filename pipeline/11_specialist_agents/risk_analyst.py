"""
03_risk_analyst.py
"""
from .base_agent import BaseFinancialAgent

class RiskAnalyst(BaseFinancialAgent):
    def _get_task_instruction(self) -> str:
        return "Identify and write exactly 3-5 bullet points of key risks (e.g. debt stress, margin contraction) citing the explicit data points from the RiskAnalystEvidence."
