# Geojit-Style Equity Research Report Generator

I built this to take a company's financial document (PDF, CSV, or TXT) and turn it into a downloadable equity research report that mirrors the Geojit Financial Services template — same layout, same sections, same tables, plus charts and a narrative. The interesting part is that the numbers in the report are pulled from the source document and verified against it, so the model can't just make them up.

## How to run it

```bash
# 1. Install the dependencies
pip install -r requirements.txt
python -m playwright install chromium

# 2. Add your API keys
cp .env.example .env
# You'll need keys for: Azure Document Intelligence, AWS Bedrock (Mistral), Azure AI (DeepSeek)

# 3. Run it on one company from the command line
python run_one.py "PDF/ICICI Q2FY26.pdf"

# 4. Or use the web UI
python -m uvicorn main:app --reload
# Then open http://localhost:8000, upload a file, and download the PDF
```

## What's under the hood

| Bit | What I used |
|---|---|
| Web app | FastAPI + Uvicorn |
| PDF rendering | Playwright (headless Chromium) rendering a Jinja2 HTML template |
| Reading the PDF | Azure Document Intelligence (OCR) |
| Pulling out the financials | Mistral Large 3 (675B) on AWS Bedrock — returns structured JSON |
| Writing the narrative | DeepSeek V4 Pro on Azure AI — qualitative only, no numbers |
| Forward estimates (FY26E/FY27E) | DeepSeek V4 Pro, clearly labeled as model projections |
| Live market data (CMP, beta, 52W H/L) | Yahoo Finance via `yfinance` |
| Charts | Matplotlib (bar + line, dual-axis) |
| Fact-checking | A Python evidence audit that checks every extracted value against the source |

## Where the template fields live

If you want to tweak the report layout or add a field, here's where to look:

- `templates/geojit_report.html` — the Jinja2 template (layout, sections, tables)
- `templates/geojit_report.css` — the teal Geojit theme, fonts, table styles
- `schema.py` → `GeojitReportData` — the Pydantic schema with every report field
- `pipeline/14_report_object_model/rom_builder.py` — assembles the data into that schema
- `pipeline/sectors/` — sector-specific labels (e.g. NII for banks, Revenue for others)
- `pipeline/15_pdf_renderer/renderer.py` — Playwright → HTML → PDF

## The pipeline, stage by stage

```
Stage 01   Financial Structure Builder
Stage 02   Company Knowledge Builder (figures out the company name + sector)
Stage 03   KPI Discovery
Stage 04   Coverage Analyzer
Stage 05   Industry Detection (keyword heuristics → picks a sector config)
Stage 06   Adaptive Analysis Planner
Stage 08   Hybrid Retrieval (Mistral Large 3 → structured JSON)
Stage 08b  Valuation & Shareholding Extractor
Stage 09   Quant Engine (builds evidence packets)
Stage 10   Evidence Builder (Pydantic validation)
Stage 11   Unified Analyst (DeepSeek V4 Pro → narrative, with numbers stripped out)
Stage 12   Verification Pipeline (claim verification)
Stage 12b  Source Fact-Checker (self-healing loop, target 100% verification)
Stage 12c  Sanity Verifier (catches absurd ratios)
Stage 12d  Unit Normalizer (fixes million-vs-crore mismatches)
Stages 11–14  Charts, ratios, projections, ROM assembly
Stage 15   PDF Renderer (Playwright → HTML → PDF)
```

## How I kept it from hallucinating

This was the part I cared about most. A research report is only useful if the numbers are real.

1. **Result Highlights** are generated in pure Python from the verified evidence packets. No LLM is involved in producing numbers.
2. **Business Description & Outlook** are written by DeepSeek, but every number in the LLM's input is replaced with a `[VERIFIED]` placeholder before it sees it. A safety-net regex scrubs any numbers that slip through in the output. The model literally never sees the figures, so it can't misquote them.
3. **Financial Tables** are extracted by Mistral as structured JSON and then fact-checked against the source document in Stage 12b.
4. **Fact-Check Stamp** — every value is checked against the source PDF, and the report shows `X/Y values confirmed` at the bottom of page 3.
5. **Forward Estimates** (FY26E/FY27E) are AI-projected and labeled `(AI-projected, not company guidance)` so no one mistakes them for guidance.
6. **Target Price** is a mechanical EPS × P/E estimate, labeled `(est., P/E×EPS)` — not dressed up as a valuation-model output.
7. **Headline / Outlook** carry an "AI-generated narrative, not human analyst opinion" tag so the reader knows what they're looking at.
8. **Key Changes arrows** say "N/A — first coverage" instead of fabricating a comparison to a prior report that doesn't exist.

## Supported input formats

- **PDF** — parsed with Azure Document Intelligence (OCR)
- **CSV** — parsed by `pipeline/csv_txt_handler.py` (skips OCR)
- **TXT** — same handler as CSV

## Example reports

Two generated PDFs are included in `submission/reports/` — pick these to review:

| Company | Sector | Why it's a good example |
|---|---|---|
| ICICI Bank | Banking | Shows sector-specific rows (NII, PAT margin) and a HOLD rating with a negative return in red |
| LTTS | IT Services | Shows a full 4-page report with mechanical target, HOLD rating, and clean IT-sector narrative |

Four more are in `outputs/` (ICICI, LTTS, JSW Energy, POCL) if you want to see other sectors.

## What each page contains (matches the Geojit sample)

**Page 1 — Cover.** Company name + rating badge, 1Y stock-vs-Sensex chart, business description, result highlights (verified bullets), outlook & valuation, quarterly financials table with YoY/QoQ, and a right sidebar with company data, shareholding, performance returns, and the analyst box.

**Page 2 — Key Highlights & Charts.** Extended key highlights, four charts (revenue, PAT, margin, quarterly), forward estimates summary (AI-projected), and sector-specific metrics where applicable (NIM/GNPA for banks).

**Page 3 — Consolidated Financials.** P&L, Balance Sheet, Cashflow, and Ratios tables across FY22–FY27E, a valuation summary, and the source-verified stamp.

**Page 4 — Recommendation & Disclaimer.** Recommendation summary, investment rating criteria, the full SEBI-compliance disclaimer with an AI disclosure, and a grievances section.

## Adding a new company or sector

1. **New company** — just upload its PDF/CSV/TXT. The pipeline auto-detects the name and sector.
2. **New sector** — drop a config file in `pipeline/sectors/` with the labels (e.g. `pl_label`, `pat_label`) and any extra metrics.
3. **New ticker** — add it to `_TICKER_MAP` in `pipeline/stock_chart.py`.

## Project structure

```
billeyeee/
├── main.py                        # FastAPI app + upload endpoint
├── run_one.py                     # CLI runner for a single company
├── schema.py                      # Pydantic models (GeojitReportData)
├── .env                           # API keys (not committed)
├── templates/
│   ├── geojit_report.html         # Geojit-style HTML template
│   └── geojit_report.css          # Teal theme CSS
├── pipeline/
│   ├── 08_hybrid_retrieval/       # Mistral Large 3 financial extraction
│   ├── 09_quant_engine/           # Evidence packets
│   ├── 11_specialist_agents/     # DeepSeek narrative (numbers stripped)
│   ├── 12b_source_verifier/      # Fact-checker + self-healing loop
│   ├── 14_report_object_model/    # ROM builder
│   ├── 15_pdf_renderer/          # Playwright PDF renderer
│   ├── sectors/                  # Sector-specific configs
│   ├── stock_chart.py            # Yahoo Finance chart + performance
│   ├── ai_projections.py         # FY26E/FY27E projections
│   └── pipeline_stage11_to_14.py # Stages 11–14 orchestrator
├── PDF/                          # Test input documents
├── outputs/                      # Generated PDF reports
└── format/                       # Geojit sample + style guide
```

## A few honest notes

- The reports are not pixel-perfect vs the Geojit sample — I didn't reproduce the logo or the vertical report-period tab on the right edge. The layout, sections, and tables match.
- The narrative sections are AI-generated and labeled as such. They are not a human analyst's opinion.
- Where the source document doesn't contain a field (e.g. cashflow for POCL), the report shows "—" or "data not available" rather than making something up.
- The target price is a mechanical P/E × EPS estimate, not a full DCF/valuation-model output. It's labeled that way on the report.
