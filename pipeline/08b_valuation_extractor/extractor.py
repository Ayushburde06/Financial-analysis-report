"""
Stage 08b: Valuation & Shareholding Extractor

Extracts the 3 sections that were missing from the Geojit sample:
  1. Valuation data: CMP, target price, P/E, P/B, EV/EBITDA, D/E, ROE
  2. Estimate revision table: old vs new FY26E/FY27E estimates + change %
  3. Shareholding pattern: Promoters, FII, MF, Public % across last 3 quarters

Uses Mistral Large 3 (same model as Stage 08) — structured JSON output.
Falls back gracefully to empty dicts if data is not in the source document.

Output schema:
{
  "valuation": {
    "cmp": 306.0,
    "target_price": 337.0,
    "upside_pct": 10.2,
    "market_cap_cr": 295735.0,
    "enterprise_value_cr": 294166.0,
    "pe_fy26e": 325.2,
    "pe_fy27e": 114.1,
    "pb_fy26e": 9.6,
    "pb_fy27e": 8.9,
    "ev_ebitda_fy26e": 240.3,
    "ev_ebitda_fy27e": 84.0,
    "roe_fy26e": 3.0,
    "roe_fy27e": 7.8,
    "de_fy26e": 0.1,
    "de_fy27e": 0.1,
    "valuation_methodology": "6x FY27 price/sales",
    "week52_high": 314.0,
    "week52_low": 190.0,
    "beta": 1.0,
    "free_float_pct": 71.9,
    "outstanding_shares_cr": 965.0,
    "face_value": 1.0,
    "dividend_yield_pct": null
  },
  "estimate_revision": {
    "metrics": ["Revenue", "EBITDA", "EBITDA Margin (%)", "PAT", "EPS"],
    "old_fy26e": {"Revenue": 30738, "EBITDA": 1686, ...},
    "new_fy26e": {"Revenue": 35020, "EBITDA": 1248, ...},
    "change_fy26e_pct": {"Revenue": 13.9, "EBITDA": -25.9, ...},
    "old_fy27e": {...},
    "new_fy27e": {...},
    "change_fy27e_pct": {...}
  },
  "shareholding": {
    "quarters": ["Q3FY25", "Q4FY25", "Q1FY26"],
    "promoters": {"Q3FY25": 0.0, "Q4FY25": 0.0, "Q1FY26": 0.0},
    "fii": {"Q3FY25": 47.3, "Q4FY25": 44.4, "Q1FY26": 42.3},
    "mf_institutions": {"Q3FY25": 20.5, "Q4FY25": 23.6, "Q1FY26": 26.6},
    "public": {"Q3FY25": 8.0, "Q4FY25": 8.5, "Q1FY26": 7.6},
    "others": {"Q3FY25": 24.1, "Q4FY25": 23.6, "Q1FY26": 23.5}
  }
}
"""

import json
import re
import sys
import os
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))


_SYSTEM_PROMPT = """You are a financial data extractor for Indian equity research reports.
Return ONLY a valid JSON object — no explanation, no markdown, no chain-of-thought.

Extract THREE sections:

1. "valuation" — stock data. Keys: cmp, target_price, upside_pct, market_cap_cr,
   enterprise_value_cr, pe_fy26e, pe_fy27e, pb_fy26e, pb_fy27e, ev_ebitda_fy26e,
   ev_ebitda_fy27e, roe_fy26e, roe_fy27e, de_fy26e, de_fy27e,
   valuation_methodology, week52_high, week52_low, beta, free_float_pct,
   outstanding_shares_cr, face_value, dividend_yield_pct.
   Use null for missing. CMP = Current Market Price.

2. "estimate_revision" — old vs new estimates table (if present). Keys:
   metrics (list), old_fy26e, new_fy26e, change_fy26e_pct,
   old_fy27e, new_fy27e, change_fy27e_pct (all dicts metric→value).
   Return empty dicts if no revision table exists.

3. "shareholding" — shareholding pattern. CRITICAL — THIS IS THE MOST IMPORTANT SECTION.
   - The OCR text contains a shareholding table with columns for quarters and rows for categories.
   - The table structure is: [header row with quarters] followed by rows of [category name] [values...]
   - Categories are labelled: Promoters, FII's (or FIIs), MFs/Institutions (or MF/Inst), Public, Others, Total.
     Also accept: "Promoter & Promoter Group", "Foreign Institutional", "Domestic",
     "Non-Institutional", "HNI", "Insurance", "DII", "Mutual Fund", "Retail", "Body Corporate"
   - NOTE: OCR may encode "FII's" as "FIIΓÇÖs" or "FIIs" — treat all of these as "fii".
   - Quarter labels appear as: Q3FY25, Q4FY25, Q1FY26, Q2FY26, or may need normalisation.
   - Extract percentages as numbers (e.g. 47.3 not "47.3%"). Values are in percent.
   - Return the EXACT number of quarters found (usually 3). DO NOT omit quarters.
   - Return:
     quarters: [list of quarter labels in order they appear, e.g. ["Q3FY25","Q4FY25","Q1FY26"]]
     promoters: {quarter: pct, ...}
     fii: {quarter: pct, ...}  (FII + FPI + Foreign Institutional — catch all "FII" variants)
     mf_institutions: {quarter: pct, ...}  (MF + DII + Institutional + Insurance + "MFs/Inst")
     public: {quarter: pct, ...}  (Public + Retail + Non-Institutional)
     others: {quarter: pct, ...}  (Others + Body Corporate + remaining)
     total: {quarter: pct, ...}  (if Total row exists)
   - IMPORTANT: If you see ANY shareholding table at all, EXTRACT ALL the data from it.
     Only return empty dicts if absolutely no shareholding table exists anywhere in the text.

OUTPUT: Pure JSON with exactly these 3 keys: valuation, estimate_revision, shareholding."""


def _clean_response(text: str) -> str:
    """Strip thinking blocks and markdown fences."""
    text = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'```(?:json)?\s*|\s*```', '', text, flags=re.IGNORECASE)
    return text.strip()


def _parse_json(raw: str) -> Dict[str, Any]:
    """Robustly extract JSON from LLM response."""
    cleaned = _clean_response(raw)
    # Direct parse
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    # Extract outermost object
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            # Try repairing truncated JSON
            open_count = candidate.count('{') - candidate.count('}')
            if 0 < open_count <= 15:
                try:
                    return json.loads(candidate + '}' * open_count)
                except (json.JSONDecodeError, ValueError):
                    pass
    return {}


def _empty_result() -> Dict[str, Any]:
    return {
        "valuation": {},
        "estimate_revision": {
            "metrics": [], "old_fy26e": {}, "new_fy26e": {},
            "change_fy26e_pct": {}, "old_fy27e": {}, "new_fy27e": {},
            "change_fy27e_pct": {}
        },
        "shareholding": {
            "quarters": [], "promoters": {}, "fii": {},
            "mf_institutions": {}, "public": {}, "others": {}
        },
    }


def _regex_shareholding(ocr_text: str) -> Dict[str, Any]:
    """
    Pre-extract shareholding data from OCR text using line-by-line parsing.
    Handles two OCR layouts:

    VERTICAL (most common — LTTS, POCL, JSW):
        Shareholding  (%)
        Q3FY25
        Q4FY25
        Q1FY26
        Promoters
        0.0
        0.0
        0.0
        FII's
        47.3
        44.4
        42.3
        ...

    HORIZONTAL (rare — ICICI):
        Shareholding (%)  Q2FY26  Q1FY26  Q2FY25
        Promoters  —  —  —
        ...

    Returns None if no parseable shareholding table is found.
    """
    if not ocr_text:
        return None

    # Normalise encoding artifacts
    cleaned = ocr_text.replace('ΓÇÖ', "'").replace('ΓÇÖs', "'s").replace('ΓÇÖS', "'S")

    # Strategy 1: Try VERTICAL layout (each number on its own line)
    result = _parse_vertical_shareholding(cleaned)
    if result:
        return result

    # Strategy 2: Try HORIZONTAL layout (categories on same line as values)
    result = _parse_horizontal_shareholding(cleaned)
    if result:
        return result

    return None


def _parse_vertical_shareholding(ocr_text: str) -> Optional[Dict[str, Any]]:
    """Parse vertical shareholding layout: category on one line, values on subsequent lines."""
    idx = ocr_text.lower().find('shareholding')
    if idx < 0:
        return None

    # Take ~800 chars after shareholding header
    snippet = ocr_text[idx:idx + 1200]
    lines = snippet.split('\n')

    qtrs = []
    categories: Dict[str, List[float]] = {}
    current_cat: Optional[str] = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Quarter header lines: Q3FY25, Q4FY25, etc.
        qtr_match = re.match(r'^Q[1-4]\s*FY\s*\d{2,4}\s*$', stripped, re.IGNORECASE)
        if qtr_match:
            qtrs.append(qtr_match.group(0).replace(' ', '').upper())
            continue

        # Category labels
        if re.search(r'promoter', stripped, re.IGNORECASE) and not re.search(r'pledge', stripped, re.IGNORECASE):
            current_cat = 'promoters'
            categories.setdefault(current_cat, [])
            continue
        if re.search(r'fii', stripped, re.IGNORECASE):
            current_cat = 'fii'
            categories.setdefault(current_cat, [])
            continue
        if re.search(r'mf[^a-z/]|mutual\s*fund|dii|institution', stripped, re.IGNORECASE) and not re.search(r'fii', stripped, re.IGNORECASE):
            current_cat = 'mf_institutions'
            categories.setdefault(current_cat, [])
            continue
        if re.search(r'public|retail|non.institutional', stripped, re.IGNORECASE):
            current_cat = 'public'
            categories.setdefault(current_cat, [])
            continue
        if re.search(r'others|body\s*corporate', stripped, re.IGNORECASE):
            current_cat = 'others'
            categories.setdefault(current_cat, [])
            continue
        if re.match(r'^\s*total\b', stripped, re.IGNORECASE) and not re.search(r'asset', stripped, re.IGNORECASE):
            current_cat = 'total'
            categories.setdefault(current_cat, [])
            continue

        # Numeric values
        num_match = re.match(r'^(\d+\.?\d*)\s*$', stripped)
        if num_match and current_cat and len(categories.get(current_cat, [])) < len(qtrs):
            categories[current_cat].append(float(num_match.group(1)))
            continue

        # Stop when we hit the next section
        if re.search(r'price\s*perform(?:ance)?|pledge|key\s*highlight|revenue\s*for', stripped, re.IGNORECASE):
            if current_cat and categories.get(current_cat):
                break

    # Validate: need at least 2 quarters and 3+ categories with data
    if len(qtrs) < 2 or len(categories) < 3:
        return None

    # Build result dict
    result: Dict[str, Any] = {'quarters': qtrs}
    for cat, vals in categories.items():
        if len(vals) >= len(qtrs):
            result[cat] = {qtrs[i]: round(vals[i], 2) for i in range(len(qtrs))}
        else:
            # Partial data — pad with remaining slots empty
            result[cat] = {qtrs[i]: vals[i] if i < len(vals) else 0.0 for i in range(len(qtrs))}

    # Ensure required cats
    for cat in ['promoters', 'fii', 'mf_institutions', 'public', 'others']:
        if cat not in result:
            result[cat] = {}

    return result


def _parse_horizontal_shareholding(ocr_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse horizontal shareholding layout: categories and values on same line.
    Example: Promoters  —  —  —  → category with 3 dashes
    """
    idx = ocr_text.lower().find('shareholding')
    if idx < 0:
        return None

    snippet = ocr_text[idx:idx + 1200]
    # Normalise dashes
    snippet = re.sub(r'[ΓÇöΓÇòΓÇö]', '—', snippet)

    qtrs = []
    qtr_line_match = re.search(r'(?:Shareholding.*?\n)(.*?)\n', snippet, re.IGNORECASE)
    if qtr_line_match:
        qtr_line = qtr_line_match.group(1)
        qtrs = re.findall(r'(Q[1-4]\s*FY\s*\d{2,4})', qtr_line, re.IGNORECASE)
        qtrs = [q.replace(' ', '').upper() for q in qtrs]

    if len(qtrs) < 2:
        return None

    cat_map = [
        ('promoters', re.compile(r'promoter', re.IGNORECASE)),
        ('fii', re.compile(r'fii', re.IGNORECASE)),
        ('mf_institutions', re.compile(r'mf[^a-z]*inst|mf/in', re.IGNORECASE)),
        ('public', re.compile(r'public', re.IGNORECASE)),
        ('others', re.compile(r'others', re.IGNORECASE)),
        ('total', re.compile(r'total', re.IGNORECASE)),
    ]

    num_pat = re.compile(r'(\d+\.?\d*|—)')
    result: Dict[str, Any] = {'quarters': qtrs}

    for label, pat in cat_map:
        for line in snippet.split('\n'):
            if pat.search(line):
                tokens = num_pat.findall(line)
                if len(tokens) >= len(qtrs):
                    vals = {}
                    for i in range(len(qtrs)):
                        t = tokens[i].strip()
                        vals[qtrs[i]] = float(t) if t != '—' and t else 0.0
                    result[label] = vals
                    break

    if len(result) >= 4:  # quarters + at least 3 categories
        for cat in ['promoters', 'fii', 'mf_institutions', 'public', 'others']:
            if cat not in result:
                result[cat] = {}
        return result

    return None


class ValuationExtractor:
    """
    Stage 08b: Extract valuation, estimate revision, and shareholding data.
    Uses GPT-5-mini via Azure OpenAI — same model as Stage 08.
    Now supports per-page extraction for 100% coverage.
    """

    @staticmethod
    def run(ocr_text: str, page_texts: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Args:
            ocr_text: Full OCR text from Stage 01
            page_texts: Optional list of per-page texts for chunked extraction

        Returns:
            Dict with keys: valuation, estimate_revision, shareholding
        """
        print("     [Valuation Extractor] Stage 08b — extracting valuation & shareholding...")

        if not ocr_text or not ocr_text.strip():
            print("     [Valuation Extractor] No OCR text — returning empty result.")
            return _empty_result()

        from pipeline.utils.llm_client import call_bedrock_mistral_large

        # ── Try LLM extraction (full or chunked) ──────────────────────────────
        result = _empty_result()

        if page_texts and len(page_texts) > 1:
            # Use one focused batch call instead of repeated page-level calls.
            # Stage 12b still verifies every extracted financial value.
            print(f"     [Valuation Extractor] Focused batch extraction ({len(page_texts)} pages)")
            cache_dir = Path("tmp/valuation_extraction_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_key = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
            cache_path = cache_dir / f"{cache_key}.json"
            cached = None
            try:
                if cache_path.exists() and os.getenv("DISABLE_PIPELINE_CACHE", "0") != "1":
                    cached = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                cached = None
            if isinstance(cached, dict):
                print("     [Valuation Extractor] Cache hit")
                result = cached
            else:
                focused = ValuationExtractor._focus_text(ocr_text, max_chars=40000)
                batch_prompt = (
                    "Extract valuation, estimate revision, and shareholding data from "
                    "the focused source text below. Preserve exact numbers and return "
                    "JSON only. Use empty objects/arrays when a field is absent; "
                    "never infer missing values.\n\n" + focused
                )
                response = call_bedrock_mistral_large(_SYSTEM_PROMPT, batch_prompt)
                parsed = _parse_json(response or "")
                result = parsed if parsed else _empty_result()
                try:
                    cache_path.write_text(json.dumps(result), encoding="utf-8")
                except Exception:
                    pass
        elif False and page_texts and len(page_texts) > 1:
            # ── Per-page chunked extraction ───────────────────────────────────
            # NO TRUNCATION — full page text for 100% extraction
            print(f"     [Valuation Extractor] Per-page extraction — {len(page_texts)} pages")
            merged_result = _empty_result()
            found_val = False
            found_sh = False
            found_est = False

            pages_to_check = list(enumerate(page_texts))

            for page_idx, page_text in pages_to_check:
                if len(page_text.strip()) < 100:
                    continue
                if found_val and found_sh and found_est:
                    break

                page_prompt = (
                    f"Extract valuation, estimate revision, and shareholding data "
                    f"from PAGE {page_idx + 1} of the document.\n\n"
                    f"PAGE {page_idx + 1} CONTENT:\n{page_text}"
                )

                response = call_bedrock_mistral_large(_SYSTEM_PROMPT, page_prompt)
                page_result = _parse_json(response or "")

                if not page_result:
                    continue

                # Merge valuation data — first page with any valuation key wins
                val = page_result.get("valuation", {})
                if val and not found_val:
                    has_val = val.get("cmp") or val.get("target_price") or val.get("market_cap_cr")
                    if has_val:
                        merged_result["valuation"] = val
                        found_val = True
                        print(f"     [Valuation Extractor] Page {page_idx + 1}: found valuation "
                              f"(CMP={val.get('cmp')}, target={val.get('target_price')})")

                # Merge estimate revision data
                er = page_result.get("estimate_revision", {})
                if er and er.get("metrics") and len(er.get("metrics", [])) > 0 and not found_est:
                    merged_result["estimate_revision"] = er
                    found_est = True
                    print(f"     [Valuation Extractor] Page {page_idx + 1}: found estimate revision")

                # Merge shareholding data
                sh = page_result.get("shareholding", {})
                if sh and sh.get("quarters") and len(sh.get("quarters", [])) > 0 and not found_sh:
                    merged_result["shareholding"] = sh
                    found_sh = True
                    print(f"     [Valuation Extractor] Page {page_idx + 1}: found shareholding (quarters={sh.get('quarters')})")

            result = merged_result

        else:
            # ── Single-pass LLM extraction ─────────────────────────────────────
            focused = ValuationExtractor._focus_text(ocr_text, max_chars=40000)
            response = call_bedrock_mistral_large(_SYSTEM_PROMPT, focused)

            if not response:
                print("     [Valuation Extractor] Empty response — returning defaults.")
                return _empty_result()

            parsed = _parse_json(response)
            if not parsed:
                print("     [Valuation Extractor] Could not parse JSON — returning defaults.")
                return _empty_result()

            result = parsed

        # Ensure all 3 top-level keys exist
        empty = _empty_result()
        for key in ["valuation", "estimate_revision", "shareholding"]:
            if key not in result or not isinstance(result[key], dict):
                result[key] = empty[key]

        # Log what was found
        val = result.get("valuation", {})
        cmp_val = val.get("cmp")
        tp_val  = val.get("target_price")
        sh_raw_qtrs = result.get("shareholding", {}).get("quarters", [])

        # Normalise shareholding quarter labels — convert date strings to FY quarter format
        # e.g. "Sep 30, 2025" → "Q2FY26", "Jun 30, 2025" → "Q1FY26"
        date_to_quarter = {
            "sep 30, 2025": "Q2FY26", "september 30, 2025": "Q2FY26",
            "jun 30, 2025": "Q1FY26", "june 30, 2025": "Q1FY26",
            "mar 31, 2025": "Q4FY25", "march 31, 2025": "Q4FY25",
            "dec 31, 2024": "Q3FY25", "december 31, 2024": "Q3FY25",
            "sep 30, 2024": "Q2FY25", "september 30, 2024": "Q2FY25",
            "jun 30, 2024": "Q1FY25", "june 30, 2024": "Q1FY25",
            "mar 31, 2024": "Q4FY24", "march 31, 2024": "Q4FY24",
        }
        normalised_qtrs = []
        sh_data = result.get("shareholding", {})
        for q in sh_raw_qtrs:
            normalised = date_to_quarter.get(q.lower().strip(), q)
            normalised_qtrs.append(normalised)

        if normalised_qtrs != sh_raw_qtrs:
            # Rebuild shareholding dict with normalised keys
            for cat in ["promoters", "fii", "mf_institutions", "public", "others"]:
                old_dict = sh_data.get(cat, {})
                new_dict = {}
                for old_q, new_q in zip(sh_raw_qtrs, normalised_qtrs):
                    if old_q in old_dict:
                        new_dict[new_q] = old_dict[old_q]
                sh_data[cat] = new_dict
            sh_data["quarters"] = normalised_qtrs
            result["shareholding"] = sh_data

        sh_qtrs = result.get("shareholding", {}).get("quarters", [])
        est_metrics = result.get("estimate_revision", {}).get("metrics", [])

        # ── Regex fallback: if LLM returned empty shareholding quarters ──
        # but OCR text has a structured shareholding table, extract it directly
        if not sh_qtrs:
            print("     [Valuation Extractor] LLM returned empty shareholding quarters "
                  "— attempting regex extraction from OCR text...")
            regex_sh = _regex_shareholding(ocr_text)
            if regex_sh and regex_sh.get("quarters"):
                result["shareholding"] = regex_sh
                sh_qtrs = regex_sh.get("quarters", [])
                print(f"     [Valuation Extractor] Regex fallback SUCCESS: "
                      f"quarters={sh_qtrs}, cats={list(regex_sh.keys())}")
            else:
                print("     [Valuation Extractor] Regex extraction also found no data — "
                      "shareholding will show as 'Not available'.")

        print(f"     [Valuation Extractor] CMP={cmp_val}, Target={tp_val}, "
              f"Shareholding quarters={sh_qtrs}, "
              f"Estimate metrics={est_metrics}")

        return result

    @staticmethod
    def _focus_text(text: str, max_chars: int = 40000) -> str:
        """
        Prioritise lines that contain valuation/shareholding keywords.
        Table-dense lines come first, rest appended after.
        """
        keywords = [
            "cmp", "target", "market cap", "pe", "p/e", "p/b", "ev/ebitda",
            "52 week", "beta", "free float", "shareholding", "promoter",
            "fii", "fpi", "dii", "mutual fund", "mf", "institutional",
            "public", "retail", "body corporate", "non-institutional",
            "estimate", "revision", "old", "new", "face value",
            "dividend", "upside", "enterprise value", "outstanding shares",
            "as on", "sep-", "jun-", "mar-", "dec-", "q1fy", "q2fy",
            "q3fy", "q4fy", "category", "holder", "holding",
        ]
        lines = text.split("\n")
        priority, rest = [], []
        for line in lines:
            ll = line.lower()
            if any(kw in ll for kw in keywords):
                priority.append(line)
            else:
                rest.append(line)

        combined = "\n".join(priority) + "\n\n---\n\n" + "\n".join(rest)
        return combined[:max_chars]
