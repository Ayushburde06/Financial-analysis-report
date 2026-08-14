"""
base.py — Abstract SectorConfig base class.
Every sector subclass defines its own field mappings, labels, and chart config.
"""
from dataclasses import dataclass, field
from typing import List, Dict
import re


@dataclass
class SectorConfig:
    """
    All per-sector customisation lives here.
    Subclass this and override the fields — nothing else needs changing.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    sector_name: str = "Generic"
    sector_aliases: List[str] = field(default_factory=list)  # e.g. ["bank", "nbfc"]

    # ── P&L field mapping ────────────────────────────────────────────────────
    # These are the raw_data keys that map to P&L line items.
    # Listed in priority order — first key with data wins.
    revenue_keys:   List[str] = field(default_factory=lambda: ["revenue", "total_income"])
    ebitda_keys:    List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:       List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    # ── Balance Sheet field mapping ──────────────────────────────────────────
    assets_keys:    List[str] = field(default_factory=lambda: ["total_assets"])
    liab_keys:      List[str] = field(default_factory=lambda: ["total_liabilities", "deposits"])
    equity_keys:    List[str] = field(default_factory=lambda: ["total_equity"])
    debt_keys:      List[str] = field(default_factory=lambda: ["total_debt", "borrowings"])
    cash_keys:      List[str] = field(default_factory=lambda: ["cash_and_equivalents", "cash"])

    # ── Sector-specific extra metrics (shown in dedicated table in PDF) ───────
    # Format: [(display_label, raw_data_key), ...]
    extra_metrics:  List[tuple] = field(default_factory=list)

    # ── PDF display labels ────────────────────────────────────────────────────
    pl_label:       str = "Revenue"       # Column header in annual P&L table
    ebitda_label:   str = "EBITDA"
    pat_label:      str = "PAT"
    currency_symbol: str = "Rs."
    unit_suffix:     str = "cr"
    unit_label:      str = "Rs. cr"

    # ── Chart config ─────────────────────────────────────────────────────────
    chart_title:        str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "Margin Breakdown (%)"

    # ── Extraction hints passed to Mistral prompt ─────────────────────────────
    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue, EBITDA, PAT, EPS, Total Assets, Total Debt, "
        "Cash & Equivalents, Operating Cash Flow."
    )

    def is_match(self, detected_sector: str) -> bool:
        s = (detected_sector or "").strip().lower()
        if not s:
            return False
        if s == self.sector_name.lower():
            return True
        for alias in self.sector_aliases:
            a = (alias or "").strip().lower()
            if not a:
                continue
            if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", s):
                return True
        return False
