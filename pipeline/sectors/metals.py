"""Metals / Mining / Steel / Aluminium sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class MetalsConfig(SectorConfig):
    sector_name: str = "Metals"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "metals", "steel", "aluminium", "aluminum", "copper", "zinc",
        "mining", "iron ore", "sponge iron",
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "net_sales", "total_income"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Production Volume (MT)",    "production_volume"),
        ("Sales Volume (MT)",         "sales_volume"),
        ("Realization (₹/MT)",        "realization_per_tonne"),
        ("EBITDA/tonne (₹)",          "ebitda_per_tonne"),
        ("Net Debt (₹ Cr)",           "net_debt"),
        ("EBITDA Margin (%)",         "ebitda_margin"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & EBITDA Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "production_volume, sales_volume, realization_per_tonne, ebitda_per_tonne, "
        "total_assets, total_debt, net_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue/Net Sales, EBITDA, PAT, EPS, "
        "Production Volume (tonnes/MT), Sales Volume, Realization per tonne, "
        "EBITDA per tonne, Total Debt, Net Debt, Cash, Operating Cash Flow."
    )
