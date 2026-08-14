"""
run_one.py — Generate report for a single PDF.
Usage: python run_one.py
Processes the first PDF found in the PDF folder.
Works for ANY PDF uploaded — not hardcoded to specific files.
"""
import asyncio
import os
import re
import time
import sys
from pathlib import Path
from fastapi import UploadFile
from starlette.datastructures import Headers
import main


def find_first_source_pdf(pdf_dir: str = "PDF") -> str | None:
    """Find the first source PDF in the folder (skip generated reports)."""
    if not os.path.isdir(pdf_dir):
        return None
    for name in sorted(os.listdir(pdf_dir)):
        lower = name.lower()
        if not lower.endswith(".pdf"):
            continue
        if "_equity_report" in lower or "geojit_report" in lower:
            continue
        return os.path.join(pdf_dir, name)
    return None


def company_name_from_pdf(pdf_path: str) -> str:
    stem = Path(pdf_path).stem
    name = re.split(r"\s*Q[1-4]", stem, flags=re.I)[0].strip()
    return name or ""


async def run_one(pdf_path: str, company_name: str) -> None:
    filename = os.path.basename(pdf_path)
    size_mb = os.path.getsize(pdf_path) / (1024 * 1024)

    print("=" * 70)
    print(f"  PDF      : {filename}")
    print(f"  Company  : {company_name}")
    print(f"  Size     : {size_mb:.2f} MB")
    print(f"  Started  : {time.strftime('%H:%M:%S')}")
    print("=" * 70)

    start = time.time()

    try:
        with open(pdf_path, "rb") as stream:
            upload = UploadFile(
                filename=filename,
                file=stream,
                headers=Headers({"content-type": "application/pdf"}),
            )
            result = await main.generate_report_endpoint(
                upload, company_name=company_name
            )

        elapsed = time.time() - start
        print("\n" + "=" * 70)
        print("  ✅ SUCCESS")
        print(f"  Output      : {result.get('pdf_path')}")
        print(f"  Recommend   : {result.get('recommendation')}")
        print(f"  Time        : {elapsed:.1f}s ({elapsed/60:.1f} min)")
        print("=" * 70)

    except Exception as exc:
        elapsed = time.time() - start
        print("\n" + "=" * 70)
        print(f"  ❌ FAILED after {elapsed:.1f}s")
        print(f"  Error : {exc}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # python scripts/run_one.py [path/to/file.pdf] [Company Name]
    if len(sys.argv) > 1:
        pdf = sys.argv[1]
        if not os.path.isfile(pdf):
            print(f"❌ File not found: {pdf}")
            sys.exit(1)
    else:
        pdf = find_first_source_pdf("PDF")
        if not pdf:
            print("❌ No PDFs found in ./PDF folder.")
            sys.exit(1)

    company = sys.argv[2] if len(sys.argv) > 2 else company_name_from_pdf(pdf)
    asyncio.run(run_one(pdf, company))
