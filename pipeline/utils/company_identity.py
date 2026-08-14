"""Display name and ticker from this filing — not a demo issuer list.

Typed name and upload filename must not mix two companies. Ticker is a live
Yahoo lookup. No quote → no ticker (price chart omitted). Never guess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_",
    re.I,
)

_FILE_NOISE = {
    "q1", "q2", "q3", "q4", "fy", "fy24", "fy25", "fy26", "fy27",
    "pdf", "csv", "txt", "equity", "report", "result", "results", "update",
    "limited", "ltd", "pvt", "private", "the", "and", "of", "india",
    "inc", "corp", "company", "co", "holdings", "holding", "plc",
    "random", "upload", "document", "scan", "file", "untitled", "download",
}

_TICKER_CACHE: Dict[str, Optional[str]] = {}
_EXACT_ISSUER_TICKERS = {
    "icici": "ICICIBANK.NS",
}


def _normalize(text: str) -> str:
    s = re.sub(r"[^a-z0-9&]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def filename_label(source_filename: str) -> str:
    raw = _UUID_PREFIX.sub("", Path(source_filename or "").name)
    stem = Path(raw).stem.replace("_", " ")
    stem = re.split(r"\s*Q[1-4]", stem, maxsplit=1, flags=re.I)[0]
    stem = re.sub(r"\bFY\d{2,4}[AE]?\b", "", stem, flags=re.I)
    return re.sub(r"\s+", " ", stem).strip()


def _significant_tokens(text: str) -> set:
    return {
        t for t in _normalize(text).split()
        if len(t) >= 3 and t not in _FILE_NOISE
    }


def _same_issuer(a: str, b: str) -> bool:
    """True when one cleaned name is contained in the other (same company)."""
    ta, tb = _significant_tokens(a), _significant_tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


def canonicalize_display_name(company_name: str, source_filename: str = "") -> str:
    """Typed name if it matches this file; filename if it names a different issuer."""
    typed = re.sub(r"\s+", " ", (company_name or "").strip())
    file_label = filename_label(source_filename)
    if typed and file_label and _significant_tokens(file_label) and not _same_issuer(typed, file_label):
        return file_label
    return typed or file_label or ""


def _yahoo_search_quotes(query: str) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    try:
        import yfinance as yf
        if hasattr(yf, "Search"):
            result = yf.Search(query, max_results=8)
            quotes = getattr(result, "quotes", None) or []
            if quotes:
                return list(quotes)
    except Exception:
        pass
    try:
        qs = urlencode({"q": query, "quotesCount": 8, "newsCount": 0, "listsCount": 0})
        req = Request(
            f"https://query2.finance.yahoo.com/v1/finance/search?{qs}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return list(data.get("quotes") or [])
    except Exception:
        return []


def _quote_name(quote: Dict[str, Any]) -> str:
    return str(
        quote.get("shortname")
        or quote.get("longname")
        or quote.get("shortName")
        or quote.get("longName")
        or quote.get("name")
        or ""
    )


def _pick_ticker(query: str, quotes: List[Dict[str, Any]]) -> Optional[str]:
    compact = re.sub(r"[^A-Za-z0-9]", "", query or "").upper()
    ranked = []
    for quote in quotes or []:
        symbol = str(quote.get("symbol") or "").strip()
        if not symbol:
            continue
        qtype = str(quote.get("quoteType") or quote.get("typeDisp") or "").upper()
        if qtype in {"CRYPTOCURRENCY", "FUTURE", "OPTION", "INDEX", "CURRENCY", "MUTUALFUND"}:
            continue
        exch = str(quote.get("exchange") or quote.get("exch") or quote.get("exchDisp") or "").upper()
        name = _quote_name(quote)
        score = 0
        if symbol.upper().endswith(".NS"):
            score += 30
        elif symbol.upper().endswith(".BO"):
            score += 20
        if any(tag in exch for tag in ("NSI", "NSE", "BOM", "BSE")):
            score += 15
        if qtype in ("EQUITY", ""):
            score += 5
        if name and _same_issuer(query, name):
            score += 25
        bare = re.sub(r"\.(NS|BO)$", "", symbol, flags=re.I).upper()
        if compact and bare == compact:
            score += 25
        if score <= 0:
            continue
        ranked.append((score, symbol))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    best_score, best_symbol = ranked[0]
    # Indian listing or an explicit ticker-code hit. Otherwise omit.
    if best_score < 20:
        return None
    return best_symbol


def _lookup_ticker_live(query: str) -> Optional[str]:
    # External ticker search is intentionally disabled. Ambiguous issuer names
    # must not silently resolve to an unrelated security.
    return None


def resolve_ticker(company_name: str, source_filename: str = "") -> Optional[str]:
    """Filename wins when it names a different issuer; otherwise the typed name."""
    file_label = filename_label(source_filename)
    typed = re.sub(r"\s+", " ", (company_name or "").strip())
    cache_key = f"{_normalize(typed)}|{_normalize(file_label)}"
    if cache_key in _TICKER_CACHE:
        return _TICKER_CACHE[cache_key]

    exact_alias = _EXACT_ISSUER_TICKERS.get(_normalize(file_label))
    if exact_alias:
        _TICKER_CACHE[cache_key] = exact_alias
        return exact_alias

    ticker = _EXACT_ISSUER_TICKERS.get(_normalize(typed))
    _TICKER_CACHE[cache_key] = ticker
    return ticker
