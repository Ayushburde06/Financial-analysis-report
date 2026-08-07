"""Pharma / Healthcare sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class PharmaConfig(SectorConfig):
    sector_name: str = "Pharma"
    sector_aliases: List[str] = field(default_factory=lambda: ["pharma", "healthcare", "pharmaceutical"])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "total_income", "net_sales"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("R&D Expense (₹ Cr)",    "r_and_d_expense"),
        ("Domestic Revenue",       "domestic_revenue"),
        ("Export Revenue",         "export_revenue"),
        ("EBITDA Margin (%)",      "ebitda_margin"),
        ("ANDA Filings",           "anda_filings"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow, "
        "r_and_d_expense, domestic_revenue, export_revenue"
    )
    extraction_hints: str = (
        "Look for: Revenue (Domestic + Export), EBITDA, PAT, EPS, "
        "R&D Expense, Total Debt, Cash & Equivalents, Operating Cash Flow."
    )
