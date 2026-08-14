"""
Stage 16: Adaptive Section Planner

Does not replace the Geojit 4-page frame. It only structures verified data
(year columns from this filing, hide empty tables) for optional section use.
"""
import re
import importlib
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from schema import (
    ReportSection, TableBlock, TableRow, ChartSpec, ChartSeries,
    NarrativeBlock, KPIBlock, KPICard,
)


def _sort_years(years: List[str]) -> List[str]:
    """Sort fiscal year labels chronologically. Handles FY20, FY21A, FY26E, etc."""
    def _key(y):
        nums = re.findall(r"\d+", y)
        num = int(nums[0]) if nums else 0
        if num > 100:
            num = num % 100
        suffix = 0 if y.upper().endswith("A") else (1 if y.upper().endswith("E") else 0)
        return (num, suffix)
    return sorted(years, key=_key)


def _has_value(val: Any) -> bool:
    """Check if a value is non-empty and non-placeholder."""
    if val is None:
        return False
    s = str(val).strip()
    return s not in ("", "—", "[N/A]", "None", "null", "NaN")


def _format_val(val: Any) -> str:
    """Format a value for display — rounds floats, handles None."""
    if not _has_value(val):
        return "—"
    try:
        f = float(str(val).replace(",", ""))
        if abs(f) >= 1000:
            return f"{f:,.0f}"
        if abs(f) >= 100:
            return f"{f:.1f}"
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(val)


class AdaptiveSectionPlanner:
    """
    Analyzes verified financial data and builds a list of ReportSection objects
    that the adaptive template renders sequentially.

    The planner is deterministic — it uses the data available, not LLM calls,
    to decide structure. LLM narratives are passed in as pre-generated text.
    """

    @staticmethod
    def plan(
        financials: Dict[str, Any],
        company_name: str,
        industry: str,
        report_period: str,
        recommendation: Any,
        narrative_sections: Dict[str, Any],
        market_data: Dict[str, Any],
        charts: Dict[str, str],
        fact_check_report: Any = None,
        appendix: Dict[str, Any] = None,
        unit_label: str = "Rs. cr",
        currency_symbol: str = "Rs.",
        segment_data: Optional[Dict[str, float]] = None,
        geo_data: Optional[Dict[str, float]] = None,
    ) -> List[ReportSection]:
        """
        Build the full list of report sections from verified data.

        Args:
            financials: The financials dict from pipeline_stage11_to_14
            company_name: Resolved company name
            industry: Detected sector
            report_period: e.g. "Q2FY26"
            recommendation: RecommendationNode
            narrative_sections: Parsed LLM narrative sections
            market_data: optional verified external market data dict
            charts: {chart_id: base64_png} from chart generator
            fact_check_report: Stage 12b verification report
            appendix: Appendix dict with provenance/quality data
            unit_label: Display unit (e.g., "Rs. cr")
            currency_symbol: Currency symbol (e.g., "Rs.")

        Returns:
            Ordered list of ReportSection objects
        """
        sections: List[ReportSection] = []
        order_counter = 0

        def _next_order():
            nonlocal order_counter
            order_counter += 1
            return order_counter

        # ── Collect ALL available year columns from data ────────────────────
        annual = financials.get("annual", {}) or {}
        forecasts = financials.get("forecasts", {}) or {}
        balance_sheet = financials.get("balance_sheet", {}) or {}
        cash_flow = financials.get("cash_flow", {}) or {}
        ratios = financials.get("ratios", {}) or {}
        quarterly = financials.get("quarterly", {}) or {}
        all_columns = financials.get("all_columns", []) or []

        # Build complete year list from all sections
        all_years_set = set()
        for section in (annual, forecasts, balance_sheet, cash_flow, ratios):
            if not isinstance(section, dict):
                continue
            for metric_data in section.values():
                if isinstance(metric_data, dict):
                    for y in metric_data.keys():
                        if re.match(r"FY\d{2,4}[AE]?$", str(y), re.IGNORECASE):
                            all_years_set.add(str(y))

        if all_columns:
            all_years = _sort_years(list(set(all_columns)))
        else:
            all_years = _sort_years(list(all_years_set))

        # Separate actual years from estimate years
        actual_years = [y for y in all_years if not y.upper().endswith("E")]
        est_years = [y for y in all_years if y.upper().endswith("E")]

        # Use the pre-rendered chart images — map chart IDs to ChartSpecs
        # for the template, but the actual images are in the charts dict
        chart_specs: Dict[str, ChartSpec] = {}

        # ── Section 1: KPI Summary (Page 1 top) ─────────────────────────────
        kpi_cards = AdaptiveSectionPlanner._build_kpi_cards(
            financials, recommendation, market_data, report_period,
            currency_symbol, unit_label
        )
        if kpi_cards:
            sections.append(ReportSection(
                id="kpi_summary",
                title="Key Metrics",
                order=_next_order(),
                content_type="kpi",
                kpi=KPIBlock(cards=kpi_cards),
                page=1,
            ))

        # ── Section 2: Company Header / Business Description ────────────────
        biz_desc = narrative_sections.get("business_description", "")
        subtitle = narrative_sections.get("report_subtitle", "")
        if biz_desc or subtitle:
            paragraphs = []
            if subtitle:
                paragraphs.append(subtitle)
            if biz_desc:
                paragraphs.append(biz_desc)
            sections.append(ReportSection(
                id="business_overview",
                title="Business Overview",
                order=_next_order(),
                content_type="narrative",
                narrative=NarrativeBlock(
                    title="Business Overview",
                    paragraphs=paragraphs,
                ),
                page=1,
            ))

        # ── Section 3: Key Highlights ───────────────────────────────────────
        highlights = narrative_sections.get("key_highlights", [])
        if highlights:
            sections.append(ReportSection(
                id="key_highlights",
                title="Key Highlights",
                order=_next_order(),
                content_type="narrative",
                narrative=NarrativeBlock(
                    title="Key Highlights",
                    bullets=highlights[:8],  # Show up to 8 highlights
                ),
                page=1,
            ))

        # ── Section 4: Quarterly Financials Table ───────────────────────────
        qtr_section = AdaptiveSectionPlanner._build_quarterly_section(
            quarterly, unit_label, report_period
        )
        if qtr_section:
            qtr_section.order = _next_order()
            qtr_section.page = 1
            sections.append(qtr_section)

        # ── Section 5: Outlook & Valuation ──────────────────────────────────
        outlook = narrative_sections.get("outlook_valuation", "")
        if outlook:
            sections.append(ReportSection(
                id="outlook_valuation",
                title="Outlook & Valuation",
                order=_next_order(),
                content_type="narrative",
                narrative=NarrativeBlock(
                    title="Outlook & Valuation",
                    paragraphs=[outlook],
                ),
                page=1,
            ))

        # ── PAGE 2: Charts + Detailed Financials ────────────────────────────

        # ── Section 6: Story in Charts ──────────────────────────────────────
        if charts:
            chart_section = AdaptiveSectionPlanner._build_charts_section(charts)
            if chart_section:
                chart_section.order = _next_order()
                chart_section.page_break = True
                chart_section.page = 2
                sections.append(chart_section)

        # ── Section 7: P&L Annual Table ─────────────────────────────────────
        pl_section = AdaptiveSectionPlanner._build_pl_table(
            annual, forecasts, actual_years, est_years, unit_label
        )
        if pl_section:
            pl_section.order = _next_order()
            pl_section.page = 2
            sections.append(pl_section)

        # ── Section 8: Balance Sheet Table ──────────────────────────────────
        bs_section = AdaptiveSectionPlanner._build_balance_sheet_table(
            balance_sheet, all_years, unit_label
        )
        if bs_section:
            bs_section.order = _next_order()
            bs_section.page = 2
            sections.append(bs_section)

        # ── Section 9: Cash Flow Table ──────────────────────────────────────
        cf_section = AdaptiveSectionPlanner._build_cash_flow_table(
            cash_flow, all_years, unit_label
        )
        if cf_section:
            cf_section.order = _next_order()
            cf_section.page = 3
            sections.append(cf_section)

        # ── Section 10: Ratios Table ────────────────────────────────────────
        ratios_section = AdaptiveSectionPlanner._build_ratios_table(
            ratios, all_years, financials.get("is_banking_sector", False)
        )
        if ratios_section:
            ratios_section.order = _next_order()
            ratios_section.page = 3
            sections.append(ratios_section)

        # ── Section 11: Forward Estimates ───────────────────────────────────
        est_section = AdaptiveSectionPlanner._build_estimates_section(
            forecasts, unit_label
        )
        if est_section:
            est_section.order = _next_order()
            est_section.page = 3
            sections.append(est_section)

        # ── Section 11b: Investment Scenarios (Bull/Base/Bear) ────────────────
        scenarios = financials.get("scenarios", []) or []
        if scenarios:
            scen_section = AdaptiveSectionPlanner._build_scenarios_section(
                scenarios, cmp=getattr(recommendation, "cmp", None)
            )
            if scen_section:
                scen_section.order = _next_order()
                scen_section.page = 3
                sections.append(scen_section)

        # ── Section 12: Change in Estimates ─────────────────────────────────
        cie = financials.get("change_in_estimates", {}) or {}
        if cie:
            cie_section = AdaptiveSectionPlanner._build_change_in_estimates_section(
                cie, unit_label
            )
            if cie_section:
                cie_section.order = _next_order()
                cie_section.page = 3
                sections.append(cie_section)

        # ── Section 13: Sector-Specific Extra Metrics ───────────────────────
        extra_metrics = financials.get("extra_metrics", []) or []
        extra_periods = financials.get("extra_metric_periods", []) or []
        if extra_metrics:
            extra_section = AdaptiveSectionPlanner._build_extra_metrics_section(
                extra_metrics, extra_periods, industry
            )
            if extra_section:
                extra_section.order = _next_order()
                extra_section.page = 3
                sections.append(extra_section)

        # ── Section 14: Segment Breakdown ───────────────────────────────────
        _seg = segment_data or {}
        if not _seg and financials.get("segment_breakdown"):
            sb = financials.get("segment_breakdown") or {}
            labels = sb.get("labels", []) or []
            values = sb.get("values", []) or []
            if labels and values:
                _seg = {str(l): float(v) for l, v in zip(labels, values) if v}
        seg_section = AdaptiveSectionPlanner._build_segment_section(_seg, unit_label)
        if seg_section:
            seg_section.order = _next_order()
            seg_section.page = 3
            sections.append(seg_section)

        # ── Section 15: Valuation Summary ───────────────────────────────────
        vt = financials.get("valuation_table", {}) or {}
        if vt and vt.get("multiples"):
            val_section = AdaptiveSectionPlanner._build_valuation_summary(vt)
            if val_section:
                val_section.order = _next_order()
                val_section.page = 3
                sections.append(val_section)

        # ── Section 16: Market Data / Company Snapshot ──────────────────────
        mkt_section = AdaptiveSectionPlanner._build_market_data_section(
            market_data, recommendation, report_period
        )
        if mkt_section:
            mkt_section.order = _next_order()
            mkt_section.page = 3
            sections.append(mkt_section)

        # ── Section 17: Verification & Provenance ───────────────────────────
        prov_section = AdaptiveSectionPlanner._build_provenance_section(
            fact_check_report, appendix
        )
        if prov_section:
            prov_section.order = _next_order()
            prov_section.page = 3
            sections.append(prov_section)

        # ── Section 18: Recommendation Summary ──────────────────────────────
        rec_section = AdaptiveSectionPlanner._build_recommendation_section(
            recommendation, report_period, market_data
        )
        if rec_section:
            rec_section.order = _next_order()
            rec_section.page_break = True
            rec_section.page = 4
            sections.append(rec_section)

        # ── Section 19: Disclaimer ──────────────────────────────────────────
        sections.append(ReportSection(
            id="disclaimer",
            title="Disclaimer & Disclosures",
            order=_next_order(),
            content_type="narrative",
            narrative=NarrativeBlock(
                title="Disclaimer & Disclosures",
                paragraphs=[
                    "This report is generated from the uploaded company document using an AI-assisted research pipeline. Historical figures are extracted from the source file and checked against it before publication.",
                    "Narrative text is AI-generated and is not human analyst opinion. Ratios, growth rates and other derived values are calculated from verified source facts. Forward estimates are model outputs, not company guidance.",
                    "If a field is not present in the source document, it is shown as 'Not available in source document'. No missing value is treated as a confirmed company fact.",
                    "Where shown, CMP, market capitalisation, beta and performance data are live market-data fields and may change after report generation.",
                    "Investments in securities are subject to market risks. Read all relevant offer documents and risk disclosures carefully before making an investment decision.",
                    "This report is an analytical output for internal review. It is not investment advice, a solicitation, or a substitute for independent professional advice.",
                ],
                is_disclaimer=True,
            ),
            page=4,
        ))

        print(f"     [Section Planner] Built {len(sections)} sections: "
              f"{[s.id for s in sections]}")
        return sections

    # ─── Helper: Build KPI cards from latest data ────────────────────────────

    @staticmethod
    def _build_kpi_cards(
        financials: Dict, recommendation: Any, market_data: Dict,
        report_period: str, currency_symbol: str, unit_label: str
    ) -> List[KPICard]:
        cards = []
        quarterly = financials.get("quarterly", {}) or {}
        annual = financials.get("annual", {}) or {}

        # Revenue KPI
        rev_q = quarterly.get("revenue", {})
        qtrs = quarterly.get("quarters", [])
        if qtrs and rev_q:
            latest_q = qtrs[-1] if qtrs else None
            rev_val = rev_q.get(latest_q)
            if _has_value(rev_val):
                yoy = quarterly.get("revenue_yoy", {}).get(latest_q)
                cards.append(KPICard(
                    label="Revenue",
                    value=f"{currency_symbol} {_format_val(rev_val)} {unit_label.split()[-1] if ' ' in unit_label else unit_label}",
                    change=f"{yoy}%" if _has_value(yoy) else None,
                    icon="chart-line",
                ))

        # PAT KPI
        pat_q = quarterly.get("pat", {})
        if qtrs and pat_q:
            latest_q = qtrs[-1]
            pat_val = pat_q.get(latest_q)
            if _has_value(pat_val):
                yoy = quarterly.get("pat_yoy", {}).get(latest_q)
                cards.append(KPICard(
                    label="PAT",
                    value=f"{currency_symbol} {_format_val(pat_val)} {unit_label.split()[-1] if ' ' in unit_label else unit_label}",
                    change=f"{yoy}%" if _has_value(yoy) else None,
                    icon="dollar-sign",
                ))

        # CMP KPI
        cmp = market_data.get("cmp") or getattr(recommendation, "cmp", None)
        if _has_value(cmp):
            cards.append(KPICard(
                label="CMP",
                value=f"{currency_symbol} {_format_val(cmp)}",
                icon="trending-up",
            ))

        # Target / Upside KPI
        target = getattr(recommendation, "target_price", None)
        upside = getattr(recommendation, "expected_return_pct", None)
        if _has_value(target):
            cards.append(KPICard(
                label="Target",
                value=f"{currency_symbol} {_format_val(target)}",
                change=f"{upside}%" if _has_value(upside) else None,
                icon="target",
            ))

        # Market Cap KPI
        mcap = market_data.get("market_cap_cr")
        if _has_value(mcap):
            cards.append(KPICard(
                label="Market Cap",
                value=f"{currency_symbol} {_format_val(mcap)} cr",
                icon="building",
            ))

        # Rating KPI
        action = getattr(recommendation, "action", None)
        if _has_value(action):
            cards.append(KPICard(
                label="Rating",
                value=action,
                icon="star",
            ))

        return cards[:6]  # Max 6 KPI cards

    # ─── Helper: Build quarterly financials section ──────────────────────────

    @staticmethod
    def _build_quarterly_section(
        quarterly: Dict, unit_label: str, report_period: str
    ) -> Optional[ReportSection]:
        qtrs = quarterly.get("quarters", [])
        if not qtrs:
            return None

        columns = list(qtrs) + ["YoY (%)", "QoQ (%)"]
        rows = []
        latest_q = qtrs[-1]

        # Define which metrics to show
        metric_configs = [
            ("revenue", "Revenue"),
            ("ebitda", "EBITDA"),
            ("ebitda_margin", "EBITDA Margin (%)"),
            ("ebit", "EBIT"),
            ("pbt", "PBT"),
            ("pat", "PAT"),
            ("pat_margin", "PAT Margin (%)"),
            ("eps", "Adj EPS (Rs.)"),
        ]

        for key, label in metric_configs:
            data = quarterly.get(key, {})
            if not data or not any(_has_value(data.get(q)) for q in qtrs):
                continue

            values = {}
            for q in qtrs:
                values[q] = _format_val(data.get(q))

            # YoY / QoQ
            yoy_key = f"{key}_yoy"
            qoq_key = f"{key}_qoq"
            yoy_data = quarterly.get(yoy_key, {})
            qoq_data = quarterly.get(qoq_key, {})
            values["YoY (%)"] = _format_val(yoy_data.get(latest_q))
            values["QoQ (%)"] = _format_val(qoq_data.get(latest_q))

            is_hl = key in ("revenue", "pat")
            rows.append(TableRow(label=label, values=values, is_highlight=is_hl))

        if not rows:
            return None

        return ReportSection(
            id="quarterly_financials",
            title="Quarterly Financials",
            content_type="table",
            table=TableBlock(
                title="Quarterly Financials",
                unit_label=unit_label,
                columns=columns,
                rows=rows,
            ),
        )

    # ─── Helper: Build charts section ────────────────────────────────────────

    @staticmethod
    def _build_charts_section(charts: Dict[str, str]) -> Optional[ReportSection]:
        if not charts:
            return None

        # The charts are already rendered as base64 PNG images.
        # We create a "mixed" section that references them by ID.
        # The template will look up the image from report.charts dict.
        chart_narratives = []
        for chart_id, b64 in charts.items():
            if isinstance(b64, str) and len(b64) > 100:
                # Create a display title for each chart
                title_map = {
                    "chart_revenue_trend": "Revenue Trend",
                    "chart_pat_trend": "PAT & EPS Trend",
                    "chart_margin": "Margin Breakdown",
                    "chart_quarterly": "Quarterly Performance",
                    "chart_segment_pie": "Revenue by Segment",
                    "chart_geo_pie": "Revenue by Geography",
                    "chart_asset_quality": "Asset Quality (NIM & GNPA)",
                }
                title = title_map.get(chart_id, chart_id.replace("chart_", "").replace("_", " ").title())

        return ReportSection(
            id="story_in_charts",
            title="Story in Charts",
            content_type="chart",
            source_note="Charts use validated source data only.",
        )

    # ─── Helper: Build P&L table ─────────────────────────────────────────────

    @staticmethod
    def _build_pl_table(
        annual: Dict, forecasts: Dict, actual_years: List[str],
        est_years: List[str], unit_label: str
    ) -> Optional[ReportSection]:
        all_cols = actual_years + est_years
        if not all_cols:
            return None

        metric_configs = [
            ("revenue", "Revenue"),
            ("ebitda", "EBITDA"),
            ("depreciation", "Depreciation"),
            ("ebit", "EBIT"),
            ("interest", "Interest"),
            ("pbt", "PBT"),
            ("tax", "Tax"),
            ("pat", "PAT"),
            ("eps", "Adj EPS (Rs.)"),
        ]

        rows = []
        for key, label in metric_configs:
            ann_data = annual.get(key, {}) or {}
            fc_data = forecasts.get(key, {}) or {}
            values = {}
            has_any = False
            for y in all_cols:
                val = ann_data.get(y) if y in actual_years else fc_data.get(y)
                if _has_value(val):
                    values[y] = _format_val(val)
                    has_any = True
                else:
                    values[y] = "—"
            if has_any:
                is_hl = key in ("revenue", "pat")
                rows.append(TableRow(label=label, values=values, is_highlight=is_hl))

        if not rows:
            return None

        return ReportSection(
            id="pl_annual",
            title="Profit & Loss (Annual)",
            content_type="table",
            table=TableBlock(
                title="Consolidated P&L",
                unit_label=unit_label,
                columns=["Y.E March"] + all_cols,
                rows=rows,
                note="E = AI estimate, not company guidance" if est_years else None,
            ),
        )

    # ─── Helper: Build Balance Sheet table ───────────────────────────────────

    @staticmethod
    def _build_balance_sheet_table(
        bs: Dict, all_years: List[str], unit_label: str
    ) -> Optional[ReportSection]:
        if not all_years or not bs:
            return None

        metric_configs = [
            ("cash", "Cash & Equivalents"),
            ("receivables", "Accounts Receivable"),
            ("inventories", "Inventories"),
            ("investments", "Investments"),
            ("gross_fixed_assets", "Gross Fixed Assets"),
            ("net_fixed_assets", "Net Fixed Assets"),
            ("total_assets", "Total Assets"),
            ("total_debt", "Total Debt"),
            ("total_equity", "Shareholder Funds"),
        ]

        rows = []
        for key, label in metric_configs:
            data = bs.get(key, {}) or {}
            values = {}
            has_any = False
            for y in all_years:
                val = data.get(y)
                if _has_value(val):
                    values[y] = _format_val(val)
                    has_any = True
                else:
                    values[y] = "—"
            if has_any:
                is_hl = key in ("total_assets", "total_equity")
                rows.append(TableRow(label=label, values=values, is_highlight=is_hl))

        if not rows:
            return None

        return ReportSection(
            id="balance_sheet",
            title="Balance Sheet",
            content_type="table",
            table=TableBlock(
                title="Balance Sheet",
                unit_label=unit_label,
                columns=["Y.E March"] + all_years,
                rows=rows,
            ),
        )

    # ─── Helper: Build Cash Flow table ───────────────────────────────────────

    @staticmethod
    def _build_cash_flow_table(
        cf: Dict, all_years: List[str], unit_label: str
    ) -> Optional[ReportSection]:
        if not all_years or not cf:
            return None

        metric_configs = [
            ("operating", "Operating Cash Flow"),
            ("investing", "Investing Cash Flow"),
            ("financing", "Financing Cash Flow"),
            ("free_cash_flow", "Free Cash Flow"),
        ]

        rows = []
        for key, label in metric_configs:
            data = cf.get(key, {}) or {}
            values = {}
            has_any = False
            for y in all_years:
                val = data.get(y)
                if _has_value(val):
                    values[y] = _format_val(val)
                    has_any = True
                else:
                    values[y] = "—"
            if has_any:
                is_hl = key == "operating"
                rows.append(TableRow(label=label, values=values, is_highlight=is_hl))

        if not rows:
            return None

        return ReportSection(
            id="cash_flow",
            title="Cash Flow Statement",
            content_type="table",
            table=TableBlock(
                title="Cash Flow",
                unit_label=unit_label,
                columns=["Y.E March"] + all_years,
                rows=rows,
            ),
        )

    # ─── Helper: Build Ratios table ──────────────────────────────────────────

    @staticmethod
    def _build_ratios_table(
        ratios: Dict, all_years: List[str], is_banking: bool
    ) -> Optional[ReportSection]:
        if not all_years or not ratios:
            return None

        rows = []

        # Header: Profitability & Return
        has_profit = any(_has_value((ratios.get(k, {}) or {}).get(y))
                         for k in ("ebitda_margin", "net_margin", "roe", "roa", "roce")
                         for y in all_years)
        if has_profit:
            rows.append(TableRow(label="Profitability & Return", values={}, is_header=True))
            for key, label in [("ebitda_margin", "EBITDA Margin (%)"),
                               ("net_margin", "Net Margin (%)"),
                               ("roe", "ROE (%)"),
                               ("roa", "ROA (%)"),
                               ("roce", "ROCE (%)")]:
                data = ratios.get(key, {}) or {}
                values = {}
                has_any = False
                for y in all_years:
                    val = data.get(y)
                    if _has_value(val):
                        values[y] = _format_val(val)
                        has_any = True
                    else:
                        values[y] = "—"
                if has_any:
                    rows.append(TableRow(label=label, values=values))

        # Header: Growth
        has_growth = any(_has_value((ratios.get(k, {}) or {}).get(y))
                         for k in ("rev_growth", "pat_growth")
                         for y in all_years)
        if has_growth:
            rows.append(TableRow(label="Growth", values={}, is_header=True))
            for key, label in [("rev_growth", "Revenue Growth (%)"),
                               ("pat_growth", "PAT Growth (%)")]:
                data = ratios.get(key, {}) or {}
                values = {}
                has_any = False
                for y in all_years:
                    val = data.get(y)
                    if _has_value(val):
                        v = float(str(val).replace(",", ""))
                        values[y] = f"{v}%" if v >= 0 else f"{v}%"
                        has_any = True
                    else:
                        values[y] = "—"
                if has_any:
                    rows.append(TableRow(label=label, values=values))

        # Header: Leverage & Valuation
        has_lev = any(_has_value((ratios.get(k, {}) or {}).get(y))
                      for k in ("de", "pe", "pb", "ev_ebitda")
                      for y in all_years)
        if has_lev:
            rows.append(TableRow(label="Leverage & Valuation", values={}, is_header=True))
            lev_configs = [("de", "D/E (x)"), ("pe", "P/E (x)"), ("pb", "P/B (x)")]
            if not is_banking:
                lev_configs.append(("ev_ebitda", "EV/EBITDA (x)"))
            for key, label in lev_configs:
                data = ratios.get(key, {}) or {}
                values = {}
                has_any = False
                for y in all_years:
                    val = data.get(y)
                    if _has_value(val):
                        values[y] = _format_val(val)
                        has_any = True
                    else:
                        values[y] = "—"
                if has_any:
                    rows.append(TableRow(label=label, values=values))

        if not rows:
            return None

        return ReportSection(
            id="ratios",
            title="Financial Ratios",
            content_type="table",
            table=TableBlock(
                title="Key Ratios",
                columns=["Y.E March"] + all_years,
                rows=rows,
            ),
        )

    # ─── Helper: Build Forward Estimates section ─────────────────────────────

    @staticmethod
    def _build_estimates_section(
        forecasts: Dict, unit_label: str
    ) -> Optional[ReportSection]:
        if not forecasts:
            return None

        # Get estimate year labels from the data
        est_years = []
        for key in ("revenue", "ebitda", "pat", "eps"):
            data = forecasts.get(key, {}) or {}
            for y in data.keys():
                if y not in est_years:
                    est_years.append(y)
        est_years = _sort_years(est_years)

        if not est_years:
            return None

        rows = []
        for key, label in [("revenue", "Revenue"),
                           ("ebitda", "EBITDA"),
                           ("pat", "PAT"),
                           ("eps", "EPS (Rs.)")]:
            data = forecasts.get(key, {}) or {}
            values = {}
            has_any = False
            for y in est_years:
                val = data.get(y)
                if _has_value(val):
                    values[y] = _format_val(val)
                    has_any = True
                else:
                    values[y] = "—"
            if has_any:
                rows.append(TableRow(label=label, values=values))

        if not rows:
            return None

        return ReportSection(
            id="forward_estimates",
            title="Forward Estimates Summary",
            content_type="table",
            table=TableBlock(
                title="Forward Estimates",
                unit_label=unit_label,
                columns=["Metric"] + est_years,
                rows=rows,
                note="AI-projected, not company guidance",
            ),
        )

    # ─── Helper: Build Scenarios section ─────────────────────────────────────

    @staticmethod
    def _build_scenarios_section(
        scenarios: List[Dict[str, Any]], cmp: Optional[float] = None
    ) -> Optional[ReportSection]:
        if not scenarios:
            return None

        rows = []
        for s in scenarios:
            label = s.get("label", "Scenario")
            target = s.get("target_price")
            prob = s.get("probability_pct")
            upside = s.get("upside_pct")
            catalysts = s.get("catalysts", [])
            values = {
                "Probability": f"{prob}%" if prob is not None else "—",
                "Target (Rs.)": _format_val(target),
                "Return (%)": (
                    f"{upside:+.1f}%" if isinstance(upside, (int, float)) else "—"
                ),
                "Catalysts": "; ".join(catalysts[:2]) if catalysts else "—",
            }
            rows.append(TableRow(
                label=label,
                values=values,
                is_highlight=(label == "Base Case"),
            ))

        cols = ["Scenario", "Probability", "Target (Rs.)", "Return (%)", "Catalysts"]
        return ReportSection(
            id="investment_scenarios",
            title="Investment Scenarios",
            content_type="table",
            table=TableBlock(
                title="Bull / Base / Bear Scenarios",
                columns=cols,
                rows=rows,
                note="Probabilities and targets are model-derived; not company guidance",
            ),
        )

    # ─── Helper: Build Change in Estimates section ───────────────────────────

    @staticmethod
    def _build_change_in_estimates_section(
        cie: Dict, unit_label: str
    ) -> Optional[ReportSection]:
        if not cie:
            return None

        # Get estimate year labels from first entry
        est_years = []
        for metric, row in cie.items():
            if isinstance(row, dict):
                for y in (row.get("old", {}) or {}).keys():
                    if y not in est_years:
                        est_years.append(y)
            break
        est_years = _sort_years(est_years)
        if not est_years:
            return None

        rows = []
        for metric, row in cie.items():
            if not isinstance(row, dict):
                continue
            old = row.get("old", {}) or {}
            new = row.get("new", {}) or {}
            chg = row.get("change_pct", {}) or {}

            values = {}
            for y in est_years:
                old_v = _format_val(old.get(y))
                new_v = _format_val(new.get(y))
                chg_v = chg.get(y)
                if _has_value(chg_v):
                    try:
                        cv = float(str(chg_v).replace(",", ""))
                        chg_str = f"+{cv}%" if cv > 0 else f"{cv}%"
                    except (TypeError, ValueError):
                        chg_str = str(chg_v)
                else:
                    chg_str = "—"
                values[y] = f"{old_v} → {new_v} ({chg_str})"

            if any(v != "— → — (—)" for v in values.values()):
                rows.append(TableRow(label=metric, values=values))

        if not rows:
            return None

        return ReportSection(
            id="change_in_estimates",
            title="Change in Estimates",
            content_type="table",
            table=TableBlock(
                title="Change in Estimates (Old → New)",
                unit_label=unit_label,
                columns=["Metric"] + est_years,
                rows=rows,
                note="Old baseline vs New AI projections",
            ),
        )

    # ─── Helper: Build Extra Metrics section ─────────────────────────────────

    @staticmethod
    def _build_extra_metrics_section(
        extra_metrics: List, extra_periods: List, industry: str
    ) -> Optional[ReportSection]:
        if not extra_metrics:
            return None

        cols = ["Metric"] + list(extra_periods)
        rows = []
        for row in extra_metrics:
            if not isinstance(row, dict):
                continue
            label = row.get("metric", "")
            values = {}
            for p in extra_periods:
                values[p] = _format_val(row.get(p))
            rows.append(TableRow(label=label, values=values))

        if not rows:
            return None

        return ReportSection(
            id="extra_metrics",
            title=f"{industry} Key Metrics",
            content_type="table",
            table=TableBlock(
                title=f"{industry} Key Metrics",
                columns=cols,
                rows=rows,
            ),
        )

    # ─── Helper: Build Segment section ───────────────────────────────────────

    @staticmethod
    def _build_segment_section(
        segment_data: Dict[str, float], unit_label: str
    ) -> Optional[ReportSection]:
        """Build segment breakdown table from label→value dict."""
        if not segment_data:
            # Fallback: financials dict from pipeline
            return None

        seg_labels = []
        seg_values = []
        for k, v in segment_data.items():
            try:
                fv = float(v)
                if fv != 0:
                    seg_labels.append(str(k))
                    seg_values.append(fv)
            except (TypeError, ValueError):
                pass

        if not seg_labels:
            return None

        rows = []
        total = sum(seg_values)
        for label, val in zip(seg_labels, seg_values):
            pct = f"{val/total*100:.1f}%" if total > 0 else "—"
            rows.append(TableRow(label=label, values={
                "Revenue": _format_val(val),
                "% of Total": pct,
            }))

        return ReportSection(
            id="segment_breakdown",
            title="Segment Breakdown",
            content_type="table",
            table=TableBlock(
                title="Revenue by Segment",
                unit_label=unit_label,
                columns=["Segment", "Revenue", "% of Total"],
                rows=rows,
            ),
        )

    # ─── Helper: Build Valuation Summary ─────────────────────────────────────

    @staticmethod
    def _build_valuation_summary(vt: Dict) -> Optional[ReportSection]:
        multiples = vt.get("multiples", {}) or {}
        metrics = multiples.get("metric", []) or []
        years = [str(y) for y in (vt.get("years") or []) if y][:2]
        fy26e = multiples.get("fy26e", []) or []
        fy27e = multiples.get("fy27e", []) or []

        if not metrics or not years:
            return None

        slot_keys = years + ["—"] * (2 - len(years))
        rows = []
        for i, m in enumerate(metrics):
            values = {}
            if i < len(fy26e):
                values[slot_keys[0]] = _format_val(fy26e[i])
            if len(years) > 1 and i < len(fy27e):
                values[slot_keys[1]] = _format_val(fy27e[i])
            rows.append(TableRow(label=m, values=values))

        return ReportSection(
            id="valuation_summary",
            title="Valuation Summary",
            content_type="table",
            table=TableBlock(
                title="Valuation Multiples",
                columns=["Metric"] + years,
                rows=rows,
                note="E = AI estimates, not company guidance",
            ),
        )

    # ─── Helper: Build Market Data section ───────────────────────────────────

    @staticmethod
    def _build_market_data_section(
        market_data: Dict, recommendation: Any, report_period: str
    ) -> Optional[ReportSection]:
        if not market_data and not recommendation:
            return None

        rows = []
        fields = [
            ("cmp", "CMP (Rs.)"),
            ("market_cap_cr", "Market Cap (Rs. cr)"),
            ("enterprise_value_cr", "Enterprise Value (Rs. cr)"),
            ("week52_high", "52-Week High (Rs.)"),
            ("week52_low", "52-Week Low (Rs.)"),
            ("beta", "Beta"),
            ("free_float_pct", "Free Float (%)"),
            ("dividend_yield_pct", "Dividend Yield (%)"),
            ("outstanding_shares_cr", "Outstanding Shares (cr)"),
            ("stock_type", "Stock Type"),
            ("nse_code", "NSE Code"),
            ("bse_code", "BSE Code"),
            ("face_value", "Face Value (Rs.)"),
            ("avg_volume_6m", "6M Avg Volume (lakh)"),
            ("sensex_value", "Sensex Value"),
        ]

        for key, label in fields:
            val = market_data.get(key)
            if _has_value(val):
                rows.append(TableRow(label=label, values={"Value": _format_val(val)}))

        # Add recommendation data
        rec_action = getattr(recommendation, "action", None)
        rec_target = getattr(recommendation, "target_price", None)
        rec_upside = getattr(recommendation, "expected_return_pct", None)
        if _has_value(rec_action):
            rows.append(TableRow(label="Rating", values={"Value": str(rec_action)}))
        if _has_value(rec_target):
            rows.append(TableRow(label="Target Price (Rs.)", values={"Value": _format_val(rec_target)}))
        if _has_value(rec_upside):
            rows.append(TableRow(label="Expected Return (%)", values={"Value": _format_val(rec_upside)}))

        if not rows:
            return None

        return ReportSection(
            id="market_data",
            title="Company Snapshot",
            content_type="table",
            table=TableBlock(
                title="Market Data & Company Snapshot",
                columns=["Field", "Value"],
                rows=rows,
                source_note="Market data is shown only when verified and supplied by the report source.",
            ),
        )

    # ─── Helper: Build Provenance / Verification section ─────────────────────

    @staticmethod
    def _build_provenance_section(
        fact_check_report: Any, appendix: Dict
    ) -> Optional[ReportSection]:
        paragraphs = []
        bullets = []

        if fact_check_report:
            verified = getattr(fact_check_report, "verified_count", 0)
            total = getattr(fact_check_report, "total", 0)
            score = getattr(fact_check_report, "score", 0)
            if total > 0:
                pct = round(score * 100, 1) if score else round(verified / total * 100, 1)
                paragraphs.append(
                    f"Source verification: {verified}/{total} values confirmed "
                    f"in the uploaded document ({pct}% verified)."
                )

        if appendix:
            cs = appendix.get("cross_source_verification", {}) or {}
            if cs.get("summary"):
                paragraphs.append(f"Secondary source check: {cs['summary']}")

            research_quality = appendix.get("research_quality", {}) or {}
            if research_quality.get("review_flags"):
                bullets.extend([f"Review flag: {f}" for f in research_quality["review_flags"]])

            official_sources = appendix.get("official_sources", []) or []
            for src in official_sources:
                if isinstance(src, dict) and src.get("url"):
                    bullets.append(f"Official source: {src.get('source_type', 'Company filing')} ({src.get('period', '')})")

        # Data provenance legend
        bullets.extend([
            "Source fact = extracted and verified from uploaded document",
            "Calculated = derived deterministically from verified values",
            "AI narrative = qualitative synthesis, not human analyst opinion",
            "E = AI estimate, not company guidance",
            "N/A = unavailable in source document",
        ])

        if not paragraphs and not bullets:
            return None

        return ReportSection(
            id="verification_provenance",
            title="Verification & Data Provenance",
            content_type="narrative",
            narrative=NarrativeBlock(
                title="Verification & Data Provenance",
                paragraphs=paragraphs,
                bullets=bullets,
            ),
        )

    # ─── Helper: Build Recommendation section ────────────────────────────────

    @staticmethod
    def _build_recommendation_section(
        recommendation: Any, report_period: str, market_data: Dict
    ) -> Optional[ReportSection]:
        action = getattr(recommendation, "action", None)
        if not _has_value(action):
            return None

        rows = []
        rows.append(TableRow(
            label=report_period or "Current",
            values={
                "Rating": str(action),
                "Target": f"Rs. {_format_val(getattr(recommendation, 'target_price', None))}",
                "CMP": f"Rs. {_format_val(getattr(recommendation, 'cmp', None) or market_data.get('cmp'))}",
            },
            is_highlight=True,
        ))

        # Rating criteria table
        criteria_rows = [
            TableRow(label="Buy", values={"Large caps": "Upside > 10%", "Midcaps": "Upside > 15%", "Small Caps": "Upside > 20%"}),
            TableRow(label="Hold", values={"Large caps": "0% - 10%", "Midcaps": "0% - 10%", "Small Caps": "0% - 10%"}),
            TableRow(label="Reduce/Sell", values={"Large caps": "Downside > 0%", "Midcaps": "Downside > 0%", "Small Caps": "Downside > 0%"}),
            TableRow(label="Not rated", values={"Large caps": "No opinion", "Midcaps": "No opinion", "Small Caps": "No opinion"}),
        ]

        return ReportSection(
            id="recommendation_summary",
            title="Recommendation Summary",
            content_type="mixed",
            tables=[
                TableBlock(
                    title="Current Recommendation",
                    columns=["Period", "Rating", "Target", "CMP"],
                    rows=rows,
                ),
                TableBlock(
                    title="Investment Rating Criteria",
                    columns=["Rating", "Large caps", "Midcaps", "Small Caps"],
                    rows=criteria_rows,
                ),
            ],
            narratives=[
                NarrativeBlock(
                    title="Rating Methodology",
                    paragraphs=[
                        "Recommendations are based on a 12-month horizon, unless otherwise specified. "
                        "The investment ratings are on absolute positive/negative return basis. "
                        "It is possible that due to volatile price fluctuation in the near to medium term, "
                        "there could be a temporary mismatch to rating.",
                        "Buy: Acquire at CMP with the target mentioned. "
                        "Hold: Hold the stock with the expected target. "
                        "Reduce: Reduce exposure due to limited upside. "
                        "Sell: Exit from the stock. "
                        "Not rated: The analyst has no investment opinion on the stock.",
                    ],
                ),
            ],
        )
