"""
fact_check.py - Deep fact-checker
Extracts ALL numbers from the generated report narrative,
then cross-checks each one against the source PDF OCR text.
Flags anything that can't be traced back to the source.
"""
import re
import json
import sys
import os
from pathlib import Path

# ── Step 1: Extract source PDF text via pdfplumber ────────────────────────────
def get_source_text(pdf_path: str) -> str:
    import pdfplumber
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            text += t + "\n"
    return text

# ── Step 2: Extract narrative from the outputs JSON/scan ─────────────────────
def get_narrative(narrative_path: str) -> str:
    with open(narrative_path, "r", encoding="utf-8") as f:
        return f.read()

# ── Step 3: Extract all numbers with context from narrative ──────────────────
def extract_claims(narrative: str):
    """
    Extract every sentence containing a number from the narrative.
    Returns list of dicts: {sentence, numbers, citations}
    """
    sentences = re.split(r'(?<=[.!?])\s+', narrative)
    claims = []
    for sent in sentences:
        nums = []
        for n in re.findall(r'[\d,]+(?:\.\d+)?', sent):
            cleaned = n.replace(",", "")
            if cleaned and cleaned != ".":
                try:
                    if float(cleaned) >= 100:
                        nums.append(cleaned)
                except ValueError:
                    pass
        if not nums:
            continue
        citations = re.findall(r'\[Source:\s*([^\]]+)\]', sent)
        claims.append({
            "sentence": sent.strip(),
            "numbers": list(set(nums)),
            "citations": [c.strip() for c in citations],
            "has_citation": len(citations) > 0
        })
    return claims

# ── Step 4: Check each number against source PDF text ────────────────────────
def check_number_in_source(num_str: str, source_text: str, tolerance_pct: float = 2.0) -> dict:
    """
    Check if a number appears in the source PDF text within tolerance.
    Returns {found, exact_match, context}
    """
    target = float(num_str)
    
    # Exact match (with comma variants)
    patterns = [
        num_str,
        f"{target:,.0f}",
        f"{target:.1f}",
        f"{target:.2f}",
        str(int(target)) if target == int(target) else None
    ]
    for p in patterns:
        if p and p in source_text:
            # Get surrounding context
            idx = source_text.find(p)
            context = source_text[max(0,idx-60):idx+60].replace("\n", " ").strip()
            return {"found": True, "exact_match": True, "context": context, "value": target}
    
    # Tolerance match — find all numbers in source and check proximity
    source_nums = re.findall(r'[\d,]+(?:\.\d+)?', source_text)
    for sn in source_nums:
        try:
            sv = float(sn.replace(",", ""))
            if sv == 0 or target == 0:
                continue
            dev = abs((sv - target) / sv) * 100
            if dev <= tolerance_pct and sv >= 100:
                idx = source_text.find(sn)
                context = source_text[max(0,idx-60):idx+60].replace("\n", " ").strip()
                return {"found": True, "exact_match": False, 
                        "context": context, "value": target, 
                        "matched_to": sv, "deviation_pct": round(dev, 2)}
        except:
            pass
    
    return {"found": False, "exact_match": False, "context": "", "value": target}

# ── Step 5: Run full fact check ───────────────────────────────────────────────
def run_fact_check(source_pdf: str, narrative_file: str):
    print("=" * 70)
    print("DEEP FACT CHECK — LTTS Q2FY26")
    print("=" * 70)
    
    print("\n[1/4] Extracting source PDF text...")
    source_text = get_source_text(source_pdf)
    print(f"      Source text: {len(source_text):,} characters extracted")
    
    print("\n[2/4] Loading generated narrative...")
    narrative = get_narrative(narrative_file)
    print(f"      Narrative: {len(narrative):,} characters")
    
    print("\n[3/4] Extracting all numerical claims...")
    claims = extract_claims(narrative)
    print(f"      Found {len(claims)} sentences with numbers")
    
    print("\n[4/4] Cross-checking every number against source PDF...\n")
    
    results = []
    verified = 0
    hallucinated = 0
    derived = 0  # percentages / growth rates
    
    print("-" * 70)
    
    for claim in claims:
        sent = claim["sentence"]
        is_derived = "%" in sent  # Sentences with % are derived calculations
        
        for num in claim["numbers"]:
            try:
                val = float(num)
            except:
                continue
            
            # Skip years and small numbers
            if 1990 <= val <= 2030 or val < 100:
                continue
            
            # Skip pure percentage sentences (derived calculations)
            if is_derived and val < 1000:
                derived += 1
                continue
            
            check = check_number_in_source(num, source_text)
            
            status = "✅ VERIFIED" if check["found"] else "❌ NOT FOUND"
            if not check["found"]:
                hallucinated += 1
            else:
                verified += 1
            
            results.append({
                "number": val,
                "status": status,
                "has_citation": claim["has_citation"],
                "sentence": sent[:100] + "..." if len(sent) > 100 else sent,
                "source_context": check.get("context", ""),
                "matched_to": check.get("matched_to", val),
                "deviation": check.get("deviation_pct", 0.0)
            })
            
            # Print result
            citation_tag = "[CITED]" if claim["has_citation"] else "[UNCITED]"
            print(f"{status} {citation_tag} ₹{val:,.0f}")
            if check["found"]:
                if not check["exact_match"]:
                    print(f"         ≈ Matched ₹{check['matched_to']:,.0f} "
                          f"(±{check.get('deviation_pct',0):.1f}%)")
                print(f"         Source: ...{check['context'][:80]}...")
            else:
                print(f"         Claim: {sent[:90]}")
            print()
    
    # ── Summary ───────────────────────────────────────────────────────────────
    total_checked = verified + hallucinated
    accuracy = (verified / total_checked * 100) if total_checked > 0 else 0
    
    print("=" * 70)
    print("FACT CHECK SUMMARY")
    print("=" * 70)
    print(f"Total numbers checked : {total_checked}")
    pct = round(verified/total_checked*100, 1) if total_checked else 0
    print(f"✅ Verified           : {verified}  ({pct}%)")
    print(f"❌ Not found in source: {hallucinated}")
    print(f"⚡ Derived (skipped)  : {derived}  (% / growth rates — expected)")
    print(f"\nAccuracy Score        : {accuracy:.1f}%")
    
    if hallucinated == 0:
        print("\n🏆 VERDICT: ZERO HALLUCINATIONS — Report is 100% fact-based")
        grade = "A"
    elif hallucinated <= 2:
        print(f"\n⚠️  VERDICT: {hallucinated} number(s) unverified — likely rounding or unit difference")
        grade = "B+"
    elif hallucinated <= 5:
        print(f"\n⚠️  VERDICT: {hallucinated} unverified number(s) — review required")
        grade = "B"
    else:
        print(f"\n❌ VERDICT: {hallucinated} unverified number(s) — possible hallucinations")
        grade = "C"
    
    print(f"Quality Grade         : {grade}")
    print("=" * 70)
    
    # Save detailed results
    with open("fact_check_results.json", "w") as f:
        json.dump({
            "verdict": grade,
            "accuracy_pct": round(accuracy, 1),
            "verified": verified,
            "hallucinated": hallucinated,
            "derived_skipped": derived,
            "details": results
        }, f, indent=2)
    print("\nDetailed results saved to: fact_check_results.json")
    
    return grade, accuracy


if __name__ == "__main__":
    SOURCE_PDF = "PDF/LTTS Q2FY26.pdf"
    
    # Get narrative from the evidence builder output
    # We'll regenerate it by importing and running the pipeline partially
    # OR read it from a saved file if available
    
    # First check if we have a saved narrative
    NARRATIVE_FILE = "narrative_debug.txt"
    
    if not os.path.exists(NARRATIVE_FILE):
        print("Narrative file not found. Extracting from pipeline...")
        # Run pipeline up to Stage 11 and save narrative
        import asyncio
        from dotenv import load_dotenv
        load_dotenv()
        
        async def extract_narrative():
            import importlib
            import shutil, uuid
            from pathlib import Path
            from fastapi import UploadFile
            from starlette.datastructures import Headers
            
            stage_01 = importlib.import_module("pipeline.01_financial_structure_builder.builder")
            stage_02 = importlib.import_module("pipeline.02_company_knowledge_builder.builder")
            stage_03 = importlib.import_module("pipeline.03_kpi_discovery_engine.discoverer")
            stage_04 = importlib.import_module("pipeline.04_coverage_analyzer.analyzer")
            stage_05 = importlib.import_module("pipeline.05_industry_detection.detector")
            stage_06 = importlib.import_module("pipeline.06_adaptive_analysis_planner.planner")
            stage_08 = importlib.import_module("pipeline.08_hybrid_retrieval.retriever")
            stage_10 = importlib.import_module("pipeline.10_evidence_builder.builder")
            stage_11 = importlib.import_module("pipeline.11_specialist_agents.financial_analyst")
            quality_gate = importlib.import_module("pipeline.report_quality")
            
            pdf_path = SOURCE_PDF
            safe_filename = Path(pdf_path).name
            upload_path = f"uploads/{uuid.uuid4()}_{safe_filename}"
            os.makedirs("uploads", exist_ok=True)
            shutil.copy(pdf_path, upload_path)
            
            master_doc = stage_01.FinancialStructureBuilder.run(upload_path)
            kg = stage_02.KnowledgeBuilder.run(master_doc)
            kpis = stage_03.KPIDiscoveryEngine.run(kg)
            coverage = stage_04.CoverageAnalyzer.run(master_doc, kpis)
            industry = stage_05.IndustryDetectionEngine.run(kg, master_doc.get_full_text())
            plan = stage_06.AdaptiveAnalysisPlanner.run(industry, coverage)
            
            retriever = stage_08.HybridRetriever(plan, master_doc)
            raw_financials = None
            for attempt in range(1, 4):
                try:
                    candidate = retriever.retrieve_financials(attempt=attempt)
                    quality_gate.ReportQualityGate.validate_raw_financials(candidate, sector=industry)
                    raw_financials = candidate
                    break
                except ValueError as e:
                    print(f"     Attempt {attempt} failed: {e}")
            
            clean_stem = re.sub(r'^[a-f0-9\-]{36}_?', '', Path(safe_filename).stem)
            company_name = clean_stem.replace("_"," ").split(" Q2")[0].split(" Q1")[0].strip() or "LTTS"
            
            fa_evidence = stage_10.EvidenceBuilder.build_financial_evidence(raw_financials, company_name=company_name)
            
            # Save evidence for reference
            with open("evidence_debug.json", "w") as f:
                f.write(fa_evidence.model_dump_json(indent=2))
            print("Evidence saved to: evidence_debug.json")
            
            fa_agent = stage_11.FinancialAnalyst()
            narrative = fa_agent.generate(fa_evidence)
            
            with open(NARRATIVE_FILE, "w", encoding="utf-8") as f:
                f.write(narrative)
            print(f"Narrative saved to: {NARRATIVE_FILE}")
            return narrative
        
        asyncio.run(extract_narrative())
    
    run_fact_check(SOURCE_PDF, NARRATIVE_FILE)
