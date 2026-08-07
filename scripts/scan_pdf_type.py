"""
Scan PDFs to determine if they are digital (selectable text) or scanned (image-only).
This helps identify which PDFs need OCR and which can use free local extraction.
"""
import os
import sys
from pathlib import Path

# Try PyPDF2 first (if available)
try:
    import PyPDF2
    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False
    print("⚠️  PyPDF2 not installed. Using pdfplumber for text extraction.")

# Try pdfplumber
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    print("⚠️  pdfplumber not installed. Installing...")
    os.system("pip install pdfplumber -q")
    import pdfplumber
    HAS_PDFPLUMBER = True

# Try PyMuPDF
try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("⚠️  PyMuPDF not installed. Installing...")
    os.system("pip install pymupdf -q")
    try:
        import fitz
        HAS_PYMUPDF = True
    except:
        HAS_PYMUPDF = False


def check_pdf_type_pdfplumber(pdf_path: str) -> tuple:
    """Check if PDF is digital or scanned using pdfplumber."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            
            # Sample first 3 pages
            sample_pages = min(3, total_pages)
            total_extracted_chars = 0
            
            for i in range(sample_pages):
                page = pdf.pages[i]
                text = page.extract_text() or ""
                total_extracted_chars += len(text.strip())
            
            # If we got significant text, it's digital
            is_digital = total_extracted_chars > 100  # More than 100 chars in 3 pages
            
            return is_digital, total_pages, total_extracted_chars
    except Exception as e:
        return None, None, f"Error: {e}"


def check_pdf_type_pymupdf(pdf_path: str) -> tuple:
    """Check if PDF is digital or scanned using PyMuPDF."""
    if not HAS_PYMUPDF:
        return None, None, "PyMuPDF not available"
    
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        
        # Sample first 3 pages
        sample_pages = min(3, total_pages)
        total_extracted_chars = 0
        
        for i in range(sample_pages):
            page = doc[i]
            text = page.get_text()
            total_extracted_chars += len(text.strip())
        
        doc.close()
        
        # If we got significant text, it's digital
        is_digital = total_extracted_chars > 100
        
        return is_digital, total_pages, total_extracted_chars
    except Exception as e:
        return None, None, f"Error: {e}"


def analyze_pdfs(pdf_dir: str = "PDF") -> None:
    """Analyze all PDFs in a directory."""
    print("=" * 80)
    print("PDF TYPE SCANNER - Digital vs. Scanned Detection")
    print("=" * 80)
    print()
    
    if not os.path.isdir(pdf_dir):
        print(f"❌ PDF folder not found: {pdf_dir}")
        return
    
    pdf_files = sorted([f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")])
    
    if not pdf_files:
        print(f"❌ No PDFs found in {pdf_dir}")
        return
    
    print(f"📁 Found {len(pdf_files)} PDF(s) in '{pdf_dir}'\n")
    
    total_pages_digital = 0
    total_pages_scanned = 0
    total_pages_unknown = 0
    
    for idx, pdf_file in enumerate(pdf_files, 1):
        pdf_path = os.path.join(pdf_dir, pdf_file)
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        
        print(f"[{idx}] {pdf_file}")
        print(f"    File size: {file_size_mb:.2f} MB")
        
        # Try pdfplumber first (most reliable)
        is_digital, total_pages, extracted_chars = check_pdf_type_pdfplumber(pdf_path)
        
        if is_digital is None:
            print(f"    ❓ Status: UNKNOWN (Error: {extracted_chars})")
            total_pages_unknown += total_pages if isinstance(total_pages, int) else 0
        else:
            print(f"    Pages: {total_pages}")
            print(f"    Extracted text: {extracted_chars} characters (from first 3 pages)")
            
            if is_digital:
                print(f"    ✅ TYPE: DIGITAL PDF (selectable text)")
                print(f"    💰 OCR Cost: $0.00 (use PyMuPDF/pdfplumber)")
                print(f"    ⚡ Speed: < 1 second")
                total_pages_digital += total_pages
            else:
                print(f"    ❌ TYPE: SCANNED PDF (image-only)")
                print(f"    💰 OCR Cost: ${total_pages * 0.01:.2f} (use Azure Document Intelligence)")
                print(f"    ⏱️  Speed: 5-10 seconds")
                total_pages_scanned += total_pages
        
        print()
    
    # Summary
    print("=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print(f"Total PDFs analyzed: {len(pdf_files)}")
    print(f"Total Digital PDF pages: {total_pages_digital} ({(total_pages_digital/(total_pages_digital+total_pages_scanned)*100 if total_pages_digital+total_pages_scanned > 0 else 0):.1f}%)")
    print(f"Total Scanned PDF pages: {total_pages_scanned} ({(total_pages_scanned/(total_pages_digital+total_pages_scanned)*100 if total_pages_digital+total_pages_scanned > 0 else 0):.1f}%)")
    
    total_pages = total_pages_digital + total_pages_scanned
    if total_pages > 0:
        ocr_cost_without_hybrid = total_pages * 0.01
        ocr_cost_with_hybrid = total_pages_scanned * 0.01
        savings = ocr_cost_without_hybrid - ocr_cost_with_hybrid
        
        print()
        print("💰 COST ANALYSIS:")
        print(f"  Without hybrid router: ${ocr_cost_without_hybrid:.2f} (all pages via Azure DI)")
        print(f"  With hybrid router:    ${ocr_cost_with_hybrid:.2f} (scanned PDFs only)")
        print(f"  💾 Potential savings:   ${savings:.2f} ({(savings/ocr_cost_without_hybrid*100):.1f}%)")
    
    print()
    print("=" * 80)
    print("✅ RECOMMENDATION:")
    if total_pages_digital > total_pages_scanned:
        print("✅ Your PDFs are mostly DIGITAL! Implement hybrid router for 80-90% cost savings.")
    else:
        print("⚠️  Your PDFs are mostly SCANNED. OCR cost optimization may be limited.")
    print("=" * 80)


if __name__ == "__main__":
    # Check current directory
    pdf_folder = "PDF" if os.path.isdir("PDF") else "./PDF"
    
    if not os.path.isdir(pdf_folder):
        # Try absolute path from workspace
        pdf_folder = "c:\\Users\\Ayush123\\Desktop\\billeyeee\\PDF"
    
    analyze_pdfs(pdf_folder)
