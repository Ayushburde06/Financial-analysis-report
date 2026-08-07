"""FMCG / Consumer Goods sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class FMCGConfig(SectorConfig):
    sector_name: str = "FMCG"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "fmcg", "consumer goods", "consumer staples", "consumer discretionary",
        "food", "beverages", "personal care", "household"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "net_sales", "total_income"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Volume Growth (%)",     "volume_growth"),
        ("Gross Margin (%)",      "gross_margin"),
        ("EBITDA Margin (%)",     "ebitda_margin"),
        ("A&P Spend (₹ Cr)",     "advertising_expense"),
        ("Distribution Outlets",  "distribution_outlets"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "Gross & EBITDA Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, dps, "
        "gross_profit, advertising_expense, volume_growth, gross_margin, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue/Net Sales, Gross Profit, EBITDA, PAT, EPS, DPS, "
        "Volume Growth (%), Gross Margin (%), A&P/Advertising Expense, "
        "Total Debt, Cash & Equivalents, Operating Cash Flow."
    )
