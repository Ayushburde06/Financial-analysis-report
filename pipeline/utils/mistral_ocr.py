"""Mistral Document AI OCR — per-page document processing.

Uses the Azure Mistral Document AI OCR endpoint:
  POST https://{account}.services.ai.azure.com/providers/mistral/azure/ocr
"""
import os
import base64
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv(override=True)

_OCR_URL = os.getenv("AZURE_MISTRAL_OCR_ENDPOINT", "https://dhairyaazure.services.ai.azure.com/providers/mistral/azure/ocr")
_MISTRAL_API_KEY = os.getenv("AZURE_MISTRAL_OCR_KEY", "")
_MISTRAL_DEPLOYMENT = os.getenv("AZURE_MISTRAL_OCR_DEPLOYMENT", "mistral-document-ai-2512")


def _extract_markdown_from_response(data: dict) -> str:
    """Extract markdown text from the Mistral Document AI API response."""
    pages = data.get("pages", [])
    page_texts = []
    for page in pages:
        md = page.get("markdown", "")
        if md.strip():
            page_texts.append(md)
    return "\n\n".join(page_texts)


def _call_mistral_ocr(
    document_bytes: bytes,
    input_type: str = "document_url",
    filename: str = "document.pdf",
) -> str:
    """
    Call Mistral Document AI to extract text from a PDF or image.

    Args:
        document_bytes: Raw bytes of the PDF or image file.
        input_type: "document_url" for PDFs, "image_url" for images.
        filename: Original filename (for logging only).

    Returns:
        Extracted markdown text, or empty string on failure.
    """
    if not _MISTRAL_API_KEY:
        print("     [Mistral OCR] ERROR: AZURE_MISTRAL_OCR_KEY not set.")
        return ""

    doc_b64 = base64.b64encode(document_bytes).decode("utf-8")
    mime_prefix = "application/pdf" if input_type == "document_url" else "image/png"

    payload = {
        "model": _MISTRAL_DEPLOYMENT,
        "document": {
            "type": input_type,
            input_type: f"data:{mime_prefix};base64,{doc_b64}",
        },
        "include_image_base64": False,
        "table_format": "markdown",
    }

    headers = {
        "Content-Type": "application/json",
        "api-key": _MISTRAL_API_KEY,
    }

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"     [Mistral OCR] Calling ({input_type}) [Attempt {attempt}/{max_attempts}]...")
            response = requests.post(
                _OCR_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code == 200:
                # Guard: empty 200 = quota exhausted, don't retry
                if not response.text or len(response.text.strip()) == 0:
                    print("     [Mistral OCR] Empty 200 response — quota likely exhausted, stopping.")
                    return ""

                data = response.json()
                text = _extract_markdown_from_response(data)
                if text.strip():
                    print(f"     [Mistral OCR] Extraction complete ({len(text)} chars).")
                    return text
                print("     [Mistral OCR] WARNING: Empty markdown in response.")

            elif response.status_code in (429, 503):
                delay = 10 * attempt
                print(f"     [Mistral OCR] {response.status_code}. Waiting {delay}s...")
                time.sleep(delay)
                continue

            elif response.status_code in (500,):
                time.sleep(10 * attempt)
                continue

            else:
                print(f"     [Mistral OCR] Error {response.status_code}: {response.text[:400]}")
                break

        except ValueError:  # JSON decode error from empty/invalid response
            print("     [Mistral OCR] Non-JSON response — quota may be exhausted, stopping.")
            return ""
        except Exception as e:
            print(f"     [Mistral OCR] Request Exception: {e}")
            if attempt < max_attempts:
                time.sleep(5)

    print("     [Mistral OCR] All retries failed.")
    return ""


def extract_pdf_full(pdf_path: str) -> str:
    """Extract full text from a PDF using Mistral Document AI (single call, entire doc)."""
    print(f"     [Mistral OCR] Extracting full document: {pdf_path}")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    file_size_mb = len(pdf_bytes) / (1024 * 1024)
    print(f"     [Mistral OCR] File size: {file_size_mb:.1f} MB")

    return _call_mistral_ocr(pdf_bytes)


def _call_mistral_ocr_with_timeout(
    document_bytes: bytes,
    timeout_s: int = 60,
    input_type: str = "document_url",
) -> str:
    """
    Call _call_mistral_ocr with a hard wall-clock timeout.
    Returns empty string if the call exceeds timeout_s seconds.
    """
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_call_mistral_ocr, document_bytes, input_type)
        try:
            return future.result(timeout=timeout_s)
        except (TimeoutError, Exception) as e:
            if isinstance(e, TimeoutError):
                print(f"     [Mistral OCR] Call timed out after {timeout_s}s.")
            else:
                print(f"     [Mistral OCR] Call failed: {e}")
            return ""


def _page_bytes_to_png(page_bytes: bytes) -> bytes:
    """
    Convert a single-page PDF (bytes) to a high-resolution PNG (300 DPI).
    Used for vision fallback when text OCR returns too little content.
    """
    import fitz
    doc = fitz.open(stream=page_bytes, filetype="pdf")
    page = doc[0]
    # 300 DPI matrix (scale factor = 300/72 ≈ 4.17)
    mat = fitz.Matrix(4.17, 4.17)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def _extract_single_page(args: Tuple[int, bytes, int]) -> Tuple[int, str]:
    """
    Worker function for parallel OCR. Extracts a single page and returns (page_idx, text).
    Strategy:
      1. Try PDF text OCR via Mistral (document_url) — fast, catches tables/text
      2. If <50 chars: convert page to 300 DPI PNG and try Mistral vision (image_url)
         — captures chart data labels, graphical tables, and financial figures
      3. Hard 60s timeout per OCR call to prevent hangs on slow API responses
    """
    page_idx, page_bytes, total_pages = args
    page_num = page_idx + 1

    # ── Step 1: PDF text OCR ────────────────────────────────────────────
    page_text = _call_mistral_ocr_with_timeout(page_bytes, timeout_s=60)
    if page_text and len(page_text.strip()) > 50:
        print(f"     [Mistral OCR] [Parallel] Page {page_num}/{total_pages} done ({len(page_text)} chars).")
        return (page_idx, page_text)

    # ── Step 2: Vision fallback — render page as 300 DPI PNG ────────────────
    print(f"     [Mistral OCR] [Parallel] Page {page_num} — text OCR sparse ({len((page_text or '').strip())} chars), "
          f"trying vision fallback (PNG 300 DPI)...")
    try:
        png_bytes = _page_bytes_to_png(page_bytes)
        vision_text = _call_mistral_ocr_with_timeout(
            png_bytes, timeout_s=60, input_type="image_url"
        )
        if vision_text and len(vision_text.strip()) > 30:
            print(f"     [Mistral OCR] [Parallel] Page {page_num}/{total_pages} vision extracted "
                  f"({len(vision_text)} chars) [CHART/IMAGE PAGE].")
            return (page_idx, vision_text)
    except Exception as e:
        print(f"     [Mistral OCR] [Parallel] Page {page_num} vision error: {e}")

    print(f"     [Mistral OCR] [Parallel] Page {page_num} — blank/decorative, skipping.")
    return (page_idx, page_text or "")


def extract_pdf_per_page(pdf_path: str, max_pages: int = 100) -> List[str]:
    """
    Extract text page-by-page from a PDF using Mistral Document AI (sequential).
    
    Each page is sent as a separate OCR call for maximum extraction quality.
    Returns a list of page texts.
    """
    print(f"     [Mistral OCR] Extracting per-page: {pdf_path}")

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError(
            "PyMuPDF (fitz) is required for per-page OCR extraction. "
            "Install with: pip install pymupdf"
        )

    doc = fitz.open(pdf_path)
    actual_pages = len(doc)
    
    if actual_pages > max_pages:
        print(f"     [Mistral OCR] WARNING: Document has {actual_pages} pages, "
              f"but max_pages={max_pages}. Pages {max_pages + 1}-{actual_pages} will be skipped.")
    
    total_pages = min(actual_pages, max_pages)
    print(f"     [Mistral OCR] Processing {total_pages}/{actual_pages} pages...")

    page_texts = []
    fail_count = 0

    for page_num in range(total_pages):
        print(f"     [Mistral OCR] Page {page_num + 1}/{total_pages}...")

        # Extract single page as a new PDF
        single_page_doc = fitz.open()
        single_page_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
        page_bytes = single_page_doc.tobytes()
        single_page_doc.close()

        # Retry per page (2 attempts)
        page_text = ""
        for retry in range(2):
            page_text = _call_mistral_ocr(page_bytes)
            if page_text and len(page_text.strip()) > 50:
                break
            if retry == 0:
                print(f"     [Mistral OCR] Page {page_num + 1} attempt {retry + 1} returned little text — retrying...")
                time.sleep(3)

        if not page_text or len(page_text.strip()) < 50:
            fail_count += 1
            print(f"     [Mistral OCR] WARNING: Page {page_num + 1} failed after 2 retries. "
                  f"({fail_count}/{total_pages} pages failed so far)")
            page_texts.append("")  # Preserve index alignment
        else:
            page_texts.append(page_text)

        if page_num < total_pages - 1:
            time.sleep(1)  # Rate limiting between pages

    doc.close()

    total_chars = sum(len(t) for t in page_texts)
    non_empty = sum(1 for t in page_texts if t.strip())
    print(f"     [Mistral OCR] Complete — {total_chars:,} chars across {non_empty}/{len(page_texts)} pages "
          f"({fail_count} failed).")
    return page_texts


def extract_pdf_per_page_parallel(
    pdf_path: str,
    max_pages: int = 100,
    max_workers: int = 3,
) -> List[str]:
    """
    Extract text page-by-page from a PDF using Mistral Document AI — PARALLEL MODE.

    All pages are sent to the OCR API concurrently (up to max_workers at once).
    Each page is still extracted individually, preserving exact page_num and layout.
    Returns a list of page texts in correct page order.

    Args:
        pdf_path:    Path to the PDF file.
        max_pages:   Maximum number of pages to process.
        max_workers: Maximum concurrent OCR requests (default 5, tune for rate limits).
    """
    import fitz  # PyMuPDF

    print(f"     [Mistral OCR] [Parallel] Starting parallel per-page extraction: {pdf_path}")

    doc = fitz.open(pdf_path)
    actual_pages = len(doc)

    if actual_pages > max_pages:
        print(f"     [Mistral OCR] [Parallel] WARNING: Document has {actual_pages} pages, "
              f"capping at {max_pages}.")
    total_pages = min(actual_pages, max_pages)
    print(f"     [Mistral OCR] [Parallel] Processing {total_pages} pages with {max_workers} workers...")

    # Pre-extract all page bytes upfront (must be done in the main thread — fitz is not thread-safe)
    all_page_bytes: List[Tuple[int, bytes, int]] = []
    for page_idx in range(total_pages):
        single_page_doc = fitz.open()
        single_page_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
        page_bytes = single_page_doc.tobytes()
        single_page_doc.close()
        all_page_bytes.append((page_idx, page_bytes, total_pages))
    doc.close()

    # Run parallel OCR — submit in batches with a small stagger to spread API load
    results: dict = {}
    fail_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {}
        for i, args in enumerate(all_page_bytes):
            future_map[executor.submit(_extract_single_page, args)] = args[0]
            if i % max_workers == (max_workers - 1):
                time.sleep(0.5)  # Small stagger between batches to avoid burst rate limiting
        for future in as_completed(future_map):
            page_idx, page_text = future.result()
            results[page_idx] = page_text
            if not page_text or len(page_text.strip()) < 50:
                fail_count += 1

    # Reassemble in correct page order
    page_texts = [results.get(i, "") for i in range(total_pages)]

    total_chars = sum(len(t) for t in page_texts)
    non_empty = sum(1 for t in page_texts if t.strip())
    print(f"     [Mistral OCR] [Parallel] Complete — {total_chars:,} chars across "
          f"{non_empty}/{total_pages} pages ({fail_count} failed).")
    return page_texts


def format_per_page_content(page_texts: List[str]) -> str:
    """
    Assemble a list of per-page texts into a single string formatted with explicit page markers.
    Marker format: <!--PAGE_BREAK page=N-->
    """
    assembled_parts = []
    for idx, page_text in enumerate(page_texts):
        page_num = idx + 1
        clean_text = page_text.strip() if page_text else ""
        assembled_parts.append(f"<!--PAGE_BREAK page={page_num}-->\n{clean_text}")
    return "\n\n".join(assembled_parts)


if __name__ == "__main__":
    import sys
    per_page = "--per-page" in sys.argv
    parallel  = "--parallel" in sys.argv
    if len(sys.argv) < 2:
        print("Usage: python mistral_ocr.py <pdf_path> [--per-page|--parallel]")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if parallel:
        pages = extract_pdf_per_page_parallel(pdf_path)
        for i, text in enumerate(pages):
            print(f"\n{'='*60}")
            print(f"PAGE {i+1} ({len(text)} chars)")
            print(f"{'='*60}")
            print(text[:2000])
    elif per_page:
        pages = extract_pdf_per_page(pdf_path)
        for i, text in enumerate(pages):
            print(f"\n{'='*60}")
            print(f"PAGE {i+1} ({len(text)} chars)")
            print(f"{'='*60}")
            print(text[:2000])
    else:
        text = extract_pdf_full(pdf_path)
        print(f"\nFull extraction: {len(text)} chars")
        print(text[:2000])