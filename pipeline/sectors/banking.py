"""Banking / Private Bank sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class BankingConfig(SectorConfig):
    sector_name: str = "Banking"
    sector_aliases: List[str] = field(default_factory=lambda: ["bank", "banking", "financial services"])

    # P&L — banks use NII as top-line, not "revenue"
    revenue_keys:   List[str] = field(default_factory=lambda: ["nii", "net_interest_income", "total_income"])
    ebitda_keys:    List[str] = field(default_factory=lambda: ["ppop", "core_operating_profit", "operating_profit", "ebitda"])
    pat_keys:       List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    # Balance Sheet — banks hold advances & deposits
    assets_keys:    List[str] = field(default_factory=lambda: ["total_assets", "advances"])
    liab_keys:      List[str] = field(default_factory=lambda: ["deposits", "total_liabilities"])
    equity_keys:    List[str] = field(default_factory=lambda: ["total_equity", "net_worth"])
    debt_keys:      List[str] = field(default_factory=lambda: ["borrowings", "total_debt"])
    cash_keys:      List[str] = field(default_factory=lambda: ["cash_and_equivalents", "cash"])

    # Sector-specific metrics shown in extra table in PDF
    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("NIM (%)",              "nim"),
        ("GNPA (%)",             "gnpa"),
        ("NNPA (%)",             "nnpa"),
        ("PCR (%)",              "pcr"),
        ("CASA Ratio (%)",       "casa_ratio"),
        ("Capital Adequacy (%)", "capital_adequacy"),
        ("Tier 1 Ratio (%)",     "tier1_ratio"),
        ("ROE (%)",              "roe"),
        ("ROA (%)",              "roa"),
        ("Credit Growth (%)",    "credit_growth"),
        ("Slippage Ratio (%)",   "slippage_ratio"),
    ])

    # PDF labels
    pl_label:        str = "NII (₹ bn)"
    ebitda_label:    str = "Operating Profit"
    pat_label:       str = "PAT (₹ bn)"
    currency_symbol: str = "₹"
    unit_suffix:     str = "bn"
    unit_label:      str = "₹ bn"

    # Chart config
    chart_title:         str = "NII & PAT Trend"
    revenue_chart_label: str = "NII"
    margin_chart_title:  str = "Asset Quality & Margins (%)"

    # Extraction
    extraction_keys: str = (
        "nii, nim, advances, deposits, casa_ratio, gnpa, nnpa, pcr, "
        "roe, roa, capital_adequacy, tier1_ratio, pat, eps, net_interest_income, "
        "credit_growth, slippage_ratio, provision_expense, "
        "depreciation, interest, other_income, pbt, tax, tax_rate, "
        "accounts_receivable, inventories, gross_fixed_assets, current_liabilities, "
        "provisions, investments, pe_ratio, pbv_ratio, ev_ebitda, ebitda_margin, pat_margin, roce, "
        "net_worth, borrowings, book_value, total_assets, total_liabilities, "
        "operating_cash_flow, investing_cash_flow, financing_cash_flow"
    )
    extraction_hints: str = (
        "Look for: Net Interest Income (NII), Net Interest Margin (NIM%), "
        "Gross NPA%, Net NPA%, Provision Coverage Ratio (PCR%), "
        "Capital Adequacy Ratio (CAR/CRAR%), CASA Ratio%, "
        "Total Advances, Total Deposits, PAT, EPS, ROE%, ROA%. "
        "Also extract full P&L items: Depreciation, Interest, Other Income, PBT, Tax, Tax Rate. "
        "Also extract full Balance Sheet items: Net Worth (Equity), Borrowings (Debt), "
        "Accounts Receivable, Inventories, Fixed Assets, Current Liabilities, Provisions, Investments, "
        "Book Value per share, Total Assets, Total Liabilities. "
        "Extract Cash Flow items: Operating CF, Investing CF, Financing CF."
    )
