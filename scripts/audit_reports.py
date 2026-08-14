"""Audit generated PDFs for empty pages, missing charts, placeholders, sparse sections."""
import json
import re
from pathlib import Path

import fitz

OUTPUT_DIR = Path("outputs")


def report_files() -> list[Path]:
    """Discover reports produced by either current or legacy naming conventions."""
    if not OUTPUT_DIR.is_dir():
        return []
    return sorted(
        path
        for path in OUTPUT_DIR.glob("*.pdf")
        if path.name.endswith(("_Equity_Report.pdf", "_Geojit_Report.pdf"))
    )


def audit(path: Path) -> dict:
    doc = fitz.open(path)
    info = {
        "file": str(path),
        "pages": doc.page_count,
        "page_detail": [],
        "issues": [],
    }
    full_parts = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        imgs = page.get_images(full=True)
        full_parts.append(text)
        heads = re.findall(
            r"(Result Highlights|Outlook & Valuation|Quarterly Financials|"
            r"Key highlights|Consolidated Financials|Recommendation Summary|"
            r"DISCLAIMER|Forward Estimates|Change in Estimates|Company Data|"
            r"Shareholding|Price Performance|Profit & Loss|Balance Sheet|"
            r"Cash Flow|Ratios)",
            text,
            re.I,
        )
        detail = {
            "page": i + 1,
            "chars": len(text.strip()),
            "images": len(imgs),
            "heads": heads,
            "preview": text[:900],
        }
        info["page_detail"].append(detail)
        if len(text.strip()) < 250:
            info["issues"].append(f"Page {i + 1}: nearly empty ({len(text.strip())} chars)")
        if i == 1 and len(imgs) == 0:
            info["issues"].append("Page 2: no chart images (expected Story in Charts here)")
        if i == 1 and len(imgs) > 0:
            info["page2_has_charts"] = True

    full = "\n".join(full_parts)
    info["em_dash_count"] = full.count("—")
    info["not_available"] = len(re.findall(r"not available|Not available", full, re.I))
    info["fake_tokens"] = re.findall(
        r"FieldInfo|undefined|\{\{|lorem ipsum|TODO|FIXME|\bNaN\b", full, re.I
    )
    if info["fake_tokens"]:
        info["issues"].append(f"Fake/placeholder tokens: {info['fake_tokens']}")

    m = re.search(r"Result Highlights(.*?)Outlook", full, re.S | re.I)
    if m:
        block = m.group(1).strip()
        info["highlights_chars"] = len(block)
        info["highlights_preview"] = block[:400]
        # bullets often use • or start after heading with little content
        if len(block) < 60:
            info["issues"].append("Result Highlights looks empty/near-empty on page 1")
    else:
        info["issues"].append("Could not locate Result Highlights block")

    if re.search(r"Shareholding", full, re.I) and re.search(
        r"Shareholding[\s\S]{0,300}(not available|—\s*—)", full, re.I
    ):
        info["issues"].append("Shareholding section empty / not available")

    if "NOT RATED" in full or "Not Rated" in full:
        info["issues"].append("Recommendation is NOT RATED (no CMP/target in source PDF)")

    total_imgs = sum(d["images"] for d in info["page_detail"])
    info["total_images"] = total_imgs
    if total_imgs < 2:
        info["issues"].append(f"Very few images embedded ({total_imgs})")

    # Thin pages (possible whitespace waste)
    for d in info["page_detail"]:
        if 250 <= d["chars"] < 900 and d["images"] == 0:
            info["issues"].append(
                f"Page {d['page']}: sparse content ({d['chars']} chars, 0 images) — possible empty whitespace"
            )

    doc.close()
    return info


def main():
    results = [audit(path) for path in report_files()]
    Path("_report_audit.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    for info in results:
        print("=" * 70)
        print(info["file"], f"({info['pages']} pages, {info['total_images']} images)")
        for d in info["page_detail"]:
            print(
                f"  P{d['page']}: {d['chars']:5d} chars | {d['images']} imgs | {d['heads'][:6]}"
            )
        print(f"  em_dashes={info['em_dash_count']}  not_available={info['not_available']}")
        print(f"  highlights_chars={info.get('highlights_chars')}")
        hp = info.get("highlights_preview")
        if hp is not None:
            print("  highlights_preview:", repr(hp[:250]))
        print("  ISSUES:")
        if not info["issues"]:
            print("   (none)")
        for issue in info["issues"]:
            print("   -", issue)
        print()


if __name__ == "__main__":
    main()
