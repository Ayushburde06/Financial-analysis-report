"""
renderer.py - Stage 15: PDF Renderer
Generates the final Geojit-style PDF by rendering the HTML in headless Chromium.
"""
import os
import sys
import tempfile
import asyncio
import re
import json
from jinja2 import Environment, FileSystemLoader

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

class PDFRenderer:
    @staticmethod
    def _validate_html_before_render(html_out: str, report_dict: dict) -> dict:
        """Fail closed if the rendered report input is incomplete or malformed.

        This is intentionally a structural gate, not a second financial extractor:
        Stage 12b already verifies source values. Here we verify that the verified
        values, tables, and chart images actually made it into the HTML sent to
        Chromium.
        """
        errors = []
        warnings = []
        required_labels = (
            "Equity Research Report",
            "Quarterly Financials",
            "Consolidated Financials",
            "Recommendation Summary",
            "Disclaimer",
        )
        missing_labels = [label for label in required_labels if label.lower() not in html_out.lower()]
        if missing_labels:
            errors.append("Missing report sections in HTML: " + ", ".join(missing_labels))

        if re.search(r"\{\{|\{%|%\}", html_out):
            errors.append("Unresolved template markup remains in generated HTML")

        # Base64 chart payloads can legitimately contain strings such as "NaN".
        # Inspect rendered text/markup, not encoded image bytes.
        html_without_images = re.sub(
            r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+", "", html_out
        )
        forbidden = ("FieldInfo", "annotation=", "undefined", "NaN")
        found_forbidden = [token for token in forbidden if token in html_without_images]
        if found_forbidden:
            errors.append("Invalid rendered values found: " + ", ".join(found_forbidden))
        if re.search(r"\[(?:key growth driver|key concern(?: or valuation comment)?)\]", html_without_images, re.IGNORECASE):
            errors.append("Prompt placeholder leaked into generated HTML")

        charts = report_dict.get("charts") or {}
        valid_charts = 0
        for chart_id, value in charts.items():
            if isinstance(value, str) and len(value) > 1000:
                valid_charts += 1
            else:
                warnings.append(f"Chart {chart_id} is empty or unusually small")
        html_chart_count = html_out.count("data:image/png;base64,")
        if charts and html_chart_count < valid_charts:
            errors.append(
                f"Only {html_chart_count}/{valid_charts} validated chart image(s) reached HTML"
            )
        if not charts:
            errors.append("No chart data was supplied to the report template")

        table_count = len(re.findall(r"<table\b", html_out, flags=re.IGNORECASE))
        if table_count < 4:
            errors.append(f"Only {table_count} HTML table(s) found; financial report is incomplete")

        text_len = len(re.sub(r"<[^>]+>", " ", html_out))
        if text_len < 1500:
            errors.append("Generated HTML contains too little report text")

        result = {
            "errors": errors,
            "warnings": warnings,
            "html_tables": table_count,
            "chart_data": valid_charts,
            "html_charts": html_chart_count,
            "text_chars": text_len,
        }
        print(
            f"     [HTML QA] {table_count} table(s), "
            f"{html_chart_count} chart image(s), {text_len:,} text chars"
        )
        for warning in warnings[:5]:
            print(f"     [HTML QA] WARNING: {warning}")
        if errors:
            raise ValueError("HTML quality gate failed: " + "; ".join(errors))
        print("     [HTML QA] Passed before Chromium rendering.")
        return result

    @staticmethod
    def _validate_pdf_after_render(pdf_path: str, expected_chart_count: int) -> dict:
        """Reopen the final PDF and verify that Chromium produced usable pages."""
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PyMuPDF is required for final PDF QA") from exc

        doc = fitz.open(pdf_path)
        page_count = doc.page_count
        page_texts = [page.get_text("text").strip() for page in doc]
        page_text_lengths = [len(text) for text in page_texts]
        image_count = sum(len(page.get_images(full=True)) for page in doc)
        bad_pages = [i + 1 for i, length in enumerate(page_text_lengths) if length < 80]
        orphan_pages = []
        for i in range(max(0, len(doc) - 1)):
            page = doc[i]
            text = page_texts[i].lower()
            next_text = page_texts[i + 1].lower()
            has_images = bool(page.get_images(full=True))
            looks_like_metric_spill = "key metrics" in text or "banking snapshot" in text
            current_is_major_section = (
                "consolidated financials" in text
                or "recommendation summary" in text
            )
            starts_next_major_section = (
                "consolidated financials" in next_text
                or "recommendation summary" in next_text
            )
            if (
                not has_images
                and len(text) < 2200
                and looks_like_metric_spill
                and not current_is_major_section
                and starts_next_major_section
            ):
                orphan_pages.append(i + 1)
        full_text = "\n".join(page.get_text("text") for page in doc)
        invalid_tokens = [token for token in ("undefined", "FieldInfo", "{{", "NaN") if token in full_text]
        doc.close()

        if page_count < 3:
            raise ValueError(f"PDF quality gate failed: only {page_count} page(s) rendered")
        if bad_pages:
            raise ValueError(f"PDF quality gate failed: nearly empty page(s): {bad_pages}")
        if orphan_pages:
            raise ValueError(
                "PDF quality gate failed: section overflow page(s) detected: "
                f"{orphan_pages}."
            )
        if invalid_tokens:
            raise ValueError("PDF quality gate failed: invalid token(s): " + ", ".join(invalid_tokens))
        if expected_chart_count and image_count < expected_chart_count:
            raise ValueError(
                f"PDF quality gate failed: {image_count} image(s) embedded, "
                f"expected at least {expected_chart_count} chart image(s)"
            )

        result = {
            "pages": page_count,
            "images": image_count,
            "page_text_lengths": page_text_lengths,
            "orphan_pages": orphan_pages,
        }
        print(
            f"     [PDF QA] Passed: {page_count} pages, {image_count} embedded image(s), "
            f"no empty or invalid pages."
        )
        return result

    @staticmethod
    async def render_pdf(report, output_path: str = "output_report.pdf", template_name: str = "geojit_report.html") -> str:
        """
        Renders the ReportData to a PDF file using Jinja2 and Playwright.
        """
        print(f"     [PDF Renderer] Compiling HTML & CSS Templates ({template_name})...")
        
        # We need absolute paths to load assets
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        templates_dir = os.path.join(project_root, "templates")
        
        env = Environment(loader=FileSystemLoader(templates_dir))
        
        # Fall back to geojit_report.html if specified template is missing
        actual_template_name = template_name if os.path.exists(os.path.join(templates_dir, template_name)) else "geojit_report.html"
        template = env.get_template(actual_template_name)
        
        report_dict = report.model_dump() if hasattr(report, "model_dump") else report.dict()

        # ── Fix Pydantic annotation leak in company.name ──────────────────────
        import re as _re
        company = report_dict.get("company", {})
        if isinstance(company, dict):
            name_val = str(company.get("name", ""))
            if "annotation=" in name_val or "FieldInfo" in name_val or "required=" in name_val:
                try:
                    actual_name = None
                    if hasattr(report, "company") and hasattr(report.company, "name"):
                        raw_name = report.company.name
                        if isinstance(raw_name, str) and "annotation=" not in raw_name:
                            actual_name = raw_name
                    company["name"] = actual_name or "Unknown Company"
                except Exception:
                    company["name"] = "Unknown Company"
                report_dict["company"] = company

        # ── Pass sector_cfg as a plain dict so Jinja2 can access attributes ──
        fin = report_dict.get("financials", {})
        if isinstance(fin, dict):
            cfg_obj = fin.get("sector_cfg")
            if cfg_obj is not None and not isinstance(cfg_obj, dict):
                # Convert dataclass / Pydantic object to dict
                try:
                    import dataclasses
                    if dataclasses.is_dataclass(cfg_obj):
                        fin["sector_cfg"] = dataclasses.asdict(cfg_obj)
                    elif hasattr(cfg_obj, "model_dump"):
                        fin["sector_cfg"] = cfg_obj.model_dump()
                    elif hasattr(cfg_obj, "__dict__"):
                        fin["sector_cfg"] = cfg_obj.__dict__
                except Exception:
                    fin["sector_cfg"] = {}
            report_dict["financials"] = fin

        # ── Strip internal [Source: field.path] citation tags ─────────────────
        def strip_source_tags(obj):
            if isinstance(obj, str):
                cleaned = _re.sub(r'\s*\[Source:[^\]]+\]', '', obj)
                cleaned = _re.sub(r'\s*\[E\]', '', cleaned)
                cleaned = _re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
                cleaned = _re.sub(r'^##\s+.+$', '', cleaned, flags=_re.MULTILINE)
                cleaned = _re.sub(r'^#\s+.+$', '', cleaned, flags=_re.MULTILINE)
                cleaned = _re.sub(r'\n{3,}', '\n\n', cleaned)
                return cleaned.strip()
            elif isinstance(obj, dict):
                return {k: strip_source_tags(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [strip_source_tags(i) for i in obj]
            return obj

        report_dict = strip_source_tags(report_dict)

        html_out = template.render(report=report_dict)

        # DEBUG: save HTML to file for inspection
        debug_html_path = os.path.join(os.path.dirname(__file__), "..", "_debug_report.html")
        with open(debug_html_path, "w", encoding="utf-8") as f:
            f.write(html_out)
        print(f"     [DEBUG] HTML saved to {debug_html_path}")
        
        # Inline CSS to avoid ERR_FILE_NOT_FOUND when loading from Temp dir
        css_filename = "modern_report.css" if "modern" in actual_template_name else "geojit_report.css"
        css_path = os.path.join(templates_dir, css_filename)
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()
            html_out = html_out.replace(
                f'<link rel="stylesheet" href="{css_filename}">', 
                f'<style>{css_content}</style>'
            ).replace(
                '<link rel="stylesheet" href="geojit_report.css">', 
                f'<style>{css_content}</style>'
            )

        # Validate the exact HTML string that will be handed to Chromium.
        # This catches missing charts/tables and unresolved template values before
        # a visually polished but incomplete PDF can be produced.
        html_qa = PDFRenderer._validate_html_before_render(html_out, report_dict)
        
        # Save to a temporary file
        temp_html_fd, temp_html_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(temp_html_fd, 'w', encoding='utf-8') as f:
            f.write(html_out)
            
        final_output_path = output_path if os.path.isabs(output_path) else os.path.join(project_root, output_path)
        os.makedirs(os.path.dirname(final_output_path), exist_ok=True)
            
        if not PLAYWRIGHT_AVAILABLE:
            print("     [PDF Renderer] WARNING: Playwright not installed. Saving HTML output instead of PDF.")
            html_save_path = os.path.join(project_root, "output_report.html")
            with open(html_save_path, 'w', encoding='utf-8') as f:
                f.write(html_out)
            if os.path.exists(temp_html_path):
                os.remove(temp_html_path)
            return html_save_path

        print("     [PDF Renderer] Launching headless Chromium to render PDF...")
        # Use Playwright to capture pixel-perfect PDF
        # Args: disable GPU features that cause font encoding issues on Windows
        # --font-render-hinting=none ensures consistent Unicode rendering
        # --disable-font-subpixel-positioning prevents ₹ glyph substitution issues
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--allow-file-access-from-files',
                        '--font-render-hinting=none',
                        '--disable-font-subpixel-positioning',
                        '--disable-gpu',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                    ]
                )
                page = await browser.new_page()
                file_url = f"file:///{temp_html_path.replace(os.sep, '/')}"
                await page.goto(file_url, wait_until="networkidle")
                # All charts and CSS are embedded in the generated HTML, so a
                # short settle period is sufficient and avoids an unnecessary
                # two-second delay on every report.
                settle_ms = max(0, int(os.getenv("PDF_RENDER_SETTLE_MS", "500")))
                await page.wait_for_timeout(settle_ms)
                await page.pdf(
                    path=final_output_path,
                    format="A4",
                    print_background=True,
                    margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"},
                )
                await browser.close()
        finally:
            if os.path.exists(temp_html_path):
                os.remove(temp_html_path)
            
        PDFRenderer._validate_pdf_after_render(
            final_output_path,
            expected_chart_count=html_qa["chart_data"],
        )
        print(f"     [PDF Renderer] PDF successfully written to {final_output_path}")
        return final_output_path
