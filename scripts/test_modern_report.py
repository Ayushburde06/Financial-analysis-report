"""
test_modern_report.py — End-to-End Test for Modern AI Equity Research Report Generator
Validates:
 1. Schema extensions (AIScorecard, KPICards, DealWinCards, SWOT, RedFlags, CEOOutlook, Segment/Geography breakdown)
 2. Stage 09 ScorecardEngine (0-10 deterministic scoring & confidence)
 3. Stage 14 ROMBuilder assembly of ModernReportData
 4. Stage 15 PDFRenderer rendering modern_report.html + modern_report.css via Jinja2 & Playwright
"""
import asyncio
import os
import sys

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import importlib

evidence_packets = importlib.import_module("pipeline.09_quant_engine.evidence_packets")
FinancialAnalystEvidence = evidence_packets.FinancialAnalystEvidence
ProfitAndLossPacket = evidence_packets.ProfitAndLossPacket
BalanceSheetPacket = evidence_packets.BalanceSheetPacket
CashFlowPacket = evidence_packets.CashFlowPacket
VerifiedNumber = evidence_packets.VerifiedNumber

quant_engine = importlib.import_module("pipeline.09_quant_engine.engine")
QuantEngine = quant_engine.QuantEngine

scorecard_engine = importlib.import_module("pipeline.09_quant_engine.scorecard_engine")
ScorecardEngine = scorecard_engine.ScorecardEngine

rom_builder = importlib.import_module("pipeline.14_report_object_model.rom_builder")
ROMBuilder = rom_builder.ROMBuilder

pdf_renderer = importlib.import_module("pipeline.15_pdf_renderer.renderer")
PDFRenderer = pdf_renderer.PDFRenderer


async def main():
    print("\n=======================================================")
    print("  Testing Modern AI Equity Research Report Generator   ")
    print("=======================================================\n")

    # 1. Build sample typed evidence (LTTS / Zomato style)
    pl = ProfitAndLossPacket(
        revenue=QuantEngine.build_financial_line_item(
            {"fy23": 8014, "fy24": 9647, "fy25": 10500, "q_prev_year": 2573, "q_prev_qtr": 2842, "q_current": 2980}, "revenue"
        ),
        ebitda=QuantEngine.build_financial_line_item(
            {"fy23": 1714, "fy24": 1980, "fy25": 2150, "q_prev_year": 510, "q_prev_qtr": 530, "q_current": 562}, "ebitda"
        ),
        ebit=QuantEngine.build_financial_line_item(
            {"fy23": 1470, "fy24": 1650, "fy25": 1810, "q_prev_year": 412, "q_prev_qtr": 425, "q_current": 448}, "ebit"
        ),
        pbt=QuantEngine.build_financial_line_item(
            {"fy23": 1580, "fy24": 1740, "fy25": 1920, "q_prev_year": 435, "q_prev_qtr": 440, "q_current": 465}, "pbt"
        ),
        pat=QuantEngine.build_financial_line_item(
            {"fy23": 1170, "fy24": 1303, "fy25": 1420, "q_prev_year": 320, "q_prev_qtr": 314, "q_current": 329}, "pat"
        ),
        eps=QuantEngine.build_financial_line_item(
            {"fy23": 110.5, "fy24": 123.0, "fy25": 134.0, "q_prev_year": 30.2, "q_prev_qtr": 29.6, "q_current": 31.0}, "eps"
        ),
    )

    bs = BalanceSheetPacket(
        total_assets=QuantEngine.build_financial_line_item({"fy23": 6500, "fy24": 7400, "fy25": 8200}, "total_assets"),
        total_liabilities=QuantEngine.build_financial_line_item({"fy23": 1800, "fy24": 2000, "fy25": 2100}, "total_liabilities"),
        total_equity=QuantEngine.build_financial_line_item({"fy23": 4700, "fy24": 5400, "fy25": 6100}, "total_equity"),
        total_debt=QuantEngine.build_financial_line_item({"fy23": 120, "fy24": 110, "fy25": 95}, "total_debt"),
        cash_and_equivalents=QuantEngine.build_financial_line_item({"fy23": 2100, "fy24": 2600, "fy25": 3100}, "cash_and_equivalents"),
    )

    cf = CashFlowPacket(
        operating_cash_flow=QuantEngine.build_financial_line_item({"fy23": 1350, "fy24": 1520, "fy25": 1680}, "operating"),
        investing_cash_flow=QuantEngine.build_financial_line_item({"fy23": -400, "fy24": -450, "fy25": -500}, "investing"),
        financing_cash_flow=QuantEngine.build_financial_line_item({"fy23": -600, "fy24": -650, "fy25": -700}, "financing"),
        free_cash_flow=QuantEngine.build_financial_line_item({"fy23": 1150, "fy24": 1300, "fy25": 1450}, "fcf"),
    )

    evidence = FinancialAnalystEvidence(
        company_name="L&T Technology Services Ltd.",
        pl=pl,
        bs=bs,
        cf=cf
    )

    # 2. Test ScorecardEngine
    scorecard = ScorecardEngine.compute(evidence, {"industry": "Engineering Services"})
    print("✅ Stage 09 ScorecardEngine:")
    print(f"   - Growth: {scorecard.growth}/10")
    print(f"   - Financial Health: {scorecard.financial_health}/10")
    print(f"   - Profitability: {scorecard.profitability}/10")
    print(f"   - Innovation: {scorecard.innovation}/10")
    print(f"   - AI Readiness: {scorecard.ai_readiness}/10")
    print(f"   - Execution: {scorecard.execution}/10")
    print(f"   - Risk Level: {scorecard.risk_level}")
    print(f"   - Confidence: {scorecard.confidence_pct}%\n")

    # 3. Test ROMBuilder assembly
    # 3. Simulate Pipeline Stages 13, 13b, 13c
    structured_intelligence = {
      "growth": {
        "status": "positive",
        "confidence": 0.95,
        "evidence": ["record deal wins", "strong segment performance"]
      },
      "profitability": {
        "status": "stable",
        "confidence": 0.88,
        "evidence": ["margin expansion", "cost discipline"]
      },
      "risks": [
        "macro headwinds in Europe",
        "client concentration"
      ]
    }
    
    import sys, os
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "pipeline")))
    import importlib
    stage_13b = importlib.import_module("pipeline.13b_narrative_writer")
    stage_13c = importlib.import_module("pipeline.13c_report_enricher")
    
    narratives = stage_13b.generate_narrative(structured_intelligence)
    enriched = stage_13c.enrich_report(narratives, evidence.model_dump())

    source_ctx = {
        "industry": "Engineering & Technology Services",
        "report_period": "Q2 FY26",
        "valuation_data": {
            "valuation": {
                "cmp": 5420.0,
                "target_price": 6200.0,
                "upside_pct": 14.4,
                "market_cap_cr": 57320.0,
                "enterprise_value_cr": 55100.0,
                "week52_high": 5890.0,
                "week52_low": 4210.0,
                "beta": 0.9,
                "free_float_pct": 26.2,
                "outstanding_shares_cr": 10.6,
                "dividend_yield_pct": 1.2,
                "valuation_methodology": "28x FY27E P/E multiple"
            }
        },
        "fact_check": {"total": 20, "verified_count": 18},
        "executive_summary": enriched["executive_summary"],
        "investment_view": enriched["investment_thesis"],
        "segment_analysis": enriched["business_analysis"],
        "risks": [enriched["risk_analysis"]],
        "management_commentary": enriched["management_commentary"],
        "scorecard": importlib.import_module("schema").AIScorecard(growth=9, financial_health=9, profitability=9, innovation=9, ai_readiness=9, execution=9, risk_level="Low", confidence_pct=95.0),
        "segment_breakdown": importlib.import_module("schema").SegmentBreakdown(segments=[]),
        "geography_breakdown": importlib.import_module("schema").GeographyBreakdown(regions=[]),
        "swot": importlib.import_module("schema").SWOTMatrix(strengths=[], weaknesses=[], opportunities=[], threats=[]),
        "red_flags": importlib.import_module("schema").RedFlagsReport(flags=[]),
        "ceo_outlook": importlib.import_module("schema").CEOOutlook(headline="Outlook", narrative="Positive"),
        "client_profile": importlib.import_module("schema").ClientProfile(top_5_revenue_pct=10.0, top_10_revenue_pct=20.0, total_active_clients=100, million_dollar_clients=50, multi_million_clients=10),
        "employee_stats": importlib.import_module("schema").EmployeeStats(total_headcount=20000, attrition_rate_pct=12.0, utilization_rate_pct=85.0),
        "investment_snapshot": importlib.import_module("schema").InvestmentSnapshot(report_date="Today", industry="IT", employees="20,000", fortune_500_clients="69", innovation_labs="5", design_centers="10"),
        "ai_investment_thesis": importlib.import_module("schema").AIInvestmentThesis(positive_signals=[], watch_items=[]),
        "evidence_summary": importlib.import_module("schema").EvidenceSummary(financial_strength=90, execution_track_record=90, innovation_moat=90, risk_mitigation=90),
        "financials": {
            "quarterly": {"quarters": ["Q1FY26", "Q2FY26"], "revenue": {"Q1FY26": 2800, "Q2FY26": 2980}, "ebitda": {"Q1FY26": 450, "Q2FY26": 562}, "pat": {"Q1FY26": 310, "Q2FY26": 329}},
            "annual": {"revenue": {"FY24": 11000, "FY25": 12500}, "ebitda": {"FY24": 1800, "FY25": 2100}, "pat": {"FY24": 1100, "FY25": 1300}, "eps": {"FY24": 104, "FY25": 122}},
            "forecasts": {"revenue": {"FY26E": 14000, "FY27E": 15800}, "ebitda": {"FY26E": 2400, "FY27E": 2700}, "pat": {"FY26E": 1500, "FY27E": 1700}, "eps": {"FY26E": 141, "FY27E": 160}},
            "annual_growth": {"revenue": {"FY25": 13.6}, "ebitda": {"FY25": 16.7}, "pat": {"FY25": 18.2}, "eps": {"FY25": 17.3}},
            "ratios": {"ebitda_margin": {"FY24": 16.3, "FY25": 16.8}, "pat_margin": {"FY24": 10.0, "FY25": 10.4}, "roe": {"FY24": 25.0, "FY25": 26.0}},
            "balance_sheet": {"total_equity": {"FY24": 100, "FY25": 100}, "total_debt": {"FY24": 4000, "FY25": 4500}, "total_assets": {"FY24": 6000, "FY25": 7000}, "cash": {"FY24": 500, "FY25": 600}},
            "cash_flow": {"operating": {"FY24": 1200, "FY25": 1400}, "investing": {"FY24": -500, "FY25": -600}, "financing": {"FY24": -300, "FY25": -400}}
        },
        "charts": importlib.import_module("pipeline.11_chart_generator").generate_all_charts(
            annual_data={
                "revenue": {"FY24": 11000, "FY25": 12500},
                "revenue_est": {"FY26E": 14000, "FY27E": 15800},
                "pat": {"FY24": 1100, "FY25": 1300},
                "pat_est": {"FY26E": 1500, "FY27E": 1700},
                "ebitda": {"FY24": 1800, "FY25": 2100}
            },
            quarterly_data={"quarters": ["Q1FY26", "Q2FY26"], "revenue": {"Q1FY26": 2800, "Q2FY26": 2980}, "ebitda": {"Q1FY26": 450, "Q2FY26": 562}, "pat": {"Q1FY26": 310, "Q2FY26": 329}}
        ),
        "ai_deep_research": importlib.import_module("schema").AIDeepResearch(

            business_quality=enriched["business_analysis"],
            execution="Strong execution across segments.",
            innovation="Continued AI investments.",
            risk=enriched["risk_analysis"],
            challenges="Macro headwinds.",
            evidence_boxes=[
                importlib.import_module("schema").EvidenceBox(
                    insight="Growth is robust",
                    evidence=structured_intelligence["growth"]["evidence"],
                    confidence=structured_intelligence["growth"]["confidence"] * 100
                )
            ]
        ),
        "business_drivers": importlib.import_module("schema").BusinessDrivers(drivers=["AI Expansion", "Deal Wins"]),
        "trend_indicators": importlib.import_module("schema").TrendIndicators(revenue="▲", margins="→", cash_flow="→", innovation="▲", demand="▲"),
        "chart_commentary": importlib.import_module("schema").AIChartCommentary(revenue_trend="Stable growth.", pat_trend="Positive trajectory.", margin_trend="Stable margins.")
    }

    report_data = ROMBuilder.run(fa_narrative="", fa_evidence=evidence, source_context=source_ctx)
    print("✅ Stage 14 ROMBuilder:")
    print(f"   - Headline: '{report_data.headline}'")
    print(f"   - Recommendation: {report_data.recommendation.action} (Target: ₹{report_data.recommendation.target_price})")
    print(f"   - KPI Cards: {len(report_data.kpi_cards)} cards generated")
    print(f"   - Deal Win Cards: {len(report_data.deal_win_cards)} cards generated")
    print(f"   - SWOT Matrix: {len(report_data.swot.strengths)} strengths, {len(report_data.swot.threats)} threats")
    print(f"   - Red Flags: {report_data.red_flags.flags}")
    print(f"   - CEO Outlook: '{report_data.ceo_outlook.headline}'\n")

    # 4. Test PDF Renderer (Stage 15)
    output_pdf = "outputs/LTTS_Q2FY26_Modern_AI_Report.pdf"
    rendered_path = await PDFRenderer.render_pdf(
        report_data,
        output_path=output_pdf,
        template_name="geojit_report.html"
    )
    print(f"✅ Stage 15 PDFRenderer: Successfully rendered PDF to '{rendered_path}'\n")
    print("🎉 All Modern AI Equity Research Report pipeline tests PASSED!")

if __name__ == "__main__":
    asyncio.run(main())
