"""
run_ltts_pipeline.py — Process LTTS Q2FY26.pdf through full 14-Stage pipeline and audit against source
"""
import asyncio
import os
import sys
from pathlib import Path
from starlette.datastructures import Headers
from fastapi import UploadFile

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import main

async def run():
    pdf_path = "PDF/LTTS Q2FY26.pdf"
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    print("=========================================================================")
    print("  RUNNING 14-STAGE PIPELINE ON REAL PDF: PDF/LTTS Q2FY26.pdf")
    print("=========================================================================\n")

    with open(pdf_path, "rb") as f:
        upload = UploadFile(
            filename="LTTS Q2FY26.pdf",
            file=f,
            headers=Headers({"content-type": "application/pdf"}),
        )
        res = await main.generate_report_endpoint(upload)

    print("\n=========================================================================")
    print(f"  ✅ PIPELINE SUCCESS: {res['status']}")
    print(f"  PDF Output Path : {res['pdf_path']}")
    print(f"  Recommendation : {res['recommendation']}")
    print("=========================================================================\n")

if __name__ == "__main__":
    asyncio.run(run())
