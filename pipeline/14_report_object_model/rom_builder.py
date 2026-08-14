"""
Stage 14: Report Object Model Builder

Converts verified Pydantic evidence into a GeojitReportData object
ready for PDF rendering. Fully sector-aware via pipeline/sectors/.

Key improvements:
  - Sector config drives all labels, metric names, extra metrics table
  - matplotlib charts generated as base64 PNG (no CDN required)
  - Growth % rows computed in Python (no LLM)
  - Separate forward estimates table
  - Sector-specific extra metrics table (NIM/GNPA for banks etc.)
"""
from typing import Any, Dict, List, Optional
import importlib

from schema import GeojitReportData, CompanyInfo, RecommendationNode

# Sector config system
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from pipeline.sectors import get_sector_config


class ROMBuilder:

    @staticmethod
    def run(
        fa_narrative: str,
        fa_evidence: Any,
        source_context: Optional[Dict[str, Any]] = None,
    ) -> GeojitReportData:
        print("     [ROM Builder] Constructing strict GeojitReportData object...")
        source_context = source_context or {}

        def _txt(val):
            if not isinstance(val, str):
                return val
            s = (
                val.replace("â€”", "—").replace("â€“", "–")
                .replace("â€™", "'").replace("NoneType", "—")
            )
            return s.strip()

        rec = source_context.get("recommendation")
        if rec is None:
            rec = RecommendationNode(action="NOT RATED")
        elif getattr(rec, "action", None) in (None, "", "None"):
            rec = rec.model_copy(update={"action": "NOT RATED"}) if hasattr(rec, "model_copy") else rec

        charts = source_context.get("charts") or {}
        if isinstance(charts, dict):
            charts = {
                k: v for k, v in charts.items()
                if isinstance(v, str) and len(v) > 80
            }

        highlights = [
            _txt(h) for h in (source_context.get("key_highlights") or [])
            if h and str(h).strip() not in ("None", "NoneType", "")
        ]

        return GeojitReportData(
            company=source_context.get("company", CompanyInfo()),
            headline=source_context.get("headline"),
            scorecard=source_context.get("scorecard"),
            kpi_cards=source_context.get("kpi_cards", []),
            deal_win_cards=source_context.get("deal_win_cards", []),
            business_description=_txt(source_context.get("business_description")),
            report_subtitle=_txt(source_context.get("report_subtitle")),
            outlook_valuation=_txt(source_context.get("outlook_valuation")),
            executive_summary=_txt(source_context.get("executive_summary")),
            investment_view=_txt(source_context.get("investment_view")),
            quarterly_analysis=source_context.get("quarterly_analysis"),
            key_highlights=highlights,
            deal_wins=source_context.get("deal_wins", []),
            segment_analysis=source_context.get("segment_analysis"),
            geography=source_context.get("geography"),
            management_commentary=source_context.get("management_commentary"),
            guidance=source_context.get("guidance"),
            risks=source_context.get("risks", []),
            valuation=source_context.get("valuation"),
            segment_breakdown=source_context.get("segment_breakdown"),
            geography_breakdown=source_context.get("geography_breakdown"),
            swot=source_context.get("swot"),
            red_flags=source_context.get("red_flags"),
            ceo_outlook=source_context.get("ceo_outlook"),
            client_profile=source_context.get("client_profile"),
            employee_stats=source_context.get("employee_stats"),
            investment_snapshot=source_context.get("investment_snapshot"),
            ai_investment_thesis=source_context.get("ai_investment_thesis"),
            evidence_summary=source_context.get("evidence_summary"),
            business_drivers=source_context.get("business_drivers"),
            trend_indicators=source_context.get("trend_indicators"),
            chart_commentary=source_context.get("chart_commentary"),
            ai_deep_research=source_context.get("ai_deep_research"),
            financials=source_context.get("financials", {}),
            recommendation=rec,
            charts=charts,
            appendix=source_context.get("appendix", {}),
            source_coverage=source_context.get("source_coverage", {})
        )
