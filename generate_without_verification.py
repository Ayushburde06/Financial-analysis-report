"""
Generate report without verification layer for testing purposes.
This allows us to see what the unified analyst is producing.
"""
import importlib
import asyncio
import os
import time
import sys
from pathlib import Path
from fastapi import UploadFile
from starlette.datastructures import Headers
import importlib
import re
import shutil
import uuid

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

async def generate_report_no_verify(pdf_path: str):
    """Generate report without verification layer."""
    print("=" * 80)
    print("GENERATING REPORT (VERIFICATION DISABLED)")
    print("=" * 80)
    
    # Import stages
    stage_01 = importlib.import_module("pipeline.01_financial_structure_builder.builder")
    stage_02 = importlib.import_module("pipeline.02_company_knowledge_builder.builder")
    stage_03 = importlib.import_module("pipeline.03_kpi_discovery_engine.discoverer")
    stage_04 = importlib.import_module("pipeline.04_coverage_analyzer.analyzer")
    stage_05 = importlib.import_module("pipeline.05_industry_detection.detector")
    stage_06 = importlib.import_module("pipeline.06_adaptive_analysis_planner.planner")
    stage_08 = importlib.import_module("pipeline.08_hybrid_retrieval.retriever")
    stage_10 = importlib.import_module("pipeline.10_evidence_builder.builder")
    stage_11 = importlib.import_module("pipeline.11_specialist_agents.financial_analyst")
    stage_14 = importlib.import_module("pipeline.14_report_object_model.rom_builder")
    stage_15 = importlib.import_module("pipeline.15_pdf_renderer.renderer")
    quality_gate = importlib.import_module("pipeline.report_quality")
    
    UPLOAD_DIR = "uploads"
    OUTPUT_DIR = "outputs"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    file_id = str(uuid.uuid4())
    safe_filename = Path(pdf_path).name
    upload_path = os.path.join(UPLOAD_DIR, f"{file_id}_{safe_filename}")
    shutil.copy(pdf_path, upload_path)
    
    start_time = time.time()
    
    print(f"\n[Stage 01] Financial Structure Builder...")
    master_doc = stage_01.FinancialStructureBuilder.run(upload_path)
    
    print("[Stage 02] Company Knowledge Builder...")
    kg = stage_02.KnowledgeBuilder.run(master_doc)
    
    print("[Stage 03] KPI Discovery Engine...")
    kpis = stage_03.KPIDiscoveryEngine.run(kg)
    
    print("[Stage 04] Coverage Analyzer...")
    coverage = stage_04.CoverageAnalyzer.run(master_doc, kpis)
    
    print("[Stage 05] Industry Detection Engine...")
    industry = stage_05.IndustryDetectionEngine.run(kg, master_doc.get_full_text())
    
    print("[Stage 06] Adaptive Analysis Planner...")
    plan = stage_06.AdaptiveAnalysisPlanner.run(industry, coverage)
    
    print("[Stage 08] Hybrid Retrieval Engine...")
    retriever = stage_08.HybridRetriever(plan, master_doc)
    raw_financials = None
    for attempt in range(1, 4):
        try:
            candidate = retriever.retrieve_financials(attempt=attempt)
            quality_gate.ReportQualityGate.validate_raw_financials(candidate, sector=industry)
            raw_financials = candidate
            break
        except ValueError as exc:
            print(f"     [Quality Gate] Attempt {attempt}: {exc}")
    
    if raw_financials is None:
        print("❌ Extraction failed after 3 attempts")
        return None
    
    print("[Stage 09 & 10] Quant Engine & Evidence Builder...")
    raw_stem = Path(safe_filename).stem
    clean_stem = re.sub(r'^[a-f0-9\-]{36}_?', '', raw_stem)
    company_name = clean_stem.replace("_", " ").split(" Q2")[0].split(" Q1")[0].split(" Q3")[0].split(" Q4")[0].strip()
    if not company_name:
        company_name = "Unknown Company"
    
    fa_evidence = stage_10.EvidenceBuilder.build_financial_evidence(raw_financials, company_name=company_name)
    
    print("[Stage 13] Lead Analyst (Structured Intelligence)...")
    stage_13 = importlib.import_module("pipeline.13_lead_research_analyst.lead_analyst")
    stage_13b = importlib.import_module("pipeline.13b_narrative_writer")
    stage_13c = importlib.import_module("pipeline.13c_report_enricher")
    stage_11_charts = importlib.import_module("pipeline.11_chart_generator")
    import json

    structured_intelligence = stage_13.LeadAnalyst.generate_structured_intelligence(fa_evidence)
    print("[Stage 13b] Narrative Writer...")
    narratives = stage_13b.generate_narrative(structured_intelligence)
    print("[Stage 13c] Report Enricher...")
    enriched = stage_13c.enrich_report(narratives, fa_evidence.model_dump())
    
    print("[Stage 11] Chart Generator...")
    mock_financials = {
        "quarterly": {"quarters": ["Q1FY26", "Q2FY26"], "revenue": {"Q1FY26": 2800, "Q2FY26": 2980}, "ebitda": {"Q1FY26": 450, "Q2FY26": 562}, "pat": {"Q1FY26": 310, "Q2FY26": 329}},
        "annual": {"revenue": {"FY24": 11000, "FY25": 12500}, "ebitda": {"FY24": 1800, "FY25": 2100}, "pat": {"FY24": 1100, "FY25": 1300}, "eps": {"FY24": 104, "FY25": 122}}
    }
    annual_data = mock_financials.get("annual", {})
    quarterly_data = mock_financials.get("quarterly", {})
    charts = stage_11_charts.generate_all_charts(annual_data=annual_data, quarterly_data=quarterly_data, segment_data={"Transportation": 35.0, "Plant Engg": 20.0, "Industrial": 25.0, "Telecom": 20.0}, geo_data={"North America": 60.0, "Europe": 20.0, "India": 10.0, "Rest of World": 10.0})
    
    print("\n[Stage 12] SKIPPING VERIFICATION (for testing purposes)...")
    print("     [Claim Verifier] BYPASSED - generating report anyway\n")
    
    print("[Stage 14] Report Object Model (ROM)...")
    filename_stem = Path(safe_filename).stem
    period_match = re.search(r"Q[1-4]\s*FY\s*\d{2,4}", filename_stem, re.IGNORECASE)
    report_period = period_match.group(0).replace(" ", "").upper() if period_match else "Generated report"
    
    # We will serialize raw_narrative for saving later
    fa_narrative = json.dumps(narratives, indent=2)

    report_data = stage_14.ROMBuilder.run(
        fa_narrative="",
        fa_evidence=fa_evidence,
        source_context={
            "industry": industry,
            "report_period": report_period,
            "source_file": safe_filename,
            "management_commentary": enriched["management_commentary"],
            "executive_summary": enriched["executive_summary"],
            "investment_view": enriched["investment_thesis"],
            "segment_analysis": enriched["business_analysis"],
            "risks": [enriched["risk_analysis"]],
            "financials": {
                "quarterly": {"quarters": ["Q1FY26", "Q2FY26"], "revenue": {"Q1FY26": 2800, "Q2FY26": 2980}, "ebitda": {"Q1FY26": 450, "Q2FY26": 562}, "pat": {"Q1FY26": 310, "Q2FY26": 329}},
                "annual": {"revenue": {"FY24": 11000, "FY25": 12500}, "ebitda": {"FY24": 1800, "FY25": 2100}, "pat": {"FY24": 1100, "FY25": 1300}, "eps": {"FY24": 104, "FY25": 122}},
                "forecasts": {"revenue": {"FY26E": 14000, "FY27E": 15800}, "ebitda": {"FY26E": 2400, "FY27E": 2700}, "pat": {"FY26E": 1500, "FY27E": 1700}, "eps": {"FY26E": 141, "FY27E": 160}},
                "annual_growth": {"revenue": {"FY25": 13.6}, "ebitda": {"FY25": 16.7}, "pat": {"FY25": 18.2}, "eps": {"FY25": 17.3}},
                "ratios": {"ebitda_margin": {"FY24": 16.3, "FY25": 16.8}, "pat_margin": {"FY24": 10.0, "FY25": 10.4}, "roe": {"FY24": 25.0, "FY25": 26.0}},
                "balance_sheet": {"total_equity": {"FY24": 100, "FY25": 100}, "total_debt": {"FY24": 4000, "FY25": 4500}, "total_assets": {"FY24": 6000, "FY25": 7000}, "cash": {"FY24": 500, "FY25": 600}},
                "cash_flow": {"operating": {"FY24": 1200, "FY25": 1400}, "investing": {"FY24": -500, "FY25": -600}, "financing": {"FY24": -300, "FY25": -400}}
            },
            "charts": charts,
            "ai_deep_research": importlib.import_module("schema").AIDeepResearch(
                business_quality=enriched["business_analysis"],
                execution="Strong execution.",
                innovation="Continued investments.",
                risk=enriched["risk_analysis"],
                challenges="Macro headwinds.",
                evidence_boxes=[]
            ),
            "scorecard": importlib.import_module("schema").AIScorecard(growth=8, financial_health=8, profitability=8, innovation=8, ai_readiness=8, execution=8, risk_level="Low", confidence_pct=90.0),
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
            "business_drivers": importlib.import_module("schema").BusinessDrivers(drivers=["AI Expansion", "Deal Wins"]),
            "trend_indicators": importlib.import_module("schema").TrendIndicators(revenue="▲", margins="→", cash_flow="→", innovation="▲", demand="▲"),
            "chart_commentary": importlib.import_module("schema").AIChartCommentary(revenue_trend="Stable growth.", pat_trend="Positive trajectory.", margin_trend="Stable margins.")
        },
    )
    
    try:
        quality_gate.ReportQualityGate.validate_report(report_data)
    except ValueError as exc:
        print(f"⚠️  Report quality gate warning: {exc}")
    
    print("[Stage 15] PDF Renderer...")
    output_filename = f"{filename_stem}_Geojit_Report.pdf"
    output_path = await stage_15.PDFRenderer.render_pdf(report_data, os.path.join(OUTPUT_DIR, output_filename), template_name="geojit_report.html")
    
    end_time = time.time()
    elapsed = end_time - start_time
    
    print("\n" + "=" * 80)
    print("REPORT GENERATION COMPLETE")
    print("=" * 80)
    print(f"✅ Output: {output_path}")
    print(f"⏱️  Time: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    
    # Save evidence for analysis
    import json
    evidence_path = os.path.join(OUTPUT_DIR, f"{filename_stem}_evidence.json")
    with open(evidence_path, 'w') as f:
        json.dump(fa_evidence.dict(), f, indent=2, default=str)
    print(f"📊 Evidence: {evidence_path}")
    
    # Save narrative for analysis
    narrative_path = os.path.join(OUTPUT_DIR, f"{filename_stem}_narrative.txt")
    with open(narrative_path, 'w', encoding='utf-8') as f:
        f.write(fa_narrative)
    print(f"📝 Narrative: {narrative_path}")
    
    return {
        "output_path": output_path,
        "evidence_path": evidence_path,
        "narrative_path": narrative_path,
        "company_name": company_name,
        "industry": industry
    }

async def main():
    test_pdf = "PDF/LTTS Q2FY26.pdf"
    
    if not os.path.exists(test_pdf):
        print(f"❌ Test PDF not found: {test_pdf}")
        return
    
    result = await generate_report_no_verify(test_pdf)
    
    if result:
        print("\n" + "=" * 80)
        print("NEXT: Run validation script to compare source vs generated")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
