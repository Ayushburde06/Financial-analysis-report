# Geojit-Style Equity Research Report Generator

Upload a company financial document and get a downloadable equity research PDF in a Geojit-inspired format. The report includes financial tables, charts, highlights, narrative analysis, and disclosures when the source supports them.

Repository: [Financial-analysis-report](https://github.com/Ayushburde06/Financial-analysis-report)

## Demo

[Open the live application](https://financial-analysis-report.vercel.app/)

### Submission reports

1. **ICICI Q2FY26**: [generated PDF](submission/reports/ICICI%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/ICICI Q2FY26.pdf`
2. **JSW Energy Q2FY26**: [generated PDF](submission/reports/JSW%20Energy%20Q2FY26_Geojit_Report.pdf) - source path: `PDF/JSW Energy Q2FY26.pdf`

## How it works

The pipeline is source-first:

1. The document is read with Azure Document Intelligence, or directly for CSV and text files.
2. Structured facts are extracted and checked against the source.
3. Python calculates derived values such as growth and margins only when the inputs are verified.
4. The verified data drives the tables, charts, and LLM-written explanations.

Missing information stays unavailable instead of being guessed. The app does not fetch market data automatically, so a missing CMP, target price, or rating remains unavailable.

Supported files: PDF, CSV, TXT, TEXT, and Markdown.

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

## Disclaimer

This is an AI-assisted document analysis and report-generation tool. It is not investment advice. The report should be reviewed against the original source document before use.
