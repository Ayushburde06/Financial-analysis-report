"""
evidence_packets.py - Typed Data Contracts for the Intelligence Layer
Strict Pydantic schemas that enforce the LLM Quarantine Rule (Rule 15).
Agents only receive these structured packets, never raw OCR text.
"""
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# Base Evidence Wrappers
# ---------------------------------------------------------

class VerifiedNumber(BaseModel):
    value: Union[float, int, str] # e.g. 1240.3 or "[N/A]"
    unit: Optional[str] = None # e.g. "Cr", "Mn", "%"
    source_page: Optional[int] = None
    source_table: Optional[str] = None
    is_estimate: bool = False # True if [E]

class FinancialLineItem(BaseModel):
    # Dynamic annual storage — captures ANY fiscal year (FY20, FY21, FY26A, etc.)
    # Keys are normalized year labels like "fy20", "fy21", "fy22", ... "fy26a", etc.
    annual: Dict[str, VerifiedNumber] = Field(default_factory=dict)

    # Backward-compatible fixed fields (still populated for legacy code paths)
    fy22: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    fy23: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    fy24: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    fy25: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    fy26e: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]", is_estimate=True))
    fy27e: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]", is_estimate=True))

    q_prev_year: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]")) # e.g. Q2FY25
    q_prev_qtr: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))  # e.g. Q1FY26
    q_current: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))   # e.g. Q2FY26

    def get_annual_value(self, year_key: str) -> VerifiedNumber:
        """Retrieve a value by year key (e.g. 'fy22', 'fy26a') from fixed fields or dynamic dict."""
        key = str(year_key or "").lower().strip()
        if hasattr(self, key) and isinstance(getattr(self, key), VerifiedNumber):
            vn = getattr(self, key)
            if vn.value != "[N/A]" and vn.value is not None:
                return vn
        return self.annual.get(key, VerifiedNumber(value="[N/A]"))

    def numeric_at(self, year_key: str) -> Optional[float]:
        vn = self.get_annual_value(year_key)
        if vn and isinstance(vn.value, (int, float)):
            return float(vn.value)
        return None

    def actual_year_values(self) -> Dict[str, float]:
        """Numeric actuals only — estimate years (fyNNe) excluded."""
        out: Dict[str, float] = {}
        for yk in ("fy22", "fy23", "fy24", "fy25"):
            val = self.numeric_at(yk)
            if val is not None:
                out[yk] = val
        for yk, vn in (self.annual or {}).items():
            low = str(yk).lower()
            if low.endswith("e"):
                continue
            if vn and isinstance(vn.value, (int, float)):
                out[low] = float(vn.value)
        return out

    def all_annual_years(self) -> list:
        """Return sorted list of all year keys that have non-N/A values."""
        years = set()
        for yk in ("fy22", "fy23", "fy24", "fy25", "fy26e", "fy27e"):
            v = getattr(self, yk, None)
            if v and v.value != "[N/A]" and v.value is not None:
                years.add(yk)
        for yk, v in (self.annual or {}).items():
            if v.value != "[N/A]" and v.value is not None:
                years.add(yk)
        return sorted(years)

# ---------------------------------------------------------
# Core Financial Statements (For Agent 1: Financial Analyst)
# ---------------------------------------------------------

class ProfitAndLossPacket(BaseModel):
    revenue: FinancialLineItem
    ebitda: FinancialLineItem
    depreciation: FinancialLineItem = Field(default_factory=FinancialLineItem)
    ebit: FinancialLineItem
    interest: FinancialLineItem = Field(default_factory=FinancialLineItem)
    other_income: FinancialLineItem = Field(default_factory=FinancialLineItem)
    pbt: FinancialLineItem
    tax: FinancialLineItem = Field(default_factory=FinancialLineItem)
    tax_rate: FinancialLineItem = Field(default_factory=FinancialLineItem)
    pat: FinancialLineItem
    eps: FinancialLineItem

class BalanceSheetPacket(BaseModel):
    cash_and_equivalents: FinancialLineItem
    accounts_receivable: FinancialLineItem = Field(default_factory=FinancialLineItem)
    inventories: FinancialLineItem = Field(default_factory=FinancialLineItem)
    other_current_assets: FinancialLineItem = Field(default_factory=FinancialLineItem)
    investments: FinancialLineItem = Field(default_factory=FinancialLineItem)
    gross_fixed_assets: FinancialLineItem = Field(default_factory=FinancialLineItem)
    net_fixed_assets: FinancialLineItem = Field(default_factory=FinancialLineItem)
    cwip: FinancialLineItem = Field(default_factory=FinancialLineItem)
    intangible_assets: FinancialLineItem = Field(default_factory=FinancialLineItem)
    other_assets: FinancialLineItem = Field(default_factory=FinancialLineItem)
    total_assets: FinancialLineItem
    current_liabilities: FinancialLineItem = Field(default_factory=FinancialLineItem)
    provisions: FinancialLineItem = Field(default_factory=FinancialLineItem)
    total_debt: FinancialLineItem
    other_liabilities: FinancialLineItem = Field(default_factory=FinancialLineItem)
    total_equity: FinancialLineItem
    reserves_and_surplus: FinancialLineItem = Field(default_factory=FinancialLineItem)
    total_liabilities: FinancialLineItem

class CashFlowPacket(BaseModel):
    operating_cash_flow: FinancialLineItem
    investing_cash_flow: FinancialLineItem
    financing_cash_flow: FinancialLineItem
    free_cash_flow: FinancialLineItem

class FinancialAnalystEvidence(BaseModel):
    company_name: str
    pl: ProfitAndLossPacket
    bs: BalanceSheetPacket
    cf: CashFlowPacket
    banking_metrics: Optional[Dict[str, Any]] = None  # extra source metrics (NIM, capacity, …)
    industry: str = ""
    period_label: str = ""
    source_unit: str = ""
    business_facts: List[str] = Field(default_factory=list)
    risk_facts: List[str] = Field(default_factory=list)

# ---------------------------------------------------------
# Growth Metrics (For Agent 2: Growth Analyst)
# ---------------------------------------------------------

class GrowthMetricsPacket(BaseModel):
    revenue_yoy: FinancialLineItem
    revenue_qoq: FinancialLineItem
    ebitda_yoy: FinancialLineItem
    pat_yoy: FinancialLineItem
    eps_yoy: FinancialLineItem
    historical_revenue_cagr_3yr: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    historical_pat_cagr_3yr: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))

class SegmentPerformance(BaseModel):
    segment_name: str
    revenue_current: VerifiedNumber
    revenue_yoy: VerifiedNumber

class GrowthAnalystEvidence(BaseModel):
    company_name: str
    growth_metrics: GrowthMetricsPacket
    segments: List[SegmentPerformance] = Field(default_factory=list)

# ---------------------------------------------------------
# Risk Metrics (For Agent 3: Risk Analyst)
# ---------------------------------------------------------

class MarginMetricsPacket(BaseModel):
    ebitda_margin: FinancialLineItem
    pat_margin: FinancialLineItem

class LiquidityMetricsPacket(BaseModel):
    debt_to_equity: FinancialLineItem
    current_ratio: FinancialLineItem
    interest_coverage: FinancialLineItem

class RiskAnalystEvidence(BaseModel):
    company_name: str
    margins: MarginMetricsPacket
    liquidity: LiquidityMetricsPacket
    # Pass along specific unverified OCR narrative context (management warnings) 
    # ONLY for the Risk Analyst to ground its claims via Layer 3 verification.
    raw_management_commentary: List[str] = Field(default_factory=list)

# ---------------------------------------------------------
# Valuation Metrics (For Agent 4: Valuation Analyst)
# ---------------------------------------------------------

class ValuationMetricsPacket(BaseModel):
    current_market_price: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    market_cap: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]"))
    pe_ratio: FinancialLineItem
    ev_ebitda: FinancialLineItem
    price_to_book: FinancialLineItem
    roe: FinancialLineItem
    roce: FinancialLineItem
    target_price: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]", is_estimate=True))
    expected_return_pct: VerifiedNumber = Field(default_factory=lambda: VerifiedNumber(value="[N/A]", is_estimate=True))

class ValuationAnalystEvidence(BaseModel):
    company_name: str
    valuation_metrics: ValuationMetricsPacket
    forward_revenue_estimates: FinancialLineItem
    forward_pat_estimates: FinancialLineItem

# ---------------------------------------------------------
# Orchestrator Packet (For Agent 5: Lead Analyst)
# ---------------------------------------------------------

class LeadAnalystEvidence(BaseModel):
    company_name: str
    current_market_price: VerifiedNumber
    target_price: VerifiedNumber
    recommendation: str # "BUY", "HOLD", "SELL" - strictly determined by Python Engine
    # Inputs from prior agents
    financial_analysis_text: str
    growth_analysis_text: str
    risk_analysis_text: str
    valuation_analysis_text: str
