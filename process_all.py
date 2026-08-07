import sys
import os
import asyncio
from fastapi import UploadFile
from starlette.datastructures import Headers

# Import the main pipeline module
import main

async def process_all_pdfs():
    pdf_dir = "PDF"
    if not os.path.exists(pdf_dir):
        print(f"Error: Directory {pdf_dir} does not exist.")
        return
        
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
        if not target_file.lower().endswith('.pdf'):
            target_file += '.pdf'
        pdf_files = [target_file] if os.path.exists(os.path.join(pdf_dir, target_file)) else []
        if not pdf_files:
            print(f"Error: Specified file {target_file} not found in {pdf_dir}.")
            return
    else:
        pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
        
    if not pdf_files:
        print(f"No PDF files found.")
        return
        
    print(f"Found {len(pdf_files)} PDFs to process.\n")
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        print(f"{'='*50}\nStarting Full Data Extraction & Equity Report Formatting for: {pdf_file}\n{'='*50}")
        
        try:
            with open(pdf_path, "rb") as f:
                # Replace spaces in filename for safety in logs/outputs
                safe_name = pdf_file.replace(" ", "_")
                upload_file = UploadFile(filename=safe_name, file=f, headers=Headers({'content-type': 'application/pdf'}))
                
                response = await main.generate_report_endpoint(upload_file)
                print(f"Successfully processed {pdf_file}.\n")
        except Exception as e:
            print(f"Failed to process {pdf_file}. Error: {e}\n")

if __name__ == "__main__":
    asyncio.run(process_all_pdfs())
