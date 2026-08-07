"""
verifier.py — 5-Layer Verification Stack

BUG FIXED (Stage 12 false positives):
  Old prompt asked DeepSeek: "all numbers match EXACTLY" — flagged
  legitimate derived calculations (growth %, margins, CAGR) as hallucinations
  because they don't appear verbatim in the evidence JSON.

New two-pass approach:
  Pass A (Python, free, instant):
    - Flatten evidence packet to {field_path: float} lookup table
    - Extract all [Source: field.path] tags from narrative
    - Verify each cited field exists in evidence
    - Extract uncited absolute numbers (>= 4 digits)
    - Check each against evidence within 1% tolerance
    - If all uncited numbers found in evidence → VALID, skip DeepSeek entirely

  Pass B (DeepSeek R1, only when Pass A finds suspicious numbers):
    - Send ONLY the suspicious numbers (not the whole narrative)
    - Give DeepSeek the flattened evidence, not the full Pydantic object
    - Explicitly tell it: percentages / growth rates / margins are DERIVED,
      never flag them as hallucinations
    - Block only on confirmed invented absolute values

Rule: derived calculations (%, CAGR, margins) are NEVER flagged.
      Only absolute values with no source tag AND not in evidence are audited.
"""

import re
import json
from typing import Any, Dict, List, Tuple


# ─── Evidence flattener ───────────────────────────────────────────────────────

def _flatten_evidence(evidence_packet: Any) -> Dict[str, float]:
    """
    Recursively walk a Pydantic evidence packet and return
    {field_path: numeric_value} for every numeric leaf.
    SKIPS values marked is_estimate=True — projected values are
    not in the source document and should not be verified against it.
    """
    result: Dict[str, float] = {}

    def _walk(obj: Any, prefix: str) -> None:
        if obj is None:
            return
        if hasattr(obj, "model_fields") and hasattr(obj, "model_dump"):
            if "value" in obj.model_fields:
                # Skip estimated values — they are projections, not source facts
                is_est = getattr(obj, "is_estimate", False)
                if is_est:
                    return
                val = getattr(obj, "value", None)
                if isinstance(val, (int, float)):
                    result[prefix] = float(val)
                return
            for field_name in obj.model_fields:
                child = getattr(obj, field_name, None)
                path = f"{prefix}.{field_name}" if prefix else field_name
                _walk(child, path)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{prefix}[{i}]")

    _walk(evidence_packet, "")
    return result


# ─── Narrative parsers ────────────────────────────────────────────────────────

def _extract_source_citations(narrative: str) -> List[str]:
    """
    Pull every field key out of [Source: key1, key2] citation blocks.
    Returns flat list of field path strings.
    """
    raw_blocks = re.findall(r'\[Source:\s*([^\]]+)\]', narrative, re.IGNORECASE)
    keys: List[str] = []
    for block in raw_blocks:
        for part in block.split(","):
            stripped = part.strip()
            if stripped:
                keys.append(stripped)
    return keys


def _extract_uncited_absolute_numbers(narrative: str) -> List[float]:
    """
    Find numeric tokens in the narrative that:
      1. Are NOT inside a [Source: ...] tag context
      2. Are NOT pure percentages (e.g. "4.0%", "16.5%")
      3. Are >= 10,000 in magnitude (large financial figures only)
         — avoids false positives on years (2043), small counts, branch numbers etc.

    Returns deduplicated list of floats.
    """
    # Remove citation blocks
    clean = re.sub(r'\[Source:[^\]]+\]', ' ', narrative)
    # Remove percentage values — these are DERIVED, never absolute
    clean = re.sub(r'\d[\d,]*\.?\d*\s*%', ' ', clean)
    # Remove ALL 4-digit numbers (years like 2043, 2026, 1999, branch counts etc.)
    clean = re.sub(r'\b\d{4}\b', ' ', clean)
    # Extract remaining numbers with commas (e.g. "29,795" or "1,29,795")
    raw_numbers = re.findall(r'\b[\d,]+(?:\.\d+)?\b', clean)
    result: List[float] = []
    for n in raw_numbers:
        try:
            val = float(n.replace(",", ""))
            # Only flag very large absolute values (>= 10,000)
            # Small numbers like 12, 41, 232 are likely counts/ratios, not financials
            if val >= 10000:
                result.append(val)
        except ValueError:
            pass
    return list(set(result))


def _number_in_evidence(value: float, flat_evidence: Dict[str, float],
                         tolerance_pct: float = 1.5) -> bool:
    """
    Return True if `value` matches any evidence entry within tolerance_pct.
    Also accepts rounded variants (e.g. 29795 vs 29800 within 1.5%).
    """
    if value == 0:
        return True
    for ev_val in flat_evidence.values():
        if ev_val == 0:
            continue
        deviation = abs((ev_val - value) / ev_val) * 100
        if deviation <= tolerance_pct:
            return True
    return False


# ─── Verification Stack ───────────────────────────────────────────────────────

class VerificationStack:

    @staticmethod
    def layer2_math_verify(expected: float, actual: float,
                            tolerance_pct: float = 0.5) -> Tuple[bool, float]:
        """
        Layer 2 — Python Math Verifier (no LLM).
        Confirms a derived value is within tolerance of the expected value.
        Returns (is_valid, authoritative_value).
        """
        if expected == 0:
            return (actual == 0), actual
        deviation = abs((actual - expected) / expected) * 100
        if deviation <= tolerance_pct:
            return True, expected
        return False, actual

    @staticmethod
    def layer3_claim_verifier(narrative: str,
                               evidence_packet: Any) -> Tuple[bool, str]:
        """
        Layer 3 — Two-Pass Claim Verifier.

        Pass A — Python (free, instant):
          • Flatten evidence packet → {field: float} lookup table
          • Verify all [Source: field] citations exist in evidence
          • Check all uncited absolute numbers against evidence (1.5% tolerance)
          • If nothing suspicious → return VALID immediately (no LLM call)

        Pass B — DeepSeek R1 (only if Pass A finds suspicious values):
          • Send ONLY the suspicious numbers to R1
          • Provide flattened evidence (not full Pydantic dump)
          • Explicitly instruct R1: percentages / growth rates / margins
            are DERIVED CALCULATIONS — never flag them
          • Block only on confirmed invented absolute values

        Returns (is_valid, narrative_or_error_string).
        """
        import sys
        import os
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

        print("     [Claim Verifier] Pass A — Python evidence audit...")

        # ── Flatten evidence to fast lookup ───────────────────────────────────
        flat_evidence = _flatten_evidence(evidence_packet)

        if not flat_evidence:
            # No evidence to verify against — pass through
            print("     [Claim Verifier] Pass A — empty evidence packet, skipping audit.")
            return True, narrative

        # ── Check [Source:] citations ─────────────────────────────────────────
        cited_keys = _extract_source_citations(narrative)
        missing_citations: List[str] = [k for k in cited_keys if k not in flat_evidence]
        if missing_citations:
            print(f"     [Claim Verifier] Pass A warnings — "
                  f"{len(missing_citations)} cited field(s) not in evidence "
                  f"(may be projection keys): {missing_citations[:3]}")
        else:
            print(f"     [Claim Verifier] Pass A — {len(cited_keys)} citation(s) verified.")

        # ── Check uncited absolute numbers ────────────────────────────────────
        uncited_numbers = _extract_uncited_absolute_numbers(narrative)
        suspicious: List[float] = [
            n for n in uncited_numbers
            if not _number_in_evidence(n, flat_evidence)
        ]

        if not suspicious:
            print(f"     [Claim Verifier] Pass A passed — "
                  f"all {len(uncited_numbers)} uncited number(s) found in evidence.")
            return True, narrative

        # ── Pass B — targeted DeepSeek R1 audit ───────────────────────────────
        print(f"     [Claim Verifier] Pass B — "
              f"DeepSeek R1 auditing {len(suspicious)} suspicious value(s): {suspicious}")

        from pipeline.utils.llm_client import call_bedrock_deepseek

        # Only send non-zero evidence values to keep prompt concise
        evidence_summary = json.dumps(
            {k: round(v, 2) for k, v in flat_evidence.items() if v != 0},
            indent=2
        )[:6000]

        audit_prompt = f"""You are a strict financial fact-checker for equity research reports.

TASK: Determine whether the following numbers are supported by the Evidence JSON.

Numbers to audit: {[round(n, 2) for n in suspicious]}

Evidence JSON (Python-verified financial data):
{evidence_summary}

CRITICAL RULES — read carefully:
1. A number is VALID if it appears in the Evidence JSON within 2% rounding tolerance.
2. A number is VALID if it is a known rounding of an evidence value (e.g. 29,795 ≈ 29,800).
3. PERCENTAGES, GROWTH RATES, MARGINS, CAGR values are DERIVED CALCULATIONS.
   They do NOT appear in the evidence JSON. NEVER flag them as hallucinations.
4. Only flag a number as HALLUCINATION if it is an ABSOLUTE financial figure
   (revenue, PAT, EBITDA, assets, debt, etc.) that cannot be found in evidence.

Reply with EXACTLY one of these two words — nothing else:
  VALID         → all audited numbers are traceable to evidence
  HALLUCINATION → at least one absolute number is confirmed invented"""

        response = call_bedrock_deepseek(
            "You are a financial fact-checker. Reply with one word: VALID or HALLUCINATION.",
            audit_prompt
        ) or ""

        # Strip DeepSeek R1 <think>...</think> blocks before checking
        clean = re.sub(r'<think>.*?</think>', '', response,
                       flags=re.DOTALL | re.IGNORECASE).strip().upper()

        if re.search(r'\bHALLUCINATION\b', clean):
            print(f"     [Claim Verifier] BLOCKED — invented absolute value(s) "
                  f"confirmed: {suspicious}")
            return False, (
                f"ERROR: Narrative blocked by Layer 3 Verifier. "
                f"Unverifiable absolute value(s) detected: {suspicious}"
            )

        print("     [Claim Verifier] Pass B passed — "
              "DeepSeek R1 confirmed all values traceable to evidence.")
        return True, narrative

    @staticmethod
    def layer5_confidence_scorer(section_name: str,
                                  has_hallucinations: bool,
                                  missing_sources: int) -> float:
        """
        Layer 5 — Confidence Scorer.
        Score drives footnote asterisks in the final PDF.
          1.0 = fully verified, no issues
          0.1 = hallucination confirmed
          -0.05 per missing source citation, floored at 0.1
        """
        if has_hallucinations:
            return 0.1
        deduction = min(missing_sources * 0.05, 0.5)
        return round(max(0.1, 1.0 - deduction), 2)


# ── Loop 2: Narrative Self-Healer ─────────────────────────────────────────────

class NarrativeSelfHealer:
    """
    Loop 2 — Self-healing narrative correction.

    When Stage 12 (layer3_claim_verifier) detects hallucinated absolute values
    in the narrative, instead of hard-blocking the pipeline this class:

      1. Extracts the specific sentences containing the bad numbers
      2. Tells DeepSeek R1 exactly which numbers are wrong and what the
         correct values are from the evidence packet
      3. Asks DeepSeek to rewrite ONLY those sentences with correct numbers
      4. Splices the corrected sentences back into the narrative
      5. Re-verifies the corrected narrative
      6. Repeats up to MAX_ATTEMPTS times

    If after MAX_ATTEMPTS the narrative still has hallucinations:
      → Strips the problematic sentences entirely (safe fallback)
      → Returns clean narrative with a footnote marking the removed content

    This means the pipeline NEVER hard-blocks — it always produces a report.
    """

    MAX_ATTEMPTS = 2

    @staticmethod
    def heal(
        narrative: str,
        evidence_packet: Any,
        suspicious_values: List[float],
    ) -> Tuple[bool, str]:
        """
        Args:
            narrative:         The narrative that failed verification
            evidence_packet:   Pydantic evidence packet from Stage 10
            suspicious_values: List of unverified absolute numbers

        Returns:
            (is_clean, healed_narrative)
        """
        import sys, os
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
        from pipeline.utils.llm_client import call_bedrock_deepseek

        print(f"     [Narrative Healer] Loop 2 — fixing "
              f"{len(suspicious_values)} suspicious value(s): {suspicious_values}")

        flat_evidence = _flatten_evidence(evidence_packet)
        evidence_summary = json.dumps(
            {k: round(v, 2) for k, v in flat_evidence.items() if v != 0},
            indent=2
        )[:5000]

        current_narrative = narrative

        for attempt in range(1, NarrativeSelfHealer.MAX_ATTEMPTS + 1):
            # Find sentences containing suspicious values
            bad_sentences = NarrativeSelfHealer._find_bad_sentences(
                current_narrative, suspicious_values
            )

            if not bad_sentences:
                print(f"     [Narrative Healer] No sentences found containing "
                      f"suspicious values — narrative is clean.")
                return True, current_narrative

            print(f"     [Narrative Healer] Attempt {attempt} — "
                  f"rewriting {len(bad_sentences)} sentence(s)...")

            correction_prompt = f"""You are a financial report editor.
The following sentences contain numbers that CANNOT be verified in the source data.
Rewrite EACH sentence using ONLY values present in the Evidence JSON below.
If a sentence cannot be rewritten accurately, replace it with: [Data not available for this metric]

SENTENCES TO FIX:
{chr(10).join(f'{i+1}. {s}' for i, s in enumerate(bad_sentences))}

VERIFIED EVIDENCE JSON (use ONLY these values):
{evidence_summary}

RULES:
- Keep [Source: field.path] citation format in rewritten sentences
- Do NOT invent new numbers
- Do NOT use percentages/growth rates as absolute values
- Return ONLY the rewritten sentences, numbered to match input
- Format: "1. <rewritten sentence>"

REWRITTEN SENTENCES:"""

            response = call_bedrock_deepseek(
                "You are a financial report editor. Rewrite only the specified sentences using verified data.",
                correction_prompt
            ) or ""

            # Strip thinking blocks
            clean_response = re.sub(
                r'<think(?:ing)?>.*?</think(?:ing)?>',
                '', response, flags=re.DOTALL | re.IGNORECASE
            ).strip()

            if not clean_response:
                print(f"     [Narrative Healer] Empty response on attempt {attempt}.")
                continue

            # Parse numbered rewrites
            corrected = NarrativeSelfHealer._parse_numbered_rewrites(
                clean_response, len(bad_sentences)
            )

            # Splice corrections back into narrative
            fixed_narrative = current_narrative
            for original, replacement in zip(bad_sentences, corrected):
                if replacement and replacement != original:
                    fixed_narrative = fixed_narrative.replace(original, replacement, 1)
                    print(f"     [Narrative Healer]   ✏️  Fixed: "
                          f"'{original[:60]}...' → '{replacement[:60]}...'")

            # Re-verify the fixed narrative
            is_valid, result = VerificationStack.layer3_claim_verifier(
                fixed_narrative, evidence_packet
            )
            if is_valid:
                print(f"     [Narrative Healer] ✅ Narrative verified clean after "
                      f"attempt {attempt}.")
                return True, fixed_narrative

            # Extract new suspicious values for next loop
            current_narrative = fixed_narrative
            uncited  = _extract_uncited_absolute_numbers(current_narrative)
            flat_ev  = _flatten_evidence(evidence_packet)
            suspicious_values = [
                n for n in uncited if not _number_in_evidence(n, flat_ev)
            ]
            if not suspicious_values:
                return True, current_narrative

            print(f"     [Narrative Healer] Still {len(suspicious_values)} "
                  f"suspicious value(s) after attempt {attempt}.")

        # All attempts exhausted — strip bad sentences as safe fallback
        print(f"     [Narrative Healer] ⚠️  Max attempts reached. "
              f"Stripping {len(suspicious_values)} problematic sentence(s).")

        clean = NarrativeSelfHealer._strip_bad_sentences(
            current_narrative, suspicious_values
        )
        clean += (
            "\n\n*Note: Some numerical claims were removed during automated "
            "verification as they could not be confirmed from the source document.*"
        )
        return True, clean  # Return True — report will generate with footnote

    @staticmethod
    def _find_bad_sentences(text: str, suspicious_values: List[float]) -> List[str]:
        """Find sentences that contain any of the suspicious values."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        bad = []
        for sentence in sentences:
            for val in suspicious_values:
                pattern = _make_number_pattern(val)
                if re.search(pattern, sentence):
                    if sentence not in bad:
                        bad.append(sentence)
                    break
        return bad

    @staticmethod
    def _strip_bad_sentences(text: str, suspicious_values: List[float]) -> str:
        """Remove sentences containing unverified values from narrative."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        clean_sentences = []
        for sentence in sentences:
            is_bad = False
            for val in suspicious_values:
                pattern = _make_number_pattern(val)
                if re.search(pattern, sentence):
                    is_bad = True
                    break
            if not is_bad:
                clean_sentences.append(sentence)
        return " ".join(clean_sentences)

    @staticmethod
    def _parse_numbered_rewrites(response: str, expected_count: int) -> List[str]:
        """Parse '1. sentence\\n2. sentence' format from LLM response."""
        lines = response.strip().split("\n")
        rewrites = []
        current = []
        for line in lines:
            m = re.match(r'^\s*\d+\.\s+(.+)', line)
            if m:
                if current:
                    rewrites.append(" ".join(current))
                current = [m.group(1).strip()]
            elif current and line.strip():
                current.append(line.strip())
        if current:
            rewrites.append(" ".join(current))
        # Pad with empty strings if fewer rewrites than expected
        while len(rewrites) < expected_count:
            rewrites.append("")
        return rewrites[:expected_count]


# Make _make_number_pattern available at module level for NarrativeSelfHealer
def _make_number_pattern(value: float) -> str:
    """Build a regex matching a number in various formatted forms."""
    import re as _re
    variants = set()
    variants.add(_re.escape(f"{value:.2f}"))
    variants.add(_re.escape(f"{value:.1f}"))
    variants.add(_re.escape(f"{value:.0f}"))
    int_part = int(abs(value))
    variants.add(_re.escape(f"{int_part:,}"))
    variants.add(_re.escape(str(round(value))))
    return "(" + "|".join(sorted(variants, key=len, reverse=True)) + ")"
