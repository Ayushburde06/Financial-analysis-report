"""
Generic fallback sector config.
Used when no specific sector is detected.

Key design: extraction_keys covers ALL possible financial metrics
across every sector. Mistral will extract whatever is present and
return null for what isn't — so the pipeline always gets maximum data
regardless of industry type.
"""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class GenericConfig(SectorConfig):
    sector_name: str = "Other"
    sector_aliases: List[str] = field(default_factory=list)  # matches everything

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("EBITDA Margin (%)",  "ebitda_margin"),
        ("PAT Margin (%)",     "pat_margin"),
        ("ROE (%)",            "roe"),
        ("ROA (%)",            "roa"),
        ("D/E Ratio",          "debt_to_equity"),
        ("Interest Coverage",  "interest_coverage"),
        ("Working Cap Days",   "working_capital_days"),
    ])

    pl_label:            str = "Revenue (₹ Cr)"
    ebitda_label:        str = "EBITDA"
    pat_label:           str = "PAT"
    chart_title:         str = "Revenue & PAT Trend"
    revenue_chart_label: str = "Revenue"
    margin_chart_title:  str = "EBITDA & PAT Margin (%)"

    # Widest possible extraction net — covers every sector type
    extraction_keys: str = (
        # Core P&L
        "revenue, total_income, net_sales, operating_revenue, "
        "gross_profit, ebitda, ebit, pbt, pat, adj_pat, "
        "eps, dps, depreciation, interest, tax, tax_rate, other_income, "
        # Sector-specific top-lines (will be null if not applicable)
        "nii, net_interest_income, nim, "          # Banking
        "aum, disbursements, "                      # NBFC
        "order_book, order_inflow, "                # Infra
        "gross_order_value, net_order_value, "      # Internet
        "cement_volume, production_volume, "        # Cement/Metals
        "installed_capacity_mw, generation_units, " # Energy
        # Balance Sheet
        "total_assets, total_liabilities, total_equity, total_debt, "
        "cash_and_equivalents, investments, net_worth, "
        "accounts_receivable, inventories, gross_fixed_assets, current_liabilities, provisions, "
        # Cash Flow & Ratios
        "operating_cash_flow, investing_cash_flow, "
        "financing_cash_flow, free_cash_flow, capex, "
        "pe_ratio, pbv_ratio, ev_ebitda, ebitda_margin, pat_margin, roce"
    )

    extraction_hints: str = (
        "Extract ALL financial data present in the document. "
        "Look for: Revenue / Net Sales / Total Income / NII (whichever applies), "
        "EBITDA / Operating Profit, EBIT, PBT, PAT, EPS, DPS, "
        "Depreciation, Interest, Other Income, Tax, Tax Rate, "
        "Total Assets, Total Debt, Net Worth / Equity, Cash & Equivalents, "
        "Accounts Receivable, Inventories, Fixed Assets, Current Liabilities, Provisions, Investments, "
        "Operating Cash Flow, Free Cash Flow, Capex. "
        "Also extract any sector-specific metrics present: "
        "order book, AUM, installed capacity, volumes, ARPU, etc. "
        "Use null for fields genuinely absent — do not invent values."
    )

    # Balance sheet / cash flow field resolution — try all aliases
    assets_keys:  List[str] = field(default_factory=lambda: [
        "total_assets", "net_assets"
    ])
    liab_keys:    List[str] = field(default_factory=lambda: [
        "total_liabilities", "total_borrowings"
    ])
    equity_keys:  List[str] = field(default_factory=lambda: [
        "total_equity", "net_worth", "shareholders_equity"
    ])
    debt_keys:    List[str] = field(default_factory=lambda: [
        "total_debt", "net_debt", "borrowings", "long_term_debt"
    ])
    cash_keys:    List[str] = field(default_factory=lambda: [
        "cash_and_equivalents", "cash", "cash_and_bank"
    ])

    def is_match(self, detected_sector: str) -> bool:
        return True  # Always matches — used as last-resort fallback
