"""
Stage 02: Company Knowledge Builder

Keyword scan over OCR text. No LLM. Works for any filing (earnings deck,
result update, annual report, CSV/TXT dump) — not tied to a company list.

Returns only complete, source-derived lines. Missing buckets stay empty.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from dom_schema import MasterDocument


# ── Keyword banks (sector-agnostic) ───────────────────────────────────────────

_COMMENTARY_KEYWORDS = [
    "guidance", "outlook", "management commentary",
    "ceo", "cfo", "managing director",
    "we expect", "we aim", "we continue", "we remain",
    "on track", "deal wins", "new orders",
    "profit before tax", "profit after tax", "core operating profit",
    "revenue of", "reported ebitda", "highest-ever",
]

_STRATEGY_KEYWORDS = [
    "expansion", "capacity", "capex", "launch", "launched",
    "new product", "partnership", "acquisition", "acquired",
    "merger", "joint venture", "market share", "digital",
    "automation", "diversif", "transform", "scale",
    "investment in", "organic", "inorganic",
]

_RISK_KEYWORDS = [
    "headwind", "pressure", "uncertain", "slowdown", "competition",
    "npa", "slippage", "default", "forex", "inflation", "shortage",
    "geopolit", "sanction", "margin compress", "asset quality",
    "challenge", "risk",
]

_ESG_KEYWORDS = [
    "esg", "csr", "carbon", "emission", "net zero",
    "greenhouse", "scope 1", "scope 2", "climate",
    "waste management", "water stewardship", "carbon neutral",
    "green power",
]


_BOILERPLATE_SNIPPETS = (
    "forward-looking", "forward looking", "safe harbour", "safe harbor",
    "cautionary statement", "securities and exchange commission",
    "digitally signed", "dear sir", "please find attached",
    "this is for your records", "no obligation to update",
    "does not undertake to update", "chart and figure labels",
    "investor presentation", "listing department", "phiroze jeejeebhoy",
    "but are not limited to", "statutory and regulatory",
    "foreign exchange rates", "we believe to be reasonable",
    "as of the date of this", "strictly confidential",
    "solely for information purposes", "should not be construed as",
    "this presentation has been prepared", "cash flow projections",
    "investment income", "undue reliance", "www.sec.gov",
    "for information purposes", "may not be copied",
    "results presentation", "next slide", "under-acquisition",
)

_COVER_LETTER_RE = re.compile(
    r"dear sir.*?(?:yours sincerely|yours faithfully|company secretary).{0,900}",
    re.I | re.S,
)
_DISCLAIMER_PAGE_RE = re.compile(
    r"(?:safe\s+harbou?r\s+statement|"
    r"forward\s*looking(?:\s+and\s+cautionary)?\s+statement|"
    r"this presentation has been prepared|"
    r"certain\s+(?:definitions|statements)\s+in\s+this\s+(?:release|presentation)).{0,7000}?"
    r"(?=<!--PAGE_BREAK|(?:\n|^)#+\s*page\s+\d+|\Z)",
    re.I | re.S,
)

_SKIP_LINE_STARTS = ("# page ", "|", "<!--", "## chart")

_DANGLING_END = re.compile(
    r"(?:[\u2013\u2014-]|,|/|:|\b(?:in|on|of|to|for|and|or|the|a|an|with|"
    r"by|from|as|at|our|its|into|some|such|well|across|towards|including|"
    r"include|than|maintain|maintains|contributing|managing)\s*)$",
    re.I,
)

_VERB = re.compile(
    r"\b(is|are|was|were|been|has|have|had|will|would|can|could|may|"
    r"grew|grow|grown|increased|increase|declined|decline|decreased|"
    r"added|acquired|launched|expanded|expand|expects|expect|aims|aim|"
    r"targets|target|reported|stood|remains|remain|continues|continue|"
    r"driven|helping|completed|signed|entered|plans|planned|focused|"
    r"focus|investing|building|delivered|deliver|achieved|achieve|"
    r"maintains|maintain|undertook|undertaken|initiated|recorded|"
    r"contributing|enabling)\b",
    re.I,
)

_GENERIC_NAME_TOKENS = {
    "india", "ltd", "limited", "pvt", "private", "company", "co",
    "corporation", "corp", "holdings", "holding", "group", "the",
    "of", "and", "national", "stock", "exchange", "bse", "nse",
    "bank", "energy", "services", "industries", "chemicals",
    "plc", "inc", "llp", "llc", "enterprises", "enterprise",
    "technologies", "technology", "limited.", "ltd.",
}

_EXCHANGE_RE = re.compile(
    r"\b(bse|nse|stock\s+exchange|national\s+stock|listing\s+department|"
    r"phiroze|dalal\s+street|sebi|exchange\s+plaza|scrip\s+code|"
    r"corporate\s+relationship)\b",
    re.I,
)

_SECTION_HEADINGS = {
    "commentary": (
        "management commentary", "business outlook", "ceo comment",
        "md&a", "from the ceo", "from the md",
    ),
    "strategy": (
        "strategy", "investment thesis", "key highlights",
        "quarterly highlights", "company highlights", "strategic",
    ),
    "risks": (
        "risk", "asset quality", "headwind", "challenges",
    ),
    "esg": (
        "esg", "sustainability", "csr", "environment",
    ),
}


def _prepare_knowledge_text(text: str) -> str:
    cleaned = text or ""
    cleaned = _COVER_LETTER_RE.sub("\n", cleaned, count=1)
    cleaned = _DISCLAIMER_PAGE_RE.sub("\n", cleaned, count=2)
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"^#+\s*page\s+\d+\s*$", " ", cleaned, flags=re.I | re.M)
    cleaned = re.sub(r"^#+\s*chart and figure labels\s*$", " ", cleaned, flags=re.I | re.M)
    cleaned = re.sub(r"^#+\s+", "", cleaned, flags=re.M)
    lines: List[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith(_SKIP_LINE_STARTS) or stripped.startswith("|"):
            continue
        if re.fullmatch(r"\d{1,3}", stripped):
            continue
        lines.append(stripped)
    joined: List[str] = []
    for line in lines:
        nxt = line.lstrip(" ·•*-")
        if joined and _should_join_lines(joined[-1], line):
            prev = joined[-1]
            if prev.endswith("-"):
                joined[-1] = prev[:-1] + nxt
            else:
                joined[-1] = prev.rstrip() + " " + nxt
        else:
            joined.append(line)
    return "\n".join(joined)


def _should_join_lines(prev: str, nxt: str) -> bool:
    if _looks_like_heading(nxt) or nxt.lstrip().startswith(("·", "•")):
        return False
    if _DANGLING_END.search(prev):
        return True
    return False


def _looks_like_heading(line: str) -> bool:
    if re.fullmatch(r"\d{1,3}", line.strip()):
        return True
    words = line.split()
    if line.isupper() and 1 <= len(words) <= 8:
        return True
    return False


def _is_mostly_numeric(sentence: str) -> bool:
    tokens = sentence.split()
    if len(tokens) < 4:
        return False
    numeric = sum(1 for tok in tokens if re.search(r"\d", tok))
    return numeric >= 3 and numeric / len(tokens) >= 0.4


def _is_boilerplate(sentence: str) -> bool:
    s = sentence.lower()
    if any(snip in s for snip in _BOILERPLATE_SNIPPETS):
        return True
    if _EXCHANGE_RE.search(s) and not re.search(r"\d", s):
        return True
    if _is_mostly_numeric(sentence):
        return True
    if sentence.count(",") >= 4 and not _VERB.search(sentence):
        return True
    return False


def _keyword_hit(sentence: str, keywords: Sequence[str]) -> bool:
    blob = f" {sentence.lower()} "
    for raw in keywords:
        kw = raw.strip().lower()
        if not kw:
            continue
        if kw in {"diversif", "geopolit", "margin compress"}:
            pattern = rf"\b{re.escape(kw)}"
        else:
            pattern = rf"\b{re.escape(kw)}\b"
        if re.search(pattern, blob):
            return True
    return False


def _polish(sentence: str) -> str:
    cleaned = re.sub(r"\s+", " ", sentence).strip(" •*-·–—")
    cleaned = re.sub(r"^[\|iI]\s+", "", cleaned)
    if cleaned and cleaned[-1] not in ".!?%":
        if _VERB.search(cleaned) and not _DANGLING_END.search(cleaned):
            cleaned += "."
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _is_usable(sentence: str) -> bool:
    if len(sentence) < 40 or len(sentence) > 220:
        return False
    if _is_boilerplate(sentence):
        return False
    if _DANGLING_END.search(sentence.rstrip(".")):
        return False
    if sentence.lstrip().startswith(("^", "*", "#")):
        return False
    if not _VERB.search(sentence):
        return False
    if "·" in sentence or "•" in sentence:
        return False
    if sentence.count('"') % 2 == 1 and "said" not in sentence.lower():
        return False
    if re.search(r"\bo\s+[A-Z]", sentence):
        return False
    last = sentence.rstrip(".").split()[-1] if sentence.split() else ""
    if last.upper() in {"FY", "EBIT", "EBITDA", "PAT", "CEO", "MANAGING", "ST"}:
        return False
    if re.search(r"\bSt\.$", sentence):
        return False
    return True


def _score(sentence: str, bucket: str) -> int:
    s = sentence.lower()
    score = 0
    if _VERB.search(sentence):
        score += 3
    if re.search(r"\d", sentence):
        score += 2
    if sentence[0].isupper() or sentence[0] in "\"“":
        score += 1
    if bucket == "commentary":
        if re.search(r"\b(said|ceo|cfo|managing director|outlook|guidance|we aim|we expect|we continue)\b", s):
            score += 5
        if '"' in sentence or "“" in sentence:
            score += 4
    if bucket == "strategy" and re.search(r"\b(esg|csr|carbon)\b", s):
        score -= 5
    if bucket == "esg" and re.search(r"\b(segment|tech|mobility)\b", s) and not re.search(
        r"\b(esg|csr|carbon|emission|net zero)\b", s
    ):
        score -= 6
    if bucket == "risks" and re.search(r"\b(inflation|forex|currency)\b", s) and not re.search(
        r"\b(headwind|npa|risk|challenge|pressure|uncertain)\b", s
    ):
        score -= 5
    if bucket == "risks" and re.search(r"\b(compliance|enablement)\b", s):
        score -= 4
    if bucket == "risks" and re.search(r"\brisk\b", s) and not _VERB.search(sentence):
        score -= 3
    return score


def _slice_after_heading(text: str, headings: Sequence[str], span: int = 1800) -> str:
    lower = text.lower()
    for heading in headings:
        idx = lower.find(heading)
        if idx >= 0:
            return text[idx: idx + span]
    return ""


def _too_similar(a: str, b: str) -> bool:
    al, bl = a.lower(), b.lower()
    if al in bl or bl in al:
        return True
    if al[:48] == bl[:48]:
        return True
    wa = set(re.findall(r"[a-z0-9]+", al))
    wb = set(re.findall(r"[a-z0-9]+", bl))
    inter = len(wa & wb)
    return inter >= 8 and inter / max(len(wa | wb), 1) >= 0.45


def _extract_ranked(
    text: str,
    keywords: Sequence[str],
    bucket: str,
    max_items: int,
) -> List[str]:
    prepared = _prepare_knowledge_text(text)
    section = _slice_after_heading(prepared, _SECTION_HEADINGS.get(bucket, ()))
    scan = (section + "\n" + prepared) if section else prepared
    parts = re.split(r"(?<=[.!?])\s+|\n+", scan)
    ranked: List[Tuple[int, str]] = []
    seen = set()
    for raw in parts:
        cleaned = _polish(raw)
        if not _is_usable(cleaned):
            continue
        if not _keyword_hit(cleaned, keywords):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        ranked.append((_score(cleaned, bucket), cleaned))
    ranked.sort(key=lambda item: item[0], reverse=True)
    picked: List[str] = []
    for score, sent in ranked:
        if score < 3:
            continue
        if any(_too_similar(sent, other) for other in picked):
            continue
        picked.append(sent)
        if len(picked) >= max_items:
            break
    return picked


def _clean_filename_company(filename: str) -> str:
    if not filename:
        return ""
    clean = re.sub(r"^[a-f0-9\-]{36}_?", "", filename)
    clean = re.sub(r"\.(pdf|csv|txt|md|text)$", "", clean, flags=re.I)
    clean = clean.replace("_", " ").replace("-", " ").strip()
    clean = re.sub(r"\s*Q[1-4]\s*FY\s*\d{2,4}", "", clean, flags=re.I).strip()
    clean = re.sub(
        r"\b(equity report|result update|investor presentation|annual report|"
        r"source verified|financial analysis|earnings update|results?)\b",
        "",
        clean,
        flags=re.I,
    )
    clean = re.sub(r"\s+", " ", clean).strip(" -_")
    tokens = [t for t in re.split(r"\s+", clean.lower()) if t]
    generic_tokens = {
        "onepager", "one", "pager", "paid", "report", "equity",
        "generated", "sample", "document", "untitled", "unknown",
        "research", "analysis", "update", "results", "result",
    }
    if not clean or len(clean) < 3:
        return ""
    if all(t in generic_tokens for t in tokens):
        return ""
    return clean


def _is_weak_company_name(name: str) -> bool:
    if not name or "\n" in name or "\r" in name:
        return True
    n = re.sub(r"\s+", " ", name).strip()
    if len(n) < 3 or len(n) > 70:
        return True
    if _EXCHANGE_RE.search(n):
        return True
    if re.search(r"\d", n):
        return True
    folded = re.sub(r"\bL\s*&\s*T\b", "LT", n, flags=re.I)
    tokens = re.findall(r"[a-z0-9]+", folded.lower())
    distinctive = [t for t in tokens if t not in _GENERIC_NAME_TOKENS and len(t) > 1]
    return not distinctive


_ACRONYM_STOP = {
    "LIMITED", "LTD", "SERVICES", "ENERGY", "BANK", "CHEMICALS",
    "INDUSTRIES", "TECHNOLOGY", "TECHNOLOGIES", "CAPITAL", "POWER",
    "MOTORS", "FINANCE", "COMPANY", "CORPORATION", "PRIVATE",
    "AND", "THE", "FOR", "INDIA", "NATIONAL", "STOCK", "EXCHANGE",
    "QUARTER", "RESULTS", "HIGHLIGHTS", "PRESENTATION", "LIMITED",
}


def _normalize_legal_name(name: str) -> str:
    name = re.sub(r"[®™]", "", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .,;:")
    name = re.sub(r"\s+LIMITED\s+[A-Z]{2,6}$", " LIMITED", name, flags=re.I)
    letters = re.sub(r"[^A-Za-z]", "", name)
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
        name = name.title().replace(" And ", " and ").replace(" Of ", " of ")
    return name


def _preserve_acronyms(name: str, source: str, filename_guess: str = "") -> str:
    found = set()
    for tok in (filename_guess or "").split():
        if tok.isupper() and 2 <= len(tok) <= 6 and tok not in _ACRONYM_STOP:
            found.add(tok)
    for tok in re.findall(
        r"(?:NSE|BSE)\s+Symbol\s*:?\s*\n?\s*:?\s*([A-Z]{2,6})",
        source[:4000],
        flags=re.I,
    ):
        found.add(tok.upper())
    words = []
    for word in name.split():
        bare = re.sub(r"[^A-Za-z]", "", word)
        hit = next((a for a in found if a.lower() == bare.lower()), None)
        if hit:
            words.append(re.sub(re.escape(bare), hit, word, count=1) if bare else hit)
        elif word.lower() == "and":
            words.append("and")
        else:
            words.append(word)
    return " ".join(words)


def _extract_company_name_via_llm(text: str) -> str:
    snippet = (text or "")[:2500].strip()
    if len(snippet) < 80:
        return ""
    try:
        from pipeline.utils.llm_client import call_azure_deepseek
        response = call_azure_deepseek(
            "Extract the listed company this document is about. "
            "Reply with only the company name, or UNKNOWN.",
            "What listed company is this document about?\n"
            "Reply with only the issuer name. If unclear, reply UNKNOWN.\n"
            "Do not reply with exchange names, report titles, or ratings.\n\n"
            f"DOCUMENT TEXT:\n{snippet}",
            temperature=0.0,
            max_tokens=32,
        )
        name = (response or "").strip().splitlines()[0].strip().strip("\"'")
        name = re.sub(r"^(company\s*name\s*[:=]\s*)", "", name, flags=re.I)
        if not name or name.upper() == "UNKNOWN" or _is_weak_company_name(name):
            return ""
        return name[:80]
    except Exception as exc:
        print(f"     [Knowledge Builder] LLM name extraction failed: {exc}")
        return ""


def _letterhead_text(text: str) -> str:
    """First-page issuer lines, minus exchange addresses. Used for any filing type."""
    raw = re.sub(r"<!--.*?-->", " ", (text or "")[:5000], flags=re.S)
    keep: List[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _EXCHANGE_RE.search(stripped):
            continue
        low = stripped.lower()
        if low.startswith((
            "dear sir", "sub:", "please find", "kindly take",
            "pursuant to", "this is for your",
        )):
            continue
        keep.append(stripped)
        if len(keep) >= 30:
            break
    return "\n".join(keep)


def _extract_company_name(text: str, filename: str = "") -> str:
    """Issuer name from letterhead / CIN line / filename. Any source, any sector."""
    header = _letterhead_text(text)
    filename_guess = _clean_filename_company(filename)
    thin_source = len((text or "").strip()) < 10000

    def accept(name: str) -> str:
        name = _normalize_legal_name(name)
        name = re.sub(r"^i\s+", "", name, flags=re.I)
        if _is_weak_company_name(name):
            return ""
        return _preserve_acronyms(name, text, filename_guess)

    for line in header.split("\n")[:8]:
        hit = accept(line)
        if hit and len(hit.split()) >= 2:
            return hit

    before_regd = re.search(
        r"^([A-Z][A-Za-z0-9&(). ]{2,70})\s*\n\s*(?:Regd\.|CIN:|Registered\s+Office)",
        header,
        re.M,
    )
    if before_regd:
        hit = accept(before_regd.group(1))
        if hit:
            return hit

    signed = re.search(
        r"\bFor\s+([A-Z][A-Za-z&(). ]{3,70}(?:Limited|Ltd\.?))",
        text[:8000],
    )
    if signed:
        hit = accept(signed.group(1))
        if hit:
            return hit

    suffixes = (
        r"Bank(?:\s+Limited)?|Technologies(?:\s+Limited)?"
        r"|Technology\s+Services(?:\s+Limited)?|Energy(?:\s+Limited)?"
        r"|Chemicals(?:\s+Limited)?|Industries(?:\s+Limited)?"
        r"|Motors(?:\s+Limited)?|Power(?:\s+Limited)?"
        r"|Finance(?:\s+Limited)?|Capital(?:\s+Limited)?"
        r"|Limited|Ltd\.?|Plc|PLC"
    )
    for match in re.findall(
        rf"\b((?:[A-Z][A-Za-z&]+\s+){{0,4}}[A-Z][A-Za-z&]+\s+(?:{suffixes}))\b",
        header,
    ):
        hit = accept(match)
        if hit:
            return hit

    rating = r"(?:BUY|SELL|HOLD|ACCUMULATE|REDUCE|NEUTRAL|UNDERPERFORM|NOT\s*RATED)"
    brokerage = re.search(
        rf"^([A-Z][A-Za-z&(). ]{{2,54}})\s*\n\s*(?:{rating}|CMP|Target\s+Price)",
        header,
        re.M,
    )
    if brokerage:
        hit = accept(brokerage.group(1))
        if hit:
            return hit

    if filename_guess and not _is_weak_company_name(filename_guess):
        return _preserve_acronyms(filename_guess, text + " " + filename_guess, filename_guess)

    if thin_source:
        llm_name = _extract_company_name_via_llm(text)
        if llm_name:
            print(f"     [Knowledge Builder] LLM company name: {llm_name}")
            return _preserve_acronyms(llm_name, text, filename_guess)

    return filename_guess or ""


def _extract_management_commentary(text: str) -> str:
    sentences = _extract_ranked(text, _COMMENTARY_KEYWORDS, "commentary", max_items=2)
    return " ".join(sentences)


class KnowledgeBuilder:
    @staticmethod
    def run(master_doc: MasterDocument, filename: str = "") -> Dict[str, Any]:
        print("     [Knowledge Builder] Organizing DOM into semantic concepts...")

        full_text = master_doc.get_full_text() or ""
        company_name = _extract_company_name(full_text, filename)
        print(f"     [Knowledge Builder] Extracted company name: {company_name or '(from filename later)'}")

        scan = full_text[:50000]
        knowledge_graph: Dict[str, Any] = {
            "company_name": company_name,
            "strategy_and_highlights": _extract_ranked(
                scan, _STRATEGY_KEYWORDS, "strategy", max_items=4
            ),
            "risks_and_challenges": _extract_ranked(
                scan, _RISK_KEYWORDS, "risks", max_items=3
            ),
            "esg_initiatives": _extract_ranked(
                scan, _ESG_KEYWORDS, "esg", max_items=2
            ),
            "management_commentary": [_extract_management_commentary(scan)],
        }

        print(
            "     [Knowledge Builder] Extracted — "
            f"strategy: {len(knowledge_graph['strategy_and_highlights'])}, "
            f"risks: {len(knowledge_graph['risks_and_challenges'])}, "
            f"ESG: {len(knowledge_graph['esg_initiatives'])} sentences."
        )
        return knowledge_graph
