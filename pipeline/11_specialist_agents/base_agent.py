"""
base_agent.py — Base Financial Agent (enforces Rule 15: LLM Quarantine)

Produces structured narrative with 4 labelled sections that the ROM builder
maps into distinct report fields:
  BUSINESS_DESCRIPTION  → report.business_description
  KEY_HIGHLIGHTS        → report.key_highlights (list of bullets)
  REPORT_SUBTITLE       → report.report_subtitle
  OUTLOOK_VALUATION     → report.outlook_valuation
"""

import re
from typing import Dict, Optional
from pydantic import BaseModel

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from pipeline.utils.llm_client import call_azure_deepseek


def _strip_thinking_blocks(text: str) -> str:
    """Remove DeepSeek R1 <think>...</think> chain-of-thought blocks."""
    return re.sub(
        r'<think(?:ing)?>.*?</think(?:ing)?>',
        '', text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()


def _strip_citation_tags(text: str) -> str:
    """Remove internal [Source: ...] tags before rendering in PDF."""
    text = re.sub(r'\s*\[Source:[^\]]+\]', '', text)
    text = re.sub(r'\s*\[E\]', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)   # **bold** → plain
    text = re.sub(r'##\s*', '', text)                  # ## headings → plain
    return text.strip()


def _strip_numbers_from_narrative(text: str) -> str:
    """
    Safety net: remove any numeric values that the LLM might have inserted
    despite instructions. Replaces standalone numbers with empty string,
    preserving the qualitative text around them.
    Also strips [VERIFIED] / [N/A] placeholders the LLM may echo back from
    the sanitized evidence packet (anti-hallucination leakage guard).
    """
    # Strip [VERIFIED] / [N/A] placeholders echoed from sanitized packet
    text = re.sub(r'\[VERIFIED\]', '', text)
    text = re.sub(r'\[N/A\]', '', text)
    # Remove patterns like "Rs. 123.45cr", "12.3%", "Rs 1,234", "+5.2%"
    text = re.sub(r'Rs\.?\s*-?\d[\d,]*\.?\d*\s*(cr|Cr|CR|bn|Bn|BN|crore|billion)?', '', text)
    text = re.sub(r'-?\d+\.?\d*\s*%', '', text)
    # Remove standalone numbers (but keep words)
    text = re.sub(r'\b-?\d+\.?\d*\b', '', text)
    # Clean up double spaces and awkward punctuation
    text = re.sub(r'\s{2,}', ' ', text)
    text = re.sub(r'\s+([,.;])', r'\1', text)
    # Clean up leftover "Rs." / "Rs" with no number after stripping
    text = re.sub(r'\bRs\.?\s*(?=[,.;)\s]|$)', '', text)
    # Clean up orphaned units left after number stripping (e.g. "to cr", "grew cr")
    text = re.sub(r'\s+(cr|Cr|CR|bn|Bn|BN|crore|billion)\b(?=[,.;)\s]|$)', '', text)
    return text.strip()


def _line_numeric(item, period: str):
    try:
        v = getattr(item, period, None)
        v = getattr(v, "value", v)
        return float(v) if isinstance(v, (int, float)) else None
    except (TypeError, ValueError):
        return None


def _magnitude(current, previous) -> Optional[str]:
    if current is None or previous in (None, 0):
        return None
    change = (current - previous) / abs(previous) * 100.0
    abs_ch = abs(change)
    if abs_ch < 2:
        return "broadly unchanged"
    direction = "higher" if change > 0 else "lower"
    if abs_ch < 8:
        return f"modestly {direction}"
    if abs_ch < 20:
        return direction
    return f"sharply {direction}"


def _pretty_metric(key: str) -> str:
    labels = {
        "revenue": "Revenue", "nii": "NII", "pat": "PAT", "ebitda": "EBITDA",
        "pbt": "PBT", "eps": "EPS", "nim": "NIM", "gnpa": "GNPA", "nnpa": "NNPA",
        "casa_ratio": "CASA", "advances": "Advances", "deposits": "Deposits",
        "gmv": "GMV", "capacity": "Capacity", "arpu": "ARPU",
    }
    if key in labels:
        return labels[key]
    return str(key or "").replace("_", " ").strip().title() or "Metric"


def _narrative_evidence_cues(evidence_packet: BaseModel) -> str:
    """Number-free, filing-specific cues so the LLM can describe THIS company."""
    cues = []
    name = getattr(evidence_packet, "company_name", "") or "This company"
    industry = getattr(evidence_packet, "industry", "") or ""
    period = getattr(evidence_packet, "period_label", "") or "the latest reported period"
    unit = getattr(evidence_packet, "source_unit", "") or ""
    cues.append(f"Company: {name}")
    if industry:
        cues.append(f"Industry in this filing: {industry}")
    cues.append(f"Reporting period: {period}")
    if unit:
        cues.append(f"Source unit: {unit}")

    pl = getattr(evidence_packet, "pl", None)
    revenue_label = "NII" if "bank" in (industry or "").lower() else "Revenue"

    def add_trend(label, item):
        if item is None:
            return
        cur = _line_numeric(item, "q_current")
        yoy = _line_numeric(item, "q_prev_year")
        qoq = _line_numeric(item, "q_prev_qtr")
        mag = _magnitude(cur, yoy)
        if mag:
            cues.append(f"{label} in {period} is {mag} versus the year-ago quarter")
        mag_q = _magnitude(cur, qoq)
        if mag_q and mag_q != mag:
            cues.append(f"{label} is {mag_q} versus the prior quarter")
        annual = {}
        if hasattr(item, "actual_year_values"):
            annual = item.actual_year_values() or {}
        years = sorted(annual)
        if len(years) >= 2:
            mag_a = _magnitude(annual[years[-1]], annual[years[-2]])
            if mag_a:
                cues.append(f"{label} on an annual basis is {mag_a} versus the prior actual year")

    add_trend(revenue_label, getattr(pl, "revenue", None) if pl else None)
    add_trend("PAT", getattr(pl, "pat", None) if pl else None)
    add_trend("EBITDA", getattr(pl, "ebitda", None) if pl else None)
    add_trend("PBT", getattr(pl, "pbt", None) if pl else None)

    extras = getattr(evidence_packet, "banking_metrics", None) or {}
    extra_names = []
    if isinstance(extras, dict):
        extra_names = [_pretty_metric(k) for k in extras.keys() if k]
        for key, item in list(extras.items())[:8]:
            add_trend(_pretty_metric(key), item)
    if extra_names:
        cues.append("Extra metrics present in this filing: " + ", ".join(extra_names[:10]))

    facts = list(getattr(evidence_packet, "business_facts", None) or [])
    if facts:
        cues.append("Activity / strategy sentences copied from this filing (figures removed):")
        for fact in facts[:5]:
            cues.append(f"  FACT: {fact}")
    else:
        cues.append(
            "No usable activity paragraph was extracted. Describe only what the "
            f"industry label ({industry or 'unspecified'}) and metric names imply. "
            "Do not invent products, brands, or geographies."
        )

    risks = list(getattr(evidence_packet, "risk_facts", None) or [])
    if risks:
        cues.append("Risk sentences copied from this filing (figures removed):")
        for fact in risks[:3]:
            cues.append(f"  RISK: {fact}")

    bs = getattr(evidence_packet, "bs", None)
    if bs and hasattr(getattr(bs, "total_assets", None), "actual_year_values"):
        if getattr(bs, "total_assets").actual_year_values():
            cues.append("Balance sheet figures are present in this filing.")
    cf = getattr(evidence_packet, "cf", None)
    if cf and hasattr(getattr(cf, "operating_cash_flow", None), "actual_year_values"):
        if getattr(cf, "operating_cash_flow").actual_year_values():
            cues.append("Operating cash flow figures are present in this filing.")

    return "\n".join(f"- {cue}" if not cue.startswith("  ") else cue for cue in cues)


def parse_narrative_sections(narrative: str) -> Dict[str, object]:
    """
    Parse the structured LLM output into separate fields.
    Expected markers: BUSINESS_DESCRIPTION, KEY_HIGHLIGHTS,
                      REPORT_SUBTITLE, OUTLOOK_VALUATION
    Returns a dict with those 4 keys plus 'full' (original text).
    """
    result = {
        "full": narrative,
        "business_description": "",
        "key_highlights": [],
        "report_subtitle": "",
        "outlook_valuation": "",
    }

    _MARKERS = ("BUSINESS_DESCRIPTION", "KEY_HIGHLIGHTS",
                "REPORT_SUBTITLE", "OUTLOOK_VALUATION")
    # Match markers with optional markdown bold (**), optional surrounding whitespace/newlines
    _marker_re = re.compile(
        r'\n?\s*\**\s*(BUSINESS_DESCRIPTION|KEY_HIGHLIGHTS|REPORT_SUBTITLE|OUTLOOK_VALUATION)\s*\**\s*\n'
    )

    # Split on section markers
    sections = _marker_re.split(narrative)

    current_key = None
    for part in sections:
        part_stripped = part.strip().strip('*').strip()
        if part_stripped in _MARKERS:
            current_key = part_stripped.lower()
        elif current_key and part_stripped:
            clean = _strip_citation_tags(part_stripped)
            if current_key == "key_highlights":
                # Parse bullet lines
                bullets = []
                for line in clean.split('\n'):
                    line = line.strip()
                    if line.startswith('•') or line.startswith('-') or line.startswith('*'):
                        bullet_text = re.sub(r'^[•\-\*]\s*', '', line).strip()
                        if bullet_text:
                            bullets.append(bullet_text)
                result["key_highlights"] = bullets
            else:
                result[current_key] = clean
            current_key = None

    # Cleanup: strip any leftover markers AND [VERIFIED]/[N/A] placeholders from each section text
    for key in ("business_description", "report_subtitle", "outlook_valuation"):
        if result[key]:
            for marker in _MARKERS:
                result[key] = result[key].replace(marker, "").strip().strip('*').strip()
            # Strip anti-hallucination placeholders that may leak from sanitized packet
            result[key] = re.sub(r'\[VERIFIED\]', '', result[key])
            result[key] = re.sub(r'\[N/A\]', '', result[key])
            result[key] = re.sub(r'\s{2,}', ' ', result[key]).strip()
    # Also clean key_highlights bullets
    if result["key_highlights"]:
        result["key_highlights"] = [
            re.sub(r'\s{2,}', ' ',
                   re.sub(r'\[N/A\]', '',
                          re.sub(r'\[VERIFIED\]', '', b))).strip()
            for b in result["key_highlights"]
        ]

    # Fallback: if parsing failed, extract bullets from full text
    if not result["key_highlights"]:
        bullets = []
        for line in narrative.split('\n'):
            line = line.strip()
            if line.startswith('•') or (line.startswith('-') and len(line) > 10):
                bullet_text = re.sub(r'^[•\-]\s*', '', line).strip()
                bullet_text = _strip_citation_tags(bullet_text)
                if bullet_text:
                    bullets.append(bullet_text)
        result["key_highlights"] = bullets

    # Fallback for missing sections
    if not result["business_description"]:
        # Try to grab first non-bullet paragraph
        for line in narrative.split('\n'):
            line = line.strip()
            if (line and not line.startswith('•') and not line.startswith('#')
                    and not line.startswith('BUSINESS') and len(line) > 30):
                result["business_description"] = _strip_citation_tags(line)
                break

    if not result["outlook_valuation"]:
        # Try to find outlook paragraph
        m = re.search(r'(Outlook.*?)\n\n', narrative, re.DOTALL | re.IGNORECASE)
        if m:
            result["outlook_valuation"] = _strip_citation_tags(m.group(1))

    # ── Off-topic brand/company leak guard ──────────────────────────────────
    # If the LLM echoes a hardcoded example (e.g. Zomato/Blinkit) into a report
    # for an unrelated company, replace the subtitle with a neutral fallback so
    # a wrong-company thesis never ships. This is a last-resort safety net; the
    # prompt itself is the primary fix.
    _OFFTOPIC_TERMS = [
        "blinkit", "zomato", "eternal limited", "hyperpure", "swiggy",
        "quick commerce", "qcb", "food delivery", "food-delivery",
        "zepto", "instamart", "online food",
    ]
    def _leaks_offtopic(text: str) -> bool:
        low = text.lower()
        return any(t in low for t in _OFFTOPIC_TERMS)

    if _leaks_offtopic(result["report_subtitle"]):
        result["report_subtitle"] = "Results as reported; thesis limited to this filing"

    # Never allow prompt/example placeholders to reach the report cover.
    _subtitle_placeholder = re.compile(
        r"\[(?:key growth driver|key concern(?: or valuation comment)?)\]",
        flags=re.IGNORECASE,
    )
    if _subtitle_placeholder.search(result["report_subtitle"]):
        result["report_subtitle"] = "Results as reported; thesis limited to this filing"

    # Also scrub leaked terms from the narrative body if the whole company is wrong
    # (business_description / outlook). Replace the term, not the whole section, to
    # preserve otherwise-valid analysis.
    for key in ("business_description", "outlook_valuation"):
        if result[key]:
            for term in _OFFTOPIC_TERMS:
                # Remove parenthetical/standalone mentions conservatively
                result[key] = re.sub(re.escape(term), "", result[key], flags=re.IGNORECASE)
            result[key] = re.sub(r'\(\s*\)', '', result[key])
            result[key] = re.sub(r'\s{2,}', ' ', result[key]).strip()

    return result


class BaseFinancialAgent:
    """
    Abstract base for all analyst agents.
    Enforces Rule 15: input must be a validated Pydantic evidence packet.
    """

    def generate(self, evidence_packet: BaseModel) -> str:
        """
        Accept a typed Pydantic evidence packet, call DeepSeek R1,
        strip thinking blocks and citation tags, return clean narrative.

        Anti-hallucination: ALL numeric values are stripped from the packet
        before passing to the LLM. The LLM sees only the structure (what data
        exists) but NOT the actual numbers — it physically cannot invent or
        misquote financial figures because it never sees them.
        """
        if not isinstance(evidence_packet, BaseModel):
            raise TypeError(
                f"LLM Quarantine Violation: Agent received raw data of type "
                f"{type(evidence_packet)}. Must be a verified Pydantic evidence packet."
            )

        cues = _narrative_evidence_cues(evidence_packet)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(cues)

        raw_response = call_azure_deepseek(system_prompt, user_prompt)
        narrative = _strip_thinking_blocks(raw_response or "")

        # Safety net: strip any numbers that slipped through
        if narrative.strip():
            narrative = _strip_numbers_from_narrative(narrative)

        if not narrative.strip():
            narrative = self._empty_placeholder(evidence_packet)

        return narrative

    def generate_analytical(
        self,
        evidence_packet: BaseModel,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Generate narrative using pre-computed analytical system/user prompts.
        Same quarantine and post-processing as generate().
        """
        if not isinstance(evidence_packet, BaseModel):
            raise TypeError(
                f"LLM Quarantine Violation: Agent received raw data of type "
                f"{type(evidence_packet)}. Must be a verified Pydantic evidence packet."
            )

        raw_response = call_azure_deepseek(system_prompt, user_prompt)
        narrative = _strip_thinking_blocks(raw_response or "")

        if narrative.strip():
            narrative = _strip_numbers_from_narrative(narrative)

        if not narrative.strip():
            narrative = self._empty_placeholder(evidence_packet)

        return narrative

    def _sanitize_packet(self, evidence_packet: BaseModel) -> str:
        """
        Strip ALL numeric values from the evidence packet before sending to LLM.
        Replaces every number with '[VERIFIED]' so the LLM knows data exists
        but cannot see or repeat specific figures.
        """
        import json, re
        raw = evidence_packet.model_dump_json(indent=2)
        # Replace all numeric values (int, float, negative, decimals) with placeholder
        sanitized = re.sub(r'-?\d+\.?\d*', '[VERIFIED]', raw)
        # Also replace "null" with "[N/A]" so LLM knows field exists but is empty
        sanitized = sanitized.replace('null', '"[N/A]"')
        return sanitized

    def _build_system_prompt(self) -> str:
        # Overridden in FinancialAnalyst
        return (
            "You are a Senior Equity Research Analyst. "
            "CRITICAL RULE: Do NOT include any specific financial figures, "
            "percentages, currency amounts, or numerical data in your response. "
            "Write ONLY qualitative analysis — business model description, "
            "growth drivers, risk factors, and outlook commentary. "
            "All numbers are rendered separately by the pipeline from verified data. "
            "Your narrative must contain ZERO numbers."
        )

    def _build_user_prompt(self, evidence_cues: str = "") -> str:
        return (
            "Write the four Geojit sections from this filing brief only. "
            "Do not invent products, geographies, peers, or numbers.\n\n"
            f"{evidence_cues}\n\n"
            f"Task:\n{self._get_task_instruction()}"
        )

    def _get_task_instruction(self) -> str:
        raise NotImplementedError("Subclasses must define their task instruction.")

    def _empty_placeholder(self, evidence_packet: BaseModel) -> str:
        company = getattr(evidence_packet, "company_name", "The company")
        industry = getattr(evidence_packet, "industry", "") or "the reported"
        return (
            f"BUSINESS_DESCRIPTION\n"
            f"{company} is covered from this filing as a {industry} business. "
            f"The source does not include a usable description of products or operations "
            f"beyond the financial statements.\n\n"
            f"KEY_HIGHLIGHTS\n"
            f"• Refer to the tables for figures printed in this filing.\n\n"
            f"REPORT_SUBTITLE\n"
            f"{industry} update; coverage limited to reported statements\n\n"
            f"OUTLOOK_VALUATION\n"
            f"This note follows the statements in the source filing. "
            f"We assign a Not Rated stance as a printed CMP and target are not available."
        )
