"""Batch entry point for the active report-generation pipeline."""
import asyncio
import os

from fastapi import UploadFile
from starlette.datastructures import Headers

import main


async def process_single_pdf(pdf_path: str) -> dict:
    filename = os.path.basename(pdf_path)
    with open(pdf_path, "rb") as stream:
        upload = UploadFile(
            filename=filename,
            file=stream,
            headers=Headers({"content-type": "application/pdf"}),
        )
        return await main.generate_report_endpoint(upload)


async def run_batch(pdf_dir: str = "PDF") -> None:
    pdf_files = sorted(
        os.path.join(pdf_dir, name)
        for name in os.listdir(pdf_dir)
        if name.lower().endswith(".pdf")
    )
    if not pdf_files:
        print(f"No PDF files found in {pdf_dir}.")
        return

    for pdf_path in pdf_files:
        print(f"Processing {os.path.basename(pdf_path)}")
        try:
            result = await process_single_pdf(pdf_path)
            print(f"Generated: {result.get('pdf_path')}\n")
        except Exception as exc:
            print(f"Failed: {pdf_path}: {exc}\n")


if __name__ == "__main__":
    asyncio.run(run_batch())
