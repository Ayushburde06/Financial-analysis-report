"""
04_valuation_analyst.py
"""
from .base_agent import BaseFinancialAgent

class ValuationAnalyst(BaseFinancialAgent):
    def _get_task_instruction(self) -> str:
        return "Write 1 paragraph providing the target price rationale and valuation commentary based on P/E, EV/EBITDA, and forward estimates. Do NOT invent a target price if it is [N/A]."
