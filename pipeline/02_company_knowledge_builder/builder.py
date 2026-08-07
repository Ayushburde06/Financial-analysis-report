"""
Stage 02: Company Knowledge Builder

IMPROVEMENT: Replaced LLM call with pure Python keyword extraction.
Old: Used call_mistral_direct() for management commentary → slow, costs money,
     returned only 26 chars (nearly empty) in tests.
New: Pure Python regex + keyword scan → instant, $0.00, more reliable.

Extracts:
  - management_commentary: sentences containing guidance/outlook keywords
  - strategy_and_highlights: sentences containing growth/expansion keywords
  - risks_and_challenges: sentences containing risk keywords
  - esg_initiatives: sentences containing ESG keywords
"""

import re
from typing import Dict, Any, List
from dom_schema import MasterDocument


# ─── Keyword banks ────────────────────────────────────────────────────────────

_COMMENTARY_KEYWORDS = [
    "guidance", "outlook", "management", "ceo", "md ", "cfo",
    "expect", "anticipate", "target", "projected", "aim", "aspire",
    "confident", "optimistic", "cautious", "next quarter", "next year",
    "fy26", "fy27", "going forward", "we believe", "we expect",
    "on track", "pipeline", "deal wins", "new orders",
]

_STRATEGY_KEYWORDS = [
    "expansion", "capacity", "investment", "capex", "launch",
    "new product", "partnership", "acquisition", "merger", "joint venture",
    "market share", "geographic", "digital", "cloud", "ai ", "automation",
    "new vertical", "diversif", "transform", "scale",
]

_RISK_KEYWORDS = [
    "risk", "challenge", "headwind", "pressure", "concern", "uncertain",
    "slowdown", "competition", "margin compress", "npa", "slippage",
    "default", "regulatory", "forex", "currency", "inflation", "shortage",
    "supply chain", "geopolit", "war", "sanction",
]

_ESG_KEYWORDS = [
    "esg", "sustainability", "carbon", "emission", "renewable",
    "green", "social", "governance", "csr", "environment",
    "net zero", "diversity", "inclusion", "water", "waste",
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _extract_sentences_by_keywords(text: str,
                                    keywords: List[str],
                                    max_sentences: int = 5) -> List[str]:
    """
    Split text into sentences, return up to max_sentences that contain
    at least one of the given keywords (case-insensitive).
    """
    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    matched: List[str] = []
    text_lower = text.lower()

    for sentence in sentences:
        s_lower = sentence.lower()
        if any(kw in s_lower for kw in keywords):
            cleaned = sentence.strip()
            if len(cleaned) > 20:  # skip trivially short fragments
                matched.append(cleaned)
        if len(matched) >= max_sentences:
            break

    return matched


def _extract_company_name(text: str, filename: str = "") -> str:
    """
    Extract company name from source PDF OCR text.
    Handles all Indian listed company types: Banks, IT, Energy, Metals, FMCG etc.
    Also handles brokerage research notes (Geojit-style) where the company name
    appears as the headline of the analyst report, not as a company letterhead.

    Priority: OCR brokerage header → company letterhead patterns → filename fallback
    """
    header = text[:3000]

    # Boilerplate to exclude
    EXCLUDE = [
        "bse limited", "national stock exchange", "exchange plaza",
        "listing department", "corporate relationship", "phiroze jeejeebhoy",
        "dalal street", "securities and exchange board", "sebi", "dear sir",
        "investor presentation", "mumbai",
        "stock exchange", "exchange of india",
        "geojit financial", "geojit securities", "geojit bnh",
    ]

    # Known brands that need exact capitalisation
    BRAND_FIXES = [
        ("Jsw", "JSW"), ("Icici", "ICICI"), ("Ltts", "LTTS"),
        ("Pocl", "POCL"), ("Hdfc", "HDFC"), ("Tcs", "TCS"),
        ("Sbi", "SBI"), ("Ndtv", "NDTV"), ("Ntpc", "NTPC"),
        ("Bhel", "BHEL"), ("Ongc", "ONGC"), ("And", "and"),
        ("Hcl", "HCL"), ("Wipro", "Wipro"), ("Irctc", "IRCTC"),
    ]

    def is_valid(name: str) -> bool:
        n = name.lower().strip()
        if len(n) < 4 or len(n) > 60:
            return False
        return not any(exc in n for exc in EXCLUDE)

    def apply_brand_fixes(name: str) -> str:
        for fix_from, fix_to in BRAND_FIXES:
            name = name.replace(fix_from, fix_to)
        return name

    # ── Pattern 0: Brokerage research note header ──────────────────────────────
    # Geojit-style reports: company name appears as FIRST non-trivial headline
    # immediately before rating signals like BUY / SELL / HOLD / CMP / Target Price
    _RATING_SIGNALS = r'(?:BUY|SELL|HOLD|ACCUMULATE|REDUCE|NEUTRAL|UNDERPERFORM)'
    _CMP_SIGNALS = r'(?:CMP|C\.M\.P|Current\s+Market\s+Price|Target\s+Price|TP\s*:)'

    # Company name on line just before rating/CMP signals
    p0_match = re.search(
        rf'([A-Z][A-Za-z&\s.()]{3,55}?)\s*\n\s*(?:{_RATING_SIGNALS}|{_CMP_SIGNALS})',
        header
    )
    if p0_match:
        name = p0_match.group(1).strip().rstrip(".")
        if is_valid(name):
            return apply_brand_fixes(name.title() if name.isupper() else name)

    # Pattern 0b: Company name on same line as rating, separated by | or —
    # Example: "ICICI Bank | BUY" or "LTTS — BUY"
    p0b_match = re.search(
        rf'([A-Z][A-Za-z&\s.()]{3,50}?)\s*(?:\||—|-|:)\s*(?:{_RATING_SIGNALS})',
        header
    )
    if p0b_match:
        name = p0b_match.group(1).strip().rstrip(".")
        if is_valid(name):
            return apply_brand_fixes(name.title() if name.isupper() else name)

    # Pattern 0c: "Result Update" / "Initiating Coverage" / "Q2FY26 Results" style headers
    p0c_match = re.search(
        r'([A-Z][A-Za-z&\s.()]{3,50}?)\s*\n\s*(?:Q[1-4]\s*FY\d{2,4}\s*Result|'
        r'Result\s+Update|Initiating\s+Coverage|Company\s+Update|'
        r'Q[1-4]\s*FY\d{2,4}\s+Update|Earnings\s+Update)',
        header, re.IGNORECASE
    )
    if p0c_match:
        name = p0c_match.group(1).strip().rstrip(".")
        if is_valid(name):
            return apply_brand_fixes(name.title() if name.isupper() else name)

    # ── Pattern 1: "XYZ Bank Limited", "ABC Technologies Limited" style ────────
    suffixes = (
        r"Bank(?:\s+Limited)?|Technologies(?:\s+Limited)?"
        r"|Technology\s+Services(?:\s+Limited)?|Energy(?:\s+Limited)?"
        r"|Chemicals(?:\s+Limited)?|Industries(?:\s+Limited)?"
        r"|Services(?:\s+Limited)?|Limited|Ltd\.?"
    )
    p1 = re.findall(
        rf'\b((?:[A-Z][A-Za-z&]+\s*){{1,4}}(?:{suffixes}))\b',
        header
    )
    for m in p1:
        name = m.strip().rstrip(".")
        if is_valid(name) and len(name.split()) >= 2:
            return name

    # ── Pattern 2: Line before "Regd. Office" or "CIN:" ───────────────────────
    p2 = re.search(
        r'([A-Z][A-Za-z&\s]{3,50}?)\s*\n\s*(?:Regd\.|CIN:|Registered\s+Office)',
        header, re.MULTILINE
    )
    if p2:
        name = p2.group(1).strip()
        if is_valid(name) and len(name.split()) >= 2:
            return name

    # ── Pattern 3: ALL CAPS company name in first 600 chars ───────────────────
    p3 = re.findall(
        r'\b([A-Z]{2,}(?:\s+(?:AND\s+)?[A-Z&]{2,}){1,5}(?:\s+LIMITED)?)\b',
        header[:600]
    )
    for m in p3:
        if any(exc in m.lower() for exc in ["national stock", "exchange", "dalal", "sebi"]):
            continue
        name = apply_brand_fixes(m.strip().title())
        if is_valid(name) and len(name.split()) >= 2:
            return name

    # ── Pattern 4: First short line that looks like a company name ─────────────
    for line in header.split('\n'):
        line = line.strip()
        if (5 < len(line) < 55 and is_valid(line)
                and re.match(r'^[A-Z]', line)
                and not re.match(r'^\d', line)
                and '.' not in line[:8]
                and '@' not in line and '/' not in line):
            return line

    # ── Fallback: clean filename ───────────────────────────────────────────────
    if filename:
        clean = re.sub(r'^[a-f0-9\-]{36}_?', '', filename)
        clean = re.sub(r'\.pdf$', '', clean, flags=re.IGNORECASE)
        clean = clean.replace("_", " ").strip()
        clean = re.sub(r'\s*Q[1-4]\s*FY\s*\d{2,4}', '', clean, flags=re.IGNORECASE).strip()
        if clean and len(clean) > 2:
            return clean

    return "Unknown Company"



def _extract_management_commentary(text: str) -> str:
    """
    Extract a concise management commentary block from the source text.
    Looks for sentences near guidance/outlook keywords and returns
    them joined as a paragraph. Falls back to a generic message.
    """
    sentences = _extract_sentences_by_keywords(text, _COMMENTARY_KEYWORDS, max_sentences=4)
    if sentences:
        return " ".join(sentences)
    return "No management commentary available in this document."


# ─── Main Builder ─────────────────────────────────────────────────────────────

class KnowledgeBuilder:
    @staticmethod
    def run(master_doc: MasterDocument, filename: str = "") -> Dict[str, Any]:
        print("     [Knowledge Builder] Organizing DOM into semantic concepts...")

        full_text = master_doc.get_full_text() or ""

        # Extract company name from PDF text
        company_name = _extract_company_name(full_text, filename)
        print(f"     [Knowledge Builder] Extracted company name: {company_name}")

        # Use first 12k chars for commentary (covers front pages with MD&A)
        commentary_text = full_text[:12000]
        # Use full text for risks/strategy (may appear anywhere)
        full_scan = full_text[:40000]

        knowledge_graph: Dict[str, Any] = {
            "company_name": company_name,  # ← NEW
            "strategy_and_highlights": _extract_sentences_by_keywords(
                full_scan, _STRATEGY_KEYWORDS, max_sentences=5
            ),
            "risks_and_challenges": _extract_sentences_by_keywords(
                full_scan, _RISK_KEYWORDS, max_sentences=5
            ),
            "esg_initiatives": _extract_sentences_by_keywords(
                full_scan, _ESG_KEYWORDS, max_sentences=3
            ),
            "management_commentary": [_extract_management_commentary(commentary_text)],
        }

        # Log summary
        n_strategy = len(knowledge_graph["strategy_and_highlights"])
        n_risks    = len(knowledge_graph["risks_and_challenges"])
        n_esg      = len(knowledge_graph["esg_initiatives"])
        print(f"     [Knowledge Builder] Extracted — "
              f"strategy: {n_strategy}, risks: {n_risks}, ESG: {n_esg} sentences.")

        return knowledge_graph
