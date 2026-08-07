"""Energy / Power sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class EnergyConfig(SectorConfig):
    sector_name: str = "Energy"
    sector_aliases: List[str] = field(default_factory=lambda: ["energy", "power", "utilities", "renewable"])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "total_income", "operating_revenue"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Installed Capacity (MW)",  "installed_capacity_mw"),
        ("Generation (MUs)",         "generation_units"),
        ("PLF (%)",                  "plf_pct"),
        ("EBITDA Margin (%)",        "ebitda_margin"),
        ("Net Debt (₹ Cr)",          "total_debt"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "total_assets, total_liabilities, total_equity, total_debt, "
        "net_worth, shareholders_fund, borrowings, cash_and_equivalents, "
        "investments, accounts_receivable, inventories, "
        "gross_fixed_assets, current_liabilities, "
        "operating_cash_flow, investing_cash_flow, financing_cash_flow, free_cash_flow, "
        "installed_capacity_mw, generation_units, plf_pct"
    )
    extraction_hints: str = (
        "Look for: Revenue, EBITDA, PAT, EPS, "
        "Installed Capacity (MW/GW), Power Generation (MUs/BUs), "
        "Plant Load Factor (PLF%), Operating Cash Flow. "
        "ALSO extract Balance Sheet items: Total Assets, Total Liabilities, "
        "Shareholders' Funds / Total Equity / Net Worth, Total Debt / Borrowings, "
        "Cash & Equivalents, Investments, Fixed Assets, Current Liabilities."
    )
