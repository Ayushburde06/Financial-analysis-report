"""
11_chart_generator.py — Matplotlib Chart Generator
Generates base64-encoded PNG charts for embedding directly in the PDF.
No CDN dependency — works fully offline in headless Chromium.

Periods come from this filing. No Q2FY26 / FY26E default axis.
"""
import io
import base64
import re
from typing import Dict, Any, Optional, List

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend — safe for headless rendering
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# Geojit brand colours
NAVY  = "#00234b"
RED   = "#b42318"
TEAL  = "#087f8c"
GREY  = "#7b8794"
LIGHT = "#d9e7ef"
GRID  = "#d9e2ec"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_png_b64(fig) -> str:
    """Convert a matplotlib figure to a base64-encoded PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return b64


def _period_sort_key(label: str):
    s = str(label or "").upper().replace(" ", "")
    qtr = re.match(r"Q(\d)FY(\d{2,4})", s)
    if qtr:
        year = int(qtr.group(2))
        return (year % 100 if year > 100 else year, int(qtr.group(1)))
    fy = re.match(r"FY(\d{2,4})([AE])?", s)
    if fy:
        year = int(fy.group(1))
        suffix = 1 if (fy.group(2) or "").upper() == "E" else 0
        return (year % 100 if year > 100 else year, 10 + suffix)
    return (99, 0, s)


def _sorted_keys(d: Dict[str, Any]) -> List[str]:
    return sorted(d.keys(), key=_period_sort_key)


def _clean(d: Dict[str, Any]) -> Dict[str, float]:
    """Keep only numeric, non-zero entries from a year→value dict."""
    out = {}
    for k, v in (d or {}).items():
        try:
            f = float(v)
            if f != 0:
                out[k] = f
        except (TypeError, ValueError):
            pass
    return out


def chart_quarters(quarterly: Dict[str, Any]) -> List[str]:
    """Quarters that actually have data, in this filing's order."""
    qtr_rev = _clean((quarterly or {}).get("revenue", {}))
    qtr_pat = _clean((quarterly or {}).get("pat", {}))
    listed = [q for q in ((quarterly or {}).get("quarters") or []) if q]
    data_keys = list(dict.fromkeys([*qtr_rev.keys(), *qtr_pat.keys()]))
    order = listed or _sorted_keys({k: 1 for k in data_keys})
    return [q for q in order if qtr_rev.get(q) or qtr_pat.get(q)]


def _styled_fig(nrows=1, ncols=1, figsize=(5.5, 2.2)):
    fig, ax = plt.subplots(nrows, ncols, figsize=figsize)
    fig.patch.set_facecolor("white")
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.titleweight": "bold",
        "axes.edgecolor": "#9aa7b5",
        "axes.labelcolor": NAVY,
        "xtick.color": "#344054",
        "ytick.color": "#344054",
    })
    return fig, ax


def _format_label(val: float) -> str:
    """Smart number formatting: show 1 decimal for small, 0 decimal for large."""
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    if abs(val) >= 100:
        return f"{val:.1f}"
    return f"{val:.2f}"


def _axis_year(label: str, is_estimate: bool) -> str:
    text = str(label)
    upper = text.upper()
    if is_estimate:
        return text if upper.endswith("E") else f"{text}E"
    if upper.startswith("FY") and not upper.endswith(("A", "E")):
        return f"{text}A"
    return text


def _label_last_bars(ax, bars, count=1, fontsize=8):
    """Annotate only the latest bar(s) — the point the reader should notice."""
    visible = [bar for bar in bars if bar.get_height()]
    for bar in visible[-count:]:
        h = bar.get_height()
        ax.annotate(
            _format_label(h),
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 4), textcoords="offset points",
            ha="center", va="bottom", fontsize=fontsize, color=NAVY, fontweight="bold",
        )


def _source_footer(fig, ax, extra=""):
    note = "Source: company filing. Hatched/grey = AI estimate, not guidance."
    if extra:
        note = extra
    ax.text(0.0, -0.20, note, transform=ax.transAxes, fontsize=6.5,
            color="#475467", ha="left")


def _finish(fig, ax):
    fig.tight_layout(pad=0.8)
    fig.subplots_adjust(bottom=0.24)
    return _to_png_b64(fig)


# ── Chart 1: Revenue / NII Annual Trend ───────────────────────────────────────

def generate_revenue_trend_chart(
    annual: Dict[str, float],
    estimates: Dict[str, float],
    revenue_label: str = "Revenue",
    allow_thin: bool = False,
) -> Optional[str]:
    """Bar chart: historical actuals (navy) + forward estimates (hatched grey)."""
    hist = _clean(annual)
    est  = _clean(estimates)
    # A 1-actual + 2-estimate chart looks like a long history. Skip it
    # unless this is a last-resort thin filing (actuals only, no estimates).
    if len(hist) < 2:
        if not allow_thin or not hist:
            return None
        est = {}
    if not hist and not est:
        return None

    hist_keys = _sorted_keys(hist)
    est_keys = _sorted_keys(est)
    years  = [_axis_year(k, False) for k in hist_keys] + [_axis_year(k, True) for k in est_keys]
    values = [hist[k] for k in hist_keys] + [est[k] for k in est_keys]
    colors = [NAVY] * len(hist) + [GREY] * len(est)

    fig, ax = _styled_fig(figsize=(7.4, 3.05))
    bars = ax.bar(years, values, color=colors, width=0.55, edgecolor="white", linewidth=0.5)
    for i, bar in enumerate(bars):
        if i >= len(hist):
            bar.set_hatch("///")
            bar.set_edgecolor(NAVY)
            bar.set_linewidth(0.6)
    _label_last_bars(ax, list(bars)[:len(hist)], count=1)

    ax.set_title(f"{revenue_label} Trend", fontsize=11, color=NAVY, fontweight="bold", pad=9, loc="left")
    ax.set_ylabel(revenue_label, fontsize=8.5, color=NAVY)
    ax.tick_params(axis="x", rotation=0, labelsize=8.5)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle="-", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    if est:
        ax.legend(handles=[
            mpatches.Patch(color=NAVY, label="Actual"),
            mpatches.Patch(facecolor=GREY, hatch="///", edgecolor=NAVY, label="AI estimate"),
        ], fontsize=7, loc="upper left", framealpha=0.7)
    _source_footer(fig, ax)
    return _finish(fig, ax)


# ── Chart 2: PAT Trend ────────────────────────────────────────────────────────

def generate_pat_trend_chart(
    pat_annual: Dict[str, float],
    pat_estimates: Dict[str, float],
    eps_annual: Dict[str, float] = None,
    allow_thin: bool = False,
) -> Optional[str]:
    """Dual-axis: PAT bars (navy) + EPS line (red) if available."""
    hist = _clean(pat_annual)
    est  = _clean(pat_estimates)
    eps  = _clean(eps_annual or {})

    if len(hist) < 2:
        if not allow_thin or not hist:
            return None
        est = {}
    if not hist and not est:
        return None

    hist_keys = _sorted_keys(hist)
    est_keys = _sorted_keys(est)
    years  = [_axis_year(k, False) for k in hist_keys] + [_axis_year(k, True) for k in est_keys]
    values = [hist[k] for k in hist_keys] + [est[k] for k in est_keys]
    colors = [NAVY] * len(hist) + [GREY] * len(est)

    if eps:
        fig, ax1 = _styled_fig(figsize=(7.4, 3.05))
        ax2 = ax1.twinx()
    else:
        fig, ax1 = _styled_fig(figsize=(7.4, 3.05))
        ax2 = None

    bars = ax1.bar(years, values, color=colors, width=0.55, edgecolor="white", linewidth=0.5)
    for i, bar in enumerate(bars):
        if i >= len(hist):
            bar.set_hatch("///")
            bar.set_edgecolor(NAVY)
            bar.set_linewidth(0.6)
    _label_last_bars(ax1, list(bars)[:len(hist)], count=1)

    if ax2 and eps:
        eps_years = [y for y in years if y in eps]
        eps_vals  = [eps[y] for y in eps_years]
        ax2.plot(eps_years, eps_vals, color=RED, marker="o", linewidth=1.8,
                 markersize=5, label="EPS")
        ax2.set_ylabel("EPS", fontsize=8, color=RED)
        ax2.tick_params(axis="y", labelcolor=RED, labelsize=8)
        ax2.spines["top"].set_visible(False)

    ax1.set_title("PAT & EPS Trend", fontsize=11, color=NAVY, fontweight="bold", pad=9, loc="left")
    ax1.set_ylabel("PAT", fontsize=8, color=NAVY)
    ax1.tick_params(axis="x", rotation=30, labelsize=8)
    ax1.tick_params(axis="y", labelsize=8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False) if not ax2 else None
    ax1.yaxis.grid(True, linestyle="-", color=GRID, linewidth=0.7)
    ax1.set_axisbelow(True)
    _source_footer(fig, ax1)
    return _finish(fig, ax1)


# ── Chart 3: Margin Breakdown (Revenue bar + Margin % line) ───────────────────

def generate_margin_chart(
    revenue_annual: Dict[str, float],
    pat_annual: Dict[str, float],
    ebitda_annual: Dict[str, float] = None,
    margin_title: str = "Margin Breakdown (%)",
    revenue_label: str = "Revenue",
    ebitda_label: str = "EBITDA",
) -> Optional[str]:
    """Dual-axis: top-line bar + PAT margin + operating margin."""
    rev = _clean(revenue_annual)
    pat = _clean(pat_annual)
    ebi = _clean(ebitda_annual or {})

    if not rev or not pat:
        return None
    # Need at least 2 years to show a meaningful margin trend line
    if len(rev) < 2 and len(pat) < 2:
        return None

    years = _sorted_keys(rev)
    rev_vals = [rev[y] for y in years]

    # Compute margins
    pat_margins  = [round(pat.get(y, 0) / rev[y] * 100, 1) if rev[y] else 0 for y in years]
    ebi_margins  = [round(ebi.get(y, 0) / rev[y] * 100, 1) if (ebi.get(y) and rev[y]) else None for y in years]

    fig, ax1 = _styled_fig(figsize=(7.4, 3.05))
    ax2 = ax1.twinx()

    bars = ax1.bar(years, rev_vals, color=LIGHT, width=0.55, edgecolor=NAVY, linewidth=0.5, label=revenue_label)
    ax1.set_ylabel(revenue_label, fontsize=8.5, color=NAVY)
    ax1.tick_params(axis="y", labelcolor=NAVY, labelsize=8.5)
    ax1.tick_params(axis="x", rotation=25, labelsize=8.5)

    ax2.plot(years, pat_margins, color=RED, marker="o", linewidth=2,
             markersize=5, label="PAT Margin %")
    if any(v is not None for v in ebi_margins):
        valid_y = [y for y, v in zip(years, ebi_margins) if v is not None]
        valid_v = [v for v in ebi_margins if v is not None]
        ax2.plot(valid_y, valid_v, color=NAVY, marker="s", linewidth=1.5,
                 markersize=4, linestyle="--", label=f"{ebitda_label} Margin %")

    ax2.set_ylabel("Margin (%)", fontsize=8.5, color=RED)
    ax2.tick_params(axis="y", labelcolor=RED, labelsize=8.5)
    ax2.yaxis.grid(True, linestyle="-", color=GRID, linewidth=0.7)

    ax1.set_title(margin_title, fontsize=11, color=NAVY, fontweight="bold", pad=9, loc="left")
    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)

    # Combined legend
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines2, labels2, fontsize=7, loc="upper left", framealpha=0.7)

    _source_footer(fig, ax1, extra="Source: company filing. Lines show calculated margins.")
    return _finish(fig, ax1)


# ── Chart 4: Quarterly Comparison (grouped bar) ───────────────────────────────

def generate_quarterly_chart(
    quarterly: Dict[str, Any],
    revenue_label: str = "Revenue",
    allow_thin: bool = False,
) -> Optional[str]:
    """Grouped bar: Revenue/NII and PAT for available quarters."""
    qtr_rev = _clean(quarterly.get("revenue", {}))
    qtr_pat = _clean(quarterly.get("pat", {}))
    quarters = chart_quarters(quarterly)
    rev_vals = [qtr_rev.get(q, 0) for q in quarters]
    pat_vals = [qtr_pat.get(q, 0) for q in quarters]

    if len(quarters) < 2 and not allow_thin:
        return None
    if len(quarters) < 1:
        return None
    if not any(rev_vals) and not any(pat_vals):
        return None

    x = np.arange(len(quarters))
    width = 0.35

    fig, ax = _styled_fig(figsize=(7.4, 3.05))
    bars1 = ax.bar(x - width/2, rev_vals, width, color=NAVY, label=revenue_label, edgecolor="white")
    bars2 = ax.bar(x + width/2, pat_vals, width, color=RED,  label="PAT", edgecolor="white")
    _label_last_bars(ax, bars1, count=1, fontsize=8)
    _label_last_bars(ax, bars2, count=1, fontsize=8)

    ax.set_title("Quarterly Performance", fontsize=11, color=NAVY, fontweight="bold", pad=9, loc="left")
    ax.set_xticks(x)
    ax.set_xticklabels(quarters, fontsize=9)
    ax.tick_params(axis="y", labelsize=8.5)
    ax.legend(fontsize=8, framealpha=0.9, loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle="-", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)
    _source_footer(fig, ax, extra="Source: company filing. Latest quarter labelled.")
    return _finish(fig, ax)


# ── Chart 5: Segment Breakdown Donut Chart ──────────────────────────────────────

def generate_segment_pie_chart(
    segment_data: Dict[str, float],
    title: str = "Revenue by Segment (%)",
) -> Optional[str]:
    """Donut chart for business segment revenue mix."""
    cleaned = _clean(segment_data)
    if not cleaned:
        return None

    labels = list(cleaned.keys())
    values = list(cleaned.values())
    colors = [NAVY, RED, "#3498db", "#2ecc71", "#f1c40f", GREY][:len(values)]

    fig, ax = _styled_fig(figsize=(5.8, 3.4))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        startangle=140, colors=colors,
        wedgeprops=dict(width=0.45, edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=7, color=NAVY)
    )
    plt.setp(autotexts, size=7, weight="bold", color="white")
    ax.set_title(title, fontsize=10.5, color=NAVY, fontweight="bold", pad=8, loc="left")
    _source_footer(fig, ax, extra="Source: company filing. Percentages show reported mix.")
    return _finish(fig, ax)


# ── Chart 6: Geography Breakdown Pie Chart ────────────────────────────────────

def generate_geography_pie_chart(
    geo_data: Dict[str, float],
    title: str = "Revenue by Geography (%)",
) -> Optional[str]:
    """Pie chart for geographic revenue distribution."""
    cleaned = _clean(geo_data)
    if not cleaned:
        return None

    labels = list(cleaned.keys())
    values = list(cleaned.values())
    colors = [NAVY, "#e67e22", "#9b59b6", "#1abc9c", GREY][:len(values)]

    fig, ax = _styled_fig(figsize=(5.8, 3.4))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        startangle=90, colors=colors,
        wedgeprops=dict(edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=7, color=NAVY)
    )
    plt.setp(autotexts, size=7, weight="bold", color="white")
    ax.set_title(title, fontsize=10.5, color=NAVY, fontweight="bold", pad=8, loc="left")
    _source_footer(fig, ax, extra="Source: company filing. Percentages show reported mix.")
    return _finish(fig, ax)


def _generate_banking_quality_chart(
    nim_data: Dict[str, float],
    gnpa_data: Dict[str, float],
    quarters: list,
) -> Optional[str]:
    """Bar+line chart: NIM bars (navy) + GNPA % line (red) for banking sector."""
    nim = _clean(nim_data)
    gnpa = _clean(gnpa_data)
    if not nim and not gnpa:
        return None
    qs = [q for q in (quarters or []) if q in nim or q in gnpa]
    if not qs:
        qs = _sorted_keys({**nim, **gnpa})
    if not qs:
        return None

    fig, ax1 = _styled_fig(figsize=(7.4, 3.05))
    nim_vals = [nim.get(q, 0) for q in qs]
    bars = ax1.bar(qs, nim_vals, color=NAVY, width=0.5, edgecolor="white", linewidth=0.5, label="NIM (%)")
    _label_last_bars(ax1, bars, count=1)
    ax1.set_ylabel("NIM (%)", fontsize=8.5, color=NAVY)
    ax1.tick_params(axis="x", rotation=20, labelsize=8.5)
    ax1.tick_params(axis="y", labelsize=8.5)
    ax1.set_ylim(0, max(nim_vals) * 1.3 if nim_vals else 6)

    if gnpa:
        ax2 = ax1.twinx()
        gnpa_vals = [gnpa.get(q, 0) for q in qs]
        ax2.plot(qs, gnpa_vals, color=RED, marker="s", linewidth=2, markersize=4, label="GNPA (%)")
        ax2.set_ylabel("GNPA (%)", fontsize=8.5, color=RED)
        ax2.tick_params(axis="y", labelsize=8.5, colors=RED)
        ax2.spines["right"].set_visible(True)
        ax2.set_ylim(0, max(gnpa_vals) * 2 if gnpa_vals else 5)

    ax1.set_title("Asset Quality (NIM & GNPA)", fontsize=10.5, color=NAVY, fontweight="bold", pad=8, loc="left")
    ax1.spines["top"].set_visible(False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    if gnpa:
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=6, loc="upper right", framealpha=0.7)
    else:
        ax1.legend(handles=bars, fontsize=6, loc="upper right", framealpha=0.7)
    _source_footer(fig, ax1, extra="Source: company filing. Latest NIM labelled.")
    return _finish(fig, ax1)


# ── Master entry point ────────────────────────────────────────────────────────

def generate_all_charts(
    annual_data: Dict[str, Any],
    quarterly_data: Dict[str, Any],
    sector_cfg=None,
    segment_data: Optional[Dict[str, float]] = None,
    geo_data: Optional[Dict[str, float]] = None,
) -> Dict[str, Optional[str]]:
    """
    Generate all 6 charts and return a dict of {chart_id: base64_png_string}.

    Args:
        annual_data:   {metric: {year: value}} — annual P&L data
        quarterly_data: {metric: {quarter: value}, "quarters": [...]}
        sector_cfg:    SectorConfig instance
        segment_data:  {segment_name: percentage_or_value}
        geo_data:      {region_name: percentage_or_value}
    """
    if not MATPLOTLIB_AVAILABLE:
        print("     [Chart Generator] WARNING: matplotlib not installed. Skipping charts.")
        return {}

    rev_label    = getattr(sector_cfg, "revenue_chart_label", "Revenue") if sector_cfg else "Revenue"
    margin_title = getattr(sector_cfg, "margin_chart_title",  "Margin Breakdown (%)") if sector_cfg else "Margin Breakdown (%)"

    rev_annual  = annual_data.get("revenue", {})
    rev_est     = annual_data.get("revenue_est", {})
    pat_annual  = annual_data.get("pat", {})
    pat_est     = annual_data.get("pat_est", {})
    eps_annual  = annual_data.get("eps", {})
    ebitda_ann  = annual_data.get("ebitda", {})

    charts = {}

    # Skip annual "trend" charts when there is only one actual year.
    # Skip annual "trend" charts when there is only one actual year.
    c1 = generate_revenue_trend_chart(rev_annual, rev_est, rev_label)
    if c1:
        charts["chart_revenue_trend"] = c1
    elif len(_clean(rev_annual)) < 2:
        print("     [Chart Generator] Skip annual NII/revenue trend: fewer than 2 actual years.")

    c2 = generate_pat_trend_chart(pat_annual, pat_est, eps_annual)
    if c2:
        charts["chart_pat_trend"] = c2
    elif len(_clean(pat_annual)) < 2:
        print("     [Chart Generator] Skip annual PAT trend: fewer than 2 actual years.")

    # Chart 3: use sector-specific metrics when available. Generic margin math
    # is not meaningful for banks because NII is not corporate revenue.
    sector_name = str(getattr(sector_cfg, "sector_name", "") if sector_cfg else "").lower()
    if "bank" in sector_name or "nbfc" in sector_name or "financial" in sector_name:
        nim_data = quarterly_data.get("nim", {}) if quarterly_data else {}
        gnpa_data = quarterly_data.get("gnpa", {}) if quarterly_data else {}
        if nim_data or gnpa_data:
            c3 = _generate_banking_quality_chart(
                nim_data, gnpa_data, quarterly_data.get("quarters", [])
            )
            if c3:
                charts["chart_asset_quality"] = c3
        else:
            c3 = generate_margin_chart(
                rev_annual, pat_annual, ebitda_ann, margin_title,
                rev_label, getattr(sector_cfg, "ebitda_label", "EBITDA")
            )
            if c3:
                charts["chart_margin"] = c3
    else:
        c3 = generate_margin_chart(
            rev_annual, pat_annual, ebitda_ann, margin_title,
            rev_label, getattr(sector_cfg, "ebitda_label", "EBITDA")
        )
        if c3:
            charts["chart_margin"] = c3

    # Chart 4: Quarterly Comparison — skip a single lonely bar.
    if quarterly_data:
        c4 = generate_quarterly_chart(quarterly_data, rev_label)
        if c4:
            charts["chart_quarterly"] = c4
        else:
            print("     [Chart Generator] Skip quarterly chart: fewer than 2 quarters.")

    # Chart 5: Segment Donut
    if segment_data:
        c5 = generate_segment_pie_chart(segment_data)
        if c5:
            charts["chart_segment_pie"] = c5

    # Chart 6: Geography Pie
    if geo_data:
        c6 = generate_geography_pie_chart(geo_data)
        if c6:
            charts["chart_geo_pie"] = c6

    print(f"     [Chart Generator] Generated {len(charts)} chart(s): {list(charts.keys())}")
    if charts:
        return charts

    # Thin filing: still emit one honest actuals-only chart so the PDF can render.
    print("     [Chart Generator] Thin filing — last-resort chart from available actuals.")
    if quarterly_data:
        c4 = generate_quarterly_chart(quarterly_data, rev_label, allow_thin=True)
        if c4:
            charts["chart_quarterly"] = c4
    if not charts:
        c1 = generate_revenue_trend_chart(rev_annual, {}, rev_label, allow_thin=True)
        if c1:
            charts["chart_revenue_trend"] = c1
    if not charts:
        c2 = generate_pat_trend_chart(pat_annual, {}, None, allow_thin=True)
        if c2:
            charts["chart_pat_trend"] = c2
    print(f"     [Chart Generator] Generated {len(charts)} chart(s): {list(charts.keys())}")
    return charts


if __name__ == "__main__":
    print("11_chart_generator.py ready — matplotlib backend.")
