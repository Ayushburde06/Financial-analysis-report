import sys
import os
import asyncio
from fastapi import UploadFile
from starlette.datastructures import Headers

# Import the main pipeline module
import main

async def run_pipeline():
    pdf_path = os.path.join("PDF", "ICICI Q2FY26.pdf")
    if not os.path.exists(pdf_path):
        print(f"Error: Could not find {pdf_path}")
        return
        
    print(f"Starting test run for {pdf_path}")
    
    # Mock UploadFile
    with open(pdf_path, "rb") as f:
        # UploadFile takes a spooled temp file or standard file object
        upload_file = UploadFile(filename="ICICI_Q2FY26.pdf", file=f, headers=Headers({'content-type': 'application/pdf'}))
        
        # Run the endpoint directly
        response = await main.generate_report_endpoint(upload_file)
        
        print("Pipeline finished successfully!")
        print("Response:", response)
        
if __name__ == "__main__":
    asyncio.run(run_pipeline())
