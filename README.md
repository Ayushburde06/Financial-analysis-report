# Geojit-Style Equity Research Report Generator

This app takes a company financial document and returns a downloadable, auto-filled equity research PDF in the style of the supplied Geojit sample.

Repository: [Financial-analysis-report](https://github.com/Ayushburde06/Financial-analysis-report)

> **Live demo note:** The public demo runs on a cost-conscious AWS EC2 instance with 2 GB RAM. To keep the instance stable, it processes one report at a time and accepts PDFs up to 30 pages. A slow response or timeout reflects the live infrastructure limit, not an intentional reduction in verification: the same source-first pipeline can be run locally for full report-quality evaluation.

## Assignment summary

The assignment was to turn an unstructured company financial document into a usable equity research report. The important part was not only producing a good-looking PDF; the numbers also needed to remain traceable to the input document.

The approach is deliberately source-first. The document is treated as the authority, the LLM is used to organize and explain information, and deterministic Python stages check the extracted values before they reach a table, chart, or paragraph. When a value is not in the source, the report leaves it unavailable instead of guessing.

## Live application

- Frontend: [https://financial-analysis-report.vercel.app/](https://financial-analysis-report.vercel.app/)
- Backend: AWS-hosted report-generation service
- Health endpoint: `/health` on the backend deployment

The Vercel interface sends the uploaded document to the AWS backend. The backend keeps provider credentials server-side and returns the generated PDF through the download flow.

## What the app does

The user uploads a PDF, CSV, TXT, TEXT, or Markdown financial document, enters the company name, and downloads a formatted research report. The report can include company information, quarterly and annual financial tables, verified metrics, charts, narrative analysis, outlook, and disclosures.

The design is source-first. Values are used only when they are present in the uploaded document or can be calculated from verified source values. Missing information stays unavailable instead of being filled with a plausible-looking guess.

In practical terms, the application separates three responsibilities:

- The source document provides facts.
- Python verifies and calculates numbers.
- The LLM makes the verified information readable and useful.

That separation is the main safeguard against wrong company names, duplicated figures, unsupported targets, and confident but untraceable financial commentary.

## How the pipeline works

1. The app receives and stores the uploaded document.
2. Azure Document Intelligence reads PDF content into page-level Markdown. CSV, TXT, TEXT, and Markdown files are read directly.
3. The LLM extracts structured company and financial facts into typed report fields.
4. Verification stages compare extracted values with the source text and retain provenance.
5. Python calculates transparent derived values such as growth, margins, and ratios when the required inputs exist.
6. Verified values drive the tables, charts, highlights, and narrative.
7. Jinja2, CSS, and Playwright render the final Geojit-style PDF for download.

### Pipeline ownership

| Pipeline responsibility | What happens | Main implementation |
|---|---|---|
| Input and document reading | Accepts the upload, validates the extension/size, and converts the document into usable text | `main.py`, `pipeline/csv_txt_handler.py` |
| Financial structure | Finds periods, statements, and candidate financial sections | `pipeline/01_financial_structure_builder/` |
| Company knowledge | Builds the company context used by later stages | `pipeline/02_company_knowledge_builder/` |
| KPI and coverage discovery | Identifies available metrics and records what the source does not contain | `pipeline/03_kpi_discovery_engine/`, `pipeline/04_coverage_analyzer/` |
| Industry and analysis planning | Adapts the report focus to the company and the available evidence | `pipeline/05_industry_detection/`, `pipeline/06_adaptive_analysis_planner/` |
| Retrieval and extraction | Retrieves relevant source passages and extracts structured values | `pipeline/08_hybrid_retrieval/`, `pipeline/08b_valuation_extractor/` |
| Quantitative analysis | Calculates derived metrics from verified inputs | `pipeline/09_quant_engine/`, `pipeline/10b_cross_metric_analyzer/` |
| Evidence and narrative | Packages evidence and asks the LLM to explain the verified story | `pipeline/10_evidence_builder/`, `pipeline/10f_analytical_prompt/`, `pipeline/10g_analytical_engine/` |
| Verification | Checks source matches, units, sanity, cross-source consistency, and claims | `pipeline/12_verification_pipeline/`, `pipeline/12b_source_verifier/`, `pipeline/12c_sanity_verifier/`, `pipeline/12d_unit_normalizer/` |
| Report object model | Converts the verified result into typed report data | `pipeline/14_report_object_model/` |
| Presentation and PDF | Builds charts, applies the Geojit-style template, and renders the downloadable PDF | `pipeline/11_chart_generator.py`, `pipeline/15_pdf_renderer/`, `templates/` |

The result is a report that can be inspected from both directions: a reviewer can read the final narrative, or trace a number back to the source evidence and the stage that produced it.

## What comes from where

| Output | Source or method |
|---|---|
| Company identity, periods, financial facts, targets, and ratings | Uploaded document, when available and verified |
| Growth, margins, ratios, and formatting | Python calculations from verified inputs |
| Explanations and organization | LLM, constrained by the verified report data |
| Charts | Matplotlib, using verified numerical series only |
| Layout and disclosures | Geojit-style HTML/CSS templates |

The app does not automatically fetch market data from Yahoo Finance or `yfinance`. If CMP, target price, rating, or another field is absent from the source, it remains unavailable.

## Failure and availability behavior

- Missing Azure credentials: `/health` reports `degraded`; report generation cannot complete until the providers are configured.
- OCR/provider failure: the request fails rather than producing a report from unreadable or incomplete input.
- LLM rate limit, quota, or timeout: generation may fail or require a retry. The app does not fabricate a fallback value.
- Application rate limit: repeated generation requests can return HTTP `429` with a `Retry-After` header.
- Missing report field: the PDF shows `—` or “Not available in source document.”

This behavior prevents wrong company identity, duplicated values, unsupported targets, and false ratings from entering the report. It also makes the output easier to audit against the supplied document.

## Run with Docker

```bash
copy .env.example .env
# Fill Azure Document Intelligence and LLM keys in .env. Never commit .env.

docker compose up --build
# Open http://localhost:8000
```

Generated files are written to `outputs/` on the host. Useful commands:

```bash
docker compose logs -f web
docker compose down
```

## Update the AWS EC2 deployment

The EC2 host runs the same Docker Compose service. After pushing changes to GitHub, update the instance with:

```bash
cd /path/to/Financial-analysis-report
git pull origin main
cp .env.example .env  # first deployment only
nano .env             # add the provider credentials on the EC2 host
docker compose up -d --build
curl http://127.0.0.1:8000/health
docker compose ps
docker compose logs --tail=100 web
```

The Compose configuration is tuned for a 2 GB EC2 instance: one report at a time, two OCR workers, a 50 MB upload limit, and a 1.5 GB container memory limit. PDF uploads are additionally limited to 30 pages in production. The health response should report `"status": "ok"` when the required Azure provider variables are configured. The EC2 security group should allow the application port only as needed; put the service behind HTTPS/reverse proxy infrastructure for a public deployment.

### Production quality note

Use the same repository and commit locally when validating report quality, then deploy that tested commit to EC2. The EC2 free-tier resource limits can cause slower processing, timeouts, or container restarts; they should not be treated as a report-quality benchmark. Keep report generation single-file on EC2, and audit representative PDFs locally before promoting changes with `git pull origin main`. For production stability, keep multimodel extraction disabled on a 2 GB instance. Enabling both models may improve quality, but significantly increases memory usage and crash risk; the safer approach is to improve single-model extraction prompts and retry handling rather than re-enable parallel models.

## Run locally with Python

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium

copy .env.example .env
# Add Azure Document Intelligence and LLM credentials

python -m uvicorn main:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000
```

For batch or script execution:

```bash
set PYTHONPATH=.
python scripts/run_one.py "PDF/ICICI Q2FY26.pdf" "ICICI Bank"
python scripts/run_one.py "PDF/LTTS Q2FY26.pdf" "LTTS"
```

## Tech stack

| Piece | Technology |
|---|---|
| Frontend | Static HTML, CSS, and JavaScript served by the API |
| Backend | FastAPI + Uvicorn |
| PDF OCR | Azure Document Intelligence |
| Structured extraction and narrative | Azure-hosted LLM APIs |
| Verification | Python pipeline stages, including source comparison |
| Charts | Matplotlib |
| PDF rendering | Jinja2 HTML/CSS + Playwright Chromium |
| Deployment | Vercel frontend with AWS backend |

## Where report fields are defined

| What | Location |
|---|---|
| Layout, sections, and tables | `templates/geojit_report.html` |
| Colours and typography | `templates/geojit_report.css` |
| Style guide | `format/geojit_style_guide.md` |
| Typed report fields | `schema.py` -> `GeojitReportData` |
| Data assembly | `pipeline/14_report_object_model/rom_builder.py` |
| PDF generation | `pipeline/15_pdf_renderer/renderer.py` |

## Acceptance criteria

| Requirement | Implementation |
|---|---|
| Geojit-style output | Four-page report structure with sidebar, charts, financial tables, recommendation, and disclaimer |
| Tables, metrics, narrative, and charts | Verified highlights, quarterly/annual tables, derived metrics, narrative, and four or more charts when data supports them |
| Multiple input formats | PDF, CSV, TXT, TEXT, and Markdown |
| No invented values | Missing fields remain `—` or unavailable |
| One-click download | UI download action calls `GET /download/{filename}` |



### Submission reports

1. **ICICI Q2FY26**: [generated PDF](submission/reports/ICICI%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/ICICI Q2FY26.pdf`
2. **JSW Energy Q2FY26**: [generated PDF](submission/reports/JSW%20Energy%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/JSW Energy Q2FY26.pdf`

## Disclaimer

This is an AI-assisted document analysis and report-generation tool. It is not investment advice. The report should be reviewed against the original source document before use.
