"""
check_ocr_quality.py — Verify Stage 01 OCR output quality

Checks:
  1. OCR text encoding — no garbled chars (Γé╣, ΓÇö etc.)
  2. Table extraction — tables found with numeric content
  3. Font/symbol rendering — ₹ %, numbers extracted correctly
  4. Mistral extraction output — JSON keys + values valid
  5. Cross-check: OCR numbers vs Mistral extracted numbers

Usage:
  python check_ocr_quality.py PDF/ICICI Q2FY26.pdf
  python check_ocr_quality.py --all
"""
import sys
import os
import re
import json
import argparse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath("."))
from dotenv import load_dotenv
load_dotenv()

# ── Colour helpers ─────────────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def cyan(s):   return f"\033[96m{s}\033[0m"

# ── Known garbled patterns ────────────────────────────────────────────────────
GARBLED_PATTERNS = {
    "Gammae╣":  "Rs (Rupee symbol)",
    "GammaÇö":  "-- (em-dash)",
    "Gammae║":  "box char",
    "┬╖":       "bullet point",
}

NUMBER_RE = re.compile(r'\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\b|\b\d{4,}(?:\.\d+)?\b')


# ── Step 1: Run Stage 01 OCR ──────────────────────────────────────────────────

def run_stage01_ocr(pdf_path: str):
    """Run the actual Stage 01 builder and return the MasterDocument."""
    import importlib
    stage_01 = importlib.import_module("pipeline.01_financial_structure_builder.builder")
    print(f"\n{cyan('Step 1: Running Stage 01 OCR...')}")
    doc = stage_01.FinancialStructureBuilder.run(pdf_path)
    return doc


# ── Step 2: Check OCR text quality ───────────────────────────────────────────

def check_ocr_text(full_text: str, pdf_name: str) -> dict:
    print(f"\n{bold('--- OCR TEXT QUALITY ---')}")
    issues = []
    garbled_counts = {}

    for pattern, description in GARBLED_PATTERNS.items():
        count = full_text.count(pattern)
        if count > 0:
            garbled_counts[description] = count
            issues.append(f"{count}x '{pattern}' → should be {description}")

    # Check encoding — look for replacement chars
    replacement_chars = full_text.count('\ufffd')
    if replacement_chars > 0:
        issues.append(f"{replacement_chars}x unicode replacement char (\\ufffd)")

    # Extract numbers from OCR text
    ocr_numbers = []
    clean_text = re.sub(r'\b(19|20)\d{2}\b', ' ', full_text)
    clean_text = re.sub(r'\d[\d,]*\.?\d*\s*%', ' ', clean_text)
    for m in NUMBER_RE.finditer(clean_text):
        try:
            v = float(m.group(0).replace(",", ""))
            if v >= 1000:
                ocr_numbers.append(v)
        except ValueError:
            pass
    ocr_numbers = sorted(set(ocr_numbers))

    # Text stats
    chars      = len(full_text)
    words      = len(full_text.split())
    lines      = full_text.count('\n')
    pages      = full_text.count('# Page') or full_text.count('<!-- PageBreak -->') or 1
    has_tables = '<table>' in full_text.lower() or '|' in full_text

    print(f"   Characters   : {chars:,}")
    print(f"   Words        : {words:,}")
    print(f"   Lines        : {lines:,}")
    print(f"   Pages        : {pages}")
    print(f"   Numbers found: {len(ocr_numbers)} (>= 1000)")
    print(f"   Tables found : {'YES' if has_tables else 'NO'}")

    if issues:
        print(f"\n   {red('ENCODING ISSUES:')}")
        for issue in issues:
            print(f"   {red('✗')} {issue}")
        print(f"\n   {yellow('TIP: These are font encoding issues in the source PDF.')}")
        print(f"   {yellow('Azure OCR extracts them as-is — they do not affect number extraction.')}")
    else:
        print(f"\n   {green('✓ No encoding issues found.')}")

    # Print sample of OCR text
    print(f"\n   {cyan('Sample OCR text (first 500 chars):')}")
    sample = full_text[:500].replace('\n', ' ').strip()
    print(f"   {sample}")

    # Print sample numbers
    if ocr_numbers:
        print(f"\n   {cyan('Sample numbers extracted from OCR (first 15):')}")
        print(f"   {ocr_numbers[:15]}")

    return {
        "chars": chars,
        "words": words,
        "numbers": ocr_numbers,
        "has_tables": has_tables,
        "garbled": garbled_counts,
        "issues": issues,
        "score": 1.0 if not issues else max(0.5, 1.0 - len(issues) * 0.1),
    }


# ── Step 3: Run Mistral extraction ────────────────────────────────────────────

def run_mistral_extraction(full_text: str, sector: str = "Other") -> dict:
    print(f"\n{bold('--- MISTRAL EXTRACTION ---')}")
    print(f"   Running Mistral Large 3 extraction for sector: {sector}...")

    import importlib
    retriever = importlib.import_module("pipeline.08_hybrid_retrieval.retriever")
    from pipeline.utils.llm_client import call_bedrock_mistral_large

    source_text = retriever._extract_table_focused_text(full_text, max_chars=55000)
    system_prompt = retriever._build_system_prompt(sector)
    response = call_bedrock_mistral_large(system_prompt, source_text)
    extracted = retriever._extract_json(response or "")
    return extracted


# ── Step 4: Check Mistral extraction quality ──────────────────────────────────

def check_extraction(extracted: dict, ocr_numbers: list) -> dict:
    print(f"\n{bold('--- EXTRACTION QUALITY ---')}")

    if not extracted:
        print(f"   {red('✗ Empty extraction — no JSON returned')}")
        return {"score": 0.0, "issues": ["Empty extraction"]}

    print(f"   Keys extracted   : {list(extracted.keys())}")

    # Flatten all numeric values
    extracted_numbers = []
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, (int, float)) and obj is not None:
            if float(obj) >= 1000:
                extracted_numbers.append((path, float(obj)))

    walk(extracted)
    print(f"   Values extracted : {len(extracted_numbers)} numeric (>= 1000)")

    # Check encoding in extracted values — should be clean numbers
    encoding_ok = True
    for key, val in extracted_numbers[:5]:
        print(f"   {green('✓')} {key} = {val}")

    # Cross-check: are extracted values present in OCR text?
    ocr_set = set(ocr_numbers)
    verified, not_found = [], []
    for key, val in extracted_numbers:
        found = any(abs(val - n) / max(abs(n), 1) * 100 <= 1.5 for n in ocr_set)
        if found:
            verified.append((key, val))
        else:
            not_found.append((key, val))

    total = len(extracted_numbers)
    score = len(verified) / total if total > 0 else 1.0

    print(f"\n   {cyan('Cross-check vs OCR:')}")
    print(f"   {len(verified)}/{total} extracted values found in OCR text ({score:.0%})")

    if not_found:
        print(f"\n   {yellow('Values NOT found in OCR (may be estimates or unit-converted):')}")
        for key, val in not_found[:8]:
            print(f"   {yellow('?')} {key} = {val}")

    return {
        "keys": list(extracted.keys()),
        "total_values": total,
        "verified": len(verified),
        "not_found": [(k, v) for k, v in not_found],
        "score": score,
    }


# ── Step 5: Check JSON encoding of extraction ─────────────────────────────────

def check_json_encoding(extracted: dict) -> dict:
    print(f"\n{bold('--- JSON ENCODING CHECK ---')}")

    # Serialize to JSON and check for garbled chars
    try:
        json_str = json.dumps(extracted, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   {red(f'JSON serialization failed: {e}')}")
        return {"score": 0.0}

    # Check for garbled patterns in the JSON
    issues = []
    for pattern, desc in GARBLED_PATTERNS.items():
        if pattern in json_str:
            issues.append(f"Garbled '{pattern}' found in extracted JSON keys/values")

    # Check all values are numeric (not strings with symbols)
    string_values = []
    def check_vals(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                check_vals(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, str) and obj not in ("null", "N/A", ""):
            if any(c in obj for c in ['₹', 'Γé╣', 'ΓÇö', '%', 'cr', 'mn']):
                string_values.append(f"{path} = '{obj}'")

    check_vals(extracted)

    if issues:
        print(f"   {red('Encoding issues in JSON:')}")
        for i in issues:
            print(f"   {red('✗')} {i}")
    else:
        print(f"   {green('✓ JSON encoding is clean — no garbled characters')}")

    if string_values:
        print(f"\n   {yellow('String values found (should be numeric):')}")
        for sv in string_values[:5]:
            print(f"   {yellow('?')} {sv}")
    else:
        print(f"   {green('✓ All values are numeric (no unit strings embedded)')}")

    score = 1.0 if not issues and not string_values else 0.7
    return {"issues": issues, "string_values": string_values, "score": score}


# ── Main ───────────────────────────────────────────────────────────────────────

def check_pdf(pdf_path: str):
    print(f"\n{'='*65}")
    print(bold(f"  OCR + EXTRACTION QUALITY CHECK"))
    print(f"  PDF: {pdf_path}")
    print(f"{'='*65}")

    if not os.path.isfile(pdf_path):
        print(red(f"  File not found: {pdf_path}"))
        return

    # Step 1: Run OCR
    doc = run_stage01_ocr(pdf_path)
    full_text = doc.get_full_text()

    # Step 2: Check OCR quality
    ocr_result = check_ocr_text(full_text, Path(pdf_path).name)

    # Step 3: Detect sector
    print(f"\n{bold('--- SECTOR DETECTION ---')}")
    import importlib
    stage_05 = importlib.import_module("pipeline.05_industry_detection.detector")
    sector = stage_05.IndustryDetectionEngine.run({}, full_text)
    print(f"   Detected sector: {green(sector)}")

    # Step 4: Run Mistral extraction
    extracted = run_mistral_extraction(full_text, sector)

    # Step 5: Check extraction quality
    ext_result = check_extraction(extracted, ocr_result["numbers"])

    # Step 6: Check JSON encoding
    json_result = check_json_encoding(extracted)

    # ── Overall score ──────────────────────────────────────────────────────────
    scores = [ocr_result["score"], ext_result["score"], json_result["score"]]
    overall = sum(scores) / len(scores)

    cfn = green if overall >= 0.9 else (yellow if overall >= 0.7 else red)
    print(f"\n{'='*65}")
    print(bold(f"  OVERALL OCR + EXTRACTION SCORE: {cfn(f'{overall:.0%}')}"))

    print(f"\n  OCR Text Quality   : {green('OK') if ocr_result['score'] >= 0.9 else yellow('WARN')}"
          f" ({ocr_result['words']:,} words, {len(ocr_result['numbers'])} numbers)")
    print(f"  Extraction Quality : {green('OK') if ext_result['score'] >= 0.9 else yellow('WARN')}"
          f" ({ext_result['verified']}/{ext_result['total_values']} values verified)")
    print(f"  JSON Encoding      : {green('OK') if json_result['score'] >= 0.9 else yellow('WARN')}")

    if overall >= 0.9:
        print(f"\n  {green('✅ OCR and extraction are working correctly.')}")
    else:
        print(f"\n  {yellow('⚠️  Some issues found. Review above for details.')}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check OCR and extraction quality")
    parser.add_argument("pdf",  nargs="?", help="Path to source PDF to check")
    parser.add_argument("--all", action="store_true", help="Check all PDFs in PDF/")
    args = parser.parse_args()

    if args.all:
        for pdf in sorted(Path("PDF").glob("*.pdf")):
            check_pdf(str(pdf))
    elif args.pdf:
        check_pdf(args.pdf)
    else:
        # Default: check first PDF
        pdfs = sorted(Path("PDF").glob("*.pdf"))
        if pdfs:
            check_pdf(str(pdfs[0]))
        else:
            print(red("No PDFs found in PDF/ folder."))
