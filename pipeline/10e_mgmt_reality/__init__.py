"""
Stage 10e: Management commentary vs reported actuals.

Compares guidance in this filing's MD&A / outlook with JSON years
that also appear in the OCR markdown. Thin source stays empty.
"""
from .cross_referencer import MgmtRealityCrossReferencer

__all__ = ["MgmtRealityCrossReferencer"]
