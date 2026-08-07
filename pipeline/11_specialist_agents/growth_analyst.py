"""
02_growth_analyst.py
"""
from .base_agent import BaseFinancialAgent

class GrowthAnalyst(BaseFinancialAgent):
    def _get_task_instruction(self) -> str:
        return "Write 1 paragraph analyzing the growth drivers, segment performance, and YoY/QoQ trajectory based strictly on the GrowthMetricsPacket."
