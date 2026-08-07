# Financial Research Pipeline Rules

## Core Principle

The pipeline is DATA-FIRST.

LLMs generate language.
Code generates numbers.

Every numerical value in the final report must originate from extracted financial data or deterministic calculations.

---

## 1. OCR & Layout

Responsible for:

- Reading PDFs
- Preserving layout
- Tables
- Images
- Page numbers
- Coordinates

Output:

Canonical Document Model (CDM)

LLMs must NOT perform OCR if a dedicated OCR model is available.

---

## 2. Structured Extraction

Model:
- Ministral 3 14B (or configured extraction model)

Responsibilities:

- Company profile
- Profit & Loss
- Balance Sheet
- Cash Flow
- Quarterly Financials
- Shareholding
- Risks
- Management Commentary
- Guidance
- Business Segments

Rules:

- Return JSON only.
- No calculations.
- No forecasting.
- No recommendations.
- No summaries unless explicitly requested.
- Missing values must be null, never invented.

---

## 3. Retrieval (RAG)

RAG is evidence retrieval only.

Never use RAG to write reports.

Retrieve only the minimum evidence required for the current task.

Use:

- Dense retrieval
- BM25
- Metadata filtering
- Reranking

---

## 4. Validation Engine

Before any downstream processing:

Validate:

- Required fields exist
- Currency consistency
- Units (Cr, Mn, Bn)
- Year alignment
- Quarter alignment
- Table completeness

Reject invalid JSON.

---

## 5. Financial Compute Engine (Python Only)

Python exclusively computes:

- Growth
- CAGR
- Margins
- ROE
- ROCE
- ROA
- EPS
- BVPS
- P/E
- P/B
- EV/EBITDA
- D/E
- Current Ratio
- Quick Ratio
- Forecast metrics

LLMs must NEVER perform financial calculations.

---

## 6. Recommendation Engine (Python Only)

Recommendations are deterministic.

Inputs include:

- CMP
- Target Price
- Expected Return
- Valuation metrics
- Configurable policy thresholds

The recommendation engine returns:

BUY / HOLD / SELL

LLMs may explain the recommendation but must never determine it.

---

## 7. Chart Generator

Only Matplotlib or Plotly may generate charts.

Charts must be regenerated from extracted numerical data.

Never:

- OCR existing charts
- Screenshot charts
- Generate fake charts with an LLM

---

## 8. Narrative Generator

LLMs may generate:

- Executive Summary
- Investment Thesis
- Outlook
- Key Positives
- Key Risks
- Management Discussion

Narrative must reference validated structured data.

Narrative must not invent metrics.

---

## 9. Evidence Binding

Every generated statement should be traceable.

Each important value should include:

- Source page
- Source table
- Confidence
- Extraction origin

---

## 10. Rendering

Renderer responsibilities:

- HTML
- CSS
- Pagination
- Tables
- Images
- Charts
- PDF generation

Rendering performs no calculations.

---

## 11. Regression Rules

No future modification may:

- Move calculations into an LLM
- Move recommendations into an LLM
- Replace deterministic charts with OCR images
- Remove validation
- Skip structured JSON

All changes must preserve the deterministic architecture.

---

## 12. Multi-Agent Swarm Architecture
Monolithic prompts are forbidden. Each agent is isolated by 
input, purpose, and output schema.

1. Financial Analyst  → P&L, BS, CF → revenue/margin/PAT analysis
2. Growth Analyst     → YoY/QoQ QuantSheet → growth drivers
3. Risk Analyst       → Debt/margins/cashflow → 3-5 cited risks
4. Valuation Analyst  → DCF/multiples/forecast → target rationale
5. Lead Analyst       → 4 agent outputs → highlights/outlook/rating

Each agent receives a typed JSON evidence packet only.
Schema defined in `/quant/evidence_packets.py`.

## 13. Hybrid Forward Projections
- Python computes all forward numbers (FY26E, FY27E) based on: Annual History > Guidance > TTM > Run-Rate (Low Confidence).
- LLM only explains the assumptions behind Python's output
- All projections tagged `[E]`. All missing actuals tagged `[N/A]`
- Neither tag is ever omitted or overridden by LLM output

## 14. The 5-Layer Verification Stack
Layer 1 — Extraction Verifier (Python)
  Number exists in MasterDocument → tag source + page
Layer 2 — Math Verifier (Python)  
  Derived metrics recompute within ±0.5% → else override
Layer 3 — Claim Verifier (LLM+RAG)
  Every narrative assertion maps to a Layer 1 verified number
Layer 4 — Cross-Agent Verifier (Python/LLM)
  Flag contradictions between agent outputs for Lead Analyst
Layer 5 — Confidence Scorer (Python)
  Section score drives footnote/asterisk in final PDF

No output from any layer enters the report without passing 
all prior layers.

## 15. LLM Quarantine Rule
LLMs never receive raw OCR output, unverified numbers, 
or another LLM's output without Python validation between them.
LLMs only receive typed, verified evidence packets.
All arithmetic stays in Python. Always.

## 16. The 14-Stage Institutional Pipeline
The end-to-end pipeline must strictly implement these 14 stages. No skipping stages.
1. Financial Structure Builder: Converts messy OCR into normalized Financial Objects (No LLM math).
2. Company Knowledge Builder: Organizes data by business concepts (Strategy, ESG, Risks) rather than pages.
3. Business KPI Discovery Engine: Identifies what success means for the specific company (e.g. CASA for Banks).
4. Coverage Analyzer: Determines evidence availability (e.g. missing 5-year historicals) without reasoning.
5. Industry Detection Engine: Detects sector and subsector to drive analysis.
6. Adaptive Analysis Planner: Determines which analysis modules to run and which to skip.
7. Storage Layer:
   - SQL: Stores financial statements, KPIs, ratios (numbers).
   - Vector DB: Stores chunked narrative (commentary, risks).
   - Knowledge Graph: Stores entity relationships.
8. Hybrid Retrieval Engine: Routes queries (Numbers -> SQL, Commentary -> Vector, Relationships -> Graph).
9. Quant Engine: Pure Python math (YoY, Margins, Projections).
10. Evidence Builder: Compiles Hybrid Retrieval output into strict Evidence Packets.
11. Specialist AI Agents: (Financial, Growth, Risk, ESG, Operations, Strategy). Each receives ONLY its packet.
12. Verification Pipeline: 6-check stack (Financial, Citation, Math, Consistency, Hallucination, Confidence).
13. Lead Research Analyst: Reads agent reports, writes executive synthesis. No calculations.
14. Report Object Model (ROM): Generates structured report objects (Tables, Charts, Sections) rather than raw HTML strings.

