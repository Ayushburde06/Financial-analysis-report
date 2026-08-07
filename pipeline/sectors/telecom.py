"""Telecom sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class TelecomConfig(SectorConfig):
    sector_name: str = "Telecom"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "telecom", "telecommunications", "wireless", "mobile", "spectrum",
        "airtel", "jio", "vodafone", "vi", "bsnl", "indus towers"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "total_income", "service_revenue"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Subscribers (Mn)",        "subscribers"),
        ("ARPU (₹)",                "arpu"),
        ("EBITDA Margin (%)",       "ebitda_margin"),
        ("Data Traffic (EBs)",      "data_traffic"),
        ("Net Debt (₹ Cr)",         "net_debt"),
        ("Capex (₹ Cr)",            "capex"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & ARPU Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "subscribers, arpu, data_traffic, capex, net_debt, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue/Service Revenue, EBITDA, PAT, EPS, "
        "Subscribers (millions), ARPU (Average Revenue Per User ₹/month), "
        "Data Traffic (Exabytes/PB), Capex, Net Debt, Operating Cash Flow."
    )
