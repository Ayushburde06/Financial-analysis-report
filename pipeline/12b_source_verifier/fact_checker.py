"""
Stage 12b: Source Verifier — Automated Fact-Checker

What it does:
  For every numeric value Mistral extracted into raw_financials JSON,
  scan the raw OCR text from Azure Document Intelligence and confirm
  that number actually appears in the source document.

How it works:
  1. Flatten raw_financials → [(field_path, value), ...]
  2. For each value, search OCR text for it within 1% tolerance
     using a regex that handles:
       - Indian comma formatting  (1,23,456.78)
       - Decimal variants         (123.4 vs 123.40)
       - Rounding                 (123.59 vs 124)
       - Billion / Crore units    (no conversion — just number match)
  3. Build a VerificationReport:
       verified:   [(field, value, matched_text_snippet)]
       unverified: [(field, value, "NOT FOUND in source")]
       score:      verified_count / total_count  (0.0–1.0)
  4. Return the report — pipeline logs it, ROM adds it to PDF

Tolerance: 1.0%
  - Handles rounding differences between how the PDF formats numbers
    and what Mistral extracted (e.g. 123.59 vs 123.6)
  - Does NOT accept large deviations — a value like 999 can't match 1200

No LLM used — pure Python regex. Free, instant, deterministic.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class FieldVerification:
    field_path:   str
    extracted:    float
    found:        bool
    snippet:      str   # surrounding text where the number was found (or "NOT FOUND")
    matched_val:  Optional[float] = None   # actual value found in OCR (may differ slightly)


@dataclass
class FactCheckReport:
    verified:       List[FieldVerification] = field(default_factory=list)
    unverified:     List[FieldVerification] = field(default_factory=list)
    score:          float = 0.0            # verified / total
    total:          int   = 0
    verified_count: int   = 0
    blocked:        bool  = False          # True if score < BLOCK_THRESHOLD
    summary:        str   = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score":          round(self.score, 3),
            "verified_count": self.verified_count,
            "total":          self.total,
            "blocked":        self.blocked,
            "summary":        self.summary,
            "verified": [
                {"field": v.field_path, "value": v.extracted, "snippet": v.snippet[:120],
                 "source_page": _source_page(v.snippet), "source_context": _source_context(v.snippet)}
                for v in self.verified
            ],
            "unverified": [
                {"field": v.field_path, "value": v.extracted, "snippet": v.snippet,
                 "source_page": _source_page(v.snippet), "source_context": _source_context(v.snippet)}
                for v in self.unverified
            ],
        }


# ── Configuration ──────────────────────────────────────────────────────────────

TOLERANCE_PCT   = 1.0    # ±1% tolerance for rounding differences
BLOCK_THRESHOLD = 0.50   # if < 50% verified → block report (likely bad extraction)
SKIP_THRESHOLD  = 50     # skip values below this — too common to be meaningful (e.g. 1, 5, 12, 25)
CONTEXT_CHARS   = 240    # preserve nearby page/table markers for provenance


# ── Helpers ────────────────────────────────────────────────────────────────────

def _flatten_raw(raw_financials: Dict[str, Any]) -> List[Tuple[str, float]]:
    """
    Flatten raw_financials JSON into a list of (field_path, numeric_value).
    Skips nulls and zero values.
    Only keeps values >= SKIP_THRESHOLD to avoid false positives on small numbers.

    Example:
        {"nii": {"fy25": 811.65, "q_current": 215.29, ...}, ...}
        → [("nii.fy25", 811.65), ("nii.q_current", 215.29), ...]
    """
    result: List[Tuple[str, float]] = []

    def _walk(obj: Any, prefix: str):
        if obj is None:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                path = f"{prefix}.{k}" if prefix else k
                _walk(v, path)
        elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
            val = float(obj)
            if val >= SKIP_THRESHOLD:
                result.append((prefix, val))
        elif isinstance(obj, str):
            try:
                val = float(obj.replace(",", "").strip())
                if val >= SKIP_THRESHOLD:
                    result.append((prefix, val))
            except ValueError:
                pass

    _walk(raw_financials, "")
    return result


def _within_tolerance(target: float, candidate: float) -> bool:
    """Return True if candidate is within TOLERANCE_PCT of target."""
    if target == 0:
        return candidate == 0
    return abs((candidate - target) / abs(target)) * 100 <= TOLERANCE_PCT


def _make_number_pattern(value: float) -> str:
    """
    Build a regex that matches the value in various formatted forms:
      811.65 → matches "811.65", "811.6", "812", "811,65", "811.650"
    Uses a flexible approach: match integers close to the value.
    """
    # Build variants to search for
    variants = set()

    # Exact float
    variants.add(re.escape(f"{value:.2f}"))
    variants.add(re.escape(f"{value:.1f}"))
    variants.add(re.escape(f"{value:.0f}"))

    # With Indian comma formatting (e.g. 1,234.56 or 1,23,456)
    int_part = int(abs(value))
    variants.add(re.escape(f"{int_part:,}"))

    # Rounded up/down
    variants.add(re.escape(str(round(value))))

    # Join as alternation
    return "(" + "|".join(sorted(variants, key=len, reverse=True)) + ")"


def _search_ocr(value: float, ocr_text: str) -> Tuple[bool, str, Optional[float]]:
    """
    Search OCR text for a number matching `value` within tolerance.

    Strategy:
      1. Build regex for the exact value and common roundings
      2. Find all numeric tokens in OCR text within ±TOLERANCE_PCT
      3. Return (found, snippet, matched_value)
    """
    pattern = _make_number_pattern(value)

    # Try exact pattern match first
    for m in re.finditer(pattern, ocr_text):
        try:
            matched_val = float(m.group(0).replace(",", ""))
            if _within_tolerance(value, matched_val):
                start = max(0, m.start() - CONTEXT_CHARS)
                end   = min(len(ocr_text), m.end() + CONTEXT_CHARS)
                snippet = "..." + ocr_text[start:end].replace("\n", " ").strip() + "..."
                return True, snippet, matched_val
        except ValueError:
            pass

    # Fallback: scan all numbers in OCR text and check tolerance
    for m in re.finditer(r'\b[\d,]+(?:\.\d+)?\b', ocr_text):
        try:
            candidate = float(m.group(0).replace(",", ""))
            if candidate < SKIP_THRESHOLD * 0.5:
                continue
            if _within_tolerance(value, candidate):
                start = max(0, m.start() - CONTEXT_CHARS)
                end   = min(len(ocr_text), m.end() + CONTEXT_CHARS)
                snippet = "..." + ocr_text[start:end].replace("\n", " ").strip() + "..."
                return True, snippet, candidate
        except ValueError:
            pass

    return False, "NOT FOUND in source document", None


def _source_page(snippet: str) -> Optional[int]:
    """Recover page number from OCR markers retained in verification snippets."""
    match = re.search(
        r"(?:SOURCE PAGE|PAGE_BREAK page=|Page\s+)\s*(\d+)",
        snippet or "", re.IGNORECASE,
    )
    return int(match.group(1)) if match else None


def _source_context(snippet: str) -> str:
    """Best-effort table/section label for human review."""
    text = (snippet or "").lower()
    for label in ("balance sheet", "cash flow", "cashflow", "profit and loss",
                  "statement of profit", "quarterly", "shareholding", "valuation"):
        if label in text:
            return label.title()
    return ""


# ── Main verifier ──────────────────────────────────────────────────────────────

class SourceFactChecker:
    """
    Stage 12b: Source Verifier.

    Usage:
        report = SourceFactChecker.verify(raw_financials, ocr_text)
        print(f"Score: {report.score:.0%} ({report.verified_count}/{report.total})")
    """

    @staticmethod
    def verify(
        raw_financials: Dict[str, Any],
        ocr_text: str,
        source_value_factor: float = 1.0,
    ) -> FactCheckReport:
        """
        Verify every extracted value against the OCR source text.

        Args:
            raw_financials: The JSON dict returned by Stage 08 (Mistral extraction)
            ocr_text:       Full OCR text from Azure Document Intelligence (Stage 01)

        Returns:
            FactCheckReport with score, verified/unverified lists, and block flag
        """
        print("     [Fact Checker] Stage 12b — Source verification starting...")

        if not ocr_text or not ocr_text.strip():
            print("     [Fact Checker] WARNING: Empty OCR text — skipping verification.")
            return FactCheckReport(
                score=1.0, total=0, verified_count=0, blocked=False,
                summary="Skipped — no OCR text available.",
            )

        if not raw_financials:
            print("     [Fact Checker] WARNING: Empty raw_financials — skipping.")
            return FactCheckReport(
                score=1.0, total=0, verified_count=0, blocked=False,
                summary="Skipped — no extracted financials to verify.",
            )

        # Flatten extracted values
        flat_values = _flatten_raw(raw_financials)

        if not flat_values:
            print("     [Fact Checker] No numeric values >= threshold found.")
            return FactCheckReport(
                score=1.0, total=0, verified_count=0, blocked=False,
                summary="No verifiable values found (all below threshold).",
            )

        verified_list:   List[FieldVerification] = []
        unverified_list: List[FieldVerification] = []

        factor = float(source_value_factor or 1.0)
        for field_path, value in flat_values:
            source_value = value / factor if factor not in (0.0, 1.0) else value
            found, snippet, matched_val = _search_ocr(source_value, ocr_text)
            fv = FieldVerification(
                field_path=field_path,
                extracted=value,
                found=found,
                snippet=snippet,
                matched_val=matched_val,
            )
            if found:
                verified_list.append(fv)
            else:
                unverified_list.append(fv)

        total          = len(flat_values)
        verified_count = len(verified_list)
        score          = verified_count / total if total > 0 else 1.0
        blocked        = score < BLOCK_THRESHOLD

        # Build human-readable summary
        summary = (
            f"{verified_count}/{total} extracted values verified in source document "
            f"({score:.0%} confidence)."
        )
        if unverified_list:
            unverified_fields = ", ".join(v.field_path for v in unverified_list[:5])
            summary += f" Unverified fields: {unverified_fields}"
            if len(unverified_list) > 5:
                summary += f" (+{len(unverified_list)-5} more)"
            summary += "."

        if blocked:
            summary += " [WARNING] BELOW THRESHOLD - report may contain inaccurate data."
        else:
            summary += " [OK] Extraction verified."

        # Log results
        print(f"     [Fact Checker] Score: {verified_count}/{total} = {score:.0%}")
        for v in verified_list:
            print(f"     [Fact Checker]   [OK] {v.field_path} = {v.extracted}"
                  + (f" (matched {v.matched_val})" if v.matched_val != v.extracted else ""))
        for v in unverified_list:
            print(f"     [Fact Checker]   [FAIL] {v.field_path} = {v.extracted} - NOT FOUND")

        if blocked:
            print(f"     [Fact Checker] [WARNING] Score {score:.0%} below block threshold "
                  f"({BLOCK_THRESHOLD:.0%}). Report flagged.")
        else:
            print(f"     [Fact Checker] [OK] Source verification passed.")

        return FactCheckReport(
            verified=verified_list,
            unverified=unverified_list,
            score=score,
            total=total,
            verified_count=verified_count,
            blocked=blocked,
            summary=summary,
        )


# ── Loop 1: Extraction Self-Healer ────────────────────────────────────────────

class ExtractionSelfHealer:
    """
    Loop 1 — Self-healing extraction.

    When Stage 12b finds unverified fields (values not in OCR source),
    this class:
      1. Identifies which field.period combinations failed
      2. Builds a targeted re-extraction prompt asking Mistral to
         look specifically for those fields in the OCR text
      3. Runs Mistral and merges corrected values back into raw_financials
      4. Re-verifies the merged data
      5. Repeats up to MAX_ATTEMPTS times

    After MAX_ATTEMPTS: sets unverified fields to null (don't invent data).
    Never invents data — only accepts values found in OCR text.
    """

    MAX_ATTEMPTS = 3

    @staticmethod
    def heal(
        raw_financials: Dict[str, Any],
        ocr_text: str,
        initial_report: "FactCheckReport",
        sector: str = "Other",
    ) -> tuple:
        """
        Args:
            raw_financials:  Original extracted JSON from Stage 08
            ocr_text:        Full OCR text from Stage 01
            initial_report:  FactCheckReport from first verification pass
            sector:          Detected sector string

        Returns:
            (healed_raw_financials, final_fact_check_report)
        """
        import sys, os
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../..")))

        report = initial_report
        current_data = dict(raw_financials)

        if not report.unverified:
            return current_data, report

        print(f"     [Self-Healer] Loop 1 — {len(report.unverified)} unverified "
              f"field(s) found. Starting self-healing...")

        from pipeline.utils.llm_client import call_bedrock_mistral_large

        for attempt in range(1, ExtractionSelfHealer.MAX_ATTEMPTS + 1):
            unverified = report.unverified
            if not unverified:
                print(f"     [Self-Healer] [OK] All fields verified after attempt {attempt-1}.")
                break

            # Build targeted list of what to re-extract
            # Group by field name (e.g. "installed_capacity_mw") and collect periods
            field_periods: Dict[str, List[str]] = {}
            for fv in unverified:
                parts = fv.field_path.split(".")
                if len(parts) >= 2:
                    field_name = parts[0]
                    period     = parts[1]
                    field_periods.setdefault(field_name, []).append(period)
                else:
                    field_periods[fv.field_path] = ["all"]

            # Build targeted extraction prompt
            targets = []
            for fname, periods in field_periods.items():
                targets.append(f"- {fname}: specifically for periods {', '.join(periods)}")
            target_str = "\n".join(targets)

            # Focused OCR context — first 30k chars (tables are usually early)
            focused_text = ocr_text[:30000]

            system_prompt = f"""You are a financial data extractor. 
Previous extraction missed these fields. Re-scan the document carefully and extract ONLY these specific values.
Return a JSON object with ONLY the fields listed below.
Use null if a value is genuinely not present — never invent numbers.

MISSING FIELDS TO RE-EXTRACT:
{target_str}

PERIOD KEY MAPPING:
  fy22, fy23, fy24, fy25 → full fiscal year actuals
  fy26e, fy27e           → forward estimates (analyst projections)  
  q_prev_year            → same quarter prior year
  q_prev_qtr             → immediately preceding quarter
  q_current              → latest reported quarter

Return ONLY a JSON object. Example:
{{"installed_capacity_mw": {{"fy26e": null, "q_current": 13211}}}}"""

            print(f"     [Self-Healer] Attempt {attempt}/{ExtractionSelfHealer.MAX_ATTEMPTS} "
                  f"— re-extracting {len(field_periods)} field(s): "
                  f"{list(field_periods.keys())}")

            response = call_bedrock_mistral_large(system_prompt, focused_text)
            if not response:
                print(f"     [Self-Healer] Empty response on attempt {attempt}. Skipping.")
                continue

            # Parse correction JSON
            import json, re as _re
            correction = {}
            cleaned = _re.sub(r'```(?:json)?\s*|\s*```', '', response).strip()
            try:
                correction = json.loads(cleaned)
            except (json.JSONDecodeError, ValueError):
                m = _re.search(r'\{.*\}', cleaned, _re.DOTALL)
                if m:
                    try:
                        correction = json.loads(m.group(0))
                    except (json.JSONDecodeError, ValueError):
                        pass

            if not correction:
                print(f"     [Self-Healer] Could not parse correction JSON on attempt {attempt}.")
                continue

            # Merge corrections into current_data
            merged_count = 0
            for field_name, period_dict in correction.items():
                if not isinstance(period_dict, dict):
                    continue
                if field_name not in current_data:
                    current_data[field_name] = {}
                for period, value in period_dict.items():
                    if value is not None:
                        old_val = current_data[field_name].get(period)
                        current_data[field_name][period] = value
                        if old_val != value:
                            print(f"     [Self-Healer]   📝 {field_name}.{period}: "
                                  f"{old_val} → {value}")
                            merged_count += 1

            if merged_count == 0:
                print(f"     [Self-Healer] No new values found on attempt {attempt}.")
                # If Mistral can't find it after 2 tries, nullify the unverified fields
                if attempt >= 2:
                    print(f"     [Self-Healer] Nullifying {len(unverified)} "
                          f"unverified field(s) — cannot confirm from source.")
                    for fv in unverified:
                        parts = fv.field_path.split(".")
                        if len(parts) >= 2:
                            fname, period = parts[0], parts[1]
                            if fname in current_data and isinstance(current_data[fname], dict):
                                current_data[fname][period] = None
                    break
                continue

            # Re-verify with corrected data
            print(f"     [Self-Healer] Re-verifying after {merged_count} correction(s)...")
            report = SourceFactChecker.verify(current_data, ocr_text)

            if not report.unverified:
                print(f"     [Self-Healer] [OK] All fields verified after attempt {attempt}!")
                break

            print(f"     [Self-Healer] Still {len(report.unverified)} unverified after "
                  f"attempt {attempt}.")

        if report.unverified:
            print(f"     [Self-Healer] [WARNING] {len(report.unverified)} field(s) remain "
                  f"unverified after {ExtractionSelfHealer.MAX_ATTEMPTS} attempts. "
                  f"Nullifying them before proceeding.")
            for fv in report.unverified:
                parts = fv.field_path.split(".")
                if len(parts) >= 2:
                    fname, period = parts[0], parts[1]
                    if fname in current_data and isinstance(current_data[fname], dict):
                        current_data[fname][period] = None
            report = SourceFactChecker.verify(current_data, ocr_text)

        return current_data, report
