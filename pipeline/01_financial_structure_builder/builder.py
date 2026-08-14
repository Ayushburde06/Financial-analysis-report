"""
Stage 01: Financial Structure Builder

Supports three input formats:
  PDF  → Azure Document Intelligence, one page at a time → Markdown
  CSV  → pandas read_csv → text table → MasterDocument DOM
  TXT  → plain text read → MasterDocument DOM

All three paths produce an identical MasterDocument output so every
downstream stage (02-15) works without any modification.
"""
import os
from pathlib import Path
import re
from dom_schema import MasterDocument, SectionNode, ParagraphNode
from pipeline.utils.azure_di_ocr import extract_pdf_azure_di


# ── Shared helpers ────────────────────────────────────────────────────────────

def _build_master_doc_from_text(text: str, source_file: str) -> MasterDocument:
    """
    Convert a plain text string into a MasterDocument DOM.
    Splits into 3,000-char pages so downstream stages see normal page counts.
    """
    master_doc = MasterDocument(
        source_file=source_file,
        source_format=Path(source_file).suffix.lower().lstrip(".") or "text",
        source_metadata={"extraction_mode": "direct_text"},
    )
    chunk_size = 3000
    chunks = [text[i:i + chunk_size] for i in range(0, max(len(text), 1), chunk_size)]
    for page_idx, chunk in enumerate(chunks):
        page_num = page_idx + 1
        section = SectionNode(heading=f"Page {page_num}", level=1)
        for p_idx, para in enumerate(chunk.split("\n\n")):
            para = para.strip()
            if para:
                section.nodes.append(ParagraphNode(
                    id=f"p{page_num}_{p_idx}",
                    page_num=page_num,
                    text=para,
                ))
        if section.nodes:
            master_doc.sections.append(section)
            master_doc.page_markdown[str(page_num)] = chunk.strip()
    return master_doc


def _parse_csv(file_path: str) -> str:
    """
    Convert a CSV into a readable text table.
    Repeats the header every 30 rows so the LLM always has column context.
    Falls back to raw file read if pandas fails.
    """
    try:
        import pandas as pd
        df = pd.read_csv(file_path).dropna(axis=1, how="all")
        header = " | ".join(str(c) for c in df.columns)
        sep = "-" * min(len(header), 120)
        lines = [header, sep]
        for i, (_, row) in enumerate(df.iterrows()):
            if i > 0 and i % 30 == 0:
                lines += [header, sep]
            lines.append(" | ".join("" if str(v) == "nan" else str(v) for v in row.values))
        return "\n".join(lines)
    except Exception as e:
        print(f"     [Stage 01] pandas CSV parse failed ({e}), falling back to raw read.")
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def _extract_pdf_text_locally(file_path: str) -> str:
    """Extract selectable PDF text locally while retaining page markers."""
    try:
        import fitz
        chunks = []
        with fitz.open(file_path) as pdf:
            for page_num, page in enumerate(pdf, start=1):
                text = page.get_text("text") or ""
                if text.strip():
                    chunks.append(
                        f"<!--PAGE_BREAK page={page_num}-->\n{text.strip()}"
                    )
        return "\n\n".join(chunks)
    except Exception as fitz_exc:
        try:
            import pdfplumber
            chunks = []
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                    if text.strip():
                        chunks.append(
                            f"<!--PAGE_BREAK page={page_num}-->\n{text.strip()}"
                        )
            return "\n\n".join(chunks)
        except Exception as exc:
            print(f"     [Stage 01] Local PDF text extraction failed: {fitz_exc}; {exc}")
            return ""


_PAGE_BREAK_PATTERN = re.compile(r'<!--PAGE_BREAK(?: page=(\d+))?-->')


# ── Main class ────────────────────────────────────────────────────────────────

class FinancialStructureBuilder:

    @staticmethod
    def run(file_path: str) -> MasterDocument:
        from dotenv import load_dotenv
        load_dotenv()

        ext = Path(file_path).suffix.lower()

        # ── CSV ───────────────────────────────────────────────────────────────
        if ext == ".csv":
            print(f"     [Stage 01] CSV input — parsing with pandas...")
            text = _parse_csv(file_path)
            print(f"     [Stage 01] CSV parsed: {len(text):,} chars")
            doc = _build_master_doc_from_text(text, file_path)
            print("     [Stage 01] MasterDocument complete (CSV).")
            return doc

        # ── TXT / MD ──────────────────────────────────────────────────────────
        if ext in (".txt", ".md"):
            print(f"     [Stage 01] Text input — reading directly...")
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            print(f"     [Stage 01] Text read: {len(text):,} chars")
            doc = _build_master_doc_from_text(text, file_path)
            print("     [Stage 01] MasterDocument complete (TXT).")
            return doc

        # ── PDF (default) — per-page Azure Layout OCR → Markdown ──────────────
        content = ""
        total_chars = 0
        # Set PREFER_LOCAL_PDF_TEXT=1 only when speed is preferred for
        # selectable, text-heavy PDFs (skips Azure Markdown OCR).
        if os.getenv("PREFER_LOCAL_PDF_TEXT", "0") != "0":
            print(f"     [Stage 01] Checking for selectable PDF text locally: {file_path}")
            content = _extract_pdf_text_locally(file_path)
            total_chars = len(content) if content else 0
            print(f"     [Local PDF] Total text extracted: {total_chars:,} chars")

        if not content or total_chars < 100:
            print(
                f"     [Stage 01] Per-page Azure OCR → Markdown: {file_path}"
            )
            content = extract_pdf_azure_di(file_path)
            total_chars = len(content) if content else 0
            print(f"     [Azure DI] Total Markdown extracted: {total_chars:,} chars")

            # Optional high-detail fallback for difficult chart-heavy scans.
            # It requires PyMuPDF only when explicitly enabled and is not part
            # of the normal fast path.
            if (not content or total_chars < 100) and os.getenv("PER_PAGE_OCR", "0") != "0" and os.getenv("AZURE_MISTRAL_OCR_KEY"):
                try:
                    from pipeline.utils.mistral_ocr import (
                        extract_pdf_per_page_parallel,
                        format_per_page_content,
                    )
                    print(f"     [Stage 01] Azure OCR was sparse; running optional per-page OCR: {file_path}")
                    page_texts = extract_pdf_per_page_parallel(
                        file_path,
                        max_workers=max(1, int(os.getenv("OCR_MAX_WORKERS", "5"))),
                    )
                    content = format_per_page_content(page_texts)
                    total_chars = len(content) if content else 0
                    print(f"     [Mistral OCR] Per-page total: {total_chars:,} chars")
                except Exception as exc:
                    print(f"     [Mistral OCR] Optional per-page OCR failed: {exc}")

        if not content or total_chars < 100:
            raise ValueError(
                "All OCR methods failed and the PDF has no selectable text. "
                "Check OCR credentials or provide a text-based PDF."
            )

        print("     [Stage 01] Parsing per-page Markdown into MasterDocument DOM...")
        master_doc = MasterDocument(
            source_file=file_path,
            source_format="pdf",
            source_metadata={
                "extraction_mode": "azure_document_intelligence_markdown"
                if content and os.getenv("PREFER_LOCAL_PDF_TEXT", "0") == "0"
                else "local_pdf_text_or_fallback",
                "markdown_chars": total_chars,
            },
        )

        # Split content into pages using regex markers
        raw_chunks = _PAGE_BREAK_PATTERN.split(content)
        
        # If pattern didn't match (e.g. single raw string without breaks)
        if len(raw_chunks) == 1:
            raw_chunks = [None, None, content]

        # raw_chunks format from re.split with 1 capture group:
        # [leading_text, page_num_1, chunk_1, page_num_2, chunk_2, ...]
        page_items = []
        i = 0
        while i < len(raw_chunks):
            chunk = raw_chunks[i]
            if chunk is None or not str(chunk).strip():
                i += 1
                continue
            
            # Check if this item is a captured page number digit
            if str(chunk).strip().isdigit() and i + 1 < len(raw_chunks):
                p_num = int(str(chunk).strip())
                p_text = raw_chunks[i + 1] if raw_chunks[i + 1] else ""
                page_items.append((p_num, p_text))
                i += 2
            else:
                p_num = len(page_items) + 1
                page_items.append((p_num, str(chunk)))
                i += 1

        for page_num, page_content in page_items:
            page_content = page_content.strip()
            if not page_content:
                continue

            section = SectionNode(heading=f"Page {page_num}", level=1)
            for p_idx, para in enumerate(page_content.split("\n\n")):
                para = para.strip()
                if para:
                    section.nodes.append(ParagraphNode(
                        id=f"p{page_num}_{p_idx}",
                        page_num=page_num,
                        text=para,
                    ))
            if section.nodes:
                master_doc.sections.append(section)
                master_doc.page_markdown[str(page_num)] = page_content

        print(f"     [Stage 01] MasterDocument complete — {len(master_doc.sections)} pages with per-page tracking.")
        return master_doc
