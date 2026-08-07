"""Cement / Building Materials sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class CementConfig(SectorConfig):
    sector_name: str = "Cement"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "cement", "building materials", "ultratech", "ambuja", "acc",
        "shree cement", "dalmia", "jk cement", "ramco"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "net_sales", "total_income"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Volume (MT)",             "cement_volume"),
        ("Realization (₹/tonne)",   "realization_per_tonne"),
        ("EBITDA/tonne (₹)",        "ebitda_per_tonne"),
        ("Capacity (MTPA)",         "installed_capacity"),
        ("Utilisation (%)",         "capacity_utilisation"),
        ("EBITDA Margin (%)",       "ebitda_margin"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Volume & Revenue Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "cement_volume, realization_per_tonne, ebitda_per_tonne, "
        "installed_capacity, capacity_utilisation, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue, EBITDA, PAT, EPS, "
        "Cement Volume (million tonnes/MT), Realization per tonne, "
        "EBITDA per tonne, Installed Capacity (MTPA), Capacity Utilisation %, "
        "Total Debt, Cash, Operating Cash Flow."
    )
