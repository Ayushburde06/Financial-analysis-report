"""
test_all_pdfs.py — Run pipeline on all 4 test PDFs and print a summary table.
"""
import asyncio
import os
import time
import sys
from pathlib import Path
from fastapi import UploadFile
from starlette.datastructures import Headers
import main

PDFS = [
    "PDF/ICICI Q2FY26.pdf",
    "PDF/JSW Energy Q2FY26.pdf",
    "PDF/LTTS Q2FY26.pdf",
    "PDF/POCL Q2FY26.pdf",
]

async def run_one(pdf_path: str) -> dict:
    filename = os.path.basename(pdf_path)
    start = time.time()
    result = {"pdf": filename, "sector": "?", "score": "?", "recommendation": "?",
              "fact_check": "?", "time": 0, "status": "❌ FAILED", "error": ""}
    try:
        with open(pdf_path, "rb") as stream:
            upload = UploadFile(
                filename=filename,
                file=stream,
                headers=Headers({"content-type": "application/pdf"}),
            )
            r = await main.generate_report_endpoint(upload)
        result["status"]         = "✅ OK"
        result["recommendation"] = r.get("recommendation", "?")
        result["time"]           = round(time.time() - start, 1)
    except Exception as exc:
        result["error"] = str(exc)[:80]
        result["time"]  = round(time.time() - start, 1)
    return result

async def main_test():
    sys.stdout.reconfigure(encoding="utf-8")
    results = []
    for pdf in PDFS:
        if not os.path.isfile(pdf):
            print(f"⚠  SKIP {pdf} — file not found")
            continue
        print(f"\n{'='*60}")
        print(f"  Running: {os.path.basename(pdf)}")
        print(f"{'='*60}")
        r = await run_one(pdf)
        results.append(r)

    # Summary table
    print("\n\n" + "="*72)
    print(f"  {'PDF':<28} {'Status':<10} {'Rec':<12} {'Time':>7}")
    print("="*72)
    for r in results:
        print(f"  {r['pdf']:<28} {r['status']:<10} {r['recommendation']:<12} {r['time']:>6}s")
        if r["error"]:
            print(f"    ↳ {r['error']}")
    print("="*72)
    passed = sum(1 for r in results if "OK" in r["status"])
    print(f"  RESULT: {passed}/{len(results)} passed\n")

if __name__ == "__main__":
    asyncio.run(main_test())
