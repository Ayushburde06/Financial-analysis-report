"""
11_chart_generator.py — Matplotlib Chart Generator
Generates base64-encoded PNG charts for embedding directly in the PDF.
No CDN dependency — works fully offline in headless Chromium.

4 Chart Types:
  1. Revenue/NII Trend      — bar chart, annual + estimates
  2. PAT Trend              — bar chart, annual + estimates
  3. Margin Breakdown       — dual-axis bar+line (revenue bar, margin % line)
  4. Quarterly Comparison   — grouped bar chart (Q2FY25, Q1FY26, Q2FY26)
"""
import io
import base64
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
RED   = "#e31837"
GREY  = "#8a9ab5"
LIGHT = "#d6dce8"

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


def _clean(d: Dict[str, Any]) -> Dict[str, float]:
    """Keep only numeric, non-zero entries from a year→value dict."""
    out = {}
    for k, v in d.items():
        try:
            f = float(v)
            if f != 0:
                out[k] = f
        except (TypeError, ValueError):
            pass
    return out


def _styled_fig(nrows=1, ncols=1, figsize=(5.5, 2.2)):
    fig, ax = plt.subplots(nrows, ncols, figsize=figsize)
    fig.patch.set_facecolor("white")
    return fig, ax


def _format_label(val: float) -> str:
    """Smart number formatting: show 1 decimal for small, 0 decimal for large."""
    if abs(val) >= 1000:
        return f"{val:,.0f}"
    if abs(val) >= 100:
        return f"{val:.1f}"
    return f"{val:.2f}"


def _bar_labels(ax, bars, fontsize=7):
    for bar in bars:
        h = bar.get_height()
        if h and abs(h) > 0:
            ax.annotate(
                _format_label(h),
                xy=(bar.get_x() + bar.get_width() / 2, h),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=fontsize, color=NAVY
            )


# ── Chart 1: Revenue / NII Annual Trend ───────────────────────────────────────

def generate_revenue_trend_chart(
    annual: Dict[str, float],
    estimates: Dict[str, float],
    revenue_label: str = "Revenue",
) -> Optional[str]:
    """Bar chart: historical revenue (navy) + forward estimates (grey)."""
    hist = _clean(annual)
    est  = _clean(estimates)
    if not hist and not est:
        return None

    years  = list(hist.keys()) + list(est.keys())
    values = list(hist.values()) + list(est.values())
    colors = [NAVY] * len(hist) + [GREY] * len(est)

    fig, ax = _styled_fig(figsize=(5.5, 2.2))
    bars = ax.bar(years, values, color=colors, width=0.55, edgecolor="white", linewidth=0.5)
    _bar_labels(ax, bars)

    ax.set_title(f"{revenue_label} Trend", fontsize=10, color=NAVY, fontweight="bold", pad=8)
    ax.set_ylabel(revenue_label, fontsize=8, color=NAVY)
    ax.tick_params(axis="x", rotation=30, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    # Legend
    patches = [
        mpatches.Patch(color=NAVY, label="Actual"),
        mpatches.Patch(color=GREY, label="Estimate"),
    ]
    if est:
        ax.legend(handles=patches, fontsize=7, loc="upper left", framealpha=0.7)

    fig.tight_layout()
    return _to_png_b64(fig)


# ── Chart 2: PAT Trend ────────────────────────────────────────────────────────

def generate_pat_trend_chart(
    pat_annual: Dict[str, float],
    pat_estimates: Dict[str, float],
    eps_annual: Dict[str, float] = None,
) -> Optional[str]:
    """Dual-axis: PAT bars (navy) + EPS line (red) if available."""
    hist = _clean(pat_annual)
    est  = _clean(pat_estimates)
    eps  = _clean(eps_annual or {})

    if not hist and not est:
        return None

    years  = list(hist.keys()) + list(est.keys())
    values = list(hist.values()) + list(est.values())
    colors = [NAVY] * len(hist) + [GREY] * len(est)

    if eps:
        fig, ax1 = _styled_fig(figsize=(5.5, 2.2))
        ax2 = ax1.twinx()
    else:
        fig, ax1 = _styled_fig(figsize=(5.5, 2.2))
        ax2 = None

    bars = ax1.bar(years, values, color=colors, width=0.55, edgecolor="white", linewidth=0.5)
    _bar_labels(ax1, bars)

    if ax2 and eps:
        eps_years = [y for y in years if y in eps]
        eps_vals  = [eps[y] for y in eps_years]
        ax2.plot(eps_years, eps_vals, color=RED, marker="o", linewidth=1.8,
                 markersize=5, label="EPS")
        ax2.set_ylabel("EPS", fontsize=8, color=RED)
        ax2.tick_params(axis="y", labelcolor=RED, labelsize=8)
        ax2.spines["top"].set_visible(False)

    ax1.set_title("PAT & EPS Trend", fontsize=10, color=NAVY, fontweight="bold", pad=8)
    ax1.set_ylabel("PAT", fontsize=8, color=NAVY)
    ax1.tick_params(axis="x", rotation=30, labelsize=8)
    ax1.tick_params(axis="y", labelsize=8)
    ax1.spines["top"].set_visible(False)
    ax1.spines["right"].set_visible(False) if not ax2 else None
    ax1.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax1.set_axisbelow(True)

    fig.tight_layout()
    return _to_png_b64(fig)


# ── Chart 3: Margin Breakdown (Revenue bar + Margin % line) ───────────────────

def generate_margin_chart(
    revenue_annual: Dict[str, float],
    pat_annual: Dict[str, float],
    ebitda_annual: Dict[str, float] = None,
    margin_title: str = "Margin Breakdown (%)",
) -> Optional[str]:
    """Dual-axis: Revenue bar (navy) + PAT margin % line (red) + EBITDA margin % line (grey)."""
    rev = _clean(revenue_annual)
    pat = _clean(pat_annual)
    ebi = _clean(ebitda_annual or {})

    if not rev or not pat:
        return None
    # Need at least 2 years to show a meaningful margin trend line
    if len(rev) < 2 and len(pat) < 2:
        return None

    years = list(rev.keys())
    rev_vals = [rev[y] for y in years]

    # Compute margins
    pat_margins  = [round(pat.get(y, 0) / rev[y] * 100, 1) if rev[y] else 0 for y in years]
    ebi_margins  = [round(ebi.get(y, 0) / rev[y] * 100, 1) if (ebi.get(y) and rev[y]) else None for y in years]

    fig, ax1 = _styled_fig(figsize=(5.5, 2.2))
    ax2 = ax1.twinx()

    bars = ax1.bar(years, rev_vals, color=LIGHT, width=0.55, edgecolor=NAVY, linewidth=0.5, label="Revenue")
    ax1.set_ylabel("Revenue", fontsize=8, color=NAVY)
    ax1.tick_params(axis="y", labelcolor=NAVY, labelsize=8)
    ax1.tick_params(axis="x", rotation=30, labelsize=8)

    ax2.plot(years, pat_margins, color=RED, marker="o", linewidth=2,
             markersize=5, label="PAT Margin %")
    if any(v is not None for v in ebi_margins):
        valid_y = [y for y, v in zip(years, ebi_margins) if v is not None]
        valid_v = [v for v in ebi_margins if v is not None]
        ax2.plot(valid_y, valid_v, color=NAVY, marker="s", linewidth=1.5,
                 markersize=4, linestyle="--", label="EBITDA Margin %")

    ax2.set_ylabel("Margin (%)", fontsize=8, color=RED)
    ax2.tick_params(axis="y", labelcolor=RED, labelsize=8)
    ax2.yaxis.grid(True, linestyle="--", alpha=0.3)

    ax1.set_title(margin_title, fontsize=10, color=NAVY, fontweight="bold", pad=8)
    ax1.spines["top"].set_visible(False)
    ax2.spines["top"].set_visible(False)

    # Combined legend
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines2, labels2, fontsize=7, loc="upper left", framealpha=0.7)

    fig.tight_layout()
    return _to_png_b64(fig)


# ── Chart 4: Quarterly Comparison (grouped bar) ───────────────────────────────

def generate_quarterly_chart(
    quarterly: Dict[str, Any],
    revenue_label: str = "Revenue",
) -> Optional[str]:
    """Grouped bar: Revenue/NII and PAT for available quarters."""
    qtr_rev = _clean(quarterly.get("revenue", {}))
    qtr_pat = _clean(quarterly.get("pat", {}))

    all_quarters = quarterly.get("quarters", ["Q2FY25", "Q1FY26", "Q2FY26"])
    # Only show quarters that have at least some data (skip empty gaps)
    quarters = [q for q in all_quarters
                if qtr_rev.get(q, 0) != 0 or qtr_pat.get(q, 0) != 0]
    if not quarters:
        quarters = all_quarters  # fallback: show all if none have data
    rev_vals = [qtr_rev.get(q, 0) for q in quarters]
    pat_vals = [qtr_pat.get(q, 0) for q in quarters]

    if not any(rev_vals) and not any(pat_vals):
        return None

    x = np.arange(len(quarters))
    width = 0.35

    fig, ax = _styled_fig(figsize=(5.5, 2.2))
    bars1 = ax.bar(x - width/2, rev_vals, width, color=NAVY, label=revenue_label, edgecolor="white")
    bars2 = ax.bar(x + width/2, pat_vals, width, color=RED,  label="PAT", edgecolor="white")
    _bar_labels(ax, bars1, fontsize=6)
    _bar_labels(ax, bars2, fontsize=6)

    # QoQ % growth overlays on revenue bars (between consecutive quarters)
    for i in range(1, len(quarters)):
        prev_r = rev_vals[i - 1]
        cur_r  = rev_vals[i]
        if prev_r and prev_r > 0 and cur_r and cur_r > 0:
            qoq = round((cur_r - prev_r) / prev_r * 100, 1)
            sign = "+" if qoq >= 0 else ""
            color = "#2e7d32" if qoq >= 0 else "#c62828"
            ax.annotate(f"{sign}{qoq}%", xy=(x[i] - width / 2, cur_r),
                        xytext=(0, 10), textcoords="offset points",
                        fontsize=5.5, color=color, fontweight="bold",
                        ha="center", va="bottom")

    ax.set_title("Quarterly Performance", fontsize=10, color=NAVY, fontweight="bold", pad=8)
    ax.set_xticks(x)
    ax.set_xticklabels(quarters, fontsize=9)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(fontsize=8, framealpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.grid(True, linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    fig.tight_layout()
    return _to_png_b64(fig)


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

    fig, ax = _styled_fig(figsize=(4.8, 2.2))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        startangle=140, colors=colors,
        wedgeprops=dict(width=0.45, edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=7, color=NAVY)
    )
    plt.setp(autotexts, size=7, weight="bold", color="white")
    ax.set_title(title, fontsize=9.5, color=NAVY, fontweight="bold", pad=6)
    fig.tight_layout()
    return _to_png_b64(fig)


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

    fig, ax = _styled_fig(figsize=(4.8, 2.2))
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        startangle=90, colors=colors,
        wedgeprops=dict(edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=7, color=NAVY)
    )
    plt.setp(autotexts, size=7, weight="bold", color="white")
    ax.set_title(title, fontsize=9.5, color=NAVY, fontweight="bold", pad=6)
    fig.tight_layout()
    return _to_png_b64(fig)


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
    qs = [q for q in quarters if q in nim or q in gnpa]
    if not qs:
        qs = list(nim.keys()) + list(gnpa.keys())
    if not qs:
        return None

    fig, ax1 = _styled_fig(figsize=(5.5, 2.2))
    nim_vals = [nim.get(q, 0) for q in qs]
    bars = ax1.bar(qs, nim_vals, color=NAVY, width=0.5, edgecolor="white", linewidth=0.5, label="NIM (%)")
    _bar_labels(ax1, bars)
    ax1.set_ylabel("NIM (%)", fontsize=7, color=NAVY)
    ax1.tick_params(axis="x", rotation=20, labelsize=7)
    ax1.tick_params(axis="y", labelsize=7)
    ax1.set_ylim(0, max(nim_vals) * 1.3 if nim_vals else 6)

    if gnpa:
        ax2 = ax1.twinx()
        gnpa_vals = [gnpa.get(q, 0) for q in qs]
        ax2.plot(qs, gnpa_vals, color=RED, marker="s", linewidth=2, markersize=4, label="GNPA (%)")
        ax2.set_ylabel("GNPA (%)", fontsize=7, color=RED)
        ax2.tick_params(axis="y", labelsize=7, colors=RED)
        ax2.spines["right"].set_visible(True)
        ax2.set_ylim(0, max(gnpa_vals) * 2 if gnpa_vals else 5)

    ax1.set_title("Asset Quality (NIM & GNPA)", fontsize=9, color=NAVY, fontweight="bold", pad=6)
    ax1.spines["top"].set_visible(False)

    lines1, labels1 = ax1.get_legend_handles_labels()
    if gnpa:
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=6, loc="upper right", framealpha=0.7)
    else:
        ax1.legend(handles=bars, fontsize=6, loc="upper right", framealpha=0.7)

    return _to_png_b64(fig)


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
    rev_est     = annual_data.get("revenue_est", {})   # FY26E, FY27E
    pat_annual  = annual_data.get("pat", {})
    pat_est     = annual_data.get("pat_est", {})
    eps_annual  = annual_data.get("eps", {})
    ebitda_ann  = annual_data.get("ebitda", {})

    charts = {}

    # Chart 1: Revenue/NII Trend
    c1 = generate_revenue_trend_chart(rev_annual, rev_est, rev_label)
    if c1:
        charts["chart_revenue_trend"] = c1

    # Chart 2: PAT & EPS Trend
    c2 = generate_pat_trend_chart(pat_annual, pat_est, eps_annual)
    if c2:
        charts["chart_pat_trend"] = c2

    # Chart 3: Margin Breakdown — merge actuals + estimates so single-year companies still render
    rev_merged  = {**rev_annual,  **rev_est}
    pat_merged  = {**pat_annual,  **pat_est}
    ebitda_merged = {**ebitda_ann, **annual_data.get("ebitda_est", {})}
    c3 = generate_margin_chart(rev_merged, pat_merged, ebitda_merged, margin_title)
    if c3:
        charts["chart_margin"] = c3

    # Chart 3b: Banking Quality (NIM & GNPA) — fills the 4th slot when margin chart is skipped
    sector_name = str(getattr(sector_cfg, "sector_name", "") if sector_cfg else "").lower()
    if "bank" in sector_name or "nbfc" in sector_name or "financial" in sector_name:
        nim_data = quarterly_data.get("nim", {}) if quarterly_data else {}
        gnpa_data = quarterly_data.get("gnpa", {}) if quarterly_data else {}
        if nim_data or gnpa_data:
            c3b = _generate_banking_quality_chart(
                nim_data, gnpa_data, quarterly_data.get("quarters", [])
            )
            if c3b:
                charts["chart_asset_quality"] = c3b

    # Chart 4: Quarterly Comparison
    if quarterly_data:
        c4 = generate_quarterly_chart(quarterly_data, rev_label)
        if c4:
            charts["chart_quarterly"] = c4

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
    return charts


if __name__ == "__main__":
    print("11_chart_generator.py ready — matplotlib backend.")
