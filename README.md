# Source-Verified Equity Research Engine

This project turns a company document into a formatted equity research report.

Upload a PDF, CSV, TXT, TEXT, or MD file. The pipeline extracts the financial data, checks it against the source, calculates the derived metrics, writes the narrative, renders the report, and gives you a downloadable PDF.

The important design decision is simple:

> Code calculates the numbers. AI helps explain them.

That keeps the report useful without letting a language model invent financial figures.

## What the app does

1. Accepts a financial document through the web UI or command line.
2. Detects the company and sector.
3. Extracts financial statements, KPIs, valuation data, and shareholding information.
4. Verifies extracted values against the uploaded source.
5. Calculates growth, margins, ratios, projections, and recommendation inputs in Python.
6. Generates an AI-assisted narrative using verified evidence.
7. Creates charts and renders a share-ready PDF.

PDF files use the OCR path. CSV, TXT, TEXT, and MD files use the structured text path, then continue through the same verification, analysis, and PDF-rendering stages.

## Run it locally

Create a virtual environment and install the dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

Copy the environment template and add your own provider credentials:

```bash
copy .env.example .env
```

Start the web app:

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

You can also run a document from the command line:

```bash
python run_one.py "path/to/company-report.pdf"
```

## Environment variables

The application reads credentials from environment variables. Keep real values in `.env` locally or in the deployment platform's secret manager. Never put them in frontend files or commit them to source control.

Required provider settings are listed in [.env.example](.env.example):

- Azure Document Intelligence for PDF OCR
- AWS Bedrock for structured financial extraction
- **DeepSeek V4 Pro** for narrative generation

Useful application settings include:

```env
ENVIRONMENT=production
LLM_REQUEST_TIMEOUT=60
GENERATE_RATE_LIMIT=20
GENERATE_RATE_WINDOW_SECONDS=600
```

In production mode, the API documentation endpoints are disabled. The server also adds browser security headers and limits report generation requests to 20 per 10 minutes per client by default.

## API surface

- `GET /` — serves the web interface
- `GET /health` — readiness check for a cloud load balancer
- `POST /generate-report` — accepts the source document and starts report generation
- `GET /download/{filename}` — downloads a generated PDF

The browser talks only to this FastAPI application. Azure and AWS credentials stay on the server and are used from environment variables, so they are never sent to the browser.

## Project layout

```text
main.py                 FastAPI app and report-generation endpoint
config.py               Environment configuration
schema.py               Typed report data models
run_one.py              Command-line runner
static/                 Upload UI and browser-side interactions
templates/              HTML/CSS templates used for PDF output
pipeline/               Extraction, retrieval, verification, analysis, and rendering stages
outputs/                Generated PDFs
uploads/                Temporary uploaded source files
tmp/                    Document-hash caches
Dockerfile              Container image with Playwright and Chromium
```

## Pipeline principles

The pipeline is intentionally data-first:

- Financial values come from the uploaded source or deterministic Python calculations.
- Missing values remain unavailable instead of being guessed.
- **DeepSeek V4 Pro** generates the business description, outlook, and research narrative from validated evidence.
- Forward estimates are labeled as estimates.
- Charts are generated from structured data.
- Verification runs before the final PDF is produced.

## Deployment

The included [Dockerfile](Dockerfile) is ready for a container platform such as Azure Container Apps, AWS App Runner, or Google Cloud Run.

For deployment:

1. Build and deploy the container.
2. Add the variables from `.env.example` through the platform's secret manager.
3. Set `ENVIRONMENT=production`.
4. Use the platform-provided `PORT` value.
5. Confirm `GET /health` returns a healthy response.

The application writes uploads, generated PDFs, and caches to local disk. Those files are temporary on most free/serverless platforms. Add object storage if reports must survive restarts or be shared between instances.

## Notes

- A first report may take a few minutes because it can call OCR and several model services.
- Repeated runs can be much faster because document results are cached.
- The service needs internet access to reach the configured OCR, model, and market-data providers.
- This is an AI-assisted research generator, not a substitute for a licensed analyst or investment advice.
