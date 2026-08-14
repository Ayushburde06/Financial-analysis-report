"""Provenance links printed in this filing — never a demo IR URL list."""
from __future__ import annotations

import re
from typing import List
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)
_IR_HINTS = (
    "investor", "invest-relation", "invest_relation",
    "result", "presentation", "annual-report", "annualreport",
    "financial-report", "quarterly",
)
_SKIP_HOSTS = (
    "facebook.com", "twitter.com", "x.com", "linkedin.com",
    "youtube.com", "instagram.com", "google.com", "goo.gl",
)


def _clean_url(raw: str) -> str:
    url = (raw or "").rstrip(".,;:)")
    url = url.split("]")[0].split(">")[0]
    return url.strip()


def _is_ir_url(url: str) -> bool:
    low = url.lower()
    host = (urlparse(url).netloc or "").lower()
    if any(skip in host for skip in _SKIP_HOSTS):
        return False
    return any(hint in low for hint in _IR_HINTS)


def official_sources_for(
    company_name: str = "",
    period: str = "",
    ocr_text: str = "",
    source_filename: str = "",
):
    """URLs actually printed in this source. Empty if none. No sample PDFs."""
    _ = (company_name, source_filename)
    found: List[str] = []
    seen = set()
    for match in _URL_RE.findall(ocr_text or ""):
        url = _clean_url(match)
        if not url or url.lower() in seen or not _is_ir_url(url):
            continue
        seen.add(url.lower())
        found.append(url)
        if len(found) >= 3:
            break
    period_label = (period or "").strip()
    return [
        {
            "source_type": "URL printed in uploaded source",
            "url": url,
            "period": period_label,
            "status": "extracted from uploaded source",
        }
        for url in found
    ]
