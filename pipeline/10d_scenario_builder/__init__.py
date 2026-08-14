"""
Stage 10d: Scenario Builder

Base case = target printed in this filing (JSON + OCR markdown).
Bull/bear only if the filing itself prints a target range.
No invented spreads, probabilities, or FY26E.
"""
from .builder import ScenarioBuilder

__all__ = ["ScenarioBuilder"]
