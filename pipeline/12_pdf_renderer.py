"""Backward-compatible wrapper for the active Stage 15 renderer."""
import importlib

_renderer = importlib.import_module("pipeline.15_pdf_renderer.renderer")

async def render_pdf(report: 'GeojitReportData', output_path: str) -> str:
    """
    Renders the ReportData to a PDF file using Jinja2 and Playwright.
    """
    return await _renderer.PDFRenderer.render_pdf(report, output_path)

if __name__ == "__main__":
    print("12_pdf_renderer.py ready.")
