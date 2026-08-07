# Geojit AI Research Report Generator — Project Status

## What Was Built

An end-to-end AI pipeline that takes any Indian company's quarterly results PDF and
generates a Geojit-style equity research report PDF automatically.

---

## Project Folder Layout

```
billeyeee/
│
├── PDF/                          ← Input PDFs (4 companies)
│   ├── ICICI Q2FY26.pdf
│   ├── JSW Energy Q2FY26.pdf
│   ├── LTTS Q2FY26.pdf
│   └── POCL Q2FY26.pdf
│
├── format/                       ← Style reference
│   ├── Eternal-Geojit.pdf        ← Geojit sample report (style target)
│   ├── eternal_raw.txt           ← OCR-extracted text from Eternal sample
│   └── geojit_style_guide.md     ← Style rules extracted from Eternal sample
│
├── outputs/                      ← Generated reports
│   ├── ICICI Q2FY26_Geojit_Report.pdf
│   ├── JSW Energy Q2FY26_Geojit_Report.pdf
│   ├── LTTS Q2FY26_Geojit_Report.pdf
│   └── POCL Q2FY26_Geojit_Report.pdf
│
├── pipeline/                     ← 15-stage AI pipeline
│   ├── 01_financial_structure_builder/  ← Azure Document Intelligence OCR
│   ├── 02_company_knowledge_builder/    ← Company name extraction + KG
│   ├── 03_kpi_discovery_engine/         ← KPI identification
│   ├── 04_coverage_analyzer/            ← Data availability check
│   ├── 05_industry_detection/           ← Auto sector detection (14 sectors)
│   ├── 06_adaptive_analysis_planner/    ← Sector-specific extraction plan
│   ├── 08_hybrid_retrieval/             ← Mistral Large 3 JSON extraction
│   ├── 08b_valuation_extractor/         ← CMP, target, shareholding extraction
│   ├── 09_quant_engine/                 ← Pydantic evidence packets
│   ├── 10_evidence_builder/             ← Evidence validation + wrapping
│   ├── 11_specialist_agents/            ← DeepSeek V4 Pro narrative generation
│   ├── 11_chart_generator.py            ← matplotlib 2x2 chart grid
│   ├── 12_verification_pipeline/        ← Claim verification + self-healing
│   ├── 12b_source_verifier/             ← Source fact-checking (100% verified)
│   ├── 14_report_object_model/          ← ROM builder (Pydantic → render dict)
│   ├── 15_pdf_renderer/                 ← Playwright → PDF
│   ├── pipeline_stage11_to_14.py        ← Orchestration layer
│   ├── report_quality.py                ← Quality gate
│   └── sectors/                         ← 14 sector configs (Banking, IT, etc.)
│       ├── banking.py
│       ├── it_services.py
│       ├── energy.py
│       ├── metals.py
│       └── ...
│
├── templates/                    ← HTML/CSS report template
│   ├── geojit_report.html        ← 4-page Geojit layout
│   └── geojit_report.css         ← Teal #00837a theme matching Eternal sample
│
├── static/                       ← Web UI
│   ├── index.html
│   ├── index.css
│   └── main.js
│
├── main.py                       ← FastAPI app (upload → pipeline → PDF)
├── run_one.py                    ← CLI runner for single PDF
├── batch_process.py              ← Batch runner for all 4 PDFs
├── schema.py                     ← Pydantic report schema
├── dom_schema.py                 ← Document Object Model schema
└── requirements.txt              ← Dependencies
```

---

## Pipeline Architecture (15 Stages)

```
PDF Upload
    │
    ▼
Stage 01 — Azure Document Intelligence OCR
    │         Extracts all text, tables, figures from PDF
    ▼
Stage 02 — Company Knowledge Builder
    │         Extracts company name from OCR text (regex patterns)
    │         Builds knowledge graph (strategy, risks, ESG sentences)
    ▼
Stage 03 — KPI Discovery Engine
    │         Identifies which KPIs are available in this document
    ▼
Stage 04 — Coverage Analyzer
    │         Checks what data is available (quarterly/annual/segment)
    ▼
Stage 05 — Industry Detection Engine
    │         Auto-detects sector from text keywords
    │         14 sectors: Banking, IT, Energy, Metals, Pharma, FMCG, etc.
    ▼
Stage 06 — Adaptive Analysis Planner
    │         Creates sector-specific extraction plan
    ▼
Stage 08 — Hybrid Retrieval Engine
    │         Mistral Large 3 (675B) via AWS Bedrock
    │         Extracts structured JSON financials from OCR text
    ▼
Stage 09 — Quant Engine
    │         Wraps raw JSON into validated Pydantic evidence packets
    ▼
Stage 10 — Evidence Builder
    │         Builds FinancialAnalystEvidence Pydantic object
    ▼
Stage 12b — Source Fact-Checker (Loop 1)
    │         Verifies extracted numbers against OCR text
    │         Self-heals unverified fields (re-extraction)
    │         Current: 13/13 values verified = 100%
    ▼
Stage 11 — Financial Analyst (DeepSeek V4 Pro, Azure AI)
    │         Generates 4 structured narrative sections:
    │           BUSINESS_DESCRIPTION — what the company does
    │           KEY_HIGHLIGHTS       — 5-6 data-driven bullets
    │           REPORT_SUBTITLE      — one-line investment thesis
    │           OUTLOOK_VALUATION    — forward-looking paragraph
    ▼
Stage 12 — Verification Pipeline (Loop 2)
    │         Verifies AI narrative claims against evidence
    │         Self-heals hallucinated sentences
    ▼
Stage 08b — Valuation & Shareholding Extractor
    │         Extracts CMP, target price, shareholding pattern
    ▼
Stage 14 — Report Object Model Builder
    │         Assembles all data into GeojitReportData Pydantic object
    │         Computes growth %, ratios, chart data from evidence
    ▼
Stage 11c — Chart Generator (matplotlib)
    │         Generates 4 charts as base64 PNG:
    │           Revenue/NII Trend, PAT Trend, Margin Trend, Quarterly
    ▼
Stage 15 — PDF Renderer (Playwright + Jinja2)
              Renders HTML template → headless Chromium → PDF
```

---

## AI Models Used

| Stage | Model | Purpose |
|---|---|---|
| Stage 08 | Mistral Large 3 (675B) — AWS Bedrock | JSON financial extraction |
| Stage 08b | Mistral Large 3 (675B) — AWS Bedrock | Valuation/shareholding extraction |
| Stage 11 | **DeepSeek V4 Pro — Azure AI** | Narrative generation (PRIMARY) |
| Stage 12 | DeepSeek V4 Pro — Azure AI | Claim verification |
| Fallback | DeepSeek R1 — AWS Bedrock | If Azure unavailable |
| OCR | Azure Document Intelligence | PDF → structured text |

---

## Generated Report Structure (4 Pages, matching Geojit Eternal)

### Page 1 — Cover / Header
```
LEFT SIDEBAR (34%)              │  RIGHT MAIN CONTENT (66%)
────────────────────────────────┼──────────────────────────────────
Company Name (large bold)       │  Report subtitle / thesis
Recommendation Badge            │  Business description (AI)
Target / CMP / Return           │  Key Highlights (5-6 bullets, AI)
Sector / Period                 │  Outlook & Valuation (AI paragraph)
Key Changes row                 │  Quarterly Financials table
Company Data table              │    (Revenue/NII, EBITDA, PAT)
Shareholding (3 quarters)       │    (YoY% and QoQ%)
Price Performance (3M/6M/1Y)    │
```

### Page 2 — Analysis
```
Key Highlights (extended bullets with detail)
2x2 Chart Grid:
  [Revenue/NII Trend]  [PAT Trend]
  [Margin Trend]       [Quarterly]
Sector Key Metrics table (NIM, GNPA, NNPA etc. for banking)
Change in Estimates table (if available)
```

### Page 3 — Consolidated Financials
```
LEFT (50%)                      │  RIGHT (50%)
────────────────────────────────┼──────────────────────────────────
Profit & Loss                   │  Balance Sheet
  FY22–FY25 + FY26E/FY27E       │    FY22–FY25 + FY26E/FY27E
────────────────────────────────┼──────────────────────────────────
Cashflow                        │  Ratios
  FY22–FY25 + FY26E/FY27E       │    ROE, ROA, Margins etc.

Valuation Summary (P/E, P/B, EV/EBITDA — shows — if unavailable)
Verification stamp: X/Y values source-verified
```

### Page 4 — Recommendation + Disclaimer
```
Recommendation History table
Investment Rating Criteria (Buy/Hold/Sell thresholds)
Disclaimer & Disclosures (SEBI-style, pipeline attribution)
```

---

## What Works

- Company name auto-extracted from OCR text for all 4 PDFs:
  - ICICI Bank ✓
  - JSW Energy Limited ✓
  - L&T Technology Services ✓
  - Pondy Oxides and Chemicals Limited ✓

- 14 sectors auto-detected from keywords

- 100% source verification on ICICI (13/13 values)

- Narrative generated by DeepSeek V4 Pro with:
  - Business description (no fabrication)
  - Bullet highlights with real numbers
  - Outlook paragraph with recommendation
  - Missing data shown as "—" not fabricated

- 4-page PDF rendered matching Geojit Eternal visual style

---

## Known Gaps vs Geojit Eternal Sample

| Feature | Eternal Sample | Our Generator | Notes |
|---|---|---|---|
| Company name | Eternal Limited | ✓ ICICI Bank | Working |
| Rating | HOLD | NOT RATED | No CMP in source PDF |
| Target price | Rs. 337 | — | Not in quarterly results PDF |
| CMP | Rs. 306 | — | Not in source PDF |
| Market Cap | Rs. 295,735cr | — | Not in quarterly results PDF |
| 52W High/Low | Rs. 314-190 | — | Not in source PDF |
| Beta | 1.0 | — | Not in source PDF |
| Free Float | 71.9% | — | Not in source PDF |
| Shareholding % | Actual % filled | Shows — | Source PDF lacks this |
| Historical P&L (FY23/FY24) | Full 3-year history | — | Only Q2FY26 in source |
| FY26E/FY27E estimates | Full analyst projections | Partial | Requires analyst model |
| Stock price chart | Historical chart | Not included | Requires market data API |
| 4 charts | Revenue+GOV+EBITDA+PAT | Revenue+PAT+Margin+Quarterly | Different data available |

**Root cause of most gaps**: The uploaded PDFs are quarterly investor presentations
(one quarter of data). Geojit reports have 3-year history + 2-year forward estimates
because the analyst team has full coverage of the company. Per the assignment spec,
missing data is correctly shown as "—" not fabricated.

---

## How to Run

```bash
# Single PDF
python run_one.py "PDF/ICICI Q2FY26.pdf"

# All 4 PDFs
python batch_process.py

# Web UI (FastAPI)
uvicorn main:app --reload --port 8000
# Then open http://localhost:8000
```

---

## Requirements

See requirements.txt. Key dependencies:
- fastapi, uvicorn — web server
- playwright — PDF rendering (headless Chromium)
- jinja2 — HTML templating
- pydantic — data validation
- pymupdf (fitz) — PDF reading/verification
- matplotlib — chart generation
- azure-ai-documentintelligence — OCR
- requests — LLM API calls
