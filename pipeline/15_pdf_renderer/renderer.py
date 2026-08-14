"""
renderer.py - Stage 15: PDF Renderer

Geojit 4-page HTML → headless Chromium → A4 PDF.
Does not invent research. Missing values print as —.
"""
import os
import tempfile
import re
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from pipeline.report_quality import (
    check_pdf_file,
    check_rendered_html,
    check_report_payload,
    score_report_quality,
    _valid_chart_count,
)

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

NA = "—"
_MOJIBAKE = (
    ("â€”", "—"),
    ("â€“", "–"),
    ("â€™", "'"),
    ("â€œ", '"'),
    ("â€\x9d", '"'),
    ("Ã—", "×"),
)

_WAIT_IMAGES_JS = """
async () => {
  const imgs = Array.from(document.images || []);
  await Promise.all(imgs.map((img) => {
    if (img.complete) return Promise.resolve();
    return new Promise((resolve) => {
      img.addEventListener("load", resolve, { once: true });
      img.addEventListener("error", resolve, { once: true });
    });
  }));
  if (document.fonts && document.fonts.ready) {
    await document.fonts.ready;
  }
}
"""


def jinja_finalize(value):
    """Print None / 'None' as an em-dash. {% if %} tests still see real None."""
    if value is None:
        return NA
    if isinstance(value, str) and value.strip() in ("None", "NoneType", "null", "undefined"):
        return NA
    return value


def file_uri(path: str) -> str:
    return Path(path).resolve().as_uri()


def clean_pdf_text(text):
    if not isinstance(text, str):
        return text
    s = text
    for bad, good in _MOJIBAKE:
        s = s.replace(bad, good)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def strip_source_tags(obj):
    if isinstance(obj, str):
        cleaned = re.sub(r"\s*\[Source:[^\]]+\]", "", obj)
        cleaned = re.sub(r"\s*\[E\]", "", cleaned)
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"^##\s+.+$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"^#\s+.+$", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return clean_pdf_text(cleaned)
    if isinstance(obj, dict):
        return {k: strip_source_tags(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_source_tags(i) for i in obj]
    return obj


class PDFRenderer:
    @staticmethod
    async def _launch_chromium(playwright, args):
        """Launch Chromium, falling back to Edge/Chrome if Playwright's browser is missing."""
        attempts = [
            {},
            {"channel": "msedge"},
            {"channel": "chrome"},
        ]
        last_error = None
        for kwargs in attempts:
            try:
                browser = await playwright.chromium.launch(
                    headless=True, args=args, **kwargs
                )
                label = kwargs.get("channel") or "playwright-chromium"
                print(f"     [PDF Renderer] Browser: {label}")
                return browser
            except Exception as exc:
                last_error = exc
                print(f"     [PDF Renderer] Launch failed ({kwargs or 'bundled'}): {exc}")
        raise last_error

    @staticmethod
    async def render_pdf(report, output_path: str = "output_report.pdf", template_name: str = "geojit_report.html") -> str:
        """
        Renders the ReportData to a PDF file using Jinja2 and Playwright.

        Always renders the Geojit 4-page template for sample/layout parity.
        report.sections may exist for metadata but does not switch templates.
        """
        # Geojit layout is mandatory for assignment/sample parity.
        # report.sections may still be populated for metadata; that must NOT
        # switch templates or disable Geojit PDF QA.
        if template_name == "adaptive_report.html":
            template_name = "geojit_report.html"
        print(f"     [PDF Renderer] Compiling HTML & CSS Templates ({template_name})...")
        
        # We need absolute paths to load assets
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        templates_dir = os.path.join(project_root, "templates")
        
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            finalize=jinja_finalize,
            autoescape=False,
        )

        def _clip_sentences(text, max_sentences=4, max_chars=650):
            """Keep Page 1 narrative compact without cutting mid-sentence."""
            if not text:
                return text
            s = str(text).strip()
            s = re.sub(
                r"(target(?: price)? of|upside of)\s+(?=[A-Z])",
                r"\1. ",
                s,
            )
            # Do not treat Rs. / Mr. as sentence ends — that produced "cr) for Q2…".
            s = re.sub(
                r"\b(Rs|Mr|Ms|Mrs|Dr|No|vs|Fig)\.\s+",
                lambda m: m.group(1) + ".\u00a0",
                s,
            )
            parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]
            complete = []
            for part in parts:
                if not re.search(r"[.!?]$", part):
                    continue
                if re.match(r"^(cr|bn|mn)\)", part, re.I):
                    continue
                if re.search(r"(?:target of|target price of|upside of)\s*[—\-–…\.]*$", part, re.I):
                    continue
                if re.search(r"target of\s+[A-Z]", part):
                    continue
                if len(part) < 20 and not re.search(r"\d", part):
                    continue
                complete.append(part)
            source = complete or [p for p in parts if re.search(r"[.!?]$", p)]
            kept = []
            used = 0
            for part in source[:max_sentences]:
                extra = len(part) + (1 if kept else 0)
                if kept and used + extra > max_chars:
                    break
                kept.append(part)
                used += extra
            return " ".join(kept).strip() or s

        env.filters["clip_sentences"] = _clip_sentences

        def _signed_chg(val):
            """Render a growth cell as +7.4 / -0.5 / —."""
            if val is None:
                return "—"
            text = str(val).strip()
            if text in ("", "—", "None", "NoneType"):
                return "—"
            try:
                number = float(text.replace("%", "").replace("+", ""))
            except (TypeError, ValueError):
                return text
            if number > 0:
                return f"+{number}"
            return str(number)

        env.filters["signed_chg"] = _signed_chg

        # Fall back to geojit_report.html if specified template is missing
        actual_template_name = template_name if os.path.exists(os.path.join(templates_dir, template_name)) else "geojit_report.html"
        template = env.get_template(actual_template_name)
        
        report_dict = report.model_dump() if hasattr(report, "model_dump") else report.dict()

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

        report_dict = strip_source_tags(report_dict)
        charts = report_dict.get("charts")
        if isinstance(charts, dict):
            report_dict["charts"] = {
                key: blob for key, blob in charts.items()
                if isinstance(blob, str) and len(blob) > 80
            }
        payload_errors = check_report_payload(report_dict)
        if payload_errors:
            raise ValueError("Assignment checks failed: " + "; ".join(payload_errors))
        quality_score = score_report_quality(report_dict, verification_errors=payload_errors)
        print(
            "     [Report quality] "
            f"{quality_score.total}/50 "
            f"(structure {quality_score.structure}/10, "
            f"accuracy {quality_score.data_accuracy}/10, "
            f"completeness {quality_score.completeness}/10, "
            f"charts {quality_score.chart_quality}/8, "
            f"narrative {quality_score.narrative_quality}/7, "
            f"valuation {quality_score.valuation}/5; "
            f"{quality_score.valuation_state})"
        )

        html_out = template.render(report=report_dict)

        # Inline CSS so Chromium can render from a temp file without extra fetches.
        css_path = os.path.join(templates_dir, "geojit_report.css")
        if os.path.exists(css_path):
            with open(css_path, "r", encoding="utf-8") as f:
                css_content = f.read()
            html_out = html_out.replace(
                '<link rel="stylesheet" href="geojit_report.css">',
                f'<style>{css_content}</style>'
            )

        html_errors = check_rendered_html(html_out, report_dict)
        if html_errors:
            raise ValueError("Assignment checks failed: " + "; ".join(html_errors))
        expected_charts = _valid_chart_count(report_dict.get("charts"))
        
        # Save to a temporary file
        temp_html_fd, temp_html_path = tempfile.mkstemp(suffix=".html")
        with os.fdopen(temp_html_fd, 'w', encoding='utf-8') as f:
            f.write(html_out)
            
        final_output_path = output_path if os.path.isabs(output_path) else os.path.join(project_root, output_path)
        os.makedirs(os.path.dirname(final_output_path), exist_ok=True)
            
        if not PLAYWRIGHT_AVAILABLE:
            raise ValueError("Assignment checks failed: PDF did not render (Playwright not installed)")

        print("     [PDF Renderer] Launching headless Chromium to render PDF...")
        # Use Playwright to capture pixel-perfect PDF
        # Args: disable GPU features that cause font encoding issues on Windows
        # --font-render-hinting=none ensures consistent Unicode rendering
        # --disable-font-subpixel-positioning prevents ₹ glyph substitution issues
        launch_args = [
            "--allow-file-access-from-files",
            "--font-render-hinting=none",
            "--disable-font-subpixel-positioning",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ]
        try:
            async with async_playwright() as p:
                browser = await PDFRenderer._launch_chromium(p, launch_args)
                page = await browser.new_page()
                await page.emulate_media(media="print")
                await page.goto(
                    file_uri(temp_html_path),
                    wait_until="load",
                    timeout=120_000,
                )
                try:
                    await page.evaluate(_WAIT_IMAGES_JS)
                except Exception as exc:
                    print(f"     [PDF Renderer] Image wait skipped: {exc}")
                settle_ms = max(0, int(os.getenv("PDF_RENDER_SETTLE_MS", "200")))
                if settle_ms:
                    await page.wait_for_timeout(settle_ms)
                await page.pdf(
                    path=final_output_path,
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={"top": "0px", "bottom": "0px", "left": "0px", "right": "0px"},
                )
                await browser.close()
        except Exception as exc:
            raise ValueError(f"Assignment checks failed: PDF did not render: {exc}") from exc
        finally:
            keep_html = os.getenv("PDF_KEEP_HTML", "").strip().lower() in {"1", "true", "yes"}
            if keep_html:
                debug_html = str(Path(final_output_path).with_suffix(".html"))
                try:
                    Path(debug_html).write_text(
                        Path(temp_html_path).read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                    print(f"     [PDF Renderer] Kept HTML at {debug_html}")
                except Exception:
                    pass
            if os.path.exists(temp_html_path):
                os.remove(temp_html_path)
            
        pdf_errors = check_pdf_file(final_output_path, expected_chart_count=expected_charts)
        if pdf_errors:
            raise ValueError("Assignment checks failed: " + "; ".join(pdf_errors))
        print("     [Assignment checks] PDF rendered successfully.")
        print(f"     [PDF Renderer] PDF successfully written to {final_output_path}")
        return final_output_path
