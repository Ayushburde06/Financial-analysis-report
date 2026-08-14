"""
Stage 03: KPI Discovery

Two passes, both source-bound:
  1) Known equity labels (NIM, PAT, TCV, PLF, …) if a number sits beside them
  2) Other labeled figures in this filing that are not on that list

Nothing is added because “every report needs revenue growth”.
A chemicals deck can surface MTPA; a marketplace deck can surface GMV.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pipeline.utils.adaptive_schema import humanize_key

# Longest phrase first inside each tuple so "net interest margin" wins over "nim".
KPI_SPECS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    ("nii", "NII", ("net interest income",)),
    ("nim", "NIM", ("net interest margin", "nim")),
    ("gnpa", "GNPA", ("gross npa", "gross npas", "gnpa")),
    ("nnpa", "NNPA", ("net npa", "net npas", "nnpa")),
    ("pcr", "PCR", ("provision coverage ratio", "provision coverage", "pcr")),
    ("casa", "CASA", ("casa ratio", "casa")),
    ("advances", "Advances", ("gross advances", "net advances", "advances")),
    ("deposits", "Deposits", ("total deposits", "term deposits", "deposit base", "deposits")),
    ("slippage_ratio", "Slippage", ("slippage ratio", "slippages")),
    ("crar", "CRAR", ("capital adequacy ratio", "capital adequacy", "crar")),
    ("roe", "ROE", ("return on equity", "roe")),
    ("roa", "ROA", ("return on assets", "roa")),
    ("pat", "PAT", ("profit after tax", "net profit", "pat")),
    ("pbt", "PBT", ("profit before tax", "pbt")),
    ("operating_profit", "Operating profit", (
        "core operating profit", "pre-provision operating profit", "ppop",
        "operating profit",
    )),
    ("ebitda", "EBITDA", ("ebitda",)),
    ("ebit", "EBIT", ("ebit",)),
    ("eps", "EPS", ("earnings per share", "eps")),
    ("revenue", "Revenue", (
        "revenue from operations", "operating revenue", "net sales", "total income",
        "revenue",
    )),
    ("ebitda_margin", "EBITDA margin", ("ebitda margin",)),
    ("pat_margin", "PAT margin", ("pat margin", "net margin")),
    ("aum", "AUM", ("assets under management", "aum")),
    ("tcv", "TCV", ("total contract value", "tcv")),
    ("headcount", "Headcount", ("headcount", "total employees")),
    ("attrition", "Attrition", ("attrition rate", "attrition")),
    ("order_book", "Order book", ("order book", "order backlog", "order inflow")),
    ("installed_capacity", "Installed capacity", ("installed capacity",)),
    ("generation", "Generation", ("net generation", "power generation")),
    ("plf", "PLF", ("plant load factor", "plf")),
    ("volume", "Volume", ("sales volume", "production volume")),
    ("capacity_mtpa", "Capacity", ("mtpa",)),
    ("capex", "Capex", ("capital expenditure", "capex")),
    ("net_debt", "Net debt", ("net debt",)),
    ("cash", "Cash", ("cash and cash equivalents", "cash and bank")),
)

KPI_ALIASES: Dict[str, Tuple[str, ...]] = {key: aliases for key, _label, aliases in KPI_SPECS}
KPI_LABELS: Dict[str, str] = {key: label for key, label, _aliases in KPI_SPECS}

_NUM = re.compile(
    r"(?:₹|rs\.?|inr)?\s*"
    r"(?:"
    r"\d{1,3}(?:,\d{2,3})+"
    r"|\d+\.\d+"
    r"|\d{4,}"
    r"|\d{1,3}\s*(?:%|bps|cr|bn|mn|mw|gw|mt|mtpa|x)"
    r")",
    re.I,
)
_COMPILED: List[Tuple[str, str, str, re.Pattern]] = [
    (key, label, alias, re.compile(rf"(?<!\w){re.escape(alias)}(?!\w)", re.I))
    for key, label, aliases in KPI_SPECS
    for alias in aliases
]

_SKIP_LABELS = {
    "page", "slide", "source", "note", "notes", "particulars", "total",
    "others", "other", "year", "quarter", "period", "amount", "item",
    "yoy", "qoq", "change", "vs", "in", "rs", "cr", "bn", "mn",
    "sep", "jun", "mar", "dec", "jan", "feb", "apr", "may", "jul",
    "aug", "oct", "nov", "description", "remarks", "unit", "units",
    "growth", "margin", "ratio", "the company", "company",
}

_JUNK_LABEL = re.compile(
    r"\b(code|script|outlook|exchange|cin|isin|split|page|slide|"
    r"ytd|yoy|qoq|inr|usd|eur|solar|wind|thermal|hydro|paper)\b",
    re.I,
)
_METRIC_HINT = re.compile(
    r"\b(ratio|margin|rate|value|income|volume|users?|fee|yield|cost|"
    r"cover|utilis|realis|arpu|gmv|gov|nov|aov|take|capacity|"
    r"generation|npa|aum|eps|pat|ebitda|revenue|profit|debt|cash|"
    r"capex|headcount|attrition|orders?|book|tcv|subscribers?|"
    r"throughput|load|premium|claims|npat|gmvs?)\b",
    re.I,
)
_PIPE_SEP = re.compile(r"^\s*\|?\s*[-:]+")


def _source_blob(knowledge_graph: Dict[str, Any], source_text: str) -> str:
    chunks: List[str] = [source_text or ""]
    if isinstance(knowledge_graph, dict):
        for key in (
            "company_name", "management_commentary",
            "strategy_and_highlights", "risks_and_challenges", "esg_initiatives",
        ):
            value = knowledge_graph.get(key)
            if isinstance(value, list):
                chunks.extend(str(item) for item in value if item)
            elif value:
                chunks.append(str(value))
    return "\n".join(chunks)


def _clean_scan_text(text: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    cleaned = re.sub(r"^#+\s*page\s+\d+\s*$", " ", cleaned, flags=re.I | re.M)
    return cleaned


def _number_beside_label(text: str, start: int, end: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    line = text[line_start:line_end]
    if _NUM.search(line):
        return True
    nxt = text[line_end + 1:].split("\n", 1)[0] if line_end < len(text) else ""
    return len(line.strip()) <= 48 and bool(_NUM.search(nxt))


def _key_from_label(label: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return re.sub(r"_+", "_", key)[:40]


def label_for(key: str) -> str:
    return KPI_LABELS.get(key) or humanize_key(key)


def aliases_for(key: str) -> Tuple[str, ...]:
    if key in KPI_ALIASES:
        return KPI_ALIASES[key]
    phrase = key.replace("_", " ").strip()
    return (phrase,) if phrase else (key,)


def metric_has_number(text: str, kpi_key: str) -> bool:
    blob = _clean_scan_text(text or "")
    for alias in aliases_for(kpi_key):
        if not alias:
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", blob, re.I):
            if _number_beside_label(blob, match.start(), match.end()):
                return True
    return False


def _usable_source_label(label: str) -> bool:
    s = re.sub(r"\s+", " ", label or "").strip(" •*-·|:.")
    if len(s) < 3 or len(s) > 42:
        return False
    low = s.lower()
    if low in _SKIP_LABELS:
        return False
    if re.fullmatch(r"q[1-4][\s\-]*fy\s*\d{2,4}", low):
        return False
    if re.search(r"\bfy\s*\d{2,4}\b", low) and len(s.split()) <= 2:
        return False
    if not re.search(r"[a-zA-Z]{3,}", s):
        return False
    if sum(ch.isdigit() for ch in s) > 4:
        return False
    return True


def _extra_is_metric(label: str) -> bool:
    s = re.sub(r"\s+", " ", label).strip(" -–—")
    s = re.sub(r"\s+\b(of|to|by|at|was|were|is|are|for|in|on)\s*$", "", s, flags=re.I)
    if s.lower().startswith(("our ", "we ", "the ", "this ", "a ", "and ", "q1", "q2", "q3", "q4")):
        return False
    if "(" in s or ")" in s:
        return False
    if _JUNK_LABEL.search(s):
        return False
    if re.search(r"\b(was|were|increased|decreased|stands|achieving|grew|up)\b", s, re.I):
        return False
    words = s.split()
    if len(words) > 5:
        return False
    acronym = s.isupper() and 3 <= len(s) <= 6 and s.isalpha()
    if len(words) == 1 and not acronym:
        return False
    if acronym or _METRIC_HINT.search(s):
        return True
    return False


def _known_alias_hit(label: str) -> bool:
    low = re.sub(r"\s+", " ", label.lower()).strip()
    low = re.sub(r"\s+\b(of|to|by|at)\s*$", "", low)
    for aliases in KPI_ALIASES.values():
        for alias in aliases:
            if len(alias) < 4:
                continue
            if alias == low or alias in low:
                return True
    return False


def _mine_source_labels(text: str) -> Dict[str, Tuple[int, str]]:
    """Pick labeled numbers that are not already in the known-metric list."""
    found: Dict[str, Tuple[int, str]] = {}

    def add(label: str) -> None:
        label = re.sub(r"\s+", " ", label).strip(" •*-·|:.-")
        label = re.sub(r"\s+\b(of|to|by|at|was|were|is|are)\s*$", "", label, flags=re.I)
        if not _usable_source_label(label) or _known_alias_hit(label):
            return
        if not _extra_is_metric(label):
            return
        key = _key_from_label(label)
        if not key or key in KPI_ALIASES:
            return
        score, current = found.get(key, (0, label))
        found[key] = (score + 1, current if len(current) <= len(label) else label)

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _PIPE_SEP.match(line):
            continue
        if line.startswith("|") and line.count("|") >= 3:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells and any(_NUM.search(c) for c in cells[1:]):
                add(cells[0])
            continue
        match = re.match(
            r"^(?:[|•·\-*]\s*)?([A-Za-z][A-Za-z0-9&/%()' .\-]{2,42}?)"
            r"\s*[:|]?\s+" + _NUM.pattern,
            line,
            re.I,
        )
        if match:
            add(match.group(1))
    return found


def discover_kpis(text: str, limit: int = 14) -> List[str]:
    text = _clean_scan_text(text or "")
    scores: Dict[str, int] = {}
    for key, _label, alias, pattern in _COMPILED:
        hits = 0
        for match in pattern.finditer(text):
            if _number_beside_label(text, match.start(), match.end()):
                hits += max(2, len(alias.split()))
        if hits:
            scores[key] = scores.get(key, 0) + hits
    known = [
        key for key, _score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ][:12]

    extras = _mine_source_labels(text)
    extra_ranked = []
    known_set = set(known)
    for key, (hits, _label) in sorted(extras.items(), key=lambda item: (-item[1][0], item[0])):
        if hits < 1:
            continue
        extra_words = set(key.split("_")) - {"and", "the", "of", "total", "net", "to", "at"}
        if any(extra_words & set(k.split("_")) for k in known_set):
            continue
        if "_" not in key and len(key) <= 6 and hits < 2 and not _METRIC_HINT.search(key):
            continue
        extra_ranked.append(key)
        if len(extra_ranked) >= 4:
            break
    for key, (_hits, label) in extras.items():
        KPI_LABELS.setdefault(key, label.strip())
        KPI_ALIASES.setdefault(key, (label.lower().strip(), key.replace("_", " ")))

    ordered: List[str] = []
    for key in known + extra_ranked:
        if key not in ordered:
            ordered.append(key)
    return ordered


class KPIDiscoveryEngine:
    @staticmethod
    def run(knowledge_graph: Dict[str, Any], source_text: str = "") -> List[str]:
        print("     [KPI Discovery] Reading source metrics...")
        blob = _clean_scan_text(source_text or _source_blob(knowledge_graph, ""))
        if len(blob.strip()) < 40:
            print("     [KPI Discovery] No usable source text.")
            return []

        found = discover_kpis(blob)
        if not found:
            print("     [KPI Discovery] No numbered metrics in this source.")
            return []

        labels = ", ".join(label_for(key) for key in found)
        print(f"     [KPI Discovery] {len(found)} from source: {labels}")
        return found
