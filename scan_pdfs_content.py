"""
Scan PDFs using Azure Document Intelligence (prebuilt-layout)
Extract content from all PDFs in the PDF folder
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def scan_pdf_with_azure(pdf_path: str) -> dict:
    """Scan a single PDF using Azure Document Intelligence."""
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential
    
    endpoint = os.getenv("AZURE_DOC_INTEL_ENDPOINT")
    key = os.getenv("AZURE_DOC_INTEL_KEY")
    
    if not endpoint or not key:
        return {"error": "Azure credentials not found"}
    
    client = DocumentIntelligenceClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )
    
    filename = Path(pdf_path).name
    print(f"\n📄 Scanning: {filename}")
    print(f"   Path: {pdf_path}")
    
    try:
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        
        print(f"   ⏳ Uploading to Azure ({len(pdf_bytes) / 1024 / 1024:.2f} MB)...")
        
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            body=pdf_bytes,
            content_type="application/octet-stream",
            output_content_format="markdown"
        )
        
        print(f"   ⏳ Processing...")
        result = poller.result()
        
        # Extract key information
        pages = len(result.pages) if result.pages else 0
        content_length = len(result.content) if result.content else 0
        
        print(f"   ✅ Success!")
        print(f"   Pages: {pages}")
        print(f"   Content length: {content_length} characters")
        
        # Return summary
        return {
            "filename": filename,
            "pages": pages,
            "content_length": content_length,
            "content_preview": result.content[:500] if result.content else "",
            "status": "success"
        }
    
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return {
            "filename": filename,
            "status": "error",
            "error": str(e)
        }


def scan_all_pdfs(pdf_dir: str = "PDF") -> None:
    """Scan all PDFs in a directory."""
    print("=" * 80)
    print("🔍 PDF SCANNER - Azure Document Intelligence")
    print("=" * 80)
    
    if not os.path.isdir(pdf_dir):
        print(f"❌ PDF folder not found: {pdf_dir}")
        return
    
    pdf_files = sorted([f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")])
    
    if not pdf_files:
        print(f"❌ No PDFs found in {pdf_dir}")
        return
    
    print(f"\n📁 Found {len(pdf_files)} PDF(s) in '{pdf_dir}'")
    
    results = []
    total_pages = 0
    total_cost = 0
    
    for pdf_file in pdf_files:
        pdf_path = os.path.join(pdf_dir, pdf_file)
        result = scan_pdf_with_azure(pdf_path)
        results.append(result)
        
        if result.get("status") == "success":
            pages = result.get("pages", 0)
            total_pages += pages
            cost = pages * 0.01
            total_cost += cost
            print(f"   💰 Cost: ${cost:.2f}")
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 SCANNING SUMMARY")
    print("=" * 80)
    
    successful = len([r for r in results if r.get("status") == "success"])
    failed = len([r for r in results if r.get("status") == "error"])
    
    print(f"✅ Successfully scanned: {successful}/{len(results)} PDFs")
    if failed > 0:
        print(f"❌ Failed: {failed}/{len(results)} PDFs")
    
    print(f"\n📄 Total pages: {total_pages}")
    print(f"💰 Total cost: ${total_cost:.2f}")
    
    # Save results
    output_file = "scan_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✅ Results saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    pdf_folder = "PDF"
    
    if not os.path.isdir(pdf_folder):
        pdf_folder = "c:\\Users\\Ayush123\\Desktop\\billeyeee\\PDF"
    
    scan_all_pdfs(pdf_folder)
