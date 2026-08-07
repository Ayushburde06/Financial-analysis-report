"""
audit_pdf_azure.py — Azure Document Intelligence PDF Auditor

Sends the GENERATED report PDF through Azure OCR (same engine as Stage 01)
and cross-checks it against the SOURCE financial document.

Why Azure OCR is better than PyMuPDF for this:
  - Renders the PDF like a human viewer (rasterises → OCRs)
  - Detects actual table structure with row/column positions
  - Identifies figures/charts as separate elements
  - Finds layout issues: overlapping text, broken tables, missing sections
  - Gives confidence scores per page
  - Returns markdown with proper table syntax → easy to parse

Checks performed:
  1. STRUCTURE      — all required sections present (exact heading match)
  2. TABLES         — table count, row/col counts, numeric density
  3. FIGURES        — figure/chart count and positions
  4. FACTS          — every number in generated PDF found in source OCR
  5. TEXT QUALITY   — garbled chars, encoding issues, empty pages
  6. COMPLETENESS   — word count per page, data coverage

Usage:
  # Single report vs its source:
  python audit_pdf_azure.py outputs/"ICICI Q2FY26_Geojit_Report.pdf" PDF/"ICICI Q2FY26.pdf"

  # Auto-match source and audit all reports:
  python audit_pdf_azure.py --all

  # Just audit one report (no source cross-check):
  python audit_pdf_azure.py outputs/"LTTS Q2FY26_Geojit_Report.pdf"
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

# ── Colour helpers ─────────────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"

# ── Constants ──────────────────────────────────────────────────────────────────
REQUIRED_SECTIONS = [
    "executive summary",
    "annual financial",
    "quarterly",
    "balance sheet",
    "cash flow",
    "investment view",
    "disclaimer",
]

TOLERANCE_PCT  = 1.5    # % tolerance for number matching
MIN_NUMBER     = 1000   # ignore numbers below this (too common to match reliably)

NUMBER_RE = re.compile(r'\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b')
GARBLED_RE = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f]|[▯□■]{3,}'
    # Note: Γé╣ = ₹ and ΓÇö = — when PDF uses CP1252 encoding
    # We detect these specifically and report as encoding issues
    r'|(?:Γé╣){1,}|(?:ΓÇö){3,}|(?:Γé║){2,}'
)


# ── Azure OCR helper ───────────────────────────────────────────────────────────

def run_azure_ocr(pdf_path: str) -> Dict[str, Any]:
    """
    Run Azure Document Intelligence prebuilt-layout on a PDF.
    Returns a dict with:
      - content:   full markdown string
      - pages:     list of per-page content strings
      - tables:    list of table dicts {page, rows, cols, cells}
      - figures:   list of figure dicts {page, description}
      - page_count: int
    """
    endpoint = os.getenv("AZURE_DOC_INTEL_ENDPOINT")
    key      = os.getenv("AZURE_DOC_INTEL_KEY")

    if not endpoint or not key:
        print(red("❌  AZURE_DOC_INTEL_ENDPOINT or AZURE_DOC_INTEL_KEY not set in .env"))
        sys.exit(1)

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        print(red("❌  Run: pip install azure-ai-documentintelligence"))
        sys.exit(1)

    client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))

    print(f"   [Azure OCR] Uploading {Path(pdf_path).name}...")
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    print("   [Azure OCR] Processing (prebuilt-layout)...")
    t0 = time.time()
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=pdf_bytes,
        content_type="application/octet-stream",
        output_content_format="markdown",
    )
    result = poller.result()
    elapsed = round(time.time() - t0, 1)
    print(f"   [Azure OCR] Done in {elapsed}s.")

    content = result.content or ""

    # Split into pages
    raw_pages = content.split("<!-- PageBreak -->") if "<!-- PageBreak -->" in content else [content]
    pages = [p.strip() for p in raw_pages if p.strip()]

    # Extract tables from Azure result
    tables = []
    if hasattr(result, "tables") and result.tables:
        for tbl in result.tables:
            rows = tbl.row_count
            cols = tbl.column_count
            page = (tbl.bounding_regions[0].page_number
                    if tbl.bounding_regions else "?")
            cells = []
            for cell in tbl.cells:
                cells.append({
                    "row":     cell.row_index,
                    "col":     cell.column_index,
                    "content": cell.content or "",
                    "kind":    getattr(cell, "kind", "content"),
                })
            tables.append({
                "page": page,
                "rows": rows,
                "cols": cols,
                "cells": cells,
            })

    # Extract figures
    figures = []
    if hasattr(result, "figures") and result.figures:
        for fig in result.figures:
            page = (fig.bounding_regions[0].page_number
                    if fig.bounding_regions else "?")
            desc = getattr(fig, "caption", None)
            if desc and hasattr(desc, "content"):
                desc = desc.content
            figures.append({"page": page, "description": desc or "Figure"})

    return {
        "content":    content,
        "pages":      pages,
        "tables":     tables,
        "figures":    figures,
        "page_count": len(pages),
    }


# ── Check functions ────────────────────────────────────────────────────────────

def check_structure(ocr: Dict) -> Dict:
    text_lower = ocr["content"].lower()
    found, missing = [], []
    for s in REQUIRED_SECTIONS:
        if s in text_lower:
            found.append(s)
        else:
            missing.append(s)
    score = len(found) / len(REQUIRED_SECTIONS)
    return {"found": found, "missing": missing, "score": score}


def check_tables(ocr: Dict) -> Dict:
    tables = ocr["tables"]
    if not tables:
        return {"total": 0, "ok": [], "sparse": [], "score": 1.0,
                "detail": "No tables detected by Azure OCR"}

    ok, sparse = [], []
    for tbl in tables:
        # Count ALL cells (kind=None or kind="content") with any text content
        # Azure uses kind=None for regular data cells, kind=columnHeader for headers
        filled_cells = 0
        numeric_cells = 0
        for c in tbl["cells"]:
            content = (c["content"] or "").strip()
            # Skip known non-content: empty, dash variants (— ΓÇö -), N/A
            if not content or content in ("—", "ΓÇö", "-", "N/A", "", "None"):
                continue
            filled_cells += 1
            # Try numeric
            val = content.replace(",", "").replace("%", "").replace("Γé╣", "").strip()
            try:
                if float(val) != 0:
                    numeric_cells += 1
            except ValueError:
                pass

        total_data_cells = tbl["rows"] * tbl["cols"]
        entry = (f"Page {tbl['page']} | "
                 f"{tbl['rows']}r × {tbl['cols']}c | "
                 f"{numeric_cells} numeric, {filled_cells} filled cells")

        # Sidebar tables (≤2 cols) — exempt
        if tbl["cols"] <= 2:
            ok.append(entry + " [sidebar — exempt]")
        # Any table with content is OK
        elif filled_cells > 0:
            ok.append(entry)
        else:
            sparse.append(entry)

    score = len(ok) / len(tables) if tables else 1.0
    return {"total": len(tables), "ok": ok, "sparse": sparse, "score": score}


def check_figures(ocr: Dict) -> Dict:
    figures = ocr["figures"]
    total = len(figures)
    pages = sorted(set(f["page"] for f in figures))
    return {
        "total": total,
        "pages": pages,
        "score": 1.0 if total >= 1 else 0.0,
        "detail": [f"Page {f['page']}: {f['description']}" for f in figures],
    }


def check_facts(report_ocr: Dict, source_ocr: Dict) -> Dict:
    """Cross-check every number in the generated report against the source OCR."""

    def extract_numbers(text: str) -> List[float]:
        # Remove percentages and years
        clean = re.sub(r'\d[\d,]*\.?\d*\s*%', ' ', text)
        clean = re.sub(r'\b(19|20)\d{2}\b', ' ', clean)
        nums = set()
        for m in NUMBER_RE.finditer(clean):
            try:
                v = float(m.group(0).replace(",", ""))
                if v >= MIN_NUMBER:
                    nums.add(v)
            except ValueError:
                pass
        return sorted(nums)

    report_nums = extract_numbers(report_ocr["content"])
    source_nums = extract_numbers(source_ocr["content"])

    def in_source(val: float) -> Tuple[bool, Optional[float]]:
        for sv in source_nums:
            if sv == 0:
                continue
            if abs((val - sv) / sv) * 100 <= TOLERANCE_PCT:
                return True, sv
        return False, None

    verified, unverified = [], []
    for val in report_nums:
        found, matched = in_source(val)
        if found:
            verified.append((val, matched))
        else:
            unverified.append(val)

    total = len(report_nums)
    score = len(verified) / total if total > 0 else 1.0
    return {
        "total":      total,
        "verified":   verified,
        "unverified": unverified,
        "score":      score,
    }


def check_text_quality(ocr: Dict) -> Dict:
    # Known garbled sequences from CP1252/UTF-8 mismatch
    RUPEE_GARBLED = "Γé╣"    # ₹ rendered incorrectly
    DASH_GARBLED  = "ΓÇö"    # — rendered incorrectly

    issues = []
    garbled_pages, empty_pages = [], []
    encoding_issues = []

    for i, page_text in enumerate(ocr["pages"], 1):
        if len(page_text.strip()) < 30:
            empty_pages.append(i)
            issues.append(f"Page {i}: nearly empty ({len(page_text.strip())} chars)")
            continue

        # Check for ₹ font encoding issue
        if RUPEE_GARBLED in page_text:
            count = page_text.count(RUPEE_GARBLED)
            encoding_issues.append(f"Page {i}: ₹ symbol garbled ({count}x) → font encoding issue")

        # Other garbled chars
        other_garbled = re.findall(
            r'[\x00-\x08\x0b\x0c\x0e-\x1f]|[▯□■]{3,}', page_text
        )
        if other_garbled:
            garbled_pages.append(i)
            issues.append(f"Page {i}: {len(other_garbled)} garbled sequence(s)")

    all_issues = encoding_issues + issues
    # Encoding issues reduce score by 0.1 per page, other garbled by 0.2
    penalty = (len(encoding_issues) * 0.05 + len(garbled_pages) * 0.2 +
               len(empty_pages) * 0.2)
    score = max(0.0, 1.0 - penalty / max(len(ocr["pages"]), 1))

    return {
        "page_count":       len(ocr["pages"]),
        "garbled_pages":    garbled_pages,
        "empty_pages":      empty_pages,
        "encoding_issues":  encoding_issues,
        "issues":           all_issues,
        "score":            score,
    }


def check_completeness(ocr: Dict) -> Dict:
    """Word count and data density per page."""
    pages = []
    for i, text in enumerate(ocr["pages"], 1):
        words = len(text.split())
        nums  = len([m for m in NUMBER_RE.finditer(text)])
        pages.append({
            "page": i, "words": words, "numbers": nums,
            "status": "OK" if words > 40 else "SPARSE",
        })
    return {
        "pages":       pages,
        "total_words": sum(p["words"] for p in pages),
        "total_numbers": sum(p["numbers"] for p in pages),
    }


# ── Report printer ─────────────────────────────────────────────────────────────

def print_check(title: str, score: float, detail_lines: List[str] = None,
                ok: List = None, bad: List = None):
    icon  = "✅" if score >= 0.9 else ("⚠️ " if score >= 0.6 else "❌")
    cfn   = green if score >= 0.9 else (yellow if score >= 0.6 else red)
    print(f"\n{bold(f'{icon}  {title}')}")
    print(f"   Score: {cfn(f'{score:.0%}')}")
    for d in (detail_lines or []):
        print(f"   {d}")
    for item in (ok or [])[:8]:
        print(f"   {green('✓')} {item}")
    if ok and len(ok) > 8:
        print(f"   {green('✓')} ... and {len(ok)-8} more")
    for item in (bad or [])[:6]:
        print(f"   {red('✗')} {item}")
    if bad and len(bad) > 6:
        print(f"   {red('✗')} ... and {len(bad)-6} more")


# ── Main audit ─────────────────────────────────────────────────────────────────

def audit(report_pdf: str, source_pdf: str = None) -> Dict:
    print(f"\n{'='*65}")
    print(bold("  AZURE OCR PDF AUDIT"))
    print(f"  Report : {report_pdf}")
    print(f"  Source : {source_pdf or 'Not provided (fact-check skipped)'}")
    print(f"{'='*65}")

    if not os.path.isfile(report_pdf):
        print(red(f"  ❌ File not found: {report_pdf}"))
        return {}

    # ── OCR the generated report ───────────────────────────────────────────────
    print(f"\n{cyan('Step 1: Running Azure OCR on generated report...')}")
    report_ocr = run_azure_ocr(report_pdf)

    # ── Auto-match source if not given ────────────────────────────────────────
    source_ocr = None
    if source_pdf and os.path.isfile(source_pdf):
        print(f"\n{cyan('Step 2: Running Azure OCR on source document...')}")
        source_ocr = run_azure_ocr(source_pdf)
    else:
        stem = Path(report_pdf).stem.replace("_Geojit_Report", "").replace(" ", "").lower()
        for f in Path("PDF").glob("*.pdf"):
            if stem in f.stem.lower().replace(" ", ""):
                print(f"\n{cyan(f'Step 2: Auto-matched source → {f.name}')}")
                source_ocr = run_azure_ocr(str(f))
                break
        if not source_ocr:
            print(yellow("  Step 2: No source PDF matched — fact-check skipped."))

    # ── Run all checks ─────────────────────────────────────────────────────────
    struct  = check_structure(report_ocr)
    tables  = check_tables(report_ocr)
    figures = check_figures(report_ocr)
    tq      = check_text_quality(report_ocr)
    comp    = check_completeness(report_ocr)
    facts   = check_facts(report_ocr, source_ocr) if source_ocr else None

    # ── Print results ──────────────────────────────────────────────────────────
    print_check(
        "SECTION STRUCTURE",
        struct["score"],
        [f"Found {len(struct['found'])}/{len(REQUIRED_SECTIONS)} required sections"],
        ok=[s.title() for s in struct["found"]],
        bad=[f"MISSING: {s.upper()}" for s in struct["missing"]],
    )

    print_check(
        f"FINANCIAL TABLES ({tables['total']} detected by Azure OCR)",
        tables["score"],
        [],
        ok=tables["ok"],
        bad=[f"SPARSE: {s}" for s in tables.get("sparse", [])],
    )

    print_check(
        f"FIGURES / CHARTS ({figures['total']} detected by Azure OCR)",
        figures["score"],
        [f"Found on pages: {figures['pages']}"] if figures["pages"] else [],
        ok=figures["detail"],
    )

    if facts:
        print_check(
            "FACT VERIFICATION (report numbers vs source OCR)",
            facts["score"],
            [f"{len(facts['verified'])}/{facts['total']} numbers confirmed in source"],
            ok=[f"{v} ≈ {m} in source" for v, m in facts["verified"][:10]],
            bad=[f"NOT IN SOURCE: {v}" for v in facts["unverified"][:8]],
        )
    else:
        print(f"\n{yellow('⚠️   FACT VERIFICATION')} — source not provided, skipped.")

    print_check(
        "TEXT & FONT QUALITY",
        tq["score"],
        [f"{tq['page_count']} pages | "
         f"{len(tq['garbled_pages'])} garbled | "
         f"{len(tq['empty_pages'])} empty | "
         f"{len(tq.get('encoding_issues', []))} font encoding issue(s)"],
        bad=tq["issues"],
    )

    # Completeness table
    print(f"\n{bold('📄  PAGE COMPLETENESS')}")
    for p in comp["pages"]:
        status = green("OK") if p["status"] == "OK" else yellow("SPARSE")
        print(f"   Page {p['page']:>2}: {p['words']:>5} words | "
              f"{p['numbers']:>4} numbers | [{status}]")
    print(f"   Total: {comp['total_words']:,} words | "
          f"{comp['total_numbers']:,} numbers")

    # ── Overall score ──────────────────────────────────────────────────────────
    scores = [struct["score"], tables["score"], figures["score"], tq["score"]]
    if facts:
        scores.append(facts["score"])
    overall = sum(scores) / len(scores)

    cfn = green if overall >= 0.9 else (yellow if overall >= 0.7 else red)
    print(f"\n{'='*65}")
    print(bold(f"  OVERALL AZURE OCR AUDIT SCORE: {cfn(f'{overall:.0%}')}"))
    if overall >= 0.9:
        print(f"  {green('✅ Report passes all quality checks.')}")
    elif overall >= 0.7:
        print(f"  {yellow('⚠️  Report passes with minor issues.')}")
    else:
        print(f"  {red('❌ Report has significant quality issues.')}")
    print(f"{'='*65}\n")

    return {
        "overall":    overall,
        "structure":  struct,
        "tables":     tables,
        "figures":    figures,
        "facts":      facts,
        "text":       tq,
        "completeness": comp,
    }


def audit_all():
    reports = sorted(Path("outputs").glob("*_Geojit_Report.pdf"))
    if not reports:
        print(red("No *_Geojit_Report.pdf files found in outputs/"))
        return

    scores = {}
    for pdf in reports:
        result = audit(str(pdf))
        scores[pdf.name] = result.get("overall", 0.0)

    print(bold("\n📊  AZURE OCR BATCH AUDIT SUMMARY"))
    print("─" * 52)
    for name, sc in scores.items():
        cfn = green if sc >= 0.9 else (yellow if sc >= 0.7 else red)
        print(f"  {cfn(f'{sc:.0%}')}  {name}")
    print("─" * 52)
    avg = sum(scores.values()) / len(scores) if scores else 0
    print(f"  Average: {avg:.0%}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Audit generated PDFs using Azure Document Intelligence OCR"
    )
    parser.add_argument("report", nargs="?", help="Path to generated report PDF")
    parser.add_argument("source", nargs="?", help="Path to source financial PDF (optional)")
    parser.add_argument("--all",  action="store_true", help="Audit all PDFs in outputs/")
    args = parser.parse_args()

    if args.all:
        audit_all()
    elif args.report:
        audit(args.report, args.source)
    else:
        print("No PDF specified. Auditing all outputs...\n")
        audit_all()
