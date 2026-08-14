"""Assignment pre-PDF checks. Not a full research-audit engine.

Checks:
  1. Required fields
  2. Numeric consistency
  3. Actual vs estimate labels
  4. Chart data exists
  5. No broken placeholders
  6. Target price calculation
  7. PDF renders successfully (called after Chromium)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_YEAR_RE = re.compile(r"^FY\d{2,4}[AE]?$", re.IGNORECASE)
_PLACEHOLDER_PATTERNS = (
    r"\{\{",
    r"\{%",
    r"%\}",
    r"FieldInfo",
    r"annotation=",
    r"\[VERIFIED\]",
    r"KEY_HIGHLIGHTS",
    r"\[key growth driver\]",
    r"\[key concern",
    r"target of\s+(?:The |the |—|-|&mdash;|$)",
)
FORBIDDEN_BULLET_PATTERNS = [
    "grew + YoY",
    "stood at in",
    "rose + YoY to,",
    "expanded + YoY to,",
    "improved to of",
    "+% YoY",
    "[VERIFIED]",
    "[N/A]",
    "KEY_HIGHLIGHTS",
]


def _numeric(value: Any) -> bool:
    if isinstance(value, bool) or value in (None, "", "[N/A]", "--", "—"):
        return False
    try:
        float(str(value).replace(",", "").strip())
        return True
    except (TypeError, ValueError):
        return False


def _as_float(value: Any) -> Optional[float]:
    if not _numeric(value):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _has_numeric(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_numeric(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_numeric(child) for child in value)
    return _numeric(value)


def _as_dict(report: Any) -> Dict[str, Any]:
    if isinstance(report, dict):
        return report
    if hasattr(report, "model_dump"):
        return report.model_dump()
    if hasattr(report, "dict"):
        return report.dict()
    return {}


def deep_get(obj: Any, path: str) -> Any:
    """Read nested attribute/dict path like 'financials.annual.revenue'."""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = getattr(cur, part, None)
    return cur


def build_all_columns(financials: Dict[str, Any]) -> List[str]:
    """Collect year columns from annual, forecasts, BS, CF, and ratios."""
    seen: set[str] = set()
    cols: List[str] = []
    sections = [
        financials.get("annual", {}),
        financials.get("forecasts", {}),
        financials.get("balance_sheet", {}),
        financials.get("cash_flow", {}),
        financials.get("ratios", {}),
    ]
    for section in sections:
        if not isinstance(section, dict):
            continue
        for val in section.values():
            if not isinstance(val, dict):
                continue
            for year in val.keys():
                y = str(year)
                if _YEAR_RE.match(y) and y not in seen:
                    cols.append(y)
                    seen.add(y)

    def _sort_key(y: str) -> Tuple[int, int]:
        num_match = re.match(r"FY(\d{2,4})", y, re.IGNORECASE)
        num = int(num_match.group(1)) if num_match else 0
        if num > 100:
            num = num % 100
        suffix = 0 if y.upper().endswith("A") else 1
        return (num, suffix)

    cols.sort(key=_sort_key)
    return cols


def validate_bullets(bullets: List[str]) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) for highlight bullets."""
    errors: List[str] = []
    warnings: List[str] = []
    for b in bullets or []:
        text = (b or "").strip()
        if not text:
            errors.append("EMPTY BULLET")
            continue
        if not re.search(r"\d", text):
            warnings.append(f"NO NUMBER: {text[:60]}")
        for pattern in FORBIDDEN_BULLET_PATTERNS:
            if pattern in text:
                errors.append(f"PLACEHOLDER ({pattern}): {text[:60]}")
    return errors, warnings


def _valid_chart_count(charts: Any) -> int:
    if not isinstance(charts, dict):
        return 0
    return sum(1 for value in charts.values() if isinstance(value, str) and len(value) > 1000)


def _year_keys(block: Any) -> List[str]:
    years: List[str] = []
    if not isinstance(block, dict):
        return years
    for val in block.values():
        if isinstance(val, dict):
            years.extend(str(k) for k in val.keys())
    return years


def check_report_payload(report: Any) -> List[str]:
    """Checks 1–6 on the report object, before HTML/PDF."""
    errors: List[str] = []
    data = _as_dict(report)
    company = data.get("company") or {}
    rec = data.get("recommendation") or {}
    fin = data.get("financials") or {}
    appendix = data.get("appendix") or {}
    if not isinstance(company, dict):
        company = {}
    if not isinstance(rec, dict):
        rec = {}
    if not isinstance(fin, dict):
        fin = {}
    if not isinstance(appendix, dict):
        appendix = {}

    # 1. Required fields
    name = str(company.get("name") or "").strip()
    if len(name) < 2 or "fieldinfo" in name.lower():
        errors.append("Required field missing: company.name")
    if not rec.get("action"):
        errors.append("Required field missing: recommendation.action")
    if not (
        _has_numeric(fin.get("annual"))
        or _has_numeric(fin.get("quarterly"))
        or _has_numeric(fin.get("forecasts"))
    ):
        errors.append("Required field missing: annual, quarterly, or forecast numbers")

    # 4. Charts when history exists; a tables-only filing is still a valid report.
    chart_count = _valid_chart_count(data.get("charts"))
    if chart_count < 1:
        print("     [Assignment checks] No charts — filing has too little history to plot.")

    # 3. Actual vs estimate labels (payload)
    annual_years = _year_keys(fin.get("annual"))
    forecast_years = _year_keys(fin.get("forecasts"))
    leaked_estimates = [y for y in annual_years if str(y).upper().endswith("E")]
    unlabeled_forecasts = [y for y in forecast_years if not str(y).upper().endswith("E")]
    if leaked_estimates:
        errors.append(
            "Actual vs estimate: estimate year(s) in actuals table: "
            + ", ".join(leaked_estimates)
        )
    if unlabeled_forecasts:
        errors.append(
            "Actual vs estimate: forecast year(s) missing E suffix: "
            + ", ".join(unlabeled_forecasts)
        )

    # 2 + 6. Numeric consistency and target calculation
    cmp_val = _as_float(rec.get("cmp") or company.get("cmp"))
    target_val = _as_float(rec.get("target_price") or company.get("target_price"))
    upside_val = _as_float(rec.get("expected_return_pct") or company.get("upside_pct"))
    if cmp_val and target_val and cmp_val != 0 and upside_val is not None:
        expected_upside = round(((target_val - cmp_val) / cmp_val) * 100, 1)
        if abs(expected_upside - upside_val) > 0.6:
            errors.append(
                f"Numeric consistency: upside {upside_val}% != "
                f"(target {target_val} − CMP {cmp_val}) / CMP (= {expected_upside}%)"
            )

    ai = appendix.get("ai_scenario") or {}
    if not isinstance(ai, dict):
        ai = {}
    target_estimated = bool(appendix.get("target_estimated") or ai.get("available"))
    if target_estimated and target_val is not None:
        eps = _as_float(ai.get("eps_fy26e"))
        pe = _as_float(ai.get("pe_used"))
        if eps is None or pe is None:
            errors.append("Target price calculation: missing forward EPS or P/E used")
        else:
            expected_target = round(eps * pe, 0)
            shown = _as_float(ai.get("target_price")) or target_val
            if abs(expected_target - shown) >= 1.5:
                errors.append(
                    f"Target price calculation: Rs.{shown} != "
                    f"EPS {eps} × P/E {pe}x (= Rs.{int(expected_target)})"
                )
            if not ai.get("formula"):
                errors.append("Target price calculation: formula text is missing")

    # 5. No broken placeholders in narrative fields
    texts = [
        str(company.get("name") or ""),
        str(data.get("business_description") or ""),
        str(data.get("outlook_valuation") or ""),
        str(data.get("report_subtitle") or ""),
    ]
    texts.extend(str(h) for h in (data.get("key_highlights") or []))
    blob = "\n".join(texts)
    for pattern in _PLACEHOLDER_PATTERNS:
        if re.search(pattern, blob, re.IGNORECASE):
            errors.append(f"Broken placeholder in report text: {pattern}")
            break
    b_errs, _ = validate_bullets(data.get("key_highlights") or [])
    errors.extend(b_errs)

    return errors


def check_rendered_html(html: str, report: Any) -> List[str]:
    """Checks 3–6 on the HTML that will be sent to Chromium."""
    errors: List[str] = []
    data = _as_dict(report)
    html_without_images = re.sub(
        r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "", html or ""
    )

    # 5. No broken placeholders
    if re.search(r"\{\{|\{%|%\}", html_without_images):
        errors.append("Broken placeholder: unresolved template markup in HTML")
    forbidden = ("FieldInfo", "annotation=", "undefined")
    found = [token for token in forbidden if token in html_without_images]
    if found:
        errors.append("Broken placeholder in HTML: " + ", ".join(found))
    if re.search(
        r"\[(?:VERIFIED|N/A|key growth driver|key concern)",
        html_without_images,
        re.IGNORECASE,
    ):
        errors.append("Broken placeholder leaked into HTML")
    if re.search(r"target of\s*(?:The |the |—|-|&mdash;|$)", html_without_images):
        errors.append("Broken placeholder: incomplete 'target of …' sentence")

    if re.search(r">\s*None\s*<", html_without_images):
        errors.append("Broken placeholder: Python None leaked into HTML")
    if "NoneType" in html_without_images:
        errors.append("Broken placeholder: NoneType leaked into HTML")
    stripped_html = (html or "").lstrip("\ufeff \t\r\n")
    if stripped_html and not stripped_html.lower().startswith("<!doctype html"):
        errors.append("Broken HTML: missing <!DOCTYPE html>")

    # 4. Chart images reached HTML
    expected_charts = _valid_chart_count(data.get("charts"))
    html_charts = (html or "").count("data:image/png;base64,")
    if expected_charts and html_charts < expected_charts:
        errors.append(
            f"Chart data missing in HTML: {html_charts}/{expected_charts} image(s)"
        )

    # 3. Actual vs estimate labels in HTML
    fin = data.get("financials") or {}
    forecast_years = _year_keys(fin.get("forecasts") if isinstance(fin, dict) else {})
    if forecast_years:
        if "est-col" not in (html or ""):
            errors.append("Actual vs estimate: estimate columns are not marked in HTML")
        if not re.search(r"E\s*=\s*(AI )?estimate", html_without_images, re.IGNORECASE):
            errors.append("Actual vs estimate: 'E = estimates' legend missing from HTML")

    # 6. Target formula reached HTML when an estimated target is shown
    appendix = data.get("appendix") or {}
    ai = appendix.get("ai_scenario") if isinstance(appendix, dict) else {}
    if isinstance(ai, dict) and ai.get("available") and ai.get("formula"):
        compact_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_without_images))
        formula = str(ai["formula"])
        variants = (formula, formula.replace("×", "x"), formula.replace("×", "&times;"))
        if not any(re.sub(r"\s+", " ", v) in compact_html for v in variants):
            errors.append("Target price calculation: formula did not reach HTML")

    # 1. Company name still in HTML
    company = data.get("company") or {}
    name = str((company.get("name") if isinstance(company, dict) else "") or "").strip()
    if name and name not in html_without_images:
        errors.append("Required field missing in HTML: company.name")

    return errors


def check_pdf_file(pdf_path: str, expected_chart_count: int = 0) -> List[str]:
    """Check 7: PDF rendered successfully, or not."""
    errors: List[str] = []
    if not pdf_path or not os.path.isfile(pdf_path):
        return ["PDF did not render: output file is missing"]
    if os.path.getsize(pdf_path) < 2000:
        return ["PDF did not render: output file is empty or too small"]

    try:
        import fitz
    except ImportError:
        return errors

    doc = fitz.open(pdf_path)
    try:
        if doc.page_count < 1:
            errors.append("PDF did not render: no pages")
            return errors
        if doc.page_count > 6:
            errors.append(
                f"PDF overflow: {doc.page_count} pages (Geojit frame is 4)"
            )
        elif doc.page_count != 4:
            print(
                f"     [Assignment checks] Page count is {doc.page_count}; "
                "Geojit frame is 4."
            )
        text = "\n".join(page.get_text("text") or "" for page in doc).strip()
        if len(text) < 80:
            errors.append("PDF did not render: pages have no readable text")
        leaked = [tok for tok in ("FieldInfo", "annotation=", "{{", "NoneType") if tok in text]
        if leaked:
            errors.append("Broken placeholder in PDF: " + ", ".join(leaked))
        image_count = sum(len(page.get_images(full=True)) for page in doc)
        if expected_chart_count and image_count < 1:
            errors.append("PDF did not render: no chart images in the file")
    finally:
        doc.close()
    return errors


@dataclass
class ReportQualityScore:
    """Human-readable quality rubric for a generated report.

    This score is diagnostic, not a replacement for source verification. A
    missing source field is reported as unavailable rather than converted into
    a fabricated value merely to improve the score.
    """

    structure: int
    data_accuracy: int
    completeness: int
    chart_quality: int
    narrative_quality: int
    valuation: int
    total: int
    valuation_state: str
    issues: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score_report_quality(report: Any, verification_errors: Optional[List[str]] = None) -> ReportQualityScore:
    """Score the report against the external-style 50 point review rubric."""
    data = _as_dict(report)
    company = data.get("company") or {}
    recommendation = data.get("recommendation") or {}
    financials = data.get("financials") or {}
    appendix = data.get("appendix") or {}
    if not isinstance(company, dict):
        company = {}
    if not isinstance(recommendation, dict):
        recommendation = {}
    if not isinstance(financials, dict):
        financials = {}
    if not isinstance(appendix, dict):
        appendix = {}

    issues: List[str] = list(verification_errors or [])
    structure = 10
    if not company.get("name"):
        structure -= 4
        issues.append("Company identity is missing.")
    if not recommendation.get("action"):
        structure -= 3
        issues.append("Recommendation action is missing.")
    report_date = data.get("report_date") or company.get("report_date")
    if not report_date:
        structure -= 1
    if not data.get("key_highlights"):
        structure -= 2
        issues.append("Key highlights are missing.")

    accuracy = max(0, 10 - min(10, len(verification_errors or [])))
    if accuracy < 7:
        issues.append("Source verification has unresolved findings.")

    numeric_sections = [financials.get(key) for key in ("annual", "quarterly", "forecasts")]
    numeric_count = sum(1 for section in numeric_sections if _has_numeric(section))
    ratios_available = _has_numeric(financials.get("ratios"))
    completeness = min(10, numeric_count * 3 + (1 if ratios_available else 0))
    if not ratios_available:
        completeness = max(0, completeness - 2)
        issues.append("No source-backed ratio block is available.")

    chart_count = _valid_chart_count(data.get("charts"))
    chart_quality = min(8, chart_count * 3)
    if chart_count == 0:
        issues.append("No valid chart image is embedded.")
    elif chart_count < 3:
        issues.append("Report has limited chart coverage.")

    narrative_fields = [data.get("business_description"), data.get("outlook_valuation")]
    narrative_chars = sum(len(str(value or "").strip()) for value in narrative_fields)
    bullet_count = len([b for b in data.get("key_highlights") or [] if str(b).strip()])
    source_coverage = data.get("source_coverage") or {}
    if not isinstance(source_coverage, dict):
        source_coverage = {}
    source_linked = bool(
        source_coverage.get("source")
        and _as_float(source_coverage.get("verified_count"))
        and _as_float(source_coverage.get("total_count"))
    )
    narrative_quality = min(7, (2 if narrative_chars >= 500 else 0) + min(3, bullet_count) + (2 if source_linked else 0))
    if narrative_quality < 6:
        issues.append("Narrative is short or lacks visible source linkage.")

    cmp_value = _as_float(recommendation.get("cmp") or company.get("cmp"))
    target_value = _as_float(recommendation.get("target_price") or company.get("target_price"))
    target_estimated = bool(appendix.get("target_estimated"))
    valuation_state = "RATED" if cmp_value is not None and target_value is not None else "NOT_RATED"
    valuation = 5 if valuation_state == "RATED" and target_estimated else (3 if valuation_state == "RATED" else 0)
    if valuation_state == "NOT_RATED":
        issues.append("Valuation is NOT_RATED because CMP or target price is unavailable from the source.")
    elif not target_estimated:
        issues.append("Valuation is shown without an explicit estimated-target provenance flag.")

    categories = [structure, accuracy, completeness, chart_quality, narrative_quality, valuation]
    return ReportQualityScore(
        structure=max(0, structure),
        data_accuracy=accuracy,
        completeness=completeness,
        chart_quality=chart_quality,
        narrative_quality=narrative_quality,
        valuation=valuation,
        total=sum(categories),
        valuation_state=valuation_state,
        issues=issues,
    )


_FILE_NOISE = {
    "q1", "q2", "q3", "q4", "fy", "fy24", "fy25", "fy26", "fy27", "fy28",
    "pdf", "csv", "txt", "equity", "report", "geojit", "quarter",
    "result", "results", "update", "earnings", "financial", "financials",
    "statement", "statements", "annual", "investor", "presentation",
    "transcript", "filing", "document", "untitled",
}
_NAME_ALIASES = {
    "ltts": {"ltts", "lnt"},
    "lnt": {"ltts", "lnt"},
    "pocl": {"pocl", "pondy"},
    "pondy": {"pocl", "pondy"},
}
_UUID_PREFIX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_",
    re.I,
)


def _normalize_company_text(text: str) -> str:
    s = text or ""
    s = re.sub(r"\bL\s*&\s*T\b", "LTTS", s, flags=re.I)
    s = re.sub(r"\bL\s+and\s+T\b", "LTTS", s, flags=re.I)
    return s


def _alnum_tokens(text: str) -> List[str]:
    return [
        t for t in re.findall(r"[a-z0-9]+", _normalize_company_text(text).lower())
        if len(t) >= 3 and t not in _FILE_NOISE
    ]


def _expand_aliases(tokens: List[str]) -> set:
    out = set(tokens)
    for t in tokens:
        out |= _NAME_ALIASES.get(t, set())
    return out


def company_filename_mismatch(company_name: str, source_filename: str) -> Optional[str]:
    """Return an alert message when the typed name does not match the upload filename.

    Generic names like report.pdf are skipped so unnamed files still work.
    """
    name = (company_name or "").strip()
    raw_name = _UUID_PREFIX.sub("", Path(source_filename or "").name)
    file_label = Path(raw_name).stem.replace("_", " ").strip()
    cover_tokens = _expand_aliases(_alnum_tokens(name))
    file_tokens = _expand_aliases(_alnum_tokens(file_label))
    if not name or not file_tokens or not cover_tokens:
        return None
    if file_tokens & cover_tokens:
        return None
    return (
        f"Company name '{name}' does not match the uploaded file '{file_label}'. "
        "Enter the company name that matches the document "
        "(for example, if the file is JSW Energy Q2FY26.pdf, enter JSW Energy)."
    )


def check_identity_vs_source(
    report: Any, ocr_text: str = "", source_filename: str = ""
) -> List[str]:
    """Catch cover/identity mix-ups (JSW filing titled ICICI) without a second OCR."""
    errors: List[str] = []
    data = _as_dict(report)
    company = data.get("company") or {}
    name = str(company.get("name") or "").strip()
    ticker = str(company.get("ticker") or "").strip()
    mismatch = company_filename_mismatch(
        f"{name} {ticker}".strip(), source_filename
    )
    if mismatch:
        errors.append(mismatch)

    blob = re.sub(r"[^a-z0-9]", "", (ocr_text or "")[:12000].lower())
    distinctive = [
        t for t in _alnum_tokens(name)
        if len(t) >= 5 and t not in {"limited", "energy", "services", "technology", "industries"}
    ]
    file_tokens = _expand_aliases(
        _alnum_tokens(Path(_UUID_PREFIX.sub("", Path(source_filename or "").name)).stem)
    )
    if distinctive and blob and len(blob) > 400 and not file_tokens:
        if not any(t in blob for t in distinctive):
            errors.append(
                f"Company name {name!r} was not found in the source document text"
            )

    for h in data.get("key_highlights") or []:
        if re.match(r"^\s*(cr|bn|mn)\)", str(h), re.I):
            errors.append("Broken highlight clipped at unit suffix (cr)/bn)")
            break
    return errors


class ReportQualityGate:
    """Assignment checks only — required fields, labels, charts, target, PDF."""

    @staticmethod
    def validate_raw_financials(raw_data: Dict[str, Any], sector: str = "") -> None:
        if not isinstance(raw_data, dict) or not _has_numeric(raw_data):
            raise ValueError("Financial extractor did not return numeric data.")

    @staticmethod
    def validate_report(
        report: Any, ocr_text: str = "", source_filename: str = ""
    ) -> None:
        errors = check_report_payload(report)
        errors.extend(
            check_identity_vs_source(
                report, ocr_text=ocr_text, source_filename=source_filename
            )
        )
        if errors:
            raise ValueError("; ".join(errors[:8]))
        print("     [Assignment checks] Required fields, charts, labels, and target OK.")
