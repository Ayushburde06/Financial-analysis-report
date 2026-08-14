"""
Stage 10b: Cross-Metric Analyzer

Detects relationships between metrics that reveal the real financial story:
  - Margin compression/expansion → attributes to cost-line moves
  - Revenue vs EBITDA growth gap → operating leverage vs cost pressure
  - PAT vs operating PAT divergence → earnings quality signals
  - Asset turnover changes → capital efficiency shifts

Pure Python, no LLM. Deterministic. Feeds conclusions to narrative stage.
"""
from .analyzer import CrossMetricAnalyzer

__all__ = ["CrossMetricAnalyzer"]