"""Infrastructure / EPC / Construction sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class InfrastructureConfig(SectorConfig):
    sector_name: str = "Infrastructure"
    sector_aliases: List[str] = field(default_factory=lambda: [
        "infrastructure", "epc", "construction", "engineering", "roads", "highways",
        "metro", "irrigation", "power transmission"
    ])

    revenue_keys: List[str] = field(default_factory=lambda: ["revenue", "total_income", "contract_revenue"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ebitda", "operating_profit"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("Order Book (₹ Cr)",     "order_book"),
        ("Order Inflow (₹ Cr)",   "order_inflow"),
        ("Order Book/Revenue (x)","order_book_revenue_ratio"),
        ("EBITDA Margin (%)",     "ebitda_margin"),
        ("D/E Ratio",             "debt_to_equity"),
        ("Working Capital Days",  "working_capital_days"),
    ])

    pl_label:        str = "Revenue (₹ Cr)"
    ebitda_label:    str = "EBITDA"
    pat_label:       str = "PAT"
    chart_title:     str = "Revenue & Order Book Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    extraction_keys: str = (
        "revenue, ebitda, ebit, pbt, pat, eps, "
        "order_book, order_inflow, "
        "total_assets, total_debt, cash_and_equivalents, "
        "operating_cash_flow, free_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Revenue/Contract Revenue, EBITDA, PAT, EPS, "
        "Order Book (backlog), Order Inflow (new orders), "
        "Total Debt, Cash & Equivalents, Operating Cash Flow. "
        "Order book is the outstanding order backlog at period end."
    )
