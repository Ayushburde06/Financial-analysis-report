"""
main.py — FastAPI endpoint for the Financial Document Intelligence Pipeline
Coordinates the strictly typed Data-First architecture for Geojit reports,
now fully implementing the 14-Stage Institutional Pipeline.
"""
import os
import sys
import asyncio

# Force UTF-8 output on Windows to prevent CP1252 encoding errors with ₹ ✅ ❌ symbols
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import uuid
import importlib
import re
import time
import logging
import traceback
from pathlib import Path
import fitz
from dom_schema import ParagraphNode, TableNode
from fastapi import FastAPI, UploadFile, File, Form, Request, BackgroundTasks
from fastapi import HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("billeyeee")

# Dynamic Imports for all 14 Stages
stage_01 = importlib.import_module("pipeline.01_financial_structure_builder.builder")
stage_02 = importlib.import_module("pipeline.02_company_knowledge_builder.builder")
stage_03 = importlib.import_module("pipeline.03_kpi_discovery_engine.discoverer")
stage_04 = importlib.import_module("pipeline.04_coverage_analyzer.analyzer")
stage_05 = importlib.import_module("pipeline.05_industry_detection.detector")
stage_06 = importlib.import_module("pipeline.06_adaptive_analysis_planner.planner")
# stage_07 (Storage Layer) is implicitly used by stage 08
stage_08 = importlib.import_module("pipeline.08_hybrid_retrieval.retriever")
# stage_09 (Quant Engine) is used inside stage_10
stage_10 = importlib.import_module("pipeline.10_evidence_builder.builder")
stage_11 = importlib.import_module("pipeline.11_specialist_agents.financial_analyst")
# stage_12 and 13 omitted for brevity in this test execution
stage_14 = importlib.import_module("pipeline.14_report_object_model.rom_builder")
quality_gate = importlib.import_module("pipeline.report_quality")

_is_production = os.getenv("ENVIRONMENT", "development").lower() == "production"
app = FastAPI(
    title="Source-Verified Equity Research Engine",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a safe error response while preserving the full server traceback."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=dict(exc.headers or {}),
        )
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    logger.error(
        "Unhandled request failure request_id=%s method=%s path=%s error=%s\n%s",
        request_id,
        request.method,
        request.url.path,
        exc,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Report generation failed unexpectedly. Please try again.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )

# The browser talks only to this server-side proxy. Provider keys stay in the
# deployment environment and are never returned to the client.
_rate_window_seconds = int(os.getenv("GENERATE_RATE_WINDOW_SECONDS", "600"))
_generate_limit = int(os.getenv("GENERATE_RATE_LIMIT", "3"))
_generation_semaphore = asyncio.Semaphore(
    max(1, int(os.getenv("GENERATION_MAX_CONCURRENT", "1")))
)
_generate_requests: dict[str, list[float]] = {}
_jobs: dict[str, dict] = {}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Add browser hardening and a lightweight abuse guard to the proxy API."""
    if request.method == "POST" and request.url.path == "/generate-report":
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        recent = [
            started_at
            for started_at in _generate_requests.get(client_ip, [])
            if now - started_at < _rate_window_seconds
        ]
        if len(recent) >= _generate_limit:
            retry_after = max(1, int(_rate_window_seconds - (now - recent[0])))
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many report requests. Please try again later."},
                headers={"Retry-After": str(retry_after)},
            )
        recent.append(now)
        _generate_requests[client_ip] = recent

        response = await call_next(request)
    else:
        response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; frame-ancestors 'none'"
    )
    if _is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# Serve the frontend UI from /static
STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".csv", ".txt", ".text", ".md"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024
MAX_LIVE_PDF_PAGES = int(os.getenv("MAX_LIVE_PDF_PAGES", "70"))


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve favicon to prevent 404 console errors."""
    favicon_path = os.path.join(STATIC_DIR, "favicon.ico")
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path, media_type="image/x-icon")
    raise HTTPException(status_code=404)

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    """Polling endpoint for the frontend to check report generation progress."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired.")
    return job


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the frontend upload UI."""
    ui_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(ui_path):
        raise HTTPException(status_code=404, detail="UI not found. Ensure static/index.html exists.")
    with open(ui_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/health")
async def health_check():
    """Readiness endpoint for AWS load balancers and deployment checks."""
    required = {
        "azure_document_intelligence": bool(os.getenv("AZURE_DOC_INTEL_ENDPOINT") and os.getenv("AZURE_DOC_INTEL_KEY")),
        "azure_gpt5_luna": bool(os.getenv("AZURE_GPT5_ENDPOINT") and os.getenv("AZURE_GPT5_KEY")),
    }
    configured = all(required.values())
    return {
        "status": "ok" if configured else "degraded",
        "service": "geojit-research-engine",
        "providers_configured": configured,
        "provider_checks": required,
    }


@app.get("/download/{filename}")
async def download_report(filename: str):
    """
    One-click PDF download endpoint.
    Usage: GET /download/LTTS_Q2FY26_Equity_Report.pdf
    """
    # Sanitize: only allow alphanumerics, spaces, dashes, underscores, dots
    safe_name = re.sub(r"[^A-Za-z0-9 _\-.]", "", filename)
    file_path = os.path.join(OUTPUT_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail=f"Report not found: {safe_name}")
    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=safe_name,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )

async def _handle_non_pdf_route(
    file_bytes: bytes, safe_filename: str, file_ext: str,
    company_name: str, cmp: str, target_price: str,
    market_cap: str, sector_override: str, pdf_path: str,
):
    """Handle CSV and TXT uploads — bypass Azure OCR, use CSV/TXT handler instead."""
    from pipeline.csv_txt_handler import handle_non_pdf
    import importlib as _il

    print(f"[CSV/TXT Mode] Processing {safe_filename}...")

    # Use an explicit override when supplied; otherwise infer the sector from
    # the uploaded source just like the PDF path does.
    industry = sector_override.strip() if sector_override.strip() else "General"
    source_text = file_bytes.decode("utf-8", errors="replace")

    # Extract raw financials from CSV/TXT
    raw_financials = handle_non_pdf(file_bytes, safe_filename, sector=industry)
    if not raw_financials:
        raise HTTPException(status_code=422,
            detail="Could not extract financial data from the uploaded file. "
                   "Ensure the CSV has headers like: Metric, FY23, FY24, FY25, Q2FY26")

    # Derive company name
    _cn = company_name.strip() if company_name else ""
    derived_name = _cn or Path(safe_filename).stem.replace("_", " ").split(" Q")[0].strip() or "Unknown Company"
    from pipeline.utils.company_identity import canonicalize_display_name
    derived_name = canonicalize_display_name(derived_name, safe_filename)
    if not sector_override.strip():
        banking_keys = {"nii", "nim", "advances", "deposits", "gnpa", "nnpa", "casa_ratio"}
        if banking_keys.intersection(raw_financials):
            industry = "Banking"
        else:
            try:
                import importlib as _sector_import
                IndustryDetectionEngine = _sector_import.import_module(
                    "pipeline.05_industry_detection.detector"
                ).IndustryDetectionEngine
                detected = IndustryDetectionEngine.run(
                    {"company_name": derived_name},
                    f"{derived_name}\n{source_text}",
                    kpis=list(raw_financials.keys()),
                )
                industry = detected or "Other"
            except Exception as exc:
                print(f"     [CSV/TXT] Sector detection unavailable: {exc}; using Other")
                industry = "Other"
    print(f"     [CSV/TXT] Company: {derived_name}, Sector: {industry}")

    # Build minimal knowledge graph
    kg = {"company_name": derived_name, "management_commentary": [""],
          "strategy_and_highlights": [], "risks_and_challenges": [],
          "esg_initiatives": [], "sector": industry}

    # Skip OCR stages — build evidence directly
    stage_12b = _il.import_module("pipeline.12b_source_verifier.fact_checker")
    stage_10  = _il.import_module("pipeline.10_evidence_builder.builder")
    stage_12  = _il.import_module("pipeline.12_verification_pipeline.verifier")

    # Treat the uploaded CSV/TXT itself as the source of truth, including its
    # unit label. This keeps non-PDF uploads on the same safety path as PDFs.
    fact_check_report = stage_12b.SourceFactChecker.verify(raw_financials, source_text)
    stage_12d = _il.import_module("pipeline.12d_unit_normalizer.unit_normalizer")
    raw_financials, unit_report = stage_12d.normalize_units(raw_financials, source_text)
    fact_check_report = stage_12b.SourceFactChecker.verify(
        raw_financials, source_text,
        source_value_factor=unit_report.conversion_factor,
    )
    if fact_check_report.blocked:
        raise HTTPException(
            status_code=422,
            detail=("Source verification failed for uploaded data: "
                    f"{fact_check_report.verified_count}/{fact_check_report.total} "
                    "values matched the file."),
        )
    fa_evidence = stage_10.EvidenceBuilder.build_financial_evidence(
        raw_financials,
        company_name=derived_name,
        industry=industry,
        extra_keys=list(raw_financials.keys()),
    )
    fa_evidence = stage_10.attach_filing_context(
        fa_evidence, industry=industry, knowledge=kg,
    )

    # Generate narrative
    stage_11_mod = _il.import_module("pipeline.11_specialist_agents.financial_analyst")
    fa_agent = stage_11_mod.FinancialAnalyst()
    fa_narrative = fa_agent.generate(fa_evidence)
    is_valid, fa_narrative = stage_12.VerificationStack.layer3_claim_verifier(
        fa_narrative, fa_evidence
    )
    if not is_valid:
        raise HTTPException(
            status_code=422,
            detail="Narrative failed claim verification; PDF generation stopped.",
        )

    # Valuation from form fields
    def _fnum(s):
        try: return float(str(s).replace(",", "").strip()) if s else None
        except: return None

    cmp_val    = _fnum(cmp)
    target_val = _fnum(target_price)
    mcap_val   = _fnum(market_cap)
    upside_val = round(((target_val - cmp_val) / cmp_val) * 100, 1) if (cmp_val and target_val and cmp_val > 0) else None
    rec_action = ("BUY" if (upside_val and upside_val > 10) else
                  "HOLD" if (upside_val and upside_val >= 0) else
                  "SELL" if (upside_val and upside_val < 0) else "NOT RATED")

    # Run ROM builder through the shared runner
    filename_stem = Path(safe_filename).stem
    period_m = re.search(r"Q[1-4]\s*FY\s*\d{2,4}", filename_stem, re.IGNORECASE)
    report_period = period_m.group(0).replace(" ", "").upper() if period_m else "Generated"

    valuation_data = {"valuation": {
        "cmp": cmp_val, "target_price": target_val,
        "market_cap_cr": mcap_val,
    }, "shareholding": {}}

    pipe_runner = _il.import_module("pipeline.pipeline_stage11_to_14")
    report_data = pipe_runner.run(
        fa_evidence=fa_evidence, fa_narrative_raw=fa_narrative,
        stage_12=stage_12, stage_08b_valuation_data=valuation_data,
        kg=kg, industry=industry, derived_name=derived_name,
        report_period=report_period, safe_filename=safe_filename,
        file_filename=safe_filename, fact_check_report=fact_check_report,
        ocr_text=source_text,
        raw_financials=raw_financials,
    )

    try:
        quality_gate.ReportQualityGate.validate_report(
            report_data, ocr_text=source_text, source_filename=safe_filename
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Assignment checks failed: {exc}") from exc

    stage_15 = _il.import_module("pipeline.15_pdf_renderer.renderer")
    output_filename = f"{filename_stem}_Equity_Report.pdf"
    try:
        output_path = await stage_15.PDFRenderer.render_pdf(
            report_data, os.path.join(OUTPUT_DIR, output_filename),
            template_name="geojit_report.html")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "success",
        "message": f"Report generated from {file_ext.upper()} input.",
        "pdf_path": output_path,
        "pdf_filename": output_filename,
        "recommendation": report_data.recommendation.action,
    }


@app.post("/generate-report")
async def generate_report_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    company_name: str = Form(default=""),
    cmp: str = Form(default=""),
    target_price: str = Form(default=""),
    market_cap: str = Form(default=""),
    sector_override: str = Form(default=""),
):
    if _generation_semaphore.locked():
        raise HTTPException(
            status_code=429,
            detail="A report is already being generated. Please wait for it to finish."
        )
    file_id = str(uuid.uuid4())
    safe_filename = Path(file.filename or "report.pdf").name
    file_ext = Path(safe_filename).suffix.lower()
    entered_name = (company_name or "").strip()
    if len(entered_name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Company name is required. Enter the listed company name, e.g. ICICI Bank.",
        )
    name_file_mismatch = quality_gate.company_filename_mismatch(
        entered_name, safe_filename
    )
    if name_file_mismatch:
        raise HTTPException(status_code=422, detail=name_file_mismatch)
    if file_ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a PDF, CSV, TXT, or MD file.",
        )
    pdf_path = os.path.join(UPLOAD_DIR, f"{file_id}_{safe_filename}")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if file_ext == ".pdf" and not file_bytes.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="The uploaded file is not a valid PDF.")
    if _is_production and file_ext == ".pdf":
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as uploaded_pdf:
                page_count = uploaded_pdf.page_count
        except Exception as exc:
            raise HTTPException(status_code=422, detail="The uploaded file is not a readable PDF.") from exc
        if page_count > MAX_LIVE_PDF_PAGES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"This live service accepts PDF files with at most "
                    f"{MAX_LIVE_PDF_PAGES} pages. The uploaded file has {page_count} pages."
                ),
            )
    with open(pdf_path, "wb") as buffer:
        buffer.write(file_bytes)

    job_id = file_id
    _jobs[job_id] = {"status": "processing", "message": "Reading and validating document..."}
    
    background_tasks.add_task(
        _process_report_task,
        job_id, file_bytes, safe_filename, file_ext, company_name, 
        cmp, target_price, market_cap, sector_override, pdf_path, file.filename
    )
    
    return {"status": "accepted", "job_id": job_id}


async def _process_report_task(
    job_id: str, file_bytes: bytes, safe_filename: str, file_ext: str, 
    company_name: str, cmp: str, target_price: str, market_cap: str, 
    sector_override: str, pdf_path: str, original_filename: str
):
    try:
        async with _generation_semaphore:
            print(f"\n--- Processing {original_filename} (14-Stage Architecture) ---")
        
            # ── Non-PDF shortcut ──────────────────────────────────────────────────────
            is_pdf = file_ext in (".pdf",)
            if not is_pdf:
                res = await _handle_non_pdf_route(
                    file_bytes=file_bytes,
                    safe_filename=safe_filename,
                    file_ext=file_ext,
                    company_name=company_name,
                    cmp=cmp, target_price=target_price,
                    market_cap=market_cap,
                    sector_override=sector_override,
                    pdf_path=pdf_path,
                )
                _jobs[job_id] = {
                    "status": "completed",
                    "pdf_path": res["pdf_path"],
                    "pdf_filename": res["pdf_filename"],
                    "message": res["message"],
                    "recommendation": res.get("recommendation", "")
                }
                return
            print("[Stage 01] Financial Structure Builder...")
            master_doc = stage_01.FinancialStructureBuilder.run(pdf_path)
    
            print("[Stage 02] Company Knowledge Builder...")
            kg = stage_02.KnowledgeBuilder.run(master_doc, filename=safe_filename)
    
            print("[Stage 03] KPI Discovery Engine...")
            kpis = stage_03.KPIDiscoveryEngine.run(kg, master_doc.get_full_text())
    
            print("[Stage 04] Coverage Analyzer...")
            coverage = stage_04.CoverageAnalyzer.run(master_doc, kpis)
    
            print("[Stage 05] Industry Detection Engine...")
            industry = stage_05.IndustryDetectionEngine.run(
                kg, master_doc.get_full_text(), kpis=kpis
            )
    
            print("[Stage 06] Adaptive Analysis Planner...")
            plan = stage_06.AdaptiveAnalysisPlanner.run(industry, coverage, kpis=kpis)
    
            print("[Stage 08] Hybrid Retrieval Engine...")
            retriever = stage_08.HybridRetriever(plan, master_doc)
            raw_financials = None
            extraction_errors = []
            # One initial extraction plus one targeted retry is enough after the
            # financial-page batch extractor; repeating the entire document three
            # times makes the assignment demo unnecessarily slow.
            for attempt in range(1, 3):
                try:
                    candidate = retriever.retrieve_financials(attempt=attempt)
                    quality_gate.ReportQualityGate.validate_raw_financials(candidate, sector=industry)
                    raw_financials = candidate
                    break
                except ValueError as exc:
                    extraction_errors.append(f"Attempt {attempt}: {exc}")
                    print(f"     [Quality Gate] {extraction_errors[-1]}")
            if raw_financials is None:
                raise HTTPException(
                    status_code=422,
                    detail="Report not generated because verified extraction failed after 2 attempts: " + " | ".join(extraction_errors),
                )

            # Verify and canonicalize extracted values before any quantification. The
            # evidence builder invokes the quant engine, so normalization must happen
            # before that boundary rather than after the first evidence packet.
            stage_12b = importlib.import_module("pipeline.12b_source_verifier.fact_checker")
            ocr_text = master_doc.get_full_text() if master_doc else ""
            fact_check_report = stage_12b.SourceFactChecker.verify(raw_financials, ocr_text)

            if fact_check_report.unverified:
                print(f"     [Pipeline] {len(fact_check_report.unverified)} unverified field(s) "
                      "— triggering extraction self-healer...")
                raw_financials, fact_check_report = stage_12b.ExtractionSelfHealer.heal(
                    raw_financials, ocr_text, fact_check_report, sector=industry
                )

            stage_12d = importlib.import_module("pipeline.12d_unit_normalizer.unit_normalizer")
            raw_financials, unit_report = stage_12d.normalize_units(raw_financials, ocr_text)
            fact_check_report = stage_12b.SourceFactChecker.verify(
                raw_financials,
                ocr_text,
                source_value_factor=unit_report.conversion_factor,
            )
            if fact_check_report.unverified:
                for field in fact_check_report.unverified:
                    parts = field.field_path.split(".")
                    if len(parts) >= 2 and isinstance(raw_financials.get(parts[0]), dict):
                        raw_financials[parts[0]][parts[1]] = None
                fact_check_report = stage_12b.SourceFactChecker.verify(
                    raw_financials,
                    ocr_text,
                    source_value_factor=unit_report.conversion_factor,
                )
            if fact_check_report.blocked:
                raise HTTPException(
                    status_code=422,
                    detail=("Source verification failed after unit normalization: "
                            f"{fact_check_report.verified_count}/{fact_check_report.total} "
                            "values verified."),
                )
    
            print("[Stage 09 & 10] Quant Engine & Evidence Builder...")
            raw_stem = Path(safe_filename).stem
            # Strip UUID prefix if present
            clean_stem = re.sub(r'^[a-f0-9\-]{36}_?', '', raw_stem)
            # Priority: 1) explicit form field, 2) Stage 02 OCR extraction, 3) filename
            # Guard: if company_name is a Pydantic FieldInfo object (leak), treat as empty
            _cn_raw = str(company_name).strip() if company_name else ""
            company_name_str = "" if ("annotation=" in _cn_raw or "FieldInfo" in _cn_raw
                                      or "required=" in _cn_raw) else _cn_raw

            # Generic-name detector: if the OCR-extracted name is just a legal suffix or
            # a single generic word (e.g. "India Ltd", "Energy Limited"), it's almost
            # certainly a mis-extraction — fall back to the filename stem instead.
            _GENERIC_NAME_TOKENS = {
                "india", "ltd", "limited", "energy", "corporation", "corp",
                "company", "co", "pvt", "private", "holdings", "holding",
                "enterprises", "enterprise", "group", "industries", "industry",
            }
            def _is_generic_name(name: str) -> bool:
                tokens = re.sub(r'[^a-zA-Z\s]', '', name.lower()).split()
                tokens = [t for t in tokens if t]
                if not tokens:
                    return True
                # Generic if every token is a generic word
                return all(t in _GENERIC_NAME_TOKENS for t in tokens)

            def _clean_company_label(name: str) -> str:
                """Remove OCR logo/slogan fragments from the display company name."""
                if not name:
                    return ""
                lines = [re.sub(r"\s+", " ", line).strip() for line in str(name).splitlines()]
                lines = [line for line in lines if line and len(line) > 2]
                # OCR often appends a logo slogan or repeated single-letter marks after
                # the actual company heading. The first meaningful line is the safest.
                return lines[0] if lines else ""

            filename_fallback = clean_stem.replace("_", " ").split(" Q2")[0].split(" Q1")[0].split(" Q3")[0].split(" Q4")[0].strip()

            if company_name_str and not _is_generic_name(company_name_str):
                derived_name = _clean_company_label(company_name_str)
            elif kg.get("company_name") and kg["company_name"] not in ("Unknown Company", "", None):
                _kg_name = str(kg["company_name"])
                _kg_clean = "" if ("annotation=" in _kg_name or "FieldInfo" in _kg_name) else _kg_name
                _kg_clean = _clean_company_label(_kg_clean)
                if _kg_clean and not _is_generic_name(_kg_clean):
                    derived_name = _kg_clean
                else:
                    derived_name = filename_fallback
            else:
                derived_name = ""
            if not derived_name:
                derived_name = filename_fallback
            if not derived_name:
                derived_name = "Unknown Company"
            from pipeline.utils.company_identity import canonicalize_display_name
            derived_name = canonicalize_display_name(derived_name, safe_filename)
            print(f"     [Pipeline] Company name resolved: {derived_name}")
            fa_evidence = stage_10.EvidenceBuilder.build_financial_evidence(
                raw_financials,
                company_name=derived_name,
                industry=industry,
                extra_keys=kpis,
            )
    
            stage_12 = importlib.import_module("pipeline.12_verification_pipeline.verifier")

            print("[Stage 11] Unified Analyst (GPT-5.6 Luna)...")
            filename_stem = Path(safe_filename).stem
            period_match_re = re.search(r"Q[1-4]\s*FY\s*\d{2,4}", filename_stem, re.IGNORECASE)
            report_period = period_match_re.group(0).replace(" ", "").upper() if period_match_re else ""
            fa_evidence = stage_10.attach_filing_context(
                fa_evidence,
                industry=industry,
                knowledge=kg,
                period_label=report_period,
            )
            stage_11 = importlib.import_module("pipeline.11_specialist_agents.financial_analyst")
            fa_agent = stage_11.FinancialAnalyst()
            fa_narrative_raw = fa_agent.generate(fa_evidence)

            print("[Stage 12] Verification Pipeline...")
            is_valid, fa_narrative = stage_12.VerificationStack.layer3_claim_verifier(
                fa_narrative_raw, fa_evidence
            )
            if not is_valid:
                raise HTTPException(
                    status_code=422,
                    detail="Narrative failed claim verification; PDF generation stopped.",
                )

            print("[Stage 08b] Valuation & Shareholding Extractor...")
            stage_08b = importlib.import_module("pipeline.08b_valuation_extractor.extractor")
            # Get per-page texts for 100% coverage extraction
            page_texts_08b = None
            if master_doc and master_doc.sections:
                page_texts_08b = []
                for section in master_doc.sections:
                    pt = ""
                    for node in section.nodes:
                        if isinstance(node, ParagraphNode):
                            pt += node.text + "\n"
                        elif isinstance(node, TableNode):
                            pt += node.csv_string + "\n"
                    page_texts_08b.append(pt.strip() if pt.strip() else "")
            valuation_data = stage_08b.ValuationExtractor.run(ocr_text, page_texts=page_texts_08b)

            print("[Stage 14] Report Object Model (ROM)...")
            if not report_period:
                filename_stem = Path(safe_filename).stem
                period_match_re = re.search(r"Q[1-4]\s*FY\s*\d{2,4}", filename_stem, re.IGNORECASE)
                report_period = period_match_re.group(0).replace(" ", "").upper() if period_match_re else "Generated report"
            if report_period == "":
                report_period = "Generated report"

            pipe_runner = importlib.import_module("pipeline.pipeline_stage11_to_14")
            report_data = pipe_runner.run(
                fa_evidence=fa_evidence,
                fa_narrative_raw=fa_narrative,
                stage_12=stage_12,
                stage_08b_valuation_data=valuation_data,
                kg=kg,
                industry=industry,
                derived_name=derived_name,
                report_period=report_period,
                safe_filename=safe_filename,
                file_filename=getattr(file, "filename", None) or pdf_path,
                fact_check_report=fact_check_report,
                ocr_text=ocr_text,
                raw_financials=raw_financials,
                source_value_factor=unit_report.conversion_factor,
            )


            try:
                quality_gate.ReportQualityGate.validate_report(
                    report_data, ocr_text=ocr_text, source_filename=safe_filename
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Assignment checks failed: {exc}") from exc

            # ── Final Verification Gate ──────────────────────────────────────────────
            # Summarize all verification stages before generating the PDF.
            _fc_score = getattr(fact_check_report, 'score', 0)
            _fc_verified = getattr(fact_check_report, 'verified_count', 0)
            _fc_total = getattr(fact_check_report, 'total', 0)
            _sanity = report_data.appendix.get('sanity_check', {}) if isinstance(
                getattr(report_data, 'appendix', None), dict) else {}
            if not isinstance(_sanity, dict):
                _sanity = {}
            _sanity_passed = _sanity.get('passed', True)
            _sanity_absurd = _sanity.get('absurd', 0)

            print("=" * 70)
            print("  VERIFICATION GATE SUMMARY")
            print("=" * 70)
            print(f"  Stage 12b (Source Fact-Check):  {_fc_verified}/{_fc_total} values "
                  f"verified ({_fc_score:.0%})")
            print(f"  Stage 12c (Sanity Check):       "
                  f"{'PASSED' if _sanity_passed else f'{_sanity_absurd} corrected'}")
            print(f"  Stage 12d (Unit Normalizer):    "
                  f"Unit: {unit_report.detected_unit}, "
                  f"Factor: {unit_report.conversion_factor}, "
                  f"Converted: {unit_report.values_converted}")
            print(f"  Stage 12  (Claim Verifier):     {'PASSED' if is_valid else 'FALLBACK'}")
            print("=" * 70)
            if _fc_score < 0.5:
                print("  ⚠️  WARNING: Source verification below 50% — report flagged.")
            if not _sanity_passed:
                print("  ⚠️  NOTE: Some computed ratios were outside sensible ranges")
                print("          and have been nullified (shown as — in the report).")
            print("  ✅ Proceeding to PDF generation.")
            print("=" * 70)

            print("[Stage 15] PDF Renderer (Source-Verified Equity Research Report)...")
            stage_15 = importlib.import_module("pipeline.15_pdf_renderer.renderer")
            output_filename = f"{filename_stem}_Equity_Report.pdf"
            try:
                output_path = await stage_15.PDFRenderer.render_pdf(
                    report_data,
                    os.path.join(OUTPUT_DIR, output_filename),
                    template_name="geojit_report.html"
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    
            _jobs[job_id] = {
                "status": "completed",
                "pdf_path": output_path,
                "pdf_filename": output_filename,
                "message": "Orchestration completed through 15-Stage Pipeline.",
                "recommendation": report_data.recommendation.action,
            }

    except Exception as exc:
        import traceback
        traceback.print_exc()
        _jobs[job_id] = {"status": "failed", "detail": str(exc)}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
