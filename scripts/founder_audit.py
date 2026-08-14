"""Founder assignment audit: OCR generated reports, verify vs source PDFs."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # PyMuPDF
from pypdf import PdfReader

from pipeline.utils.azure_di_ocr import extract_pdf_azure_di

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs"
SRC_DIR = ROOT / "PDF"
AUDIT_DIR = ROOT / "tmp" / "founder_audit"

PAIRS = [
    ("ICICI Q2FY26_Equity_Report.pdf", "ICICI Q2FY26.pdf", "ICICI Bank"),
    ("LTTS Q2FY26_Equity_Report.pdf", "LTTS Q2FY26.pdf", "LTTS"),
    ("JSW Energy Q2FY26_Equity_Report.pdf", "JSW Energy Q2FY26.pdf", "JSW Energy"),
    ("POCL Q2FY26_Equity_Report.pdf", "POCL Q2FY26.pdf", "POCL"),
]

PLACEHOLDERS = [
    r"\{\{",
    r"FieldInfo",
    r"\[VERIFIED\]",
    r"\[N/A\]",
    r"KEY_HIGHLIGHTS",
    r"target of\s+(?:The |the |—)",
    r"grew \+ YoY",
    r"undefined",
]
OFFTOPIC = ["zomato", "blinkit", "swiggy", "zepto", "hyperpure"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def pdf_text_embedded(path: Path) -> tuple[int, list[str], int]:
    reader = PdfReader(str(path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    n_images = 0
    try:
        doc = fitz.open(str(path))
        for page in doc:
            n_images += len(page.get_images())
        doc.close()
    except Exception:
        pass
    return len(pages), pages, n_images


def render_pages(path: Path, stem: str, max_pages: int = 2) -> list[str]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(path))
    saved = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
        out = AUDIT_DIR / f"{stem}_p{i + 1}.png"
        pix.save(str(out))
        saved.append(str(out))
    doc.close()
    return saved


def extract_numbers(text: str) -> list[float]:
    found = []
    for raw in re.findall(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?|\d+\.\d+|\d{2,})(?![\w])", text):
        try:
            found.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return found


def number_in_source(value: float, source: str) -> bool:
    if value is None:
        return False
    # Exact and rounded variants used in tables / OCR
    candidates = {
        f"{value:g}",
        f"{value:.1f}",
        f"{value:.2f}",
        f"{int(round(value))}",
        f"{value:,.1f}",
        f"{value:,.2f}",
    }
    blob = source.replace(",", "")
    compact = f"{value:.2f}".rstrip("0").rstrip(".")
    if compact and compact in blob:
        return True
    src_nums = extract_numbers(source)
    for n in src_nums:
        if value == 0:
            continue
        if abs(n - value) <= max(0.05, abs(value) * 0.006):
            return True
        if abs(n - value) < 1.05 and abs(value) >= 10:
            # OCR often drops decimals: 123.59 vs 124
            if abs(round(value) - round(n)) <= 1:
                return True
    for c in candidates:
        if c.replace(",", "") in blob:
            return True
    return False


def headline_metrics(text: str) -> dict:
    t = text.replace("\n", " ")
    out = {}
    m = re.search(r"CMP\s*Rs\.?\s*([\d,.]+)", t, re.I)
    if m:
        out["cmp"] = float(m.group(1).replace(",", ""))
    m = re.search(r"Target\s*Rs\.?\s*([\d,.]+)", t, re.I)
    if m:
        out["target"] = float(m.group(1).replace(",", ""))
    m = re.search(r"FY26E EPS[^\n]{0,40}?Rs\.?\s*([\d.]+)\s*[×x]\s*([\d.]+)", t, re.I)
    if m:
        out["eps_fy26e"] = float(m.group(1))
        out["pe"] = float(m.group(2))
    # Latest-quarter PAT / NII / Revenue from table-ish lines
    m = re.search(r"PAT[^\n]{0,40}?(\d{2,5}\.\d{1,2})", t)
    if m:
        out["pat_q"] = float(m.group(1))
    m = re.search(r"\bNII[^\n]{0,40}?(\d{2,5}\.\d{1,2})", t)
    if m:
        out["nii_q"] = float(m.group(1))
    m = re.search(r"Revenue[^\n]{0,40}?(\d{2,6}\.\d{1,2})", t)
    if m:
        out["rev_q"] = float(m.group(1))
    m = re.search(r"\bNIM\s+(\d+\.\d+)%", t)
    if m:
        out["nim"] = float(m.group(1))
    m = re.search(r"\bGNPA\s+(\d+\.\d+)%", t)
    if m:
        out["gnpa"] = float(m.group(1))
    m = re.search(r"Adj EPS[^\n]{0,80}?(\d+\.\d)", t)
    if m:
        out["eps_q"] = float(m.group(1))
    return out


def writing_flags(text: str) -> list[str]:
    flags = []
    low = text.lower()
    if re.search(r"\bwe (buy|sell|recommend|maintain a (buy|hold|sell))\b", low):
        flags.append("Sounds like a human analyst recommendation")
    if " hold" in low and "not rated" in low and re.search(r"\bHOLD\b", text):
        if "Investment Rating Criteria" not in text.split("HOLD")[0][-80:]:
            flags.append("HOLD appears outside the rating-criteria table")
    for term in OFFTOPIC:
        if term in low and "icici" in low:
            flags.append(f"Off-topic leak: {term}")
    if re.search(r"target of\s+(The |the |—)", text):
        flags.append("Broken 'target of The…' fragment")
    for pat in PLACEHOLDERS:
        if re.search(pat, text):
            flags.append(f"Placeholder leaked: {pat}")
            break
    # Incomplete last sentence on page 1 narrative
    if re.search(r"\b(target of|upside of)\s*$", text.strip(), re.I | re.M):
        flags.append("Truncated valuation sentence")
    return flags


def presentation_flags(text: str, pages: int, images: int) -> list[str]:
    flags = []
    if pages != 4:
        flags.append(f"Page count is {pages}, sample is 4")
    if images < 2:
        flags.append(f"Few/no charts (image objects={images})")
    if "NOT RATED" not in text and "NOT\nRATED" not in text:
        flags.append("Missing NOT RATED badge")
    if re.search(r"\bBUY\b", text) and "Investment Rating Criteria" in text:
        pass  # criteria table is allowed
    if "AI-generated narrative" not in text and "AI-generated" not in text:
        flags.append("Missing AI-narrative disclaimer")
    if "Not available in source document" not in text and "not present in the source" not in text.lower():
        flags.append("No explicit missing-data language")
    if "FY26E EPS" in text:
        flags.append("Invented FY26E EPS × P/E formula still on page")
    return flags


def main():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for out_name, src_name, company in PAIRS:
        out_path = OUT_DIR / out_name
        src_path = SRC_DIR / src_name
        rec = {
            "company": company,
            "report": out_name,
            "source": src_name,
            "exists": out_path.exists() and src_path.exists(),
        }
        if not rec["exists"]:
            rec["error"] = "missing file"
            reports.append(rec)
            continue

        n_pages, page_texts, n_images = pdf_text_embedded(out_path)
        report_text = "\n".join(page_texts)
        rec["pages"] = n_pages
        rec["images"] = n_images
        rec["report_chars"] = len(report_text)
        rec["previews"] = render_pages(out_path, Path(out_name).stem, 2)

        print(f"\n=== OCR report: {out_name} ===")
        ocr_report = extract_pdf_azure_di(str(out_path)) or report_text
        rec["ocr_report_chars"] = len(ocr_report)
        combined_report = report_text + "\n" + ocr_report

        print(f"=== OCR source: {src_name} ===")
        ocr_source = extract_pdf_azure_di(str(src_path))
        rec["ocr_source_chars"] = len(ocr_source or "")
        source_blob = ocr_source or ""

        metrics = headline_metrics(combined_report)
        rec["metrics"] = metrics
        verified = {}
        unverified = []
        skip = {"cmp", "target", "eps_fy26e", "pe"}  # live market / model, not source
        for key, val in metrics.items():
            if key in skip:
                verified[key] = "live/model"
                continue
            ok = number_in_source(val, source_blob)
            verified[key] = "source" if ok else "NOT IN SOURCE"
            if not ok:
                unverified.append(f"{key}={val}")
        rec["metric_check"] = verified
        rec["unverified_source_numbers"] = unverified

        rec["writing"] = writing_flags(combined_report)
        rec["presentation"] = presentation_flags(combined_report, n_pages, n_images)
        rec["has_not_rated"] = "NOT RATED" in combined_report or "NOT\nRATED" in combined_report
        rec["has_hold_badge"] = bool(re.search(r"rec-hold|\bHOLD\b", combined_report)) and "NOT RATED" not in combined_report[:800]
        rec["page1_excerpt"] = page_texts[0][:1800] if page_texts else ""
        rec["stamp"] = None
        m = re.search(r"(\d+)/(\d+)\s+values confirmed", combined_report, re.I)
        if m:
            rec["stamp"] = f"{m.group(1)}/{m.group(2)}"
        rec["issues"] = rec["writing"] + rec["presentation"] + [
            f"Source mismatch: {x}" for x in unverified
        ]
        reports.append(rec)
        print(f"  pages={n_pages} images={n_images} stamp={rec['stamp']} issues={rec['issues']}")

    out = ROOT / "tmp" / "founder_audit.json"
    out.write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
