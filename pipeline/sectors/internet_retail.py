"""Internet / E-commerce / Quick Commerce / Retail sector configuration.
Covers: Zomato, Eternal, Swiggy, Nykaa, Meesho, Flipkart-type companies.
"""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class InternetRetailConfig(SectorConfig):
    sector_name: str = "Internet & Retail"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "internet", "e-commerce", "ecommerce", "quick commerce", "food delivery",
        "online retail", "catalogue retail", "digital platform", "marketplace",
        "zomato", "eternal", "swiggy", "nykaa", "meesho", "blinkit",
        "hyperpure", "nov", "gross order value", "gov", "gmv",
        "quick commerce", "d2c", "direct to consumer"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: [
        "revenue", "total_income", "revenue_from_operations", "net_revenue"
    ])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "adjusted_ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "adj_pat", "net_profit", "adjusted_pat"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("GOV / NOV (₹ Cr)",         "gross_order_value"),
        ("EBITDA Margin (%)",         "ebitda_margin"),
        ("Active Users (Mn)",         "active_users"),
        ("Orders per Day (Mn)",       "daily_orders"),
        ("Take Rate (%)",             "take_rate"),
        ("Contribution Margin (%)",   "contribution_margin"),
        ("Store Count",               "store_count"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & GOV Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, adj_pat, eps, "
        "gross_order_value, net_order_value, active_users, daily_orders, "
        "take_rate, contribution_margin, store_count, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue from Operations, EBITDA (may be negative), "
        "Adjusted EBITDA, PAT, Adjusted PAT, EPS, "
        "Gross Order Value (GOV) or Net Order Value (NOV), "
        "Active Users/Customers, Daily Orders, Take Rate %, "
        "Contribution Margin %, Store Count/Dark Stores, "
        "Cash & Equivalents, Operating Cash Flow."
    )
