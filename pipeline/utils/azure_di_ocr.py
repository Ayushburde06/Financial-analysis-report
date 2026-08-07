"""Azure Document Intelligence OCR — fallback when Mistral OCR quota is exhausted.

Uses the prebuilt-layout model to extract text from PDFs.
"""
import os
import time
import requests
import hashlib
from pathlib import Path
from typing import List


def extract_pdf_azure_di(pdf_path: str) -> str:
    """
    Extract text from a PDF using Azure Document Intelligence (prebuilt-layout).
    Sends the PDF for analysis, polls until complete, returns extracted text.
    """
    # Re-read from .env on every call to pick up any changes
    import os
    from dotenv import load_dotenv
    load_dotenv(override=True)
    _di_endpoint = os.getenv("AZURE_DOC_INTEL_ENDPOINT", "https://namte.cognitiveservices.azure.com/")
    _di_key = os.getenv("AZURE_DOC_INTEL_KEY", "")
    
    if not _di_endpoint or not _di_key:
        print("     [Azure DI] ERROR: AZURE_DOC_INTEL_ENDPOINT or AZURE_DOC_INTEL_KEY not set.")
        return ""

    endpoint = _di_endpoint.rstrip("/")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    cache_dir = Path("tmp") / "ocr_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{hashlib.sha256(pdf_bytes).hexdigest()}.txt"
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8", errors="replace")
        if len(cached) >= 100:
            print(f"     [Azure DI] OCR cache hit: {len(cached):,} chars")
            return cached

    file_size_mb = len(pdf_bytes) / (1024 * 1024)
    print(f"     [Azure DI] Starting extraction for {pdf_path} ({file_size_mb:.1f} MB)")

    # Step 1: Submit document for analysis
    analyze_url = (
        f"{endpoint}/formrecognizer/documentModels/prebuilt-layout"
        f":analyze?api-version=2023-07-31"
    )
    headers = {
        "Content-Type": "application/octet-stream",
        "Ocp-Apim-Subscription-Key": _di_key,
    }

    try:
        response = requests.post(analyze_url, headers=headers, data=pdf_bytes, timeout=120)
        if response.status_code != 202:
            print(f"     [Azure DI] Submit failed: {response.status_code} - {response.text[:300]}")
            return ""

        operation_location = response.headers.get("Operation-Location", "")
        if not operation_location:
            print("     [Azure DI] No Operation-Location header in response.")
            return ""

    except Exception as e:
        print(f"     [Azure DI] Submit error: {e}")
        return ""

    # Step 2: Poll for results
    poll_headers = {"Ocp-Apim-Subscription-Key": _di_key}
    max_polls = 30  # 30 * 3s = 90s max

    for poll in range(max_polls):
        time.sleep(3)
        try:
            poll_response = requests.get(operation_location, headers=poll_headers, timeout=60)
        except Exception as e:
            print(f"     [Azure DI] Poll error: {e}")
            continue

        if poll_response.status_code == 200:
            # Some Azure resources return HTTP 200 while the operation is
            # still running. Do not parse the status envelope as a final
            # analysis result until the operation explicitly succeeds.
            try:
                poll_state = str(poll_response.json().get("status", "")).lower()
            except Exception:
                poll_state = ""
            if poll_state in ("succeeded", "complete", "completed"):
                break
            if poll_state in ("failed", "canceled", "cancelled", "rejected"):
                print(f"     [Azure DI] Analysis ended with status: {poll_state}")
                return ""
            continue
        elif poll_response.status_code != 202:
            print(f"     [Azure DI] Poll failed: {poll_response.status_code}")
            return ""
    else:
        print("     [Azure DI] Timed out waiting for analysis.")
        return ""

    # Step 3: Extract text from result
    result = poll_response.json()
    analyze_result = result.get("analyzeResult", result)
    pages = analyze_result.get("pages", [])
    if not pages and not analyze_result.get("content"):
        print(
            "     [Azure DI] Successful response contained no text. "
            f"Top-level keys={list(result.keys())}; "
            f"analyzeResult keys={list(analyze_result.keys()) if isinstance(analyze_result, dict) else type(analyze_result).__name__}"
        )

    page_texts = []
    for page_num, page in enumerate(pages, start=1):
        lines = page.get("lines", [])
        page_lines = []
        for line in lines:
            content = line.get("content", "")
            if content.strip():
                page_lines.append(content)
        if page_lines:
            page_texts.append(
                f"<!--PAGE_BREAK page={page_num}-->\n" + "\n".join(page_lines)
            )

    # Some Document Intelligence responses provide the complete reading-order
    # text in `analyzeResult.content` but omit page line objects. Preserve that
    # content instead of incorrectly treating the successful response as empty.
    if not page_texts:
        full_content = analyze_result.get("content", "")
        if isinstance(full_content, str) and full_content.strip():
            page_texts.append(full_content.strip())

    text = "\n\n".join(page_texts)
    total_chars = len(text)
    if total_chars >= 100:
        cache_path.write_text(text, encoding="utf-8")
    print(f"     [Azure DI] Extraction complete — {total_chars:,} chars across {len(page_texts)} pages.")
    return text
