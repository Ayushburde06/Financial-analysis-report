"""
Stage 08b: Valuation & Shareholding

Reads CMP / multiples, estimate revisions, and shareholding from this
filing. Periods come from Stage 08 detection — not from a Q2FY26 or
FY26E template. Missing stays empty. Nothing is invented.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

_s08 = importlib.import_module("pipeline.08_hybrid_retrieval.retriever")

_CATS = ("promoters", "fii", "mf_institutions", "public", "others", "total")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_DATE_RE = re.compile(
    r"\b("
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\.?\s*(?P<day>\d{1,2})?[,]?\s*(?P<year>\d{4})"
    r"|"
    r"(?P<day2>\d{1,2})[-/\s]+"
    r"(?P<mon2>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"[-/\s]+(?P<year2>\d{2,4})"
    r")\b",
    re.I,
)


def date_to_fy_quarter(month: int, year: int) -> str:
    """Indian FY: Apr–Mar. Sep 2025 → Q2FY26, Mar 2025 → Q4FY25."""
    if month >= 4:
        quarter = (month - 4) // 3 + 1
        fy = (year + 1) % 100
    else:
        quarter = 4
        fy = year % 100
    return f"Q{quarter}FY{fy:02d}"


def normalize_period_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text.lower() in ("null", "none", "—", "-"):
        return ""
    match = _s08._QTR_RE.search(text)
    if match:
        return _s08._qtr_label(match.group(1), match.group(3), bool(match.group(2)))
    date_match = _DATE_RE.search(text)
    if date_match:
        mon = (date_match.group("mon") or date_match.group("mon2") or "").lower()[:3]
        year_raw = date_match.group("year") or date_match.group("year2") or ""
        month = _MONTHS.get(mon, 0)
        year = int(year_raw)
        if year < 100:
            year += 2000
        if month:
            return date_to_fy_quarter(month, year)
    return text.replace(" ", "").upper()


def _clean_response(text: str) -> str:
    text = re.sub(
        r"<think(?:ing)?>.*?</think(?:ing)?>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text, flags=re.IGNORECASE)
    return text.strip()


def _parse_json(raw: str) -> Dict[str, Any]:
    cleaned = _clean_response(raw or "")
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return {}
    candidate = match.group(0)
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        open_count = candidate.count("{") - candidate.count("}")
        if 0 < open_count <= 15:
            try:
                return json.loads(candidate + ("}" * open_count))
            except (json.JSONDecodeError, ValueError):
                return {}
    return {}


def _empty_result() -> Dict[str, Any]:
    return {
        "valuation": {},
        "estimate_revision": {
            "metrics": [],
            "years": [],
            "old_fy26e": {},
            "new_fy26e": {},
            "change_fy26e_pct": {},
            "old_fy27e": {},
            "new_fy27e": {},
            "change_fy27e_pct": {},
        },
        "shareholding": {
            "quarters": [],
            "promoters": {},
            "fii": {},
            "mf_institutions": {},
            "public": {},
            "others": {},
        },
    }


def _line_quarter(stripped: str) -> str:
    compact = stripped.strip().rstrip(":").strip()
    if len(compact) > 28:
        return ""
    match = _s08._QTR_RE.search(compact)
    if not match:
        return ""
    leftover = _s08._QTR_RE.sub("", compact).strip(" :-|/")
    if leftover:
        return ""
    return _s08._qtr_label(match.group(1), match.group(3), bool(match.group(2)))


def _classify_row(stripped: str) -> str:
    low = stripped.lower()
    if re.search(r"promoter", low) and not re.search(r"pledge", low):
        return "promoters"
    if re.search(r"\bfii|\bfpi|foreign institutional", low):
        return "fii"
    if re.search(r"mutual\s*fund|\bmf\b|\bdii\b|institution", low) and not re.search(r"\bfii", low):
        return "mf_institutions"
    if re.search(r"public|retail|non.?institutional", low):
        return "public"
    if re.search(r"others|body\s*corporate", low):
        return "others"
    if re.match(r"total\b", low) and not re.search(r"asset|income|revenue", low):
        return "total"
    return ""


def _score_shareholding(parsed: Optional[Dict[str, Any]]) -> Tuple[int, int]:
    if not parsed:
        return (0, 0)
    qtrs = parsed.get("quarters") or []
    filled = 0
    for cat in _CATS:
        vals = parsed.get(cat) or {}
        filled += sum(1 for v in vals.values() if isinstance(v, (int, float)))
    return (len(qtrs), filled)


def _parse_vertical_shareholding(snippet: str) -> Optional[Dict[str, Any]]:
    qtrs: List[str] = []
    categories: Dict[str, List[float]] = {}
    current_cat: Optional[str] = None
    for line in snippet.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        qtr = _line_quarter(stripped)
        if qtr:
            if qtr not in qtrs:
                qtrs.append(qtr)
            continue
        cat = _classify_row(stripped)
        if cat:
            current_cat = cat
            categories.setdefault(current_cat, [])
            continue
        num_match = re.match(r"^(\d+\.?\d*)\s*%?\s*$", stripped)
        if num_match and current_cat and qtrs:
            if len(categories[current_cat]) < len(qtrs):
                categories[current_cat].append(float(num_match.group(1)))
            continue
        if re.search(r"price\s*perform|pledge|key\s*highlight", stripped, re.I):
            if current_cat and categories.get(current_cat):
                break
    if len(qtrs) < 2 or sum(1 for v in categories.values() if v) < 2:
        return None
    result: Dict[str, Any] = {"quarters": qtrs}
    for cat, vals in categories.items():
        result[cat] = {
            qtrs[i]: round(vals[i], 2)
            for i in range(min(len(vals), len(qtrs)))
        }
    for cat in _CATS:
        result.setdefault(cat, {})
    return result


def _parse_horizontal_shareholding(snippet: str) -> Optional[Dict[str, Any]]:
    snippet = snippet.replace("ΓÇÖ", "'")
    qtrs: List[str] = []
    for match in _s08._QTR_RE.finditer(snippet[:400]):
        label = _s08._qtr_label(match.group(1), match.group(3), bool(match.group(2)))
        if label and label not in qtrs:
            qtrs.append(label)
    if len(qtrs) < 2:
        return None
    num_pat = re.compile(r"(\d+\.?\d*|—|--|–|-)")
    result: Dict[str, Any] = {"quarters": qtrs}
    for line in snippet.split("\n"):
        cat = _classify_row(line.strip())
        if not cat or cat in result:
            continue
        tokens = [t for t in num_pat.findall(line)]
        if len(tokens) < len(qtrs):
            continue
        vals = {}
        for i, qtr in enumerate(qtrs):
            token = tokens[i].strip()
            if token in ("—", "--", "–", "-", ""):
                continue
            try:
                vals[qtr] = float(token)
            except ValueError:
                continue
        if vals:
            result[cat] = vals
    filled = sum(1 for cat in _CATS if result.get(cat))
    if filled < 2:
        return None
    for cat in _CATS:
        result.setdefault(cat, {})
    return result


def parse_shareholding(ocr_text: str) -> Optional[Dict[str, Any]]:
    """Deterministic table parse. Empty if this source has no shareholding grid."""
    if not ocr_text:
        return None
    cleaned = ocr_text.replace("ΓÇÖ", "'").replace("’", "'").replace("‘", "'")
    low = cleaned.lower()
    starts = [m.start() for m in re.finditer(r"shareholding", low)]
    if not starts:
        return None
    best: Optional[Dict[str, Any]] = None
    best_score = (0, 0)
    for idx in starts[:8]:
        snippet = cleaned[idx: idx + 1800]
        for parser in (_parse_vertical_shareholding, _parse_horizontal_shareholding):
            parsed = parser(snippet)
            score = _score_shareholding(parsed)
            if score > best_score:
                best_score = score
                best = parsed
    return best


def _normalize_shareholding(raw: Any) -> Dict[str, Any]:
    empty = _empty_result()["shareholding"]
    if not isinstance(raw, dict):
        return empty
    qtrs = []
    for item in raw.get("quarters") or []:
        label = normalize_period_label(item)
        if label and label not in qtrs:
            qtrs.append(label)
    result: Dict[str, Any] = {"quarters": qtrs}
    for cat in _CATS:
        src = raw.get(cat) if isinstance(raw.get(cat), dict) else {}
        mapped = {}
        for key, val in src.items():
            label = normalize_period_label(key)
            if not label or not isinstance(val, (int, float)):
                continue
            mapped[label] = float(val)
        result[cat] = mapped
    if qtrs and not any(result.get(cat) for cat in _CATS if cat != "total"):
        return empty
    return result


def _compat_estimates(er: Dict[str, Any], estimates: List[str]) -> Dict[str, Any]:
    """Keep source years, and alias the first two into the current template slots."""
    years = [str(y).upper() for y in (er.get("years") or []) if y]
    if not years:
        for item in estimates:
            digits = re.search(r"(\d{2,4})", str(item))
            if digits:
                years.append(f"FY{_s08._fy2(digits.group(1)):02d}E")
    old = er.get("old") if isinstance(er.get("old"), dict) else {}
    new = er.get("new") if isinstance(er.get("new"), dict) else {}
    chg = er.get("change_pct") if isinstance(er.get("change_pct"), dict) else {}

    def _bucket(kind: str, year: str) -> Dict[str, Any]:
        key = f"{kind}_{year.lower()}"
        nested = {"old": old, "new": new, "change_pct": chg}.get(kind, {})
        if isinstance(er.get(key), dict) and er[key]:
            return er[key]
        if kind == "change_pct":
            alt = er.get(f"change_{year.lower()}_pct")
            if isinstance(alt, dict) and alt:
                return alt
        for variant in (year, year.upper(), year.lower()):
            val = nested.get(variant)
            if isinstance(val, dict):
                return val
        return {}

    out = {
        "metrics": list(er.get("metrics") or []),
        "years": years,
        "old": old,
        "new": new,
        "change_pct": chg,
        "old_fy26e": er.get("old_fy26e") if isinstance(er.get("old_fy26e"), dict) else {},
        "new_fy26e": er.get("new_fy26e") if isinstance(er.get("new_fy26e"), dict) else {},
        "change_fy26e_pct": er.get("change_fy26e_pct") if isinstance(er.get("change_fy26e_pct"), dict) else {},
        "old_fy27e": er.get("old_fy27e") if isinstance(er.get("old_fy27e"), dict) else {},
        "new_fy27e": er.get("new_fy27e") if isinstance(er.get("new_fy27e"), dict) else {},
        "change_fy27e_pct": er.get("change_fy27e_pct") if isinstance(er.get("change_fy27e_pct"), dict) else {},
    }
    for i, slot in enumerate(("fy26e", "fy27e")):
        if i >= len(years):
            break
        year = years[i]
        if not out[f"old_{slot}"]:
            out[f"old_{slot}"] = _bucket("old", year)
        if not out[f"new_{slot}"]:
            out[f"new_{slot}"] = _bucket("new", year)
        if not out[f"change_{slot}_pct"]:
            out[f"change_{slot}_pct"] = _bucket("change_pct", year)
    if not out["metrics"]:
        for block in (out["old_fy26e"], out["new_fy26e"], out["old_fy27e"]):
            if isinstance(block, dict) and block:
                out["metrics"] = list(block.keys())
                break
    return out


def _compat_valuation(val: Dict[str, Any], estimates: List[str]) -> Dict[str, Any]:
    if not isinstance(val, dict):
        return {}
    out = dict(val)
    years = [e.upper() for e in estimates]
    aliases = {
        "pe": ("pe_fy26e", "pe_fy27e"),
        "pb": ("pb_fy26e", "pb_fy27e"),
        "ev_ebitda": ("ev_ebitda_fy26e", "ev_ebitda_fy27e"),
        "roe": ("roe_fy26e", "roe_fy27e"),
        "de": ("de_fy26e", "de_fy27e"),
    }
    for field, slots in aliases.items():
        payload = out.get(field)
        if not isinstance(payload, dict):
            continue
        for i, alias in enumerate(slots):
            if out.get(alias) not in (None, "", "null"):
                continue
            if i >= len(years):
                continue
            year = years[i]
            for key in (year, year.lower(), year.replace("FY", "fy")):
                if payload.get(key) not in (None, "", "null"):
                    out[alias] = payload[key]
                    break
    return {k: v for k, v in out.items() if v not in (None, "", "null")}


def _build_system_prompt(periods: Dict[str, Any]) -> str:
    q_current = periods.get("q_current") or ""
    estimates = [e.upper() for e in (periods.get("estimates") or [])]
    est_line = ", ".join(estimates) if estimates else "only years actually printed as estimates"
    q_line = q_current or "the latest quarter header in this file"
    return f"""You extract valuation, estimate revisions, and shareholding from this filing.
Return only JSON. No markdown.

This source's reporting quarter is {q_line}.
Estimate years in this source: {est_line}.
Do not assume Q2FY26 or FY26E/FY27E unless those labels are in the text.

1. "valuation" — only values printed in this document.
   Keys: cmp, target_price, upside_pct, market_cap_cr, enterprise_value_cr,
   pe_ratio, pbv_ratio, week52_high, week52_low, beta, free_float_pct,
   outstanding_shares_cr, face_value, dividend_yield_pct, valuation_methodology.
   Also pe / pb / ev_ebitda / roe / de as objects keyed by the estimate years above.
   For template compatibility you may also fill pe_fy26e / pe_fy27e from the first
   two estimate years actually present. null if absent. Never invent CMP or a target.

2. "estimate_revision" — only if an old-vs-new estimates table exists.
   metrics: list of row labels as printed.
   years: the estimate year headers as printed.
   old / new / change_pct: objects keyed by those year labels, each mapping metric to number.
   Also fill old_fy26e, new_fy26e, change_fy26e_pct (and fy27e) from the first two
   source years so the current report frame can render them.
   If there is no revision table: metrics=[], empty objects.

3. "shareholding" — only if a shareholding / holding pattern table exists.
   quarters: labels in table order, normalised to QnFYyy (Q2-2026 means Q2FY26).
   promoters, fii, mf_institutions, public, others, total: quarter to percent.
   Use the number of quarters in the table. Do not pad with 0. If a cell is blank
   or a dash, omit that quarter. Empty objects if no table.

OUTPUT: JSON with keys valuation, estimate_revision, shareholding."""


def _focus_text(text: str, max_chars: int = 40000) -> str:
    keywords = (
        "cmp", "target", "market cap", "pe", "p/e", "p/b", "ev/ebitda",
        "52 week", "beta", "free float", "shareholding", "promoter",
        "fii", "fpi", "dii", "mutual fund", "institutional",
        "public", "retail", "body corporate", "non-institutional",
        "estimate", "revision", "face value", "dividend", "upside",
        "enterprise value", "outstanding shares", "holding pattern",
        "q1", "q2", "q3", "q4", "fy",
    )
    lines = (text or "").split("\n")
    priority, rest = [], []
    for line in lines:
        low = line.lower()
        if any(kw in low for kw in keywords):
            priority.append(line)
        else:
            rest.append(line)
    return ("\n".join(priority) + "\n\n---\n\n" + "\n".join(rest))[:max_chars]


class ValuationExtractor:
    @staticmethod
    def run(ocr_text: str, page_texts: Optional[List[str]] = None) -> Dict[str, Any]:
        print("     [Valuation Extractor] Reading valuation & shareholding from source...")
        if not ocr_text or not ocr_text.strip():
            print("     [Valuation Extractor] No source text.")
            return _empty_result()

        periods = _s08.detect_periods(ocr_text)
        print(
            f"     [Valuation Extractor] Periods q={periods.get('q_current') or '—'} "
            f"est={periods.get('estimates') or []}"
        )

        regex_sh = parse_shareholding(ocr_text)
        if regex_sh and regex_sh.get("quarters"):
            print(
                f"     [Valuation Extractor] Shareholding from tables: "
                f"{regex_sh.get('quarters')}"
            )

        from pipeline.utils.llm_client import call_bedrock_mistral_large

        cache_dir = Path("tmp/valuation_extraction_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha256(ocr_text.encode("utf-8")).hexdigest()
        cache_path = cache_dir / f"{cache_key}.json"
        parsed: Dict[str, Any] = {}
        try:
            if cache_path.exists() and os.getenv("DISABLE_PIPELINE_CACHE", "0") != "1":
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached:
                    print("     [Valuation Extractor] Cache hit")
                    parsed = cached
        except (OSError, ValueError, json.JSONDecodeError):
            parsed = {}

        if not parsed:
            focused = _focus_text(ocr_text, max_chars=40000)
            user_prompt = (
                "Extract valuation, estimate revision, and shareholding from this source. "
                "Use null / empty objects when a field is not printed. Never infer.\n\n"
                + focused
            )
            response = call_bedrock_mistral_large(_build_system_prompt(periods), user_prompt)
            parsed = _parse_json(response or "") or {}
            try:
                cache_path.write_text(json.dumps(parsed), encoding="utf-8")
            except OSError:
                pass

        result = _empty_result()
        result["valuation"] = _compat_valuation(
            parsed.get("valuation") if isinstance(parsed.get("valuation"), dict) else {},
            periods.get("estimates") or [],
        )
        result["estimate_revision"] = _compat_estimates(
            parsed.get("estimate_revision") if isinstance(parsed.get("estimate_revision"), dict) else {},
            periods.get("estimates") or [],
        )
        if regex_sh and regex_sh.get("quarters"):
            result["shareholding"] = regex_sh
        else:
            result["shareholding"] = _normalize_shareholding(parsed.get("shareholding"))

        val = result.get("valuation") or {}
        sh_qtrs = (result.get("shareholding") or {}).get("quarters") or []
        est_metrics = (result.get("estimate_revision") or {}).get("metrics") or []
        print(
            f"     [Valuation Extractor] CMP={val.get('cmp')}, "
            f"Target={val.get('target_price')}, "
            f"Shareholding={sh_qtrs or '—'}, "
            f"Estimate rows={len(est_metrics)}"
        )
        return result
