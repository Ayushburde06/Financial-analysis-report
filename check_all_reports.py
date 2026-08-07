"""Deep check: charts, tables, numbers for all generated reports."""
import fitz
import re
from pathlib import Path

REPORTS = [
    "outputs/ICICI Q2FY26_Geojit_Report.pdf",
    "outputs/LTTS Q2FY26_Geojit_Report.pdf",
    "outputs/POCL Q2FY26_Geojit_Report.pdf",
    "outputs/JSW Energy Q2FY26_Geojit_Report.pdf",
]

BAD_PATTERNS = ["+% YoY", "grew + YoY", "[VERIFIED]", "[N/A]", "KEY_HIGHLIGHTS", "0.0%"]


def count_images(page):
    return len(page.get_images())


def section_text(doc, page_idx, start_kw, end_kw):
    text = doc[page_idx].get_text()
    lines = text.splitlines()
    out, capture = [], False
    for line in lines:
        s = line.strip()
        if start_kw in s:
            capture = True
        if capture:
            out.append(s)
        if capture and end_kw in s and start_kw not in s:
            break
    return out


def numeric_cells(lines):
    nums = 0
    dashes = 0
    for s in lines:
        if s in ("—", "-", "--"):
            dashes += 1
        elif re.match(r"^[\d,.]+$", s):
            nums += 1
    return nums, dashes


for path in REPORTS:
    name = Path(path).stem.replace("_Geojit_Report", "")
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")

    doc = fitz.open(path)
    pages = doc.page_count
    full = "\n".join(doc[i].get_text() for i in range(pages))

    issues = []

    # Page count
    print(f"  Pages: {pages} {'OK' if pages == 4 else 'FAIL'}")

    # Charts (page 1 stock + page 2 grid)
    p1_imgs = count_images(doc[0])
    p2_imgs = count_images(doc[1])
    print(f"  Page 1 images (stock chart): {p1_imgs} {'OK' if p1_imgs >= 1 else 'MISSING'}")
    print(f"  Page 2 images (4 charts): {p2_imgs} {'OK' if p2_imgs >= 3 else 'SPARSE'}")

    # Quarterly table page 1
    has_qtr = "Quarterly Financials" in full or "Quarterly" in full
    qtr_nums, qtr_dash = numeric_cells(full.split("Quarterly")[1][:800] if "Quarterly" in full else [])
    print(f"  Quarterly table: {'present' if has_qtr else 'MISSING'}")

    # Page 2 tables
    has_fwd = "Forward Estimates" in full
    has_chg = "Change in Estimates" in full
    print(f"  Forward Estimates table: {'OK' if has_fwd else 'MISSING'}")
    print(f"  Change in Estimates table: {'OK' if has_chg else 'MISSING'}")

    # Page 3 - P&L, BS, Ratios
    p3 = doc[2].get_text()
    for sec in ["Profit", "Balance Sheet", "Ratio", "Valuation Summary"]:
        ok = sec in p3
        print(f"  Page 3 {sec}: {'OK' if ok else 'MISSING'}")
        if not ok:
            issues.append(f"Missing {sec} on page 3")

    # Balance sheet values
    bs_lines = section_text(doc, 2, "Balance Sheet", "Cashflow")
    bs_nums, bs_dash = numeric_cells(bs_lines)
    bs_has_total = any("Total Assets" in l for l in bs_lines)
    bs_has_data = bs_nums > 0
    print(f"  Balance Sheet rows: Total Assets={'yes' if bs_has_total else 'no'}, numeric cells={bs_nums}, dashes={bs_dash}")
    if bs_has_total and not bs_has_data:
        issues.append("Balance Sheet has rows but no numeric values")

    # Text quality
    for pat in BAD_PATTERNS:
        if pat in full:
            issues.append(f"Bad pattern found: {pat}")

    # Highlights with numbers
    bullets = [l.strip() for l in full.splitlines() if l.strip().startswith("•") or "for Q2FY26" in l or "for the quarter" in l.lower()]
    no_num_bullets = [b for b in bullets[:10] if b and not re.search(r"\d", b)]
    if no_num_bullets:
        issues.append(f"{len(no_num_bullets)} highlight(s) without numbers")

    # Valuation summary ROE/D/E
    if "Valuation Summary" in p3:
        m = re.search(r"Valuation Summary.*?ROE.*?D/E", p3, re.DOTALL)
        if m:
            block = m.group(0)[:200]
            roe_all_dash = "ROE" in block and block.count("—") >= 2
            if roe_all_dash:
                issues.append("Valuation ROE all dashes")

    # Summary
    if issues:
        print(f"  ISSUES ({len(issues)}):")
        for i in issues:
            print(f"    - {i}")
    else:
        print(f"  RESULT: ALL CHECKS PASSED")

    doc.close()
