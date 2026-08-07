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
from typing import Dict
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


def _narrative_evidence_cues(evidence_packet: BaseModel) -> str:
    """Build number-free interpretation cues from verified evidence."""
    def value(item, period):
        try:
            v = getattr(item, period, None)
            v = getattr(v, "value", v)
            return float(v) if isinstance(v, (int, float)) else None
        except (TypeError, ValueError):
            return None

    def trend(label, item):
        if item is None:
            return None
        cur = value(item, "q_current")
        yoy = value(item, "q_prev_year")
        qoq = value(item, "q_prev_qtr")
        cues = []
        if cur is not None and yoy not in (None, 0):
            cues.append(f"{label} is {'higher' if cur > yoy else 'lower'} YoY")
        if cur is not None and qoq not in (None, 0):
            cues.append(f"{label} is {'higher' if cur > qoq else 'lower'} QoQ")
        return "; ".join(cues) if cues else None

    cues = []
    pl = getattr(evidence_packet, "pl", None)
    for label, field in (("primary metric", "revenue"), ("PAT", "pat"),
                         ("EBITDA", "ebitda"), ("PBT", "pbt")):
        cue = trend(label, getattr(pl, field, None) if pl else None)
        if cue:
            cues.append(cue)

    banking = getattr(evidence_packet, "banking_metrics", None) or {}
    if banking:
        cues.append("Banking-sector evidence is available")
        for label, field in (("NIM", "nim"), ("GNPA", "gnpa"),
                             ("NNPA", "nnpa"), ("CASA", "casa_ratio"),
                             ("credit growth", "credit_growth")):
            item = banking.get(field) if isinstance(banking, dict) else getattr(banking, field, None)
            cue = trend(label, item)
            if cue:
                cues.append(cue)

    available = [name for name in ("pl", "bs", "cf", "banking_metrics")
                 if getattr(evidence_packet, name, None)]
    cues.append("Available evidence sections: " + ", ".join(available))
    return "\n".join(f"- {cue}." for cue in cues)


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
        result["report_subtitle"] = "Growth trajectory intact; valuation warrants monitoring"

    # Never allow prompt/example placeholders to reach the report cover.
    _subtitle_placeholder = re.compile(
        r"\[(?:key growth driver|key concern(?: or valuation comment)?)\]",
        flags=re.IGNORECASE,
    )
    if _subtitle_placeholder.search(result["report_subtitle"]):
        result["report_subtitle"] = "Growth trajectory and valuation remain under review"

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

        packet_json = self._sanitize_packet(evidence_packet)
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            packet_json, _narrative_evidence_cues(evidence_packet)
        )

        raw_response = call_azure_deepseek(system_prompt, user_prompt)
        narrative = _strip_thinking_blocks(raw_response or "")

        # Safety net: strip any numbers that slipped through
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

    def _build_user_prompt(self, packet_json: str, evidence_cues: str = "") -> str:
        return (
            f"Evidence Packet (verified financial data):\n"
            f"```json\n{packet_json}\n```\n\n"
            f"Deterministic interpretation cues (derived only from verified values; no figures):\n"
            f"{evidence_cues}\n\n"
            f"Task:\n{self._get_task_instruction()}"
        )

    def _get_task_instruction(self) -> str:
        raise NotImplementedError("Subclasses must define their task instruction.")

    def _empty_placeholder(self, evidence_packet: BaseModel) -> str:
        company = getattr(evidence_packet, "company_name", "the company")
        return (
            f"BUSINESS_DESCRIPTION\n"
            f"{company} operates in the financial services sector. "
            f"Detailed business description not available.\n\n"
            f"KEY_HIGHLIGHTS\n"
            f"• Financial data extracted from source document.\n"
            f"• Refer to tables below for extracted metrics.\n\n"
            f"REPORT_SUBTITLE\n"
            f"Results update — refer to financial tables\n\n"
            f"OUTLOOK_VALUATION\n"
            f"Insufficient data to generate outlook. "
            f"Refer to extracted financial tables for available metrics. "
            f"We assign a Not Rated stance pending complete financial data."
        )
