"""
Stage 12d: Unit Normalizer — Source Unit Detection & Conversion

What it does:
  Some source documents report financials in "Rs. Million" (e.g. LTTS, POCL)
  while others report in "Rs. Crore" (e.g. JSW Energy). The extraction (Mistral)
  picks up raw numbers without unit context. If the source uses millions but the
  pipeline treats values as crores, every number is 10x inflated.

  This module:
    1. Scans the OCR text for unit indicators ("Rs. Million", "Rs. Crore", etc.)
    2. Determines the dominant reporting unit
    3. If millions → converts all raw_financials values to crores (÷10)
    4. Logs the conversion for transparency
    5. Returns corrected raw_financials + a report

  Runs AFTER Stage 12b (fact-check) so the fact-check validates raw numbers
  against the source, and BEFORE Stage 10 evidence rebuild so downstream uses
  corrected values.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class UnitReport:
    detected_unit:  str = "crore"   # "crore", "million", or "unknown"
    conversion_factor: float = 1.0  # multiply extracted values by this
    values_converted: int = 0
    summary: str = ""
    sample_snippets: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected_unit": self.detected_unit,
            "conversion_factor": self.conversion_factor,
            "values_converted": self.values_converted,
            "summary": self.summary,
        }


# Counts / ratios / per-share metrics must never be scaled million→crore.
_NON_MONETARY_KEYS = {
    "headcount", "employees", "employee_count", "eps", "diluted_eps",
    "basic_eps", "book_value", "bvps", "nim", "gnpa", "nnpa", "pcr",
    "casa_ratio", "roe", "roa", "roce", "capital_adequacy", "credit_growth",
    "ebitda_margin", "pat_margin", "net_margin", "gross_margin", "pe", "pb",
    "ev_ebitda", "beta", "dividend_yield", "free_float", "shares_outstanding",
    "outstanding_shares", "face_value",
}


def is_non_monetary_metric(key: str) -> bool:
    """True for counts, ratios, margins, and per-share fields."""
    k = str(key or "").lower().split(".")[0]
    if k in _NON_MONETARY_KEYS:
        return True
    return any(token in k for token in (
        "margin", "ratio", "growth", "yield", "per_share", "headcount", "employee",
    ))


def _detect_unit(ocr_text: str) -> Tuple[str, float, list]:
    """
    Scan OCR text for unit indicators in financial table headers.
    Returns (unit_name, conversion_factor, sample_snippets).

    Detection priority:
      1. Table header patterns like "(Rs. Million)", "(in Rs. Crore)", "Rs. Million"
      2. Count occurrences of "million" vs "crore" near financial keywords
      3. Default to "crore" (most common in Indian filings)
    """
    if not ocr_text:
        return "unknown", 1.0, []

    text_lower = ocr_text.lower()

    # Pattern: look for unit indicators near table headers / financial context
    # e.g. "Particulars (Rs. Million)", "(in Rs. Crore)", "Rs. Million", "₹ Million"
    million_patterns = [
        r"rs\.?\s*million",
        r"inr\s*million",
        r"₹\s*million",
        r"rs\s*mill",
        r"\(in\s*million",
        r"particulars.*million",
    ]
    crore_patterns = [
        r"rs\.?\s*crore",
        r"inr\s*crore",
        r"₹\s*crore",
        r"rs\s*cr\b",
        r"\(in\s*crore",
        r"particulars.*crore",
    ]

    million_count = 0
    crore_count = 0
    million_snippets = []

    for pat in million_patterns:
        for m in re.finditer(pat, text_lower):
            million_count += 1
            if len(million_snippets) < 3:
                start = max(0, m.start() - 20)
                end = min(len(text_lower), m.end() + 20)
                million_snippets.append(ocr_text[start:end].replace("\n", " ").strip())

    for pat in crore_patterns:
        for m in re.finditer(pat, text_lower):
            crore_count += 1

    # Decision: if "million" appears in table-header context more than "crore",
    # the source reports in millions → convert to crores (÷10)
    if million_count > 0 and million_count >= crore_count:
        return "million", 0.1, million_snippets
    elif crore_count > 0:
        return "crore", 1.0, []
    else:
        return "unknown", 1.0, []


def _apply_conversion(raw_financials: Dict[str, Any], factor: float) -> int:
    """
    Multiply all numeric values in raw_financials by the conversion factor.
    Returns the count of values converted.
    """
    count = 0

    def _convert(obj):
        nonlocal count
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            if obj != 0:
                count += 1
            return obj * factor
        if isinstance(obj, str):
            try:
                val = float(obj.replace(",", "").strip())
                if val != 0:
                    count += 1
                return str(val * factor)
            except ValueError:
                return obj
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(v) for v in obj]
        return obj

    return count  # count is set by side effect in _convert


def normalize_units(raw_financials: Dict[str, Any], ocr_text: str) -> Tuple[Dict[str, Any], UnitReport]:
    """
    Detect source unit and convert raw_financials to crores if needed.

    Args:
        raw_financials: The JSON dict from Stage 08 extraction
        ocr_text:       Full OCR text from Stage 01

    Returns:
        (corrected_raw_financials, UnitReport)
    """
    print("     [Unit Normalizer] Stage 12d — Detecting source reporting unit...")

    unit, factor, snippets = _detect_unit(ocr_text)

    report = UnitReport(
        detected_unit=unit,
        conversion_factor=factor,
        sample_snippets=snippets,
    )

    if factor == 1.0:
        report.summary = f"Source reports in '{unit}' — no conversion needed."
        print(f"     [Unit Normalizer] Detected unit: {unit} — no conversion needed.")
        return raw_financials, report

    # Apply conversion — never scale non-monetary metrics (counts, ratios, per-share).
    import copy
    corrected = copy.deepcopy(raw_financials)

    def _convert_obj(obj):
        nonlocal count
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, (int, float)):
            if obj != 0:
                count += 1
            return round(obj * factor, 4) if isinstance(obj, float) else obj * factor
        if isinstance(obj, str):
            try:
                val = float(obj.replace(",", "").strip())
                if val != 0:
                    count += 1
                return str(round(val * factor, 4))
            except ValueError:
                return obj
        if isinstance(obj, dict):
            return {k: _convert_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert_obj(v) for v in obj]
        return obj

    count = 0
    for key, value in list(corrected.items()):
        if is_non_monetary_metric(key):
            continue
        corrected[key] = _convert_obj(value)
    report.values_converted = count
    report.summary = (
        f"Source reports in '{unit}'. Converted {count} values to crores "
        f"(factor={factor}). Sample: {snippets[0] if snippets else 'N/A'}"
    )

    print(f"     [Unit Normalizer] Detected unit: {unit} → converting {count} values "
          f"to crores (×{factor})")
    if snippets:
        print(f"     [Unit Normalizer] Evidence: \"{snippets[0]}\"")

    return corrected, report
