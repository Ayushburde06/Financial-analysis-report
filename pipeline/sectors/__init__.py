"""
pipeline/sectors/ — Modular sector configuration system.

To add a new sector:
  1. Create pipeline/sectors/your_sector.py
  2. Define a class inheriting SectorConfig
  3. It auto-registers — no other files need editing.

Usage:
    from pipeline.sectors import get_sector_config
    cfg = get_sector_config("Banking")
    cfg.pl_label          # "NII (₹ bn)"
    cfg.extraction_keys   # list of JSON keys Mistral should extract
    cfg.chart_title       # "NII & PAT Trend"
"""
from .base import SectorConfig
from .registry import get_sector_config, list_sectors

__all__ = ["SectorConfig", "get_sector_config", "list_sectors"]
