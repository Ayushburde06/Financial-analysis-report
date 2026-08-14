"""
Stage 10c: Earnings Quality Analyzer

Separates real operating performance from cosmetic/one-time effects
using this filing's actual years only. Thin source → unscored, not HIGH.
"""
from .scorer import EarningsQualityScorer

__all__ = ["EarningsQualityScorer"]
