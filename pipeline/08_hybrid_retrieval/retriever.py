"""
Stage 08: Hybrid Retrieval Engine

Reads tables from this filing. Periods, unit, and extra metrics come
from the source — not from a Q2FY26 template.

Keys = sector config for the detected industry + Stage 03 KPIs.
Missing stays null. Nothing is invented.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_QTR_RE = re.compile(
    r"(?<!\w)Q\s*([1-4])\s*[-/]?\s*(FY)?\s*['’]?\s*(\d{2,4})(?!\d)",
    re.I,
)
_FY_RE = re.compile(
    r"(?<!\w)(?<!Q[1-4])FY\s*['’]?\s*(\d{2,4})\s*([AE])?(?!\w)",
    re.I,
)
_NUMBER_RE = re.compile(r"\b[\d,]+(?:\.\d+)?\b")

_BASE_PAGE_TERMS = (
    "revenue", "sales", "ebitda", "ebit", "pbt", "pat", "profit", "loss",
    "balance sheet", "cash flow", "assets", "liabilities", "debt", "equity",
    "eps", "margin", "particulars", "shareholding", "nii", "npa", "nim",
    "advances", "deposits", "standalone", "consolidated",
)


def _fy2(raw: str) -> int:
    year = int(raw)
    return year % 100 if year >= 100 else year


def _as_fy_year(raw: str, fy_marked: bool) -> int:
    year = int(raw)
    if year >= 2000:
        year = year % 100
    elif not fy_marked:
        return 0
    if 18 <= year <= 40:
        return year
    return 0


def _qtr_label(quarter: str, year: str, fy_marked: bool) -> str:
    fy = _as_fy_year(year, fy_marked)
    if not fy:
        return ""
    return f"Q{int(quarter)}FY{fy:02d}"


def _qtr_key(label: str) -> Tuple[int, int]:
    match = re.match(r"Q([1-4])FY(\d{2})$", label, re.I)
    if not match:
        return (0, 0)
    return (int(match.group(2)), int(match.group(1)))


def _prev_quarter(label: str) -> str:
    year, quarter = _qtr_key(label)
    if quarter <= 1:
        return f"Q4FY{year - 1:02d}"
    return f"Q{quarter - 1}FY{year:02d}"


def _yoy_quarter(label: str) -> str:
    year, quarter = _qtr_key(label)
    return f"Q{quarter}FY{year - 1:02d}"


def _fy_key(year: str, suffix: str = "") -> str:
    token = f"fy{_fy2(year):02d}"
    mark = (suffix or "").lower()
    if mark == "e":
        return token + "e"
    if mark == "a":
        return token + "a"
    return token


def detect_periods(text: str) -> Dict[str, Any]:
    """Read quarter / year headers from this source. Do not assume Q2FY26."""
    blob = text or ""
    q_counts: Counter = Counter()
    for match in _QTR_RE.finditer(blob):
        label = _qtr_label(match.group(1), match.group(3), bool(match.group(2)))
        if label:
            q_counts[label] += 1

    frequent = [label for label, n in q_counts.items() if n >= 2]
    pool = frequent or list(q_counts.keys())
    q_current = ""
    if pool:
        q_current = max(pool, key=lambda lab: (q_counts[lab], _qtr_key(lab)))
    q_prev_qtr = ""
    q_prev_year = ""
    if q_current:
        want_qtr = _prev_quarter(q_current)
        want_yoy = _yoy_quarter(q_current)
        if want_qtr in q_counts:
            q_prev_qtr = want_qtr
        if want_yoy in q_counts:
            q_prev_year = want_yoy

    fy_counts: Counter = Counter()
    for match in _FY_RE.finditer(blob):
        fy_counts[_fy_key(match.group(1), match.group(2) or "")] += 1

    actuals = sorted(
        (k for k, n in fy_counts.items() if not k.endswith("e") and n >= 1),
        key=lambda k: (int(re.sub(r"\D", "", k) or 0), k),
    )
    estimates = sorted(
        (k for k, n in fy_counts.items() if k.endswith("e") and n >= 1),
        key=lambda k: (int(re.sub(r"\D", "", k) or 0), k),
    )
    latest_fy = actuals[-1] if actuals else ""

    return {
        "q_current": q_current,
        "q_prev_qtr": q_prev_qtr,
        "q_prev_year": q_prev_year,
        "quarters": sorted(pool, key=_qtr_key) if pool else [],
        "actuals": actuals,
        "estimates": estimates,
        "latest_fy": latest_fy,
        "unit": detect_unit(blob),
    }


def detect_unit(text: str) -> str:
    window = (text or "")[:20000].lower()
    scores = {
        "crore": len(re.findall(r"\b(?:rs\.?\s*)?cr(?:ore)?s?\b|₹\s*cr", window)),
        "million": len(re.findall(r"\b(?:rs\.?\s*)?(?:mn|million)s?\b|₹\s*mn", window)),
        "billion": len(re.findall(r"\b(?:rs\.?\s*)?(?:bn|billion)s?\b|₹\s*bn", window)),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] else ""


def _labels_for(keys: Sequence[str]) -> List[str]:
    try:
        discoverer = importlib.import_module("pipeline.03_kpi_discovery_engine.discoverer")
        return [discoverer.label_for(k) for k in keys]
    except Exception:
        from pipeline.utils.adaptive_schema import humanize_key
        return [humanize_key(k) for k in keys]


def _merge_keys(cfg_keys: str, extra_keys: Optional[Sequence[str]]) -> str:
    seen: List[str] = []
    for part in re.split(r"\s*,\s*", cfg_keys or ""):
        key = part.strip()
        if key and key not in seen:
            seen.append(key)
    cfg_blob = " ".join(seen)
    for key in extra_keys or []:
        token = str(key).strip()
        if token and token not in seen and token not in cfg_blob:
            seen.append(token)
    return ", ".join(seen)


def _extract_table_focused_text(full_text: str, max_chars: int = 55000) -> str:
    lines = (full_text or "").split("\n")
    table_lines: List[str] = []
    prose_lines: List[str] = []
    for line in lines:
        if len(_NUMBER_RE.findall(line)) >= 3:
            table_lines.append(line)
        else:
            prose_lines.append(line)
    return ("\n".join(table_lines) + "\n\n" + "\n".join(prose_lines))[:max_chars]


def _select_financial_pages(
    page_texts: List[str],
    extra_terms: Optional[Sequence[str]] = None,
) -> List[int]:
    terms = list(_BASE_PAGE_TERMS)
    for term in extra_terms or []:
        phrase = str(term).replace("_", " ").strip().lower()
        if phrase and phrase not in terms:
            terms.append(phrase)
    selected: List[int] = []
    for idx, page in enumerate(page_texts):
        lower = page.lower()
        keyword_hits = sum(lower.count(term) for term in terms)
        numeric_lines = sum(
            1 for line in page.splitlines()
            if len(_NUMBER_RE.findall(line)) >= 3
        )
        if keyword_hits >= 2 or numeric_lines >= 3:
            selected.append(idx)
    return selected or list(range(len(page_texts)))


def _clean_llm_response(text: str) -> str:
    text = re.sub(
        r"<think(?:ing)?>.*?</think(?:ing)?>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE)
    return text.strip()


def _extract_json(raw: str) -> Dict[str, Any]:
    cleaned = _clean_llm_response(raw or "")
    preview = cleaned[:200] if cleaned else "(empty)"
    print(f"     [Hybrid Retriever] Parsing cleaned response (len={len(cleaned)}): {preview}...")
    try:
        result = json.loads(cleaned)
        print(f"     [Hybrid Retriever] Parsed JSON (keys: {list(result.keys())})")
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"     [Hybrid Retriever] Direct parse failed: {exc}")

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        print(f"     [Hybrid Retriever] No JSON object in response. Preview: {(raw or '')[:300]}...")
        return {}
    candidate = match.group(0)
    try:
        result = json.loads(candidate)
        print(f"     [Hybrid Retriever] Parsed extracted object (keys: {list(result.keys())})")
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"     [Hybrid Retriever] Extracted object parse failed: {exc}")
        open_count = candidate.count("{") - candidate.count("}")
        if 0 < open_count <= 10:
            try:
                result = json.loads(candidate + ("}" * open_count))
                print(f"     [Hybrid Retriever] Repaired JSON (keys: {list(result.keys())})")
                return result
            except (json.JSONDecodeError, ValueError) as exc2:
                print(f"     [Hybrid Retriever] Repair failed: {exc2}")
    print(f"     [Hybrid Retriever] Failed to parse JSON. Preview: {(raw or '')[:300]}...")
    return {}


def _period_prompt_block(periods: Dict[str, Any]) -> str:
    q_current = periods.get("q_current") or ""
    q_prev_qtr = periods.get("q_prev_qtr") or ""
    q_prev_year = periods.get("q_prev_year") or ""
    actuals = periods.get("actuals") or []
    estimates = periods.get("estimates") or []
    unit = periods.get("unit") or ""
    latest_fy = periods.get("latest_fy") or ""

    if q_current or actuals:
        lines = ["PERIODS IN THIS SOURCE (from table headers — map only these):"]
        if q_current:
            lines.append(f"  q_current   = {q_current}   (latest reported quarter)")
        else:
            lines.append("  q_current   = null  (no quarter header found)")
        if q_prev_qtr:
            lines.append(f"  q_prev_qtr  = {q_prev_qtr}")
        else:
            lines.append("  q_prev_qtr  = null  (prior quarter not in this filing)")
        if q_prev_year:
            lines.append(f"  q_prev_year = {q_prev_year}")
        else:
            lines.append("  q_prev_year = null  (year-ago quarter not in this filing)")
        if actuals:
            lines.append("  annual actuals: " + ", ".join(actuals))
        if estimates:
            lines.append("  estimates: " + ", ".join(estimates))
        if latest_fy:
            lines.append(f"  latest_fy label for period_labels.fy25-style key: {latest_fy}")
        if unit:
            lines.append(f"  unit: {unit}")
        lines.append(
            "Do not map a quarter that is not listed above. "
            "Do not assume Q2FY26 or any other sample period."
        )
        return "\n".join(lines)

    return (
        "PERIODS: Read the TABLE HEADERS in this document.\n"
        "  q_current   = latest reported quarter in those headers\n"
        "  q_prev_qtr  = immediately preceding quarter, only if present\n"
        "  q_prev_year = same quarter prior year, only if present\n"
        "  fyNN / fyNNe / fyNNa = fiscal years actually printed\n"
        "Do not assume Q2FY26, FY25, or FY26E."
    )


def _json_lit(value: Any) -> str:
    return json.dumps(value) if value else "null"


def _merge_period_labels(extracted: Any, periods: Dict[str, Any]) -> Dict[str, Any]:
    detected = {
        "q_current": periods.get("q_current") or None,
        "q_prev_qtr": periods.get("q_prev_qtr") or None,
        "q_prev_year": periods.get("q_prev_year") or None,
        "fy25": periods.get("latest_fy") or None,
        "unit": periods.get("unit") or None,
    }
    merged = dict(detected)
    if isinstance(extracted, dict):
        for key, val in extracted.items():
            if val in (None, "", "null", "—", "-"):
                continue
            if key in detected and detected[key]:
                continue
            merged[key] = val
    return merged


def _build_system_prompt(
    sector: str,
    extra_keys: Optional[Sequence[str]] = None,
    periods: Optional[Dict[str, Any]] = None,
) -> str:
    from pipeline.sectors import get_sector_config

    cfg = get_sector_config(sector)
    keys = _merge_keys(cfg.extraction_keys, extra_keys)
    labels = _labels_for(extra_keys or [])
    source_metrics = ""
    if labels:
        source_metrics = (
            "METRICS NUMBERED IN THIS FILING (extract these with the same period keys):\n"
            + ", ".join(labels)
            + "\n"
        )
    period_block = _period_prompt_block(periods or {})
    unit = (periods or {}).get("unit") or "the unit printed in the tables"
    q_current = (periods or {}).get("q_current") or ""
    q_prev_qtr = (periods or {}).get("q_prev_qtr") or ""
    q_prev_year = (periods or {}).get("q_prev_year") or ""
    latest_fy = (periods or {}).get("latest_fy") or ""
    unit_lit = (periods or {}).get("unit") or ""

    return f"""You extract numbers from Indian company filings.
Return only a JSON object. No markdown, no explanation.

INDUSTRY: {sector or "unspecified"}
Extractor keys for this industry (use null when the line is not in the tables):
{keys}

{source_metrics}{period_block}

JSON SHAPE — each metric is an object with period sub-keys:
  fyNN / fyNNa = actual fiscal years present in the source
  fyNNe        = estimate years present in the source
  q_prev_year, q_prev_qtr, q_current = the three quarter slots above

Always include:
  "period_labels": {{
    "q_current": {_json_lit(q_current)},
    "q_prev_qtr": {_json_lit(q_prev_qtr)},
    "q_prev_year": {_json_lit(q_prev_year)},
    "fy25": {_json_lit(latest_fy)},
    "unit": {_json_lit(unit_lit)}
  }}
Read labels from table headers. If a header is missing, that field is null.

Also extract any other numbered line item in the financial tables, snake_case key,
same period sub-keys. Do not drop a metric because it is unusual for this industry.

SOURCE FORMAT: Markdown pages. Prefer pipe tables (| col | col |) and HTML <table>.
Take numbers from tables, not from commentary.

RULES:
  - null if the document does not state the value
  - never invent or scale a number
  - raw numbers only; keep the source unit ({unit})
  - output JSON starting with {{ and ending with }}"""


def _build_retry_prompt(
    sector: str,
    attempt: int,
    source_text: str,
    extra_keys: Optional[Sequence[str]] = None,
    periods: Optional[Dict[str, Any]] = None,
) -> str:
    from pipeline.sectors import get_sector_config

    cfg = get_sector_config(sector)
    labels = ", ".join(_labels_for(extra_keys or []))
    period_block = _period_prompt_block(periods or {})
    metric_line = f"Source metrics: {labels}\n" if labels else ""
    note = (
        f"\n\nRETRY {attempt}: previous JSON was incomplete.\n"
        f"Re-read every table. Industry: {sector}.\n"
        f"{cfg.extraction_hints}\n"
        f"{metric_line}{period_block}\n"
        "Still use null when a value is not printed."
    )
    return source_text + note


class HybridRetriever:
    def __init__(self, execution_plan: Any, master_doc: Any = None):
        self.execution_plan = execution_plan
        self.master_doc = master_doc
        self.sector: str = getattr(execution_plan, "sector", None) or ""
        self.sector_module: str = getattr(execution_plan, "sector_module", None) or self.sector

    def _get_page_texts(self) -> List[str]:
        # Prefer the source-preserved page Markdown when Stage 01 provides it.
        # This keeps OCR tables, page boundaries, and figure text intact for
        # extraction. Fall back to the DOM projection for older documents or
        # synthetic test fixtures.
        page_markdown = getattr(self.master_doc, "page_markdown", None) or {}
        if page_markdown:
            return [
                str(page_markdown[key]).strip()
                for key in sorted(page_markdown, key=lambda value: int(value) if str(value).isdigit() else str(value))
                if str(page_markdown[key]).strip()
            ]
        pages = []
        if self.master_doc and getattr(self.master_doc, "sections", None):
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
        label = self.sector or self.sector_module or "source"
        print(f"     [Hybrid Retriever] Extracting {label} financials — attempt {attempt}...")
        from pipeline.utils.llm_client import call_bedrock_mistral_large

        extra_keys = list(getattr(self.execution_plan, "discovered_kpis", None) or [])
        page_texts = self._get_page_texts()
        extra_terms = extra_keys + _labels_for(extra_keys)

        if page_texts:
            selected = _select_financial_pages(page_texts, extra_terms)
            print(
                f"     [Hybrid Retriever] Financial pages: "
                f"{len(selected)}/{len(page_texts)}"
            )
            source_text = "\n\n".join(
                f"===== SOURCE PAGE {idx + 1} =====\n{page_texts[idx]}"
                for idx in selected
            )
        else:
            raw_text = (self.master_doc.get_full_text() if self.master_doc else "") or ""
            source_text = _extract_table_focused_text(raw_text, max_chars=55000)

        if not source_text.strip():
            print("     [Hybrid Retriever] No source text.")
            return {}

        periods = detect_periods(source_text)
        print(
            f"     [Hybrid Retriever] Periods "
            f"q={periods.get('q_current') or '—'} "
            f"qoq={periods.get('q_prev_qtr') or '—'} "
            f"yoy={periods.get('q_prev_year') or '—'} "
            f"unit={periods.get('unit') or '—'}"
        )
        system_prompt = _build_system_prompt(
            self.sector or self.sector_module,
            extra_keys=extra_keys,
            periods=periods,
        )

        cache_dir = Path("tmp") / "financial_extraction_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(
            f"{self.sector}\n{','.join(extra_keys)}\n{source_text}".encode(
                "utf-8", errors="ignore"
            )
        ).hexdigest()
        cache_path = cache_dir / f"{cache_key}.json"
        if attempt == 1 and cache_path.exists() and os.getenv("DISABLE_PIPELINE_CACHE", "0") != "1":
            try:
                cached_result = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached_result, dict) and cached_result:
                    print("     [Hybrid Retriever] Financial extraction cache hit")
                    return cached_result
            except (OSError, ValueError, json.JSONDecodeError):
                pass

        user_prompt = (
            _build_retry_prompt(
                self.sector or self.sector_module,
                attempt,
                source_text,
                extra_keys=extra_keys,
                periods=periods,
            )
            if attempt > 1 else
            "Extract every numbered financial line from these source pages. "
            "Return one JSON object. Use null when a value is not printed.\n\n"
            + source_text
        )
        response = call_bedrock_mistral_large(system_prompt, user_prompt)
        result = _extract_json(response or "")
        if result:
            result["period_labels"] = _merge_period_labels(
                result.get("period_labels"), periods
            )
            try:
                cache_path.write_text(json.dumps(result), encoding="utf-8")
            except OSError:
                pass
        print(
            f"     [Hybrid Retriever] Extraction complete. "
            f"Keys: {list(result.keys())[:10]}"
        )
        return result

    def retrieve_narratives(self) -> List[str]:
        if self.master_doc and hasattr(self.master_doc, "knowledge_graph"):
            return self.master_doc.knowledge_graph.get("management_commentary", []) or []
        return []
