"""
Stage 08: Hybrid Retrieval Engine

IMPROVEMENTS over previous version:
  1. Sector-aware system prompts — Banking gets banking keys, IT gets IT keys.
     Old: One generic prompt for all sectors → missed banking-specific metrics.
     New: Prompt dynamically built from detected sector → higher extraction accuracy.

  2. Targeted text chunking — splits OCR text into sections and prioritises
     financial table sections rather than dumping 60k chars raw.
     Old: First 60k chars sent verbatim → tables buried under prose.
     New: Table sections extracted first, prose appended after.

  3. Smarter JSON repair — handles partial JSON, truncated responses,
     and DeepSeek R1 thinking block variants (<think> and <thinking>).

  4. Retry prompt is sector-specific, not hardcoded to banking.
"""

import json
import re
import sys
import os
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


# ─── Sector-specific field definitions ───────────────────────────────────────

_SECTOR_FIELDS: Dict[str, Dict[str, str]] = {
    "Banking": {
        "keys": (
            "nii, nim, advances, deposits, casa_ratio, gnpa, nnpa, pcr, "
            "roe, roa, capital_adequacy, tier1_ratio, pat, eps, net_interest_income, "
            "credit_growth, slippage_ratio, provision_expense"
        ),
        "hints": (
            "Look for: Net Interest Income (NII), Net Interest Margin (NIM%), "
            "Gross NPA%, Net NPA%, Provision Coverage Ratio (PCR%), "
            "Capital Adequacy Ratio (CAR/CRAR%), CASA Ratio%, "
            "Total Advances, Total Deposits, PAT, EPS, ROE%, ROA%."
        ),
    },
    "NBFC": {
        "keys": (
            "aum, disbursements, gnpa, nnpa, pcr, roe, roa, "
            "pat, eps, net_interest_income, cost_of_funds, yield_on_advances, "
            "capital_adequacy, total_assets"
        ),
        "hints": (
            "Look for: AUM (Assets Under Management), Disbursements, "
            "GNPA%, NNPA%, PCR%, Yield on Advances, Cost of Funds, "
            "Capital Adequacy, PAT, EPS, ROE%, ROA%."
        ),
    },
    "IT Services": {
        "keys": (
            "revenue, ebitda, ebit, pbt, pat, eps, dps, "
            "total_assets, total_equity, total_debt, cash_and_equivalents, "
            "operating_cash_flow, free_cash_flow, headcount, attrition_rate"
        ),
        "hints": (
            "Look for: Revenue from Operations, EBITDA, EBIT, PBT, PAT, EPS, "
            "Total Employees/Headcount, Attrition Rate%, "
            "Cash & Equivalents, Operating Cash Flow, Free Cash Flow."
        ),
    },
    "Energy": {
        "keys": (
            "revenue, ebitda, ebit, pbt, pat, eps, "
            "total_assets, total_debt, cash_and_equivalents, "
            "operating_cash_flow, free_cash_flow, "
            "installed_capacity_mw, generation_units, plf_pct"
        ),
        "hints": (
            "Look for: Revenue, EBITDA, PAT, EPS, Total Debt, "
            "Installed Capacity (MW/GW), Power Generation (MUs/BUs), "
            "Plant Load Factor (PLF%), Operating Cash Flow."
        ),
    },
    "Pharma": {
        "keys": (
            "revenue, ebitda, ebit, pbt, pat, eps, "
            "total_assets, total_debt, cash_and_equivalents, "
            "operating_cash_flow, free_cash_flow, "
            "r_and_d_expense, domestic_revenue, export_revenue"
        ),
        "hints": (
            "Look for: Revenue (Domestic + Export), EBITDA, PAT, EPS, "
            "R&D Expense, Total Debt, Cash & Equivalents, Operating Cash Flow."
        ),
    },
}

# Default for all other sectors (Infrastructure, FMCG, Auto, etc.)
_DEFAULT_FIELDS: Dict[str, str] = {
    "keys": (
        "revenue, ebitda, ebit, pbt, pat, eps, dps, interest, tax, "
        "total_assets, total_liabilities, total_equity, total_debt, "
        "cash_and_equivalents, operating_cash_flow, investing_cash_flow, "
        "financing_cash_flow, free_cash_flow"
    ),
    "hints": (
        "Look for: Revenue, EBITDA, EBIT, PBT, PAT, EPS, DPS, "
        "Total Assets, Total Debt, Cash & Equivalents, "
        "Operating Cash Flow, Free Cash Flow."
    ),
}


# ─── Text pre-processor ───────────────────────────────────────────────────────

def _extract_table_focused_text(full_text: str, max_chars: int = 55000) -> str:
    """
    Reorder OCR text to put table-dense sections first.
    Heuristic: lines with 3+ consecutive number-like tokens are likely table rows.
    This ensures financial tables reach the model before prose fills the context.
    """
    lines = full_text.split("\n")
    table_lines: List[str] = []
    prose_lines: List[str] = []

    number_pattern = re.compile(r'\b[\d,]+(?:\.\d+)?\b')

    for line in lines:
        numbers_in_line = number_pattern.findall(line)
        # Lines with >= 3 numbers are likely table rows
        if len(numbers_in_line) >= 3:
            table_lines.append(line)
        else:
            prose_lines.append(line)

    # Tables first, then prose
    reordered = "\n".join(table_lines) + "\n\n" + "\n".join(prose_lines)
    return reordered[:max_chars]


def _select_financial_pages(page_texts: List[str]) -> List[str]:
    """Select likely financial pages while retaining the original OCR corpus."""
    keywords = (
        "revenue", "sales", "ebitda", "ebit", "pbt", "pat", "profit", "loss",
        "balance sheet", "cash flow", "assets", "liabilities", "debt", "equity",
        "eps", "margin", "quarter", "annual", "financial", "particulars",
        "shareholding", "valuation", "nii", "npa", "nim", "advances", "deposits",
    )
    selected = []
    for page in page_texts:
        lower = page.lower()
        keyword_hits = sum(lower.count(term) for term in keywords)
        numeric_lines = sum(
            1 for line in page.splitlines()
            if len(re.findall(r"\b[\d,]+(?:\.\d+)?\b", line)) >= 3
        )
        if keyword_hits >= 2 or numeric_lines >= 3:
            selected.append(page)
    return selected or page_texts


# ─── JSON extractor ───────────────────────────────────────────────────────────

def _clean_llm_response(text: str) -> str:
    """Remove DeepSeek thinking blocks and markdown fences."""
    # Handle both <think> and <thinking> variants
    text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text,
                  flags=re.DOTALL | re.IGNORECASE)
    # Remove ```json ... ``` fences
    text = re.sub(r'```(?:json)?\s*|\s*```', '', text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json(raw: str) -> Dict[str, Any]:
    """
    Robustly extract JSON from LLM response.
    Tries in order:
      1. Direct json.loads after cleaning
      2. Regex match of outermost { ... }
      3. Attempt JSON repair on truncated responses (add closing braces)
    """
    cleaned = _clean_llm_response(raw)

    # DEBUG: Log what we're trying to parse
    preview = cleaned[:200] if cleaned else "(empty)"
    print(f"     [Hybrid Retriever] Parsing cleaned response (len={len(cleaned)}): {preview}...")

    # Attempt 1: direct parse
    try:
        result = json.loads(cleaned)
        print(f"     [Hybrid Retriever] ✓ Parsed JSON directly (keys: {list(result.keys())})")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        print(f"     [Hybrid Retriever] Direct parse failed: {e}")

    # Attempt 2: extract outermost object
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        candidate = match.group(0)
        print(f"     [Hybrid Retriever] Found JSON-like object (len={len(candidate)})")
        try:
            result = json.loads(candidate)
            print(f"     [Hybrid Retriever] ✓ Parsed extracted object (keys: {list(result.keys())})")
            return result
        except (json.JSONDecodeError, ValueError) as e:
            print(f"     [Hybrid Retriever] Extracted object parse failed: {e}")
            # Attempt 3: repair truncated JSON by closing open braces
            open_count = candidate.count('{') - candidate.count('}')
            if 0 < open_count <= 10:
                repaired = candidate + ('}' * open_count)
                print(f"     [Hybrid Retriever] Attempting repair (adding {open_count} closing braces)...")
                try:
                    result = json.loads(repaired)
                    print(f"     [Hybrid Retriever] ✓ Repaired JSON parsed (keys: {list(result.keys())})")
                    return result
                except (json.JSONDecodeError, ValueError) as e2:
                    print(f"     [Hybrid Retriever] Repair failed: {e2}")

    print(f"     [Hybrid Retriever] ✗ Failed to parse JSON from response. Raw preview: {raw[:300]}...")
    return {}


# ─── System prompt builder ────────────────────────────────────────────────────

def _build_system_prompt(sector: str) -> str:
    """Build a sector-specific extraction system prompt using SectorConfig."""
    import sys, os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from pipeline.sectors import get_sector_config
    cfg = get_sector_config(sector)

    return f"""You are a financial data extractor specialising in Indian equity research reports.
Your ONLY job is to return a valid JSON object. No explanation, no markdown, no chain-of-thought.

SECTOR DETECTED: {sector}

REQUIRED JSON KEYS for {sector}:
{cfg.extraction_keys}

EXTRACTION HINTS for {sector}:
{cfg.extraction_hints}

JSON SCHEMA — each key must be an object with these period sub-keys:
  fy22, fy23, fy24, fy25        → full fiscal year actuals (use null if absent)
  fy26e, fy27e                  → forward estimates (use null if absent)
  q_prev_year                   → same quarter prior year  (e.g. Q2FY25)
  q_prev_qtr                    → immediately preceding quarter (e.g. Q1FY26)
  q_current                     → latest reported quarter (e.g. Q2FY26)

PERIOD MAPPING RULES:
  Q2FY26 → q_current | Q1FY26 → q_prev_qtr | Q2FY25 → q_prev_year
  FY25   → fy25      | FY24   → fy24        | FY23   → fy23

CRITICAL RULES:
  - Use null for any value not explicitly stated in the document
  - NEVER invent or estimate values
  - Extract raw numbers only (no units in values — use the number itself)
  - All values in same unit as source (do not convert)
  - OUTPUT: Pure JSON starting with {{ and ending with }}"""


def _build_retry_prompt(sector: str, attempt: int, source_text: str) -> str:
    """Build a targeted retry prompt using sector config hints."""
    import sys, os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
    from pipeline.sectors import get_sector_config
    cfg = get_sector_config(sector)

    retry_note = (
        f"\n\nRETRY ATTEMPT {attempt}: Previous extraction was incomplete.\n"
        f"Carefully re-scan EVERY TABLE in the document.\n"
        f"Specifically look for these {sector} metrics:\n"
        f"{cfg.extraction_hints}\n"
        f"Return ALL values you can find. Still use null for genuinely absent values."
    )
    return source_text + retry_note


# ─── Main Retriever ───────────────────────────────────────────────────────────

class HybridRetriever:
    def __init__(self, execution_plan: Any, master_doc: Any = None):
        self.execution_plan = execution_plan
        self.master_doc = master_doc
        # Detect sector from execution plan (set by Stage 05)
        self.sector: str = getattr(execution_plan, "sector", None) or "Other"

    def _get_page_texts(self) -> List[str]:
        """Get text for each page from the MasterDocument using proper type checks."""
        pages = []
        if self.master_doc and self.master_doc.sections:
            from dom_schema import ParagraphNode, TableNode
            for section in self.master_doc.sections:
                page_text = ""
                for node in section.nodes:
                    if isinstance(node, ParagraphNode):
                        page_text += node.text + "\n"
                    elif isinstance(node, TableNode):
                        page_text += node.csv_string + "\n"
                if page_text.strip():
                    pages.append(page_text.strip())
        return pages

    def retrieve_financials(self, attempt: int = 1) -> Dict[str, Any]:
        print(f"     [Hybrid Retriever] Extracting {self.sector} financials "
              f"via GPT-5-mini — attempt {attempt}...")
        from pipeline.utils.llm_client import call_bedrock_mistral_large

        # Get page texts for per-page chunked extraction
        page_texts = self._get_page_texts()
        system_prompt = _build_system_prompt(self.sector)

        if not page_texts:
            # Fallback: full-text extraction
            raw_text = (self.master_doc.get_full_text() if self.master_doc else "") or ""
            source_text = _extract_table_focused_text(raw_text, max_chars=55000)
            user_prompt = source_text or "No source text available."
            if attempt > 1:
                user_prompt = _build_retry_prompt(self.sector, attempt, source_text)
            response = call_bedrock_mistral_large(system_prompt, user_prompt)
            return _extract_json(response or "")

        # ── Per-page chunked extraction (PARALLEL) ─────────────────────────
        # Extract financial data from each page concurrently, then merge results
        # NO TRUNCATION — each page gets its full text for 100% extraction
        selected_pages = _select_financial_pages(page_texts)
        print(
            f"     [Hybrid Retriever] Financial-page batch extraction: "
            f"{len(selected_pages)}/{len(page_texts)} pages"
        )
        source_chunks = []
        for page_idx, page_text in enumerate(page_texts):
            if page_text in selected_pages:
                source_chunks.append(
                    f"===== SOURCE PAGE {page_idx + 1} =====\n{page_text}"
                )
        source_text = "\n\n".join(source_chunks)
        cache_dir = Path("tmp") / "financial_extraction_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(
            f"{self.sector}\n{source_text}".encode("utf-8", errors="ignore")
        ).hexdigest()
        cache_path = cache_dir / f"{cache_key}.json"
        if attempt == 1 and cache_path.exists():
            try:
                cached_result = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached_result, dict) and cached_result:
                    print("     [Hybrid Retriever] Financial extraction cache hit")
                    return cached_result
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        user_prompt = (
            _build_retry_prompt(self.sector, attempt, source_text)
            if attempt > 1 else
            "Extract all required financial values from these source pages. "
            "Return one complete JSON object and use null for absent values.\n\n"
            + source_text
        )
        response = call_bedrock_mistral_large(system_prompt, user_prompt)
        result = _extract_json(response or "")
        if result:
            cache_path.write_text(json.dumps(result), encoding="utf-8")
        print(
            f"     [Hybrid Retriever] Batch extraction complete. "
            f"Keys: {list(result.keys())[:10]}"
        )
        return result

        print(f"     [Hybrid Retriever] Per-page extraction (PARALLEL) — {len(page_texts)} pages")
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _extract_page(args):
            page_idx, page_text = args
            if len(page_text.strip()) < 100:
                return page_idx, {}
            page_prompt = (
                f"Extract financial data from PAGE {page_idx + 1} of the document.\n\n"
                f"PAGE {page_idx + 1} CONTENT:\n{page_text}"
            )
            response = call_bedrock_mistral_large(system_prompt, page_prompt)
            page_result = _extract_json(response or "")
            return page_idx, page_result or {}

        all_results: Dict[str, Any] = {}
        extraction_page = None

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_idx = {
                executor.submit(_extract_page, (idx, txt)): idx
                for idx, txt in enumerate(page_texts)
            }
            # Gather in order of completion
            for future in as_completed(future_to_idx):
                page_idx, page_result = future.result()
                if not page_result:
                    continue

                has_significant_data = any(
                    page_result.get(k) and len(str(page_result[k])) > 100
                    for k in ['profit_loss', 'balance_sheet', 'annual', 'quarterly', 'nii', 'pat']
                )
                if has_significant_data and not extraction_page:
                    extraction_page = page_idx + 1
                    print(f"     [Hybrid Retriever] Page {page_idx + 1} has significant financial data")

                # Merge non-null fields into all_results
                for key, value in page_result.items():
                    if isinstance(value, dict) and value:
                        if key not in all_results or not all_results[key]:
                            all_results[key] = value
                        else:
                            existing = all_results[key]
                            if isinstance(existing, dict):
                                for k, v in value.items():
                                    if isinstance(v, dict) and v:
                                        if k not in existing or not existing[k]:
                                            existing[k] = v
                                    elif v not in (None, '', [], {}, 'null'):
                                        if k not in existing or existing[k] in (None, '', '—', 'null'):
                                            existing[k] = v
                    elif value not in (None, '', [], {}, 'null'):
                        if key not in all_results or all_results[key] in (None, '', [], 'null'):
                            all_results[key] = value

        print(f"     [Hybrid Retriever] Per-page parallel extraction complete. "
              f"Best data from page {extraction_page or 'unknown'}. "
              f"Keys: {list(all_results.keys())[:10]}")
        return all_results

    def retrieve_narratives(self) -> List[str]:
        """
        Return management commentary sentences extracted by Stage 02.
        Falls back to empty list — narratives are optional context only.
        """
        if self.master_doc and hasattr(self.master_doc, "knowledge_graph"):
            return self.master_doc.knowledge_graph.get("management_commentary", [])
        return []
