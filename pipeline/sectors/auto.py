"""Automobile / Auto Ancillary sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class AutoConfig(SectorConfig):
    sector_name: str = "Auto"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "auto", "automobile", "automotive", "vehicle", "2-wheeler",
        "passenger vehicle", "commercial vehicle", "auto ancillary", "tyre"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "net_sales", "total_income"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Total Volumes (units)",    "total_volumes"),
        ("Domestic Volumes",         "domestic_volumes"),
        ("Export Volumes",           "export_volumes"),
        ("ASP (₹ per unit)",         "average_selling_price"),
        ("EBITDA Margin (%)",        "ebitda_margin"),
        ("EV Mix (%)",               "ev_mix_pct"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, dps, "
        "total_volumes, domestic_volumes, export_volumes, average_selling_price, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow, ev_mix_pct"
    )
    extraction_hints: str = (
        "Look for: Revenue/Net Sales, EBITDA, PAT, EPS, "
        "Total Vehicle Volumes/Units Sold, Domestic vs Export volumes, "
        "Average Selling Price (ASP), Total Debt, Cash, Operating Cash Flow."
    )
