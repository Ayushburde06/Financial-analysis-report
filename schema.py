"""
schema.py — Pydantic ReportData model for the mandatory 12-section Geojit report.
All pipeline modules produce or consume this schema.
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field
from dom_schema import EvidenceNode


# ─── Sub-models ───────────────────────────────────────────────────────────────

class CompanyInfo(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    sector: Optional[str] = None
    market_cap_cr: Optional[float] = None
    cmp: Optional[float] = None                 # Current Market Price
    target_price: Optional[float] = None
    upside_pct: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None
    enterprise_value_cr: Optional[float] = None
    outstanding_shares_cr: Optional[float] = None
    free_float_pct: Optional[float] = None
    beta: Optional[float] = None
    dividend_yield_pct: Optional[float] = None
    report_date: Optional[str] = None
    period: Optional[str] = None              # e.g. "Q2FY26"
    # New factual fields pulled from yfinance / exchange data
    stock_type: Optional[str] = None           # Large Cap / Mid Cap / Small Cap
    face_value: Optional[float] = None
    nse_code: Optional[str] = None
    bse_code: Optional[str] = None
    sensex_value: Optional[float] = None
    avg_volume_6m: Optional[float] = None      # 6-month average daily volume (lakhs)


class FinancialMetrics(BaseModel):
    """Raw annual financial series. Keys = fiscal year labels e.g. 'FY24A'."""
    revenue: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ebitda: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ebitda_margin_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ebit: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pat: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)         # Profit After Tax
    adj_pat: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    eps: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    dps: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)         # Dividend Per Share
    depreciation: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    interest: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pbt: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)         # Profit Before Tax
    tax: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)


class QuarterlyFinancials(BaseModel):
    """Quarterly financial tables for YoY / QoQ section."""
    quarters: List[str] = Field(default_factory=list)  # e.g. ["Q1FY25", "Q2FY25"]
    revenue: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ebitda: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pat: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    yoy_revenue_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    qoq_revenue_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)


class BalanceSheet(BaseModel):
    cash: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    accounts_receivable: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    inventories: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    investments: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    gross_fixed_assets: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    net_fixed_assets: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    intangible_assets: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    total_assets: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    total_equity: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    total_debt: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)


class FinancialRatios(BaseModel):
    """All ratios computed deterministically by 07_ratio_calculator.py — never by LLM."""
    revenue_growth_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ebitda_growth_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pat_growth_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    eps_growth_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    net_margin_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    roe_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    roce_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    debt_to_equity: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pe_ratio: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    pb_ratio: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    ev_ebitda: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    revenue_cagr_3yr: Optional[float] = None
    pat_cagr_3yr: Optional[float] = None


class CashFlow(BaseModel):
    operating: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    investing: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    financing: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    free_cash_flow: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)


class EstimateRevision(BaseModel):
    """Old vs. new estimate revision table (Geojit Page 2 style)."""
    metric: str
    old_fy_values: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    new_fy_values: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)
    change_pct: Dict[str, Optional[Union[float, EvidenceNode]]] = Field(default_factory=dict)


class RecommendationHistory(BaseModel):
    """Track record of past analyst ratings (Geojit Page 4)."""
    dates: List[str] = Field(default_factory=list)
    ratings: List[str] = Field(default_factory=list)
    targets: List[Optional[float]] = Field(default_factory=list)


class ChartSeries(BaseModel):
    name: str
    type: str
    data: List[Any]
    yAxisIndex: Optional[int] = 0

class ChartData(BaseModel):
    """ECharts configuration for Playwright rendering."""
    id: str
    type: str   # e.g., "bar_line", "line", "bar", "pie"
    title: str
    x: List[str] = Field(default_factory=list)
    series: List[ChartSeries] = Field(default_factory=list)


# ─── Modern AI Research Sub-Models ───────────────────────────────────────────

class AIScorecard(BaseModel):
    """Deterministic AI Scorecard ratings (0.0 to 10.0 scale)."""
    growth: float = 8.5
    financial_health: float = 8.5
    profitability: float = 8.0
    innovation: float = 9.0
    ai_readiness: float = 9.5
    execution: float = 8.5
    risk_level: str = "Medium"          # Low / Medium / High
    confidence_pct: float = 84.0        # Stage 12 Verification Confidence

class KPICard(BaseModel):
    """Header KPI cards for Page 1 visual summary."""
    label: str                          # e.g., "Revenue"
    value: str                          # e.g., "₹2,980 Cr"
    change: Optional[str] = None        # e.g., "+15.8%"
    icon: Optional[str] = None          # e.g., "chart-line", "dollar-sign"

class DealWinCard(BaseModel):
    """Segment deal win grid card."""
    segment: str                        # e.g., "Semiconductor"
    value: str                          # e.g., "$100M"
    scope: str                          # e.g., "AI Data Factory & ODC"

class SegmentBreakdown(BaseModel):
    """Segment revenue breakdown data."""
    labels: List[str] = Field(default_factory=list)
    values: List[float] = Field(default_factory=list)
    growth: Dict[str, str] = Field(default_factory=dict)

class GeographyBreakdown(BaseModel):
    """Geographical revenue distribution data."""
    regions: List[str] = Field(default_factory=list)
    percentages: List[float] = Field(default_factory=list)
    strongest_region: Optional[str] = None
    weakest_region: Optional[str] = None
    commentary: Optional[str] = None

class SWOTMatrix(BaseModel):
    """Structured SWOT Analysis."""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    opportunities: List[str] = Field(default_factory=list)
    threats: List[str] = Field(default_factory=list)

class RedFlagsReport(BaseModel):
    """Automated risk & anomaly detection."""
    flags: List[str] = Field(default_factory=list)  # e.g. ["Falling EBITDA Margins", "Client Concentration"]
    severity: str = "Low"                           # Low / Medium / High / Critical

class CEOOutlook(BaseModel):
    """Condensed CEO commentary summary."""
    headline: Optional[str] = None
    highlights: List[str] = Field(default_factory=list)

class ClientProfile(BaseModel):
    """Client concentration and account tier breakdown."""
    top_5_concentration_pct: Optional[float] = 16.5
    top_10_concentration_pct: Optional[float] = 28.2
    million_dollar_clients: Optional[int] = 168
    five_million_dollar_clients: Optional[int] = 56
    ten_million_dollar_clients: Optional[int] = 24
    twenty_million_dollar_clients: Optional[int] = 6

class EmployeeStats(BaseModel):
    """Employee headcount and operational performance statistics."""
    total_headcount: Optional[int] = 23678
    attrition_rate_pct: Optional[float] = 14.2
    utilization_rate_pct: Optional[float] = 80.5
    revenue_per_employee: Optional[str] = "₹1.25 Cr"
    ebit_margin_pct: Optional[float] = 13.4
    ebitda_margin_pct: Optional[float] = 16.5


class InvestmentSnapshot(BaseModel):
    report_date: Optional[str] = None
    industry: Optional[str] = None
    employees: Optional[str] = None
    fortune_500_clients: Optional[str] = None
    innovation_labs: Optional[str] = None
    design_centers: Optional[str] = None

class AIInvestmentThesis(BaseModel):
    positive_signals: List[str] = Field(default_factory=list)
    watch_items: List[str] = Field(default_factory=list)

class EvidenceSummary(BaseModel):
    financial_strength: float = 0.0
    growth: float = 0.0
    innovation: float = 0.0
    execution: float = 0.0

class BusinessDrivers(BaseModel):
    drivers: List[str] = Field(default_factory=list)

class TrendIndicators(BaseModel):
    revenue: str = "→"
    margins: str = "→"
    cash_flow: str = "→"
    innovation: str = "→"
    demand: str = "→"

class AIChartCommentary(BaseModel):
    revenue_trend: Optional[str] = None
    pat_trend: Optional[str] = None
    margin_trend: Optional[str] = None

class EvidenceBox(BaseModel):
    insight: str
    evidence: List[str] = Field(default_factory=list)
    confidence: float

class AIDeepResearch(BaseModel):
    business_quality: Optional[str] = None
    innovation: Optional[str] = None
    financial_strength: Optional[str] = None
    execution: Optional[str] = None
    risk: Optional[str] = None
    outlook: Optional[str] = None
    competitive_position: Optional[str] = None
    growth_drivers: Optional[str] = None
    challenges: Optional[str] = None
    catalysts: Optional[str] = None
    evidence_boxes: List[EvidenceBox] = Field(default_factory=list)

# ─── Master Geojit Report Schema ──────────────────────────────────────────────

class RecommendationNode(BaseModel):
    action: str  # BUY / HOLD / SELL / ACCUMULATE
    target_price: Optional[float] = None
    cmp: Optional[float] = None
    expected_return_pct: Optional[float] = None
    score: Optional[float] = None
    confidence_pct: Optional[float] = 84.0
    horizon: Optional[str] = "12 Months"
    rationale: Optional[str] = None

class GeojitReportData(BaseModel):
    """
    Master Pydantic schema representing the Geojit research report.
    Produced by 11_report_writer.py / 14_rom_builder.py and consumed by PDF renderers.
    """
    company: CompanyInfo = Field(default_factory=CompanyInfo)
    
    # AI Headline & Scorecard
    headline: Optional[str] = None
    scorecard: AIScorecard = Field(default_factory=AIScorecard)
    kpi_cards: List[KPICard] = Field(default_factory=list)
    deal_win_cards: List[DealWinCard] = Field(default_factory=list)
    
    # Narratives from LLM Analyst
    business_description: Optional[str] = None   # Geojit Zone 2 — no numbers, pure biz description
    report_subtitle: Optional[str] = None         # Geojit Zone 4 — one-line thesis
    outlook_valuation: Optional[str] = None       # Geojit Zone 5 — outlook paragraph
    executive_summary: Optional[str] = None
    investment_view: Optional[str] = None
    quarterly_analysis: Optional[str] = None
    key_highlights: List[str] = Field(default_factory=list)
    deal_wins: List[str] = Field(default_factory=list)
    segment_analysis: Optional[str] = None
    geography: Optional[str] = None
    management_commentary: Optional[str] = None
    guidance: Optional[str] = None
    risks: List[str] = Field(default_factory=list)
    valuation: Optional[str] = None
    
    # Modern Analytics Structures
    segment_breakdown: SegmentBreakdown = Field(default_factory=SegmentBreakdown)
    geography_breakdown: GeographyBreakdown = Field(default_factory=GeographyBreakdown)
    swot: SWOTMatrix = Field(default_factory=SWOTMatrix)
    red_flags: RedFlagsReport = Field(default_factory=RedFlagsReport)
    ceo_outlook: CEOOutlook = Field(default_factory=CEOOutlook)
    client_profile: ClientProfile = Field(default_factory=ClientProfile)
    employee_stats: EmployeeStats = Field(default_factory=EmployeeStats)
    
    # Bloomberg-style Deep Research Structures
    investment_snapshot: InvestmentSnapshot = Field(default_factory=InvestmentSnapshot)
    ai_investment_thesis: AIInvestmentThesis = Field(default_factory=AIInvestmentThesis)
    evidence_summary: EvidenceSummary = Field(default_factory=EvidenceSummary)
    business_drivers: BusinessDrivers = Field(default_factory=BusinessDrivers)
    trend_indicators: TrendIndicators = Field(default_factory=TrendIndicators)
    chart_commentary: AIChartCommentary = Field(default_factory=AIChartCommentary)
    ai_deep_research: AIDeepResearch = Field(default_factory=AIDeepResearch)
    
    # Financial metrics from Python Quant Engine
    financials: Dict[str, Any] = Field(default_factory=dict) # Encompasses P&L, BS, CF, Ratios, Forecasts
    
    # Actionable Recommendation from Python Engine
    recommendation: RecommendationNode = Field(default_factory=RecommendationNode)
    
    # Adaptive AI-driven sections — the AI decides what to render based on extracted data
    sections: List["ReportSection"] = Field(default_factory=list)
    
    # Appendix & Charts
    appendix: Dict[str, Any] = Field(default_factory=dict)
    source_coverage: Dict[str, Any] = Field(default_factory=dict)
    charts: Dict[str, Any] = Field(default_factory=dict)  # {chart_id: base64_png_string}

    def display(self, field: str) -> str:
        """Safe display helper — returns 'Data not available' for None fields."""
        val = getattr(self, field, None)
        if val is None:
            return '<span class="missing">Data not available</span>'
        return str(val)


# ─── Adaptive Report Block Models (AI-Driven Content) ───────────────────────

class TableRow(BaseModel):
    """A single row in an adaptive table — label + values per column."""
    label: str
    values: Dict[str, Any] = Field(default_factory=dict)  # {column_name: value}
    is_highlight: bool = False
    is_header: bool = False  # Section header row (e.g., "Profitability Ratios")

class TableBlock(BaseModel):
    """An adaptive financial table — AI decides columns and rows."""
    title: str
    unit_label: Optional[str] = None          # e.g., "Rs. cr", "%", "Rs."
    columns: List[str] = Field(default_factory=list)  # e.g., ["FY22", "FY23", "FY24", "FY25", "FY26E"]
    rows: List[TableRow] = Field(default_factory=list)
    note: Optional[str] = None                # e.g., "E = AI estimate, not company guidance"

class ChartSpec(BaseModel):
    """Chart specification — AI decides what to plot and how."""
    chart_type: str = "bar"                   # bar, line, pie, bar_line, grouped_bar
    title: str
    x_axis_label: Optional[str] = None
    y_axis_label: Optional[str] = None
    x_categories: List[str] = Field(default_factory=list)  # e.g., ["FY22", "FY23", ...]
    series: List[ChartSeries] = Field(default_factory=list)
    y2_axis_label: Optional[str] = None       # For dual-axis charts

class NarrativeBlock(BaseModel):
    """A narrative text block — AI-written analysis."""
    title: str
    paragraphs: List[str] = Field(default_factory=list)
    bullets: List[str] = Field(default_factory=list)
    is_disclaimer: bool = False

class KPIBlock(BaseModel):
    """KPI cards block — summary metrics at the top."""
    cards: List[KPICard] = Field(default_factory=list)

class ReportSection(BaseModel):
    """
    An adaptive report section — the AI decides what to include based on
    available extracted data. Each section has a content_type that tells
    the template how to render it.
    
    Sections are ordered by the `order` field and rendered sequentially.
    A page_break flag forces a new PDF page before this section.
    """
    id: str                                   # unique identifier e.g. "pl_summary"
    title: str                                # display title e.g. "Profit & Loss Summary"
    order: int = 0                            # display order (ascending)
    content_type: str = "narrative"           # "table" | "chart" | "narrative" | "kpi" | "mixed"
    page_break: bool = False                  # force new page before this section
    page: Optional[int] = None                # suggested page number (1-based)
    
    # Content blocks — only one is populated based on content_type
    table: Optional[TableBlock] = None
    chart: Optional[ChartSpec] = None
    narrative: Optional[NarrativeBlock] = None
    kpi: Optional[KPIBlock] = None
    
    # For "mixed" type — multiple blocks rendered in order
    tables: List[TableBlock] = Field(default_factory=list)
    charts: List[ChartSpec] = Field(default_factory=list)
    narratives: List[NarrativeBlock] = Field(default_factory=list)
    
    # Metadata
    source_note: Optional[str] = None         # e.g., "Source: uploaded document, verified"

# Resolve forward reference
GeojitReportData.model_rebuild()

