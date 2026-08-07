"""IT Services sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class ITServicesConfig(SectorConfig):
    sector_name: str = "IT Services"
    sector_aliases: List[str] = field(default_factory=lambda: ["it", "technology", "software", "tech"])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "total_income", "operating_revenue"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("EBITDA Margin (%)",  "ebitda_margin"),
        ("Headcount",          "headcount"),
        ("Attrition Rate (%)", "attrition_rate"),
        ("Utilisation (%)",    "utilisation"),
        ("USD Revenue",        "usd_revenue"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, dps, "
        "total_assets, total_liabilities, total_equity, total_debt, "
        "net_worth, shareholders_fund, borrowings, cash_and_equivalents, "
        "investments, accounts_receivable, inventories, "
        "gross_fixed_assets, current_liabilities, "
        "operating_cash_flow, investing_cash_flow, financing_cash_flow, "
        "free_cash_flow, headcount, attrition_rate"
    )
    extraction_hints: str = (
        "Look for: Revenue from Operations, EBITDA, EBIT, PBT, PAT, EPS, "
        "Total Employees/Headcount, Attrition Rate%, "
        "Cash & Equivalents, Operating Cash Flow, Free Cash Flow. "
        "ALSO extract Balance Sheet items: Total Assets, Total Liabilities, "
        "Shareholders' Funds / Total Equity / Net Worth, Total Debt / Borrowings, "
        "Investments, Accounts Receivable, Inventories, Fixed Assets, Current Liabilities."
    )
