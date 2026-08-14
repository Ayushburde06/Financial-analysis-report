"""Azure Document Intelligence OCR — per-page Markdown.

Stage 01 default:
  1. Split the PDF into single-page chunks (PyMuPDF)
  2. Run prebuilt-layout with outputContentFormat=markdown on each page
  3. Convert HTML tables to GitHub-flavored Markdown tables
  4. Stitch pages with <!--PAGE_BREAK page=N--> markers
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv

_WORKING_ANALYZE_URL: Optional[str] = None
_URL_LOCK = threading.Lock()


def _di_credentials() -> Tuple[str, str]:
    load_dotenv(override=True)
    endpoint = (os.getenv("AZURE_DOC_INTEL_ENDPOINT", "") or "").rstrip("/")
    key = os.getenv("AZURE_DOC_INTEL_KEY", "")
    return endpoint, key


def _markdown_enabled() -> bool:
    return os.getenv("OCR_MARKDOWN", "1").strip().lower() not in ("0", "false", "no")


def _per_page_enabled() -> bool:
    return os.getenv("OCR_PER_PAGE", "1").strip().lower() not in ("0", "false", "no")


def _max_workers() -> int:
    try:
        return max(1, int(os.getenv("OCR_MAX_WORKERS", "4")))
    except ValueError:
        return 4


def _max_pages() -> int:
    try:
        return max(1, int(os.getenv("OCR_MAX_PAGES", "120")))
    except ValueError:
        return 120


def _analyze_urls(endpoint: str) -> List[str]:
    """Newer markdown APIs first; formrecognizer path is what this resource already uses."""
    return [
        (
            f"{endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"
            f"?api-version=2024-11-30&outputContentFormat=markdown"
        ),
        (
            f"{endpoint}/formrecognizer/documentModels/prebuilt-layout:analyze"
            f"?api-version=2024-11-30&outputContentFormat=markdown"
        ),
        (
            f"{endpoint}/formrecognizer/documentModels/prebuilt-layout:analyze"
            f"?api-version=2024-02-29-preview&outputContentFormat=markdown"
        ),
    ]


def _chart_ocr_enabled() -> bool:
    return os.getenv("OCR_CHARTS", "1").strip().lower() not in ("0", "false", "no")


_NUM_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+\.\d+|\d{2,})(?![\w])"
)


def _legacy_analyze_url(endpoint: str) -> str:
    return (
        f"{endpoint}/formrecognizer/documentModels/prebuilt-layout"
        f":analyze?api-version=2023-07-31"
    )


def _cell_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return " ".join(text.split()).replace("|", "\\|")


def _html_table_to_markdown(table_html: str) -> str:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, flags=re.I | re.S)
    parsed: List[List[str]] = []
    header_row = 0
    for i, row in enumerate(rows):
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.I | re.S)
        if not cells:
            continue
        parsed.append([_cell_text(c) for c in cells])
        if header_row == 0 and re.search(r"<th\b", row, flags=re.I):
            header_row = len(parsed) - 1
    if not parsed:
        return ""
    width = max(len(r) for r in parsed)
    for row in parsed:
        while len(row) < width:
            row.append("")
    header = parsed[header_row]
    body = parsed[:header_row] + parsed[header_row + 1 :]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def html_tables_to_markdown(text: str) -> str:
    """Turn Azure DI HTML <table> blocks into GFM pipe tables for the LLM."""
    if not text or "<table" not in text.lower():
        return text

    def repl(match: re.Match) -> str:
        converted = _html_table_to_markdown(match.group(0))
        return converted or match.group(0)

    return re.sub(r"<table\b.*?</table>", repl, text, flags=re.I | re.S)


def _simplify_figures(text: str) -> str:
    def repl(match: re.Match) -> str:
        inner = match.group(1)
        inner = re.sub(
            r"<figcaption\b[^>]*>(.*?)</figcaption>",
            r"\n\1\n",
            inner,
            flags=re.I | re.S,
        )
        inner = re.sub(r"<[^>]+>", "", inner)
        return unescape(inner).strip()

    return re.sub(r"<figure\b[^>]*>(.*?)</figure>", repl, text, flags=re.I | re.S)


def _normalize_page_breaks(markdown: str) -> str:
    """Map Azure <!-- PageBreak --> comments onto our Stage 01 markers."""
    parts = re.split(r"<!--\s*PageBreak\s*-->", markdown, flags=re.I)
    if len(parts) <= 1:
        return markdown.strip()
    out = []
    for i, part in enumerate(parts, start=1):
        chunk = part.strip()
        if chunk:
            out.append(f"<!--PAGE_BREAK page={i}-->\n{chunk}")
    return "\n\n".join(out)


def format_per_page_markdown(page_texts: List[str]) -> str:
    parts = []
    for idx, page_text in enumerate(page_texts):
        clean = (page_text or "").strip()
        parts.append(f"<!--PAGE_BREAK page={idx + 1}-->\n{clean}")
    return "\n\n".join(parts)


def _lines_from_pages(analyze_result: dict) -> str:
    page_texts = []
    for page_num, page in enumerate(analyze_result.get("pages") or [], start=1):
        lines = [
            line.get("content", "")
            for line in page.get("lines") or []
            if (line.get("content") or "").strip()
        ]
        if lines:
            page_texts.append(f"<!--PAGE_BREAK page={page_num}-->\n" + "\n".join(lines))
    return "\n\n".join(page_texts)


def markdown_from_analyze_result(result: dict) -> str:
    analyze = result.get("analyzeResult", result) or {}
    content = analyze.get("content") or ""
    if isinstance(content, str) and content.strip():
        md = html_tables_to_markdown(content)
        md = _simplify_figures(md)
        return md.strip()
    return _lines_from_pages(analyze).strip()


def _number_tokens(text: str) -> List[str]:
    return _NUM_RE.findall(text or "")


def _tables_json_to_markdown(analyze: dict) -> str:
    """Build pipe tables from Azure tables[] when Markdown missed the grid."""
    tables = analyze.get("tables") or []
    blocks = []
    for table in tables:
        cells = table.get("cells") or []
        if not cells:
            continue
        max_r = max(int(c.get("rowIndex") or 0) for c in cells)
        max_c = max(int(c.get("columnIndex") or 0) for c in cells)
        grid = [["" for _ in range(max_c + 1)] for _ in range(max_r + 1)]
        for cell in cells:
            row = int(cell.get("rowIndex") or 0)
            col = int(cell.get("columnIndex") or 0)
            grid[row][col] = (
                (cell.get("content") or "").replace("|", "\\|").replace("\n", " ").strip()
            )
        header = grid[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in grid[1:]:
            lines.append("| " + " | ".join(row) + " |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _needs_chart_ocr(md: str, result: dict) -> bool:
    """True when the page looks like a chart/figure with little structured text."""
    if not _chart_ocr_enabled():
        return False
    analyze = (result or {}).get("analyzeResult") or result or {}
    figures = analyze.get("figures") or []
    tables = analyze.get("tables") or []
    n = len(_number_tokens(md))
    has_table = bool(tables) or "|" in (md or "")
    if has_table and n >= 10:
        return False
    # Pies/bars often have loose % labels but no markdown table.
    if len(figures) >= 2 and not has_table:
        return True
    if figures and n < 12:
        return True
    if len((md or "").strip()) < 180:
        return True
    return False


def _merge_markdown(base: str, extra: str, heading: str = "") -> str:
    base = (base or "").strip()
    extra = (extra or "").strip()
    if not extra:
        return base
    if extra in base:
        return base
    extra_nums = set(_number_tokens(extra))
    base_nums = set(_number_tokens(base))
    new_nums = extra_nums - base_nums
    extra_only = extra
    if not new_nums and "|" not in extra:
        if len(base) >= 180:
            return base
    if heading and extra_only:
        extra_only = f"{heading}\n{extra_only}"
    if not base:
        return extra_only
    return f"{base}\n\n{extra_only}"


def _fitz_page_text(page_bytes: bytes) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    doc = fitz.open(stream=page_bytes, filetype="pdf")
    try:
        return (doc[0].get_text("text") or "").strip()
    finally:
        doc.close()


def _page_to_png(page_bytes: bytes, dpi: int = 200) -> bytes:
    import fitz

    doc = fitz.open(stream=page_bytes, filetype="pdf")
    try:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        png = pix.tobytes("png")
        if len(png) > 3_500_000:
            pix = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
            png = pix.tobytes("jpeg")
        return png
    finally:
        doc.close()


def _submit_analyze(
    url: str,
    key: str,
    payload_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> requests.Response:
    headers = {
        "Content-Type": content_type,
        "Ocp-Apim-Subscription-Key": key,
    }
    response = requests.post(url, headers=headers, data=payload_bytes, timeout=120)
    if response.status_code == 415:
        headers = {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": key,
        }
        body = {"base64Source": base64.b64encode(payload_bytes).decode("ascii")}
        response = requests.post(url, headers=headers, json=body, timeout=120)
    return response


def _poll_result(operation_location: str, key: str, max_polls: int = 24, delay: float = 1.5) -> dict:
    headers = {"Ocp-Apim-Subscription-Key": key}
    last = {}
    for _ in range(max_polls):
        time.sleep(delay)
        try:
            poll = requests.get(operation_location, headers=headers, timeout=60)
        except Exception as exc:
            print(f"     [Azure DI] Poll error: {exc}")
            continue
        if poll.status_code not in (200, 202):
            print(f"     [Azure DI] Poll failed: {poll.status_code}")
            return {}
        try:
            last = poll.json()
        except Exception:
            continue
        status = str(last.get("status", "")).lower()
        if status in ("succeeded", "complete", "completed"):
            return last
        if status in ("failed", "canceled", "cancelled", "rejected"):
            print(f"     [Azure DI] Analysis ended with status: {status}")
            return {}
    print("     [Azure DI] Timed out waiting for analysis.")
    return {}


def _analyze_bytes_full(
    payload_bytes: bytes,
    endpoint: str,
    key: str,
    markdown: bool = True,
    content_type: str = "application/octet-stream",
) -> Tuple[str, dict]:
    global _WORKING_ANALYZE_URL
    if markdown:
        with _URL_LOCK:
            cached = _WORKING_ANALYZE_URL
        urls = [cached] if cached else _analyze_urls(endpoint)
    else:
        urls = [_legacy_analyze_url(endpoint)]

    last_error = ""
    for url in urls:
        if not url:
            continue
        try:
            response = _submit_analyze(url, key, payload_bytes, content_type=content_type)
        except Exception as exc:
            last_error = str(exc)
            print(f"     [Azure DI] Submit error: {exc}")
            continue
        if response.status_code == 202:
            if markdown:
                with _URL_LOCK:
                    if not _WORKING_ANALYZE_URL:
                        print("     [Azure DI] Markdown Layout API ready.")
                    _WORKING_ANALYZE_URL = url
            operation_location = response.headers.get("Operation-Location", "")
            if not operation_location:
                print("     [Azure DI] No Operation-Location header in response.")
                continue
            result = _poll_result(operation_location, key)
            if not result:
                continue
            text = markdown_from_analyze_result(result)
            if not markdown:
                text = text or _lines_from_pages(result.get("analyzeResult", result) or "")
            return text or "", result
        last_error = f"{response.status_code}: {response.text[:180]}"
        if response.status_code in (400, 404):
            print(f"     [Azure DI] Markdown endpoint skipped ({response.status_code})")
            continue
        print(f"     [Azure DI] Submit failed: {last_error}")
        break
    if last_error:
        print(f"     [Azure DI] Analyze failed: {last_error}")
    return "", {}


def _analyze_pdf_bytes(pdf_bytes: bytes, endpoint: str, key: str, markdown: bool = True) -> str:
    text, _ = _analyze_bytes_full(pdf_bytes, endpoint, key, markdown=markdown)
    return text


def _split_pdf_pages(pdf_path: str, max_pages: int) -> List[Tuple[int, bytes]]:
    import fitz

    doc = fitz.open(pdf_path)
    try:
        total = min(len(doc), max_pages)
        if len(doc) > max_pages:
            print(
                f"     [Azure DI] Document has {len(doc)} pages; "
                f"capping at {max_pages}."
            )
        pages: List[Tuple[int, bytes]] = []
        for idx in range(total):
            one = fitz.open()
            one.insert_pdf(doc, from_page=idx, to_page=idx)
            pages.append((idx, one.tobytes()))
            one.close()
        return pages
    finally:
        doc.close()


def _page_cache_dir(pdf_hash: str) -> Path:
    path = Path("tmp") / "ocr_cache" / "pages_v2" / pdf_hash
    path.mkdir(parents=True, exist_ok=True)
    return path


def _enrich_page_markdown(
    page_bytes: bytes,
    md: str,
    result: dict,
    endpoint: str,
    key: str,
    page_label: str,
) -> str:
    """Add JSON tables, local PDF text, and chart-image OCR into page Markdown."""
    analyze = (result or {}).get("analyzeResult") or result or {}
    text = md or ""

    table_md = _tables_json_to_markdown(analyze)
    if table_md and "|" not in text:
        text = _merge_markdown(text, table_md)

    local = _fitz_page_text(page_bytes)
    if local:
        text = _merge_markdown(text, local)

    if not _needs_chart_ocr(text, result):
        return text

    print(f"     [Azure DI] {page_label} chart/figure OCR (page image)...")
    try:
        png = _page_to_png(page_bytes, dpi=200)
    except Exception as exc:
        print(f"     [Azure DI] {page_label} PNG render failed: {exc}")
        return text

    ctype = "image/jpeg" if png[:3] == b"\xff\xd8\xff" else "image/png"
    chart_md, _ = _analyze_bytes_full(
        png, endpoint, key, markdown=True, content_type=ctype
    )
    if chart_md:
        before = len(_number_tokens(text))
        text = _merge_markdown(
            text, chart_md, heading="## Chart and figure labels"
        )
        after = len(_number_tokens(text))
        print(
            f"     [Azure DI] {page_label} chart OCR added "
            f"{after - before} number(s), now {len(text):,} chars."
        )
        if after > before:
            return text

    # Vector charts / outlined fonts: layout OCR misses labels. Luna vision reads them.
    try:
        from pipeline.utils.llm_client import call_luna_vision
        vision_md = call_luna_vision(png, mime=ctype)
    except Exception as exc:
        print(f"     [Azure DI] {page_label} Luna vision failed: {exc}")
        vision_md = ""
    if vision_md:
        before = len(_number_tokens(text))
        text = _merge_markdown(
            text, vision_md, heading="## Chart and figure labels"
        )
        after = len(_number_tokens(text))
        print(
            f"     [Azure DI] {page_label} Luna vision added "
            f"{after - before} number(s), now {len(text):,} chars."
        )
    return text


def _analyze_one_page(args: Tuple[int, bytes, int, str, str, str]) -> Tuple[int, str]:
    page_idx, page_bytes, total, endpoint, key, cache_file = args
    cache_path = Path(cache_file)
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8", errors="replace").strip()
        if len(cached) >= 20:
            return page_idx, cached

    text, result = _analyze_bytes_full(page_bytes, endpoint, key, markdown=True)
    text = _enrich_page_markdown(
        page_bytes,
        text or "",
        result,
        endpoint,
        key,
        page_label=f"Page {page_idx + 1}/{total}",
    )
    text = (text or "").strip()
    if text:
        cache_path.write_text(text, encoding="utf-8")
        print(
            f"     [Azure DI] Page {page_idx + 1}/{total} markdown "
            f"({len(text):,} chars)."
        )
    else:
        print(f"     [Azure DI] Page {page_idx + 1}/{total} returned no markdown.")
    return page_idx, text


def extract_pdf_azure_di_pages(pdf_path: str) -> List[str]:
    """OCR each PDF page to Markdown. Returns a list aligned to page order."""
    endpoint, key = _di_credentials()
    if not endpoint or not key:
        print("     [Azure DI] ERROR: AZURE_DOC_INTEL_ENDPOINT or AZURE_DOC_INTEL_KEY not set.")
        return []

    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    cache_root = _page_cache_dir(pdf_hash)

    try:
        page_blobs = _split_pdf_pages(pdf_path, _max_pages())
    except Exception as exc:
        print(f"     [Azure DI] Page split failed ({exc}); using whole-document OCR.")
        return []

    total = len(page_blobs)
    workers = min(_max_workers(), total)
    print(
        f"     [Azure DI] Per-page Markdown OCR: {total} pages, "
        f"{workers} workers."
    )

    jobs = []
    for idx, blob in page_blobs:
        cache_file = str(cache_root / f"p{idx + 1:03d}.md")
        jobs.append((idx, blob, total, endpoint, key, cache_file))

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for i, job in enumerate(jobs):
            futures[pool.submit(_analyze_one_page, job)] = job[0]
            if i % workers == workers - 1:
                time.sleep(0.2)
        for future in as_completed(futures):
            idx, text = future.result()
            results[idx] = text

    return [results.get(i, "") for i in range(total)]


def _extract_whole_document(pdf_path: str, markdown: bool) -> str:
    endpoint, key = _di_credentials()
    if not endpoint or not key:
        return ""
    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()
    print(
        f"     [Azure DI] Whole-document "
        f"{'Markdown' if markdown else 'layout'} OCR "
        f"({len(pdf_bytes) / (1024 * 1024):.1f} MB)..."
    )
    text = _analyze_pdf_bytes(pdf_bytes, endpoint, key, markdown=markdown)
    if markdown and text:
        return _normalize_page_breaks(text)
    return text


def extract_pdf_azure_di(pdf_path: str) -> str:
    """
    Extract a PDF as per-page Markdown (default).

    Falls back to whole-document Markdown, then to the older line-layout API.
    """
    endpoint, key = _di_credentials()
    if not endpoint or not key:
        print("     [Azure DI] ERROR: AZURE_DOC_INTEL_ENDPOINT or AZURE_DOC_INTEL_KEY not set.")
        return ""

    with open(pdf_path, "rb") as handle:
        pdf_bytes = handle.read()

    cache_dir = Path("tmp") / "ocr_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    cache_path = cache_dir / f"{pdf_hash}.pages.v2.md"
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8", errors="replace")
        if len(cached) >= 100:
            print(f"     [Azure DI] Markdown OCR cache hit: {len(cached):,} chars")
            return cached

    file_size_mb = len(pdf_bytes) / (1024 * 1024)
    print(f"     [Azure DI] Starting Markdown extraction for {pdf_path} ({file_size_mb:.1f} MB)")

    text = ""
    if _markdown_enabled() and _per_page_enabled():
        pages = extract_pdf_azure_di_pages(pdf_path)
        nonempty = sum(1 for page in pages if (page or "").strip())
        assembled = format_per_page_markdown(pages) if pages else ""
        if nonempty >= max(1, int(0.4 * max(len(pages), 1))) and len(assembled) >= 100:
            text = assembled
            print(
                f"     [Azure DI] Per-page Markdown complete — "
                f"{len(text):,} chars across {nonempty}/{len(pages)} pages."
            )
        else:
            print("     [Azure DI] Per-page Markdown too sparse; trying whole document.")

    if len(text) < 100 and _markdown_enabled():
        text = _extract_whole_document(pdf_path, markdown=True)
        if text:
            print(f"     [Azure DI] Whole-document Markdown complete — {len(text):,} chars.")

    if len(text) < 100:
        print("     [Azure DI] Falling back to 2023 layout line OCR.")
        text = _extract_whole_document(pdf_path, markdown=False)

    if len(text) >= 100:
        cache_path.write_text(text, encoding="utf-8")
        print(f"     [Azure DI] Extraction complete — {len(text):,} chars.")
    else:
        print("     [Azure DI] Extraction produced no usable text.")
    return text
