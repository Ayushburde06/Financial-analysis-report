"""
PeerBenchmark — compare this company's growth to a median that is IN the filing.

Does not invent India-wide sector medians. If the source has no peer/median
figure, the report stays empty.
"""
from typing import Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class PeerBenchmarkReport:
    sector: str
    revenue_growth_vs_sector: Optional[str] = None  # "above", "below", "inline"
    revenue_growth_gap_pp: Optional[float] = None
    narrative: str = ""


class PeerBenchmark:
    @staticmethod
    def compare(
        revenue_growth_pct: Optional[float],
        sector: str,
        ebitda_margin_pct: Optional[float] = None,
        sector_median_growth: Optional[float] = None,
        sector_median_ebitda_margin: Optional[float] = None,
    ) -> PeerBenchmarkReport:
        report = PeerBenchmarkReport(sector=sector or "")
        if revenue_growth_pct is None or sector_median_growth is None:
            return report

        gap = round(float(revenue_growth_pct) - float(sector_median_growth), 1)
        report.revenue_growth_gap_pp = gap
        sector_label = sector or "sector"
        if gap > 3:
            report.revenue_growth_vs_sector = "above"
            report.narrative = (
                f"Revenue growth of {revenue_growth_pct}% is {gap}pp above "
                f"the {sector_label} median ({sector_median_growth}%) in this filing."
            )
        elif gap < -3:
            report.revenue_growth_vs_sector = "below"
            report.narrative = (
                f"Revenue growth of {revenue_growth_pct}% trails the "
                f"{sector_label} median ({sector_median_growth}%) by {abs(gap)}pp."
            )
        else:
            report.revenue_growth_vs_sector = "inline"
            report.narrative = (
                f"Revenue growth of {revenue_growth_pct}% is in line with the "
                f"{sector_label} median ({sector_median_growth}%)."
            )

        median_margin = sector_median_ebitda_margin
        if (
            ebitda_margin_pct is not None
            and median_margin is not None
            and float(median_margin) > 0
        ):
            margin_gap = round(float(ebitda_margin_pct) - float(median_margin), 1)
            if abs(margin_gap) > 2:
                direction = "above" if margin_gap > 0 else "below"
                extra = (
                    f" EBITDA margin is {abs(margin_gap)}pp {direction} the "
                    f"filing median ({median_margin}%)."
                )
                report.narrative = (report.narrative + extra).strip()

        return report
