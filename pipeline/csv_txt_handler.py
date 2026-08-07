"""
csv_txt_handler.py — CSV and TXT input handler

Converts CSV or TXT financial data into the same raw_financials JSON dict
that the PDF pipeline produces, so everything downstream works unchanged.

Supported formats:
  CSV: rows = metrics, columns = periods (e.g. FY23,FY24,FY25,Q2FY26)
       First column = metric name, rest = values
  TXT: free-form text with financial data — sent to DeepSeek V4 Pro
       for extraction using same prompt as Stage 08
"""
import csv
import io
import json
import re
from typing import Dict, Any, Optional


# Metric name → raw_financials JSON key mapping
_CSV_METRIC_MAP = {
    # Revenue / top line
    "revenue":              "revenue",
    "net revenue":          "revenue",
    "sales":                "revenue",
    "net sales":            "revenue",
    "total revenue":        "revenue",
    "revenue from ops":     "revenue",
    "nii":                  "nii",
    "net interest income":  "nii",

    # Profitability
    "ebitda":               "ebitda",
    "operating profit":     "ebitda",
    "ebit":                 "ebit",
    "pat":                  "pat",
    "net profit":           "pat",
    "profit after tax":     "pat",
    "net income":           "pat",
    "eps":                  "eps",
    "earnings per share":   "eps",
    "diluted eps":          "eps",

    # Balance sheet
    "total assets":         "total_assets",
    "total liabilities":    "total_liabilities",
    "total equity":         "total_equity",
    "shareholders equity":  "total_equity",
    "total debt":           "total_debt",
    "borrowings":           "total_debt",
    "cash":                 "cash",
    "cash and equivalents": "cash",

    # Cash flow
    "operating cf":         "operating_cash_flow",
    "operating cash flow":  "operating_cash_flow",
    "cfo":                  "operating_cash_flow",
    "investing cf":         "investing_cash_flow",
    "cfi":                  "investing_cash_flow",
    "financing cf":         "financing_cash_flow",
    "cff":                  "financing_cash_flow",

    # Banking
    "advances":             "advances",
    "loans":                "advances",
    "deposits":             "deposits",
    "nim":                  "nim",
    "gnpa":                 "gnpa",
    "nnpa":                 "nnpa",
    "pcr":                  "pcr",
    "casa":                 "casa_ratio",
    "roe":                  "roe",
    "roa":                  "roa",
    "capital adequacy":     "capital_adequacy",
    "car":                  "capital_adequacy",
    "tier 1":               "tier1_ratio",
    "tier1":                "tier1_ratio",
}

# Period label → raw_financials field mapping
_PERIOD_MAP = {
    "fy22":     "fy22",  "fy2022": "fy22",  "2022": "fy22",
    "fy23":     "fy23",  "fy2023": "fy23",  "2023": "fy23",
    "fy24":     "fy24",  "fy2024": "fy24",  "2024": "fy24",
    "fy25":     "fy25",  "fy2025": "fy25",  "2025": "fy25",
    "fy26e":    "fy26e", "fy26":   "fy26e",
    "fy27e":    "fy27e", "fy27":   "fy27e",
    "q1fy25":   "q_prev_year",  "q1 fy25": "q_prev_year",
    "q2fy25":   "q_prev_year",  "q2 fy25": "q_prev_year",
    "q3fy25":   "q_prev_year",  "q4fy25":  "q_prev_year",
    "q1fy26":   "q_prev_qtr",   "q1 fy26": "q_prev_qtr",
    "q2fy26":   "q_current",    "q2 fy26": "q_current",
    "q3fy26":   "q_current",    "q4fy26":  "q_current",
    "current":  "q_current",
    "prev qtr": "q_prev_qtr",   "prev quarter": "q_prev_qtr",
    "yoy":      "q_prev_year",
}


def _safe_float(val: str) -> Optional[float]:
    if not val or val.strip() in ("", "-", "—", "N/A", "NA", "n/a"):
        return None
    cleaned = re.sub(r"[,₹$%\s]", "", val.strip())
    try:
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None


def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def parse_csv(content: str) -> Dict[str, Any]:
    """
    Parse CSV where:
      Row 1 = headers: Metric | Period1 | Period2 | ...
      Row 2+ = data:   Revenue | 29795   | 25710   | ...
    """
    raw: Dict[str, Any] = {}
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return raw

    # First row = headers
    headers = [h.strip().lower() for h in rows[0]]
    if not headers:
        return raw

    # Map header positions to period keys
    period_fields = []
    for h in headers[1:]:   # skip first col (metric name)
        norm = _norm_key(h)
        field = _PERIOD_MAP.get(norm, norm)
        period_fields.append(field)

    for row in rows[1:]:
        if not row:
            continue
        metric_label = _norm_key(row[0])
        json_key = None
        for candidate, jkey in _CSV_METRIC_MAP.items():
            if candidate in metric_label or metric_label in candidate:
                json_key = jkey
                break
        if not json_key:
            continue

        metric_data: Dict[str, Any] = {}
        for i, field in enumerate(period_fields):
            cell_idx = i + 1
            if cell_idx < len(row):
                v = _safe_float(row[cell_idx])
                if v is not None:
                    metric_data[field] = v

        if metric_data:
            raw[json_key] = metric_data

    print(f"     [CSV Handler] Parsed {len(raw)} metric(s) from CSV.")
    return raw


def parse_txt(content: str, sector: str = "") -> Dict[str, Any]:
    """
    Send free-form TXT to DeepSeek V4 Pro with same extraction prompt
    as Stage 08 (Hybrid Retrieval), returning same JSON structure.
    """
    from pipeline.utils.llm_client import call_azure_deepseek

    sector_hint = f"Sector: {sector}. " if sector else ""
    is_banking = any(w in sector.lower() for w in ("bank", "nbfc", "finance"))

    if is_banking:
        fields = """nii, nim, advances, deposits, casa_ratio, gnpa, nnpa,
pcr, roe, roa, capital_adequacy, tier1_ratio, pat, eps"""
    else:
        fields = """revenue, ebitda, ebit, pat, eps, total_assets,
total_equity, total_debt, cash, operating_cash_flow"""

    system = "You are a financial data extraction expert. Extract structured financials from text. Return ONLY valid JSON."
    user = f"""{sector_hint}Extract all financial metrics from the text below.

For each metric, extract values for: fy22, fy23, fy24, fy25, fy26e, fy27e, 
q_prev_year, q_prev_qtr, q_current.
Use null for missing values. Numbers only (no units in values).

Required metrics: {fields}

Return JSON format:
{{
  "revenue": {{"fy25": 9642, "q_current": 2980, ...}},
  "pat":     {{"fy25": 1264, "q_current": 329, ...}},
  ...
}}

TEXT:
{content[:8000]}"""

    print("     [TXT Handler] Sending to DeepSeek V4 Pro for extraction...")
    raw_resp = call_azure_deepseek(system, user, max_tokens=2048, temperature=0.1)
    if not raw_resp:
        return {}

    raw_resp = re.sub(r"```json|```", "", raw_resp).strip()
    m = re.search(r"\{.*\}", raw_resp, re.DOTALL)
    if not m:
        return {}

    try:
        data = json.loads(m.group(0))
        print(f"     [TXT Handler] Extracted {len(data)} metric(s) from TXT.")
        return data
    except json.JSONDecodeError:
        return {}


def handle_non_pdf(file_content: bytes, filename: str, sector: str = "") -> Dict[str, Any]:
    """
    Main entry point. Detects CSV vs TXT and returns raw_financials dict.
    """
    ext = Path(filename).suffix.lower()
    try:
        text = file_content.decode("utf-8", errors="replace")
    except Exception:
        text = ""

    if ext == ".csv":
        print(f"     [Input Handler] CSV file detected: {filename}")
        return parse_csv(text)
    elif ext in (".txt", ".text", ".md"):
        print(f"     [Input Handler] TXT file detected: {filename}")
        return parse_txt(text, sector=sector)
    else:
        print(f"     [Input Handler] Unknown extension {ext} — treating as TXT.")
        return parse_txt(text, sector=sector)
