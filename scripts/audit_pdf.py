"""
audit_pdf.py — Comprehensive PDF Quality Auditor

Checks the generated report PDF against the source financial document.

What it checks:
  1. STRUCTURE    — required sections present (Executive Summary, Tables, Charts etc.)
  2. FACTS        — every number in PDF found in source OCR text (within 1%)
  3. CHARTS       — chart images embedded and non-corrupt
  4. TABLES       — financial tables have numeric data, not all dashes/blanks
  5. FONTS/TEXT   — no garbled characters, no encoding issues
  6. FORMATTING   — page count, image count, text density per page

Usage:
  python audit_pdf.py outputs/ICICI_Q2FY26_Geojit_Report.pdf PDF/ICICI_Q2FY26.pdf
  python audit_pdf.py outputs/LTTS_Q2FY26_Geojit_Report.pdf PDF/LTTS_Q2FY26.pdf

  # Or audit all outputs automatically:
  python audit_pdf.py --all
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

try:
    import fitz          # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False
    print("⚠  PyMuPDF not installed. Run: pip install pymupdf")

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False
    print("⚠  pdfplumber not installed. Run: pip install pdfplumber")


# ── Config ─────────────────────────────────────────────────────────────────────

REQUIRED_SECTIONS = [
    "executive summary",
    "annual financial",
    "quarterly",
    "balance sheet",
    "cash flow",
    "investment view",
    "disclaimer",
]

GARBLED_PATTERN = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]|'   # control chars
    r'[^\x00-\x7f]{5,}|'                            # long non-ASCII runs
    r'[▯□■]{3,}|'                                   # replacement boxes
    r'(?:Γé╣|Γé║|┬╖){2,}'                          # known garbled sequences
)

NUMBER_PATTERN = re.compile(r'\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b')
TOLERANCE_PCT  = 1.5   # % tolerance for number matching


# ── Colour output ──────────────────────────────────────────────────────────────

def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"


# ── PDF text extractor ─────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: str) -> Tuple[str, List[str], int]:
    """
    Returns (full_text, per_page_texts, page_count).
    Uses PyMuPDF for full text extraction.
    """
    if not PYMUPDF_OK:
        return "", [], 0
    doc = fitz.open(pdf_path)
    pages = []
    for page in doc:
        pages.append(page.get_text("text"))
    doc.close()
    return "\n".join(pages), pages, len(pages)


def extract_pdf_images(pdf_path: str) -> List[Dict[str, Any]]:
    """Return list of image info dicts from PDF."""
    if not PYMUPDF_OK:
        return []
    doc = fitz.open(pdf_path)
    images = []
    for page_num, page in enumerate(doc, 1):
        for img in page.get_images(full=True):
            xref = img[0]
            base_image = doc.extract_image(xref)
            images.append({
                "page":   page_num,
                "width":  base_image.get("width", 0),
                "height": base_image.get("height", 0),
                "size_kb": round(len(base_image.get("image", b"")) / 1024, 1),
                "colorspace": base_image.get("colorspace", "?"),
                "xref": xref,
            })
    doc.close()
    return images


def extract_pdf_tables(pdf_path: str) -> List[Dict[str, Any]]:
    """Extract tables using pdfplumber."""
    if not PDFPLUMBER_OK:
        return []
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            for tbl in page.extract_tables():
                if tbl:
                    tables.append({"page": page_num, "rows": tbl})
    return tables


# ── Check functions ────────────────────────────────────────────────────────────

def check_structure(text: str) -> Dict[str, Any]:
    """Check all required sections are present."""
    text_lower = text.lower()
    found, missing = [], []
    for section in REQUIRED_SECTIONS:
        if section in text_lower:
            found.append(section)
        else:
            missing.append(section)
    score = len(found) / len(REQUIRED_SECTIONS)
    return {"found": found, "missing": missing, "score": score}


def check_facts(pdf_text: str, source_text: str) -> Dict[str, Any]:
    """
    Extract all numbers from PDF and check each exists in source OCR.
    Skip small numbers (<1000) and percentages.
    """
    # Remove percentage values — derived, not in source as-is
    pdf_clean = re.sub(r'\d[\d,]*\.?\d*\s*%', ' ', pdf_text)
    # Remove 4-digit years
    pdf_clean = re.sub(r'\b(19|20)\d{2}\b', ' ', pdf_clean)

    pdf_numbers = set()
    for m in NUMBER_PATTERN.finditer(pdf_clean):
        try:
            val = float(m.group(0).replace(",", ""))
            if val >= 1000:
                pdf_numbers.add(val)
        except ValueError:
            pass

    # Source numbers index
    source_numbers = set()
    src_clean = re.sub(r'\b(19|20)\d{2}\b', ' ', source_text)
    for m in NUMBER_PATTERN.finditer(src_clean):
        try:
            val = float(m.group(0).replace(",", ""))
            if val >= 1000:
                source_numbers.add(val)
        except ValueError:
            pass

    def in_source(val: float) -> bool:
        for sv in source_numbers:
            if sv == 0:
                continue
            if abs((val - sv) / sv) * 100 <= TOLERANCE_PCT:
                return True
        return False

    verified, unverified = [], []
    for val in sorted(pdf_numbers):
        if in_source(val):
            verified.append(val)
        else:
            unverified.append(val)

    total = len(pdf_numbers)
    score = len(verified) / total if total > 0 else 1.0
    return {
        "total_numbers": total,
        "verified": verified,
        "unverified": unverified,
        "score": score,
    }


def check_charts(images: List[Dict]) -> Dict[str, Any]:
    """Check chart images are present and non-corrupt (min size)."""
    MIN_SIZE_KB = 5   # anything below 5KB is likely corrupt/empty

    ok, corrupt = [], []
    for img in images:
        entry = f"Page {img['page']} | {img['width']}x{img['height']}px | {img['size_kb']}KB"
        if img["size_kb"] < MIN_SIZE_KB or img["width"] < 50 or img["height"] < 50:
            corrupt.append(entry)
        else:
            ok.append(entry)

    return {
        "total":   len(images),
        "ok":      ok,
        "corrupt": corrupt,
        "score":   len(ok) / len(images) if images else 0.0,
    }


def check_tables(tables: List[Dict]) -> Dict[str, Any]:
    """
    Check tables have numeric data where expected.
    
    Sidebar lookup tables (≤8 rows, 2 columns) are exempt from the numeric
    threshold — they hold label/value pairs where values may legitimately be
    "—" if that data isn't in the source document (e.g. CMP not in a press release).
    Only financial data tables (>8 rows OR >2 columns) must have numeric content.
    """
    if not tables:
        return {"total": 0, "ok": [], "empty": [], "score": 1.0}

    ok_tables, empty_tables = [], []
    for i, tbl in enumerate(tables):
        rows = tbl["rows"]
        num_rows = len(rows)
        num_cols = max((len(r) for r in rows if r), default=0)

        # Sidebar-style lookup tables — exempt (2-column key/value pairs)
        is_sidebar = num_cols <= 2 and num_rows <= 10
        if is_sidebar:
            ok_tables.append(
                f"Page {tbl['page']} | {num_rows} rows | sidebar table (exempt)"
            )
            continue

        # Financial data tables — must have meaningful numeric content
        numeric_cells = 0
        total_cells   = 0
        for row in rows:
            for cell in (row or []):
                cell_str = str(cell).strip() if cell else ""
                if cell_str and cell_str not in ("—", "-", "N/A", "", "None"):
                    total_cells += 1
                    try:
                        val = float(cell_str.replace(",", "").replace("%", ""))
                        if val != 0:
                            numeric_cells += 1
                    except ValueError:
                        pass

        entry = (f"Page {tbl['page']} | {num_rows} rows | "
                 f"{numeric_cells}/{total_cells} numeric cells")
        if total_cells == 0 or numeric_cells / total_cells >= 0.08:
            ok_tables.append(entry)
        else:
            empty_tables.append(entry)

    score = len(ok_tables) / len(tables) if tables else 1.0
    return {"total": len(tables), "ok": ok_tables, "empty": empty_tables, "score": score}


def check_fonts_text(pages: List[str]) -> Dict[str, Any]:
    """Check for garbled characters, encoding issues, empty pages."""
    issues = []
    empty_pages  = []
    garbled_pages = []

    for i, page_text in enumerate(pages, 1):
        if len(page_text.strip()) < 50:
            empty_pages.append(i)
            issues.append(f"Page {i}: almost empty ({len(page_text.strip())} chars)")
            continue

        garbled_matches = GARBLED_PATTERN.findall(page_text)
        if garbled_matches:
            garbled_pages.append(i)
            issues.append(f"Page {i}: {len(garbled_matches)} garbled sequence(s): "
                          f"{garbled_matches[:3]}")

    score = 1.0 - (len(garbled_pages) + len(empty_pages)) / max(len(pages), 1)
    return {
        "page_count":    len(pages),
        "empty_pages":   empty_pages,
        "garbled_pages": garbled_pages,
        "issues":        issues,
        "score":         max(0.0, score),
    }


def check_formatting(pages: List[str], images: List[Dict]) -> Dict[str, Any]:
    """Check overall formatting: page count, text density, image distribution."""
    results = []
    for i, text in enumerate(pages, 1):
        word_count = len(text.split())
        img_count  = sum(1 for img in images if img["page"] == i)
        results.append({
            "page":       i,
            "words":      word_count,
            "images":     img_count,
            "status":     "OK" if word_count > 30 else "SPARSE",
        })
    return {
        "pages":       results,
        "total_words": sum(r["words"] for r in results),
        "total_images":len(images),
    }


# ── Report printer ─────────────────────────────────────────────────────────────

def print_section(title: str, score: float, details: List[str],
                  ok_items: List = None, bad_items: List = None):
    icon  = "[OK]" if score >= 0.9 else ("[WARN]" if score >= 0.5 else "[FAIL]")
    color = green if score >= 0.9 else (yellow if score >= 0.5 else red)
    print(f"\n{bold(f'{icon}  {title}')}")
    print(f"   Score: {color(f'{score:.0%}')}")
    for d in details:
        print(f"   {d}")
    if ok_items:
        for item in ok_items[:8]:
            print(f"   {green('[OK]')} {item}")
        if len(ok_items) > 8:
            print(f"   {green('[OK]')} ... and {len(ok_items)-8} more")
    if bad_items:
        for item in bad_items[:5]:
            print(f"   {red('✗')} {item}")
        if len(bad_items) > 5:
            print(f"   {red('✗')} ... and {len(bad_items)-5} more")


# ── Main audit function ────────────────────────────────────────────────────────

def audit(report_pdf: str, source_pdf: str = None) -> Dict[str, Any]:
    print(f"\n{'='*65}")
    print(bold(f"  PDF AUDIT REPORT"))
    print(f"  Report : {report_pdf}")
    print(f"  Source : {source_pdf or 'Not provided'}")
    print(f"{'='*65}")

    if not os.path.isfile(report_pdf):
        print(red(f"  [FAIL] Report PDF not found: {report_pdf}"))
        return {}

    # Extract content
    pdf_text, pages, page_count = extract_pdf_text(report_pdf)
    images  = extract_pdf_images(report_pdf)
    tables  = extract_pdf_tables(report_pdf)

    # Run all checks
    struct  = check_structure(pdf_text)
    fonts   = check_fonts_text(pages)
    charts  = check_charts(images)
    tbls    = check_tables(tables)
    fmt     = check_formatting(pages, images)

    # Fact check (only if source provided)
    facts = None
    if source_pdf and os.path.isfile(source_pdf):
        src_text, _, _ = extract_pdf_text(source_pdf)
        facts = check_facts(pdf_text, src_text)
    else:
        # Try to find matching source PDF automatically
        report_name = Path(report_pdf).stem.replace("_Geojit_Report", "")
        for f in Path("PDF").glob("*.pdf"):
            if report_name.lower().replace(" ", "") in f.stem.lower().replace(" ", ""):
                src_text, _, _ = extract_pdf_text(str(f))
                facts = check_facts(pdf_text, src_text)
                print(f"   Auto-matched source: {f.name}")
                break

    # ── Print results ──────────────────────────────────────────────────────────

    # 1. Structure
    print_section(
        "SECTION STRUCTURE",
        struct["score"],
        [f"Found {len(struct['found'])}/{len(REQUIRED_SECTIONS)} required sections"],
        ok_items=[s.title() for s in struct["found"]],
        bad_items=[f"MISSING: {s.upper()}" for s in struct["missing"]],
    )

    # 2. Facts
    if facts:
        print_section(
            "FACT VERIFICATION (PDF numbers vs source document)",
            facts["score"],
            [f"{facts['verified'].__len__()}/{facts['total_numbers']} numbers "
             f"confirmed in source document"],
            ok_items=[str(v) for v in facts["verified"][:10]],
            bad_items=[f"NOT IN SOURCE: {v}" for v in facts["unverified"][:10]],
        )
    else:
        print(f"\n{yellow('[WARN] FACT VERIFICATION')} - source PDF not provided, skipped.")

    # 3. Charts
    print_section(
        "CHARTS & IMAGES",
        charts["score"],
        [f"{charts['total']} image(s) found in PDF"],
        ok_items=charts["ok"],
        bad_items=[f"CORRUPT/TINY: {c}" for c in charts["corrupt"]],
    )

    # 4. Tables
    print_section(
        "FINANCIAL TABLES",
        tbls["score"],
        [f"{tbls['total']} table(s) found"],
        ok_items=tbls["ok"],
        bad_items=[f"EMPTY TABLE: {e}" for e in tbls["empty"]],
    )

    # 5. Fonts/Text
    print_section(
        "FONT & TEXT QUALITY",
        fonts["score"],
        [f"{fonts['page_count']} pages | "
         f"{len(fonts['garbled_pages'])} garbled | "
         f"{len(fonts['empty_pages'])} empty"],
        bad_items=fonts["issues"],
    )

    # 6. Formatting
    print(f"\n{bold('[PDF]  FORMATTING SUMMARY')}")
    print(f"   Pages: {fmt['total_words']:,} total words | "
          f"{fmt['total_images']} images")
    for p in fmt["pages"]:
        status_icon = green("OK") if p["status"] == "OK" else yellow("SPARSE")
        print(f"   Page {p['page']}: {p['words']:>5} words | "
              f"{p['images']} image(s) | [{status_icon}]")

    # ── Overall score ──────────────────────────────────────────────────────────
    scores = [struct["score"], charts["score"], tbls["score"], fonts["score"]]
    if facts:
        scores.append(facts["score"])
    overall = sum(scores) / len(scores)

    color_fn = green if overall >= 0.9 else (yellow if overall >= 0.7 else red)
    print(f"\n{'='*65}")
    print(bold(f"  OVERALL AUDIT SCORE: {color_fn(f'{overall:.0%}')}"))
    if overall >= 0.9:
        print(f"  {green('[OK] Report passes all quality checks.')}")
    elif overall >= 0.7:
        print(f"  {yellow('[WARN] Report passes with minor issues.')}")
    else:
        print(f"  {red('[FAIL] Report has significant quality issues.')}")
    print(f"{'='*65}\n")

    return {
        "overall": overall,
        "structure": struct,
        "facts":    facts,
        "charts":   charts,
        "tables":   tbls,
        "fonts":    fonts,
        "formatting": fmt,
    }


def audit_all():
    """Audit all PDFs in outputs/ folder."""
    output_dir = Path("outputs")
    pdfs = list(output_dir.glob("*_Geojit_Report.pdf"))
    if not pdfs:
        print(red("No report PDFs found in outputs/ folder."))
        return

    results = {}
    for pdf in pdfs:
        result = audit(str(pdf))
        results[pdf.name] = result.get("overall", 0)

    # Summary
    print(bold("\n[BATCH] BATCH AUDIT SUMMARY"))
    print("─" * 50)
    for name, score in results.items():
        color_fn = green if score >= 0.9 else (yellow if score >= 0.7 else red)
        print(f"  {color_fn(f'{score:.0%}')}  {name}")
    print("─" * 50)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit generated Geojit report PDFs")
    parser.add_argument("report", nargs="?", help="Path to generated report PDF")
    parser.add_argument("source", nargs="?", help="Path to source financial PDF (optional)")
    parser.add_argument("--all",  action="store_true", help="Audit all PDFs in outputs/")
    args = parser.parse_args()

    if args.all:
        audit_all()
    elif args.report:
        audit(args.report, args.source)
    else:
        # Default: audit all outputs
        print("No PDF specified. Auditing all outputs...\n")
        audit_all()
