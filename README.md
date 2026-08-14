# Geojit-Style Equity Research Report Generator

Upload a company financial document and get a downloadable equity research PDF in a Geojit-inspired format. The report includes financial tables, charts, highlights, narrative analysis, and disclosures when the source supports them.

Repository: [Financial-analysis-report](https://github.com/Ayushburde06/Financial-analysis-report)

## Demo

[Open the live application](https://financial-analysis-report.vercel.app/)

The live demo processes one report at a time and limits PDFs to 30 pages because OCR, analysis, and PDF rendering use significant CPU and memory. Large or scanned PDFs may take longer, time out, or produce a less complete run under resource pressure. For the most reliable report-quality evaluation, clone the repository and run the pipeline locally.

### Submission reports

1. **ICICI Q2FY26**: [generated PDF](submission/reports/ICICI%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/ICICI Q2FY26.pdf`
2. **JSW Energy Q2FY26**: [generated PDF](submission/reports/JSW%20Energy%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/JSW Energy Q2FY26.pdf`

## How it works

The pipeline is source-first: the uploaded document remains the authority, while Python and the LLM have clearly separated jobs.

1. **Read the source.** PDFs go through Azure Document Intelligence and become page-level Markdown. CSV and text files are read directly.
2. **Find the structure.** The pipeline identifies the company, reporting periods, statements, KPIs, and useful evidence sections in that Markdown.
3. **Create structured data.** The LLM organizes the facts into typed JSON report fields. Each important value keeps a reference to the source evidence behind it.
4. **Verify and calculate.** Deterministic Python checks units, sanity, and consistency, then calculates growth, margins, and ratios only from verified inputs.
5. **Build charts and analysis.** Tables and Matplotlib charts use verified numerical series. The LLM writes highlights and outlook around those numbers instead of inventing new ones.
6. **Render the report.** The verified JSON is mapped into the Geojit-style HTML/CSS template and Playwright renders the final downloadable PDF.

When `USE_MULTIMODEL=1`, GPT-5.6 Luna and DeepSeek V4 Pro run in parallel for extraction and narrative writing. Their results are combined or compared before the verified report is built. This can improve resilience and coverage, but it also uses more CPU, memory, and API quota, so the lighter single-model mode is better suited to a small hosted instance.

If the source does not contain a value, the report leaves it unavailable rather than guessing. The app does not fetch market data automatically, so a missing CMP, target price, or rating remains unavailable.

Supported files: PDF, CSV, TXT, TEXT, and Markdown.

## Run locally

Create a virtual environment, install the dependencies, add the Azure credentials to `.env`, and start the API:

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

## Built with

The application uses FastAPI and Uvicorn for the backend, Azure Document Intelligence for PDF reading, and Azure-hosted LLM APIs for structured extraction and narrative writing. Python handles verification and calculations; Matplotlib creates the charts; Jinja2, HTML/CSS, and Playwright produce the final PDF.

## Report template and fields

The report layout and sections are defined in [templates/geojit_report.html](templates/geojit_report.html), with styling in [templates/geojit_report.css](templates/geojit_report.css). Typed report fields live in [schema.py](schema.py), data is assembled in [pipeline/14_report_object_model/rom_builder.py](pipeline/14_report_object_model/rom_builder.py), and PDF rendering is handled by [pipeline/15_pdf_renderer/renderer.py](pipeline/15_pdf_renderer/renderer.py).

## Disclaimer

This is an AI-assisted document analysis and report-generation tool. It is not investment advice. The report should be reviewed against the original source document before use.
