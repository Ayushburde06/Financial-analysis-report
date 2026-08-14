"""
Stage 05: Industry Detection

Reads the filing. Order:
  1) industry/sector line or legal-name suffix in this source
  2) numbered KPIs already found in Stage 03
  3) distinctive operating language

No issuer list. No LLM. A chemicals or insurance deck can keep that
label; Stage 08 then uses the matching config, or the generic extractor
plus the source KPIs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pipeline.sectors import get_sector_config, list_sectors

# Distinctive operating language. Company names are not used.
SECTOR_TERMS: Dict[str, List[Tuple[str, int]]] = {
    "Banking": [
        ("net interest income", 5), ("net interest margin", 5),
        ("gross npa", 4), ("net npa", 4), ("gnpa", 3), ("nnpa", 3),
        ("casa ratio", 4), ("provision coverage", 3),
        ("capital adequacy", 3), ("crar", 3), ("tier 1", 3),
        ("slippage ratio", 3), ("credit cost", 3),
        ("loan book", 2), ("advances", 2), ("nii", 3),
        ("scheduled commercial bank", 4),
    ],
    "NBFC": [
        ("non-banking financial", 5), ("nbfc", 5),
        ("assets under management", 4), ("gold loan", 4),
        ("vehicle finance", 4), ("housing finance", 3),
        ("disbursements", 3), ("cost of funds", 3),
        ("yield on advances", 3),
    ],
    "IT Services": [
        ("total contract value", 5), ("attrition rate", 4),
        ("constant currency", 4), ("digital engineering", 4),
        ("utilization rate", 3), ("utilisation rate", 3),
        ("offshore revenue", 3), ("deal wins", 3), ("tcv", 3),
        ("it services", 3), ("software services", 3),
        ("engineering services", 3),
    ],
    "Pharma": [
        ("active pharmaceutical", 5), ("anda filing", 5), ("usfda", 4),
        ("biosimilar", 4), ("formulation", 3), ("clinical trial", 3),
        ("pharmaceutical", 3),
    ],
    "Energy": [
        ("plant load factor", 5), ("installed capacity", 4),
        ("power generation", 4), ("net generation", 4),
        ("renewable energy", 3), ("solar capacity", 3), ("wind capacity", 3),
        ("megawatt", 3), ("gigawatt", 3), ("mw capacity", 4),
        ("plf", 3), ("thermal generation", 3),
    ],
    "Infrastructure": [
        ("order inflow", 4), ("order backlog", 4), ("epc contract", 5),
        ("engineering procurement construction", 5),
        ("roads and highways", 4), ("order book", 3),
    ],
    "FMCG": [
        ("rural demand", 4), ("advertising and promotion", 4),
        ("consumer goods", 4), ("personal care", 3), ("fmcg", 4),
    ],
    "Auto": [
        ("passenger vehicle", 5), ("commercial vehicle", 4),
        ("two-wheeler", 4), ("wholesale dispatches", 4),
        ("retail offtake", 4), ("vehicle volumes", 4),
        ("automotive", 3),
    ],
    "Metals": [
        ("realization per tonne", 5), ("ebitda per tonne", 4),
        ("hot rolled coil", 4), ("coking coal", 4), ("iron ore", 3),
        ("sponge iron", 3), ("lme", 3),
    ],
    "Cement": [
        ("clinker", 5), ("cement volume", 5), ("blended cement", 4),
        ("grey cement", 4), ("cement", 3),
    ],
    "Telecom": [
        ("average revenue per user", 5), ("subscriber base", 4),
        ("5g rollout", 4), ("spectrum", 3), ("data traffic", 3),
        ("arpu", 4),
    ],
    "Internet & Retail": [
        ("gross merchandise value", 5), ("gross order value", 5),
        ("monthly transacting users", 5), ("take rate", 4),
        ("quick commerce", 4), ("average order value", 4),
        ("e-commerce", 3), ("gmv", 4),
    ],
}

_KPI_HINTS: Dict[str, Tuple[str, int]] = {
    "nii": ("Banking", 6), "nim": ("Banking", 6),
    "gnpa": ("Banking", 5), "nnpa": ("Banking", 5),
    "casa": ("Banking", 5), "crar": ("Banking", 4),
    "advances": ("Banking", 3), "deposits": ("Banking", 3),
    "aum": ("NBFC", 5),
    "tcv": ("IT Services", 6), "attrition": ("IT Services", 5),
    "headcount": ("IT Services", 3),
    "installed_capacity": ("Energy", 6), "generation": ("Energy", 5),
    "plf": ("Energy", 6),
    "order_book": ("Infrastructure", 4),
    "arpu": ("Telecom", 4),
    "gmv": ("Internet & Retail", 6), "take_rate": ("Internet & Retail", 6),
    "monthly_transacting_users": ("Internet & Retail", 5),
    "gross_merchandise_value": ("Internet & Retail", 6),
    "capacity_mtpa": ("Metals", 3),
}

# Source phrases → keep as-is when not in the 12-sector registry.
_OPEN_HINTS: Tuple[Tuple[str, str], ...] = (
    (r"\bspecialty chemicals?\b", "Specialty Chemicals"),
    (r"\bchemicals?\b", "Chemicals"),
    (r"\blife insurance\b", "Life Insurance"),
    (r"\bgeneral insurance\b", "General Insurance"),
    (r"\binsurance\b", "Insurance"),
    (r"\breal estate\b|\brealty\b", "Real Estate"),
    (r"\bhospitality\b|\bhotels?\b", "Hospitality"),
    (r"\bairline\b|\baviation\b", "Aviation"),
    (r"\blogistics\b|\bwarehousing\b", "Logistics"),
    (r"\bmedia\b|\bbroadcast\b", "Media"),
)

_NAME_SUFFIX: Tuple[Tuple[str, str], ...] = (
    (r"\bbank(?:\s+limited|\s+ltd)?$", "Banking"),
    (r"\bnbfc\b", "NBFC"),
    (r"\benergy(?:\s+limited|\s+ltd)?$", "Energy"),
    (r"\bpower(?:\s+limited|\s+ltd)?$", "Energy"),
    (r"\bcement(?:s)?(?:\s+limited|\s+ltd)?$", "Cement"),
    (r"\bpharma(?:ceuticals?)?(?:\s+limited|\s+ltd)?$", "Pharma"),
    (r"\bchemicals?(?:\s+limited|\s+ltd)?$", "Chemicals"),
    (r"\bsteel(?:\s+limited|\s+ltd)?$", "Metals"),
    (r"\bmotors?(?:\s+limited|\s+ltd)?$", "Auto"),
    (r"\btechnology services\b", "IT Services"),
)

_DECLARE_RE = (
    r"(?:industry|sector|business)\s*[:\-–]\s*([A-Za-z][A-Za-z&/ \-]{2,42})",
    r"engaged in(?: the)? (?:manufacture|manufacturing|production|business) of ([A-Za-z][A-Za-z ,&]{3,48})",
    r"is an? ([A-Za-z][A-Za-z&/ \-]{3,40}?) (?:company|manufacturer|producer|lender)",
)

_MIN_SCORE = 8
_SKIP_DECLARE = {
    "india", "limited", "growth", "presentation", "results", "update",
    "investor", "company", "the company", "operations", "overview",
}


def _blob(knowledge_graph: Dict[str, Any], source_text: str) -> str:
    parts = [source_text or ""]
    if isinstance(knowledge_graph, dict):
        name = knowledge_graph.get("company_name")
        if name:
            parts.append(str(name))
        for key in ("strategy_and_highlights", "management_commentary"):
            val = knowledge_graph.get(key)
            if isinstance(val, list):
                parts.extend(str(x) for x in val if x)
            elif val:
                parts.append(str(val))
    return " ".join(parts)


def _hit_count(term: str, text: str) -> int:
    return len(re.findall(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text.lower()))


def _title(label: str) -> str:
    words = re.sub(r"\s+", " ", label).strip(" .,;:-").split()
    small = {"and", "of", "the", "&"}
    out = []
    for i, w in enumerate(words):
        if i and w.lower() in small:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower() if not w.isupper() else w)
    return " ".join(out)[:48]


def _map_to_known(phrase: str) -> str:
    low = phrase.lower()
    for sector in list_sectors():
        if sector == "Other":
            continue
        cfg = get_sector_config(sector)
        if cfg.is_match(phrase) or cfg.sector_name.lower() == low:
            return cfg.sector_name
    return ""


def _legal_stem(company_name: str) -> str:
    return re.sub(
        r"\s*Q[1-4]\s*FY\s*\d{2,4}.*$",
        "",
        (company_name or "").strip(),
        flags=re.I,
    ).strip()


def _from_name_or_declare(text: str, company_name: str) -> str:
    """High-confidence: legal-name suffix or an Industry/Sector line."""
    name = _legal_stem(company_name)
    for pattern, sector in _NAME_SUFFIX:
        if name and re.search(pattern, name, re.I):
            return sector

    window = (text or "")[:8000]
    for pattern in _DECLARE_RE:
        match = re.search(pattern, window, re.I)
        if not match:
            continue
        raw = _title(match.group(1))
        if not raw or raw.lower() in _SKIP_DECLARE or len(raw) < 4:
            continue
        mapped = _map_to_known(raw)
        return mapped or raw
    return ""


def _from_open_hints(text: str) -> str:
    """Keep labels the 12-sector registry does not own (chemicals, insurance)."""
    low = (text or "")[:8000].lower()
    for pattern, label in _OPEN_HINTS:
        if re.search(pattern, low):
            return label
    return ""


def _sector_from_kpis(kpis: Optional[Iterable[str]]) -> str:
    votes: Dict[str, int] = {}
    for key in kpis or []:
        hint = _KPI_HINTS.get(str(key))
        if not hint:
            continue
        sector, weight = hint
        votes[sector] = votes.get(sector, 0) + weight
    if not votes:
        return ""
    best = max(votes, key=votes.get)
    if votes[best] >= 10:
        return best
    return ""


def _score_sectors(text: str, kpis: Optional[Iterable[str]]) -> Dict[str, int]:
    scores: Dict[str, int] = {}
    lower = text.lower()
    for sector, terms in SECTOR_TERMS.items():
        total = 0
        for term, weight in terms:
            hits = min(_hit_count(term, lower), 3)
            if hits:
                total += weight * hits
        if total:
            scores[sector] = total
    for key in kpis or []:
        hint = _KPI_HINTS.get(str(key))
        if not hint:
            continue
        sector, boost = hint
        scores[sector] = scores.get(sector, 0) + boost
    return scores


def _pick(scores: Dict[str, int]) -> str:
    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_sector, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if best < _MIN_SCORE:
        return ""
    if best_sector == "NBFC" and scores.get("Banking", 0) >= best - 4:
        return "Banking" if scores.get("Banking", 0) >= best else "NBFC"
    if best_sector == "Cement" and scores.get("Metals", 0) >= best:
        return "Metals"
    if best - second < 3 and second >= _MIN_SCORE:
        if best_sector == "Infrastructure" and scores.get("IT Services", 0) >= second:
            return "IT Services"
        if best_sector == "Telecom" and scores.get("Internet & Retail", 0) >= second:
            return "Internet & Retail"
    return best_sector


class IndustryDetectionEngine:
    @staticmethod
    def run(
        knowledge_graph: Dict[str, Any],
        source_text: str = "",
        kpis: Optional[List[str]] = None,
    ) -> str:
        print("     [Industry Detector] Reading source industry cues...")
        kg = knowledge_graph if isinstance(knowledge_graph, dict) else {}
        text = _blob(kg, source_text)
        name = str(kg.get("company_name") or "")
        declared = _from_name_or_declare(text, name)
        open_label = _from_open_hints(text)
        from_kpis = _sector_from_kpis(kpis)
        scores = _score_sectors(text, kpis)
        from_terms = _pick(scores)
        top = dict(sorted(scores.items(), key=lambda item: -item[1])[:4])

        # Numbered KPIs win when they clearly contradict a name suffix
        # (e.g. a holding company name vs a bank result).
        if from_kpis and declared and from_kpis != declared:
            if scores.get(from_kpis, 0) >= scores.get(declared, 0) + 8:
                sector = from_kpis
            else:
                sector = declared
        elif declared:
            sector = declared
        elif from_kpis:
            sector = from_kpis
        elif from_terms:
            sector = from_terms
        else:
            sector = open_label

        if sector:
            print(f"     [Industry Detector] {sector}  scores={top}")
            return sector
        print(f"     [Industry Detector] No clear sector  scores={top or '{}'}")
        return ""
