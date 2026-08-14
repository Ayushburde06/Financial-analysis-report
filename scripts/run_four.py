"""Generate the four assignment test PDFs sequentially."""
import asyncio
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

from fastapi import UploadFile
from starlette.datastructures import Headers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_DIR = ROOT / "submission" / "reports"

PAIRS = [
    ("PDF/ICICI Q2FY26.pdf", "ICICI Bank"),
    ("PDF/LTTS Q2FY26.pdf", "LTTS"),
    ("PDF/JSW Energy Q2FY26.pdf", "JSW Energy"),
    ("PDF/POCL Q2FY26.pdf", "POCL"),
]


def copy_to_submission(pdf_filename: str) -> str:
    """Copy the generated Equity Report into submission/reports/."""
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    src = ROOT / "outputs" / pdf_filename
    if not src.is_file():
        return ""
    dest_equity = SUBMISSION_DIR / pdf_filename
    dest_geojit = SUBMISSION_DIR / pdf_filename.replace(
        "_Equity_Report.pdf", "_Geojit_Report.pdf"
    )
    shutil.copy2(src, dest_equity)
    shutil.copy2(src, dest_geojit)
    print(f"  COPIED -> {dest_equity}")
    print(f"  COPIED -> {dest_geojit}")
    return str(dest_geojit)


async def generate_one(pdf_path: str, company_name: str) -> dict:
    filename = os.path.basename(pdf_path)
    started = time.time()
    print("\n" + "=" * 70)
    print(f"  START {filename}  as  {company_name}")
    print("=" * 70)
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
        elapsed = time.time() - started
        pdf_filename = result.get("pdf_filename") or ""
        submission_path = copy_to_submission(pdf_filename) if pdf_filename else ""
        print(f"  OK {filename} in {elapsed:.0f}s -> {pdf_filename}")
        return {
            "file": filename,
            "ok": True,
            "elapsed": elapsed,
            "submission_path": submission_path,
            **result,
        }
    except Exception as exc:
        elapsed = time.time() - started
        print(f"  FAIL {filename} after {elapsed:.0f}s: {exc}")
        traceback.print_exc()
        return {"file": filename, "ok": False, "elapsed": elapsed, "error": str(exc)}


async def main_async() -> None:
    summary = []
    for path, name in PAIRS:
        if not os.path.isfile(path):
            summary.append({"file": path, "ok": False, "error": "missing"})
            continue
        summary.append(await generate_one(path, name))
    print("\n" + "=" * 70)
    print("  BATCH SUMMARY")
    for row in summary:
        status = "OK" if row.get("ok") else "FAIL"
        print(f"  {status:4}  {row.get('file')}  {row.get('elapsed', 0):.0f}s  {row.get('error', row.get('submission_path') or row.get('pdf_filename', ''))}")
    print("=" * 70)
    if any(not row.get("ok") for row in summary):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main_async())
