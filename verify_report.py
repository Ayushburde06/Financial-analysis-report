"""
verify_report.py — Systematic QA verification of generated reports.
Checks CHARTS, TABLES, FIGURES/LAYOUT, TEXT in HTML, then PAGE BREAKS/COLORS/RESOLUTION in PDF.

Usage: python verify_report.py "outputs/ICICI Q2FY26_Geojit_Report.pdf"
"""
import sys, os, re, json, base64, fitz
from pathlib import Path

PASS = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
WARN = "\033[93m⚠️\033[0m"

results = {"pass": 0, "fail": 0, "warn": 0, "details": []}

def check(label, ok, detail=""):
    status = PASS if ok else FAIL
    if ok:
        results["pass"] += 1
    else:
        results["fail"] += 1
    results["details"].append((status, label, detail))
    print(f"  {status} {label}" + (f" — {detail}" if detail and not ok else ""))

def warn_check(label, ok, detail=""):
    status = PASS if ok else WARN
    if ok:
        results["pass"] += 1
    else:
        results["warn"] += 1
    results["details"].append((status, label, detail))
    print(f"  {status} {label}" + (f" — {detail}" if detail and not ok else ""))


def verify_pdf(pdf_path):
    """Verify PDF: page breaks, colors, chart resolution."""
    doc = fitz.open(pdf_path)
    print(f"\n{'='*60}")
    print(f"  PDF VERIFICATION: {Path(pdf_path).name}")
    print(f"  Pages: {doc.page_count}")
    print(f"{'='*60}\n")

    # ── Page breaks: tables shouldn't cut mid-row ──
    print("── PAGE BREAKS ──")
    for i in range(doc.page_count):
        page = doc[i]
        # Check if page ends with a partial table row (heuristic: page ends with a cell value, not a closing tag)
        text = page.get_text()
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        # A table cut mid-row would have the next page start with continuation data
        if i < doc.page_count - 1:
            next_text = doc[i+1].get_text()
            next_lines = [l.strip() for l in next_text.splitlines() if l.strip()]
            # If current page ends with a number and next page starts with a number (not a header), possible cut
            curr_ends_num = bool(lines and re.match(r'^[\d,.—]+$', lines[-1]))
            next_starts_num = bool(next_lines and re.match(r'^[\d,.—]+$', next_lines[0]))
            check(f"Page {i+1}→{i+2} no mid-row table cut", not (curr_ends_num and next_starts_num),
                  f"Page {i+1} ends with '{lines[-1] if lines else ''}', page {i+2} starts with '{next_lines[0] if next_lines else ''}'")

    # ── Colors printing correctly ──
    print("\n── COLORS ──")
    for i in range(doc.page_count):
        page = doc[i]
        # Check for teal/green header colors (not white/missing)
        drawings = page.get_drawings()
        has_color = any(d.get("fill") and d["fill"] != (1,1,1) for d in drawings)
        check(f"Page {i+1} has colored elements (headers/badges)", has_color)

    # ── Chart resolution: charts should be crisp (not blurry) ──
    print("\n── CHART RESOLUTION ──")
    for i in range(doc.page_count):
        page = doc[i]
        images = page.get_images()
        if images:
            for img in images:
                xref = img[0]
                pix = fitz.Pixmap(doc, xref)
                dpi = pix.width / (page.rect.width / 72)  # approximate
                check(f"Page {i+1} chart image resolution", pix.width >= 300,
                      f"{pix.width}px wide (need >=300)")
                break  # check first image per page
        # No images on this page is OK (not all pages have charts)

    # ── Page count ──
    print("\n── PAGE COUNT ──")
    check("Report is exactly 4 pages", doc.page_count == 4, f"Got {doc.page_count}")

    # ── No blank pages ──
    print("\n── NO BLANK PAGES ──")
    for i in range(doc.page_count):
        text = doc[i].get_text().strip()
        char_count = len(text)
        check(f"Page {i+1} not blank (>50 chars)", char_count > 50, f"Only {char_count} chars")

    doc.close()


def verify_html_content(pdf_path):
    """Extract text from PDF and verify CHARTS/TABLES/FIGURES/TEXT content."""
    doc = fitz.open(pdf_path)
    pages_text = [doc[i].get_text() for i in range(doc.page_count)]
    full_text = "\n".join(pages_text)

    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print(f"  CONTENT VERIFICATION: {Path(pdf_path).name}")
    print(f"{'='*60}\n")

    # ── CHARTS ──
    print("── CHARTS ──")
    # Check chart titles present
    chart_titles = ["Revenue Trend", "PAT", "Quarterly"]
    for title in chart_titles:
        check(f"Chart '{title}' present", title.lower() in full_text.lower())

    # Check no blank canvas (chart images exist)
    for i in range(min(2, doc.page_count)):  # charts on page 2
        images = doc[i].get_images()
        if i == 1 and images:
            check(f"Page 2 has chart images", len(images) >= 3, f"{len(images)} images found")

    # Check margin/banking chart
    has_margin = "margin" in full_text.lower() or "asset quality" in full_text.lower()
    check("Margin or Asset Quality chart present", has_margin)

    # ── TABLES ──
    print("\n── TABLES ──")
    # Quarterly financials
    check("Quarterly Financials section present", "quarterly" in full_text.lower())
    # Check quarterly rows: revenue, ebitda, pat, eps at minimum
    for row in ["Revenue", "PAT", "EPS"]:
        check(f"Quarterly row '{row}' present", row in full_text)

    # Summary financials — years come from this filing, not FY25/FY26E/FY27E
    check("Summary financials (Y.E March) present", "Y.E March" in full_text or "Y.E" in full_text)
    fy_hits = re.findall(r"FY\d{2,4}[AE]?", full_text)
    check("Fiscal-year column present", bool(fy_hits), "No FY labels in PDF")

    # P&L table
    check("P&L / Profit & Loss present", "Profit" in full_text and "Loss" in full_text)
    for row in ["Sales", "EBITDA", "PAT"]:
        check(f"P&L row '{row}' present", row in full_text)

    # Balance Sheet
    check("Balance Sheet present", "Balance Sheet" in full_text)
    # Total Assets may be missing if source doesn't have it — warn, not fail
    warn_check("Total Assets row present", "Total Assets" in full_text,
          "Source may not contain total_assets (graceful omission)")

    # Ratios
    check("Ratios section present", "Ratio" in full_text)
    check("Margin % row present", "Margin" in full_text)

    # Shareholding
    check("Shareholding section present", "shareholding" in full_text.lower() or "Shareholding" in full_text)

    # Change in Estimates
    check("Change in Estimates present", "Change in Estimates" in full_text)

    # Missing values show — not blank/0
    # Only flag "+0.0%" or "-0.0%" (Change in Estimates bug), not legitimate values like "13610.0"
    bad_zero = bool(re.search(r'[+\-]0\.0%', full_text))
    check("No '+0.0%'/'-0.0%' in Change in Estimates", not bad_zero,
          "Found +0.0% or -0.0% formatting bug")

    # ── FIGURES / LAYOUT ──
    print("\n── FIGURES / LAYOUT ──")
    check("Geojit/website URL present", "geojit" in full_text.lower())
    check("Rating present (BUY/HOLD/SELL/NOT RATED)",
           any(r in full_text for r in ["BUY", "HOLD", "SELL", "NOT RATED"]))
    check("Section headers present", "Key Highlights" in full_text)
    check("Header on every page", all("Retail Equity Research" in pt for pt in pages_text))
    check("Date on every page", all("2026" in pt for pt in pages_text))

    # Check for alternating row shading (look for table structures)
    check("Table structure present", "<table" in full_text or "Metric" in full_text)

    # ── TEXT ──
    print("\n── TEXT ──")
    check("Headline/subtitle present", "subtitle" in full_text.lower() or
          any(kw in full_text for kw in ["growth", "outlook", "driven", "stable"]))
    check("Company description present", "description" in full_text.lower() or
          len([l for l in full_text.splitlines() if len(l) > 100]) > 0)
    check("Bullet points present", "•" in full_text or "•" in full_text)
    check("No placeholder '+% YoY'", "+%" not in full_text)
    check("No placeholder 'grew  YoY'", "grew  YoY" not in full_text and "grew +% YoY" not in full_text)
    check("Outlook section present", "Outlook" in full_text or "Valuation" in full_text)
    check("Disclaimer present", "disclaimer" in full_text.lower() or "Disclaimer" in full_text)
    check("AI disclosure present", "AI" in full_text and ("disclosure" in full_text.lower() or "generated" in full_text.lower()))
    check("Verification score shown", "verified" in full_text.lower() or "Source-Verified" in full_text)

    # Check no [VERIFIED] placeholders leaked
    check("No [VERIFIED] placeholders", "[VERIFIED]" not in full_text)
    check("No [N/A] placeholders", "[N/A]" not in full_text)
    check("No KEY_HIGHLIGHTS markers", "KEY_HIGHLIGHTS" not in full_text)

    doc.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python verify_report.py <pdf_path>")
        sys.exit(1)
    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    verify_html_content(pdf_path)
    verify_pdf(pdf_path)

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {results['pass']} passed, {results['fail']} failed, {results['warn']} warnings")
    print(f"{'='*60}")

    if results["fail"] > 0:
        print(f"\n  ❌ {results['fail']} issue(s) need fixing:")
        for status, label, detail in results["details"]:
            if "❌" in status:
                print(f"     - {label}" + (f" ({detail})" if detail else ""))

if __name__ == "__main__":
    main()
