"""
CrossMetricAnalyzer — relationships across metrics from THIS filing.

Uses the actual years / quarters present. Does not assume FY25 or FY26E.
Empty source → empty report. Missing PAT growth stays missing, not 0.
"""
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field


_ANNUAL_ACTUAL_RE = re.compile(r"^fy\d{2,4}a?$", re.IGNORECASE)
_REVENUE_KEYS = (
    "revenue", "nii", "net_interest_income", "total_income",
    "net_sales", "operating_revenue", "gmv",
)
_EBITDA_KEYS = ("ebitda", "operating_profit", "ppop")
_PAT_KEYS = ("pat", "net_profit", "profit_after_tax")
_ASSET_KEYS = ("total_assets", "advances", "net_assets")
_FIXED_ASSET_KEYS = ("net_fixed_assets", "gross_fixed_assets", "fixed_assets")

_COST_LABELS = {
    "raw_material_cost": "raw material costs",
    "employee_cost": "employee costs",
    "other_expenses": "other operating expenses",
    "total_expenses": "total expenses",
    "interest": "interest costs",
    "depreciation": "depreciation",
    "finance_costs": "finance costs",
}


@dataclass
class MarginShift:
    metric: str
    current_value: float
    previous_value: float
    change_bps: float
    direction: str
    attribution: List[str]
    magnitude: str


@dataclass
class GrowthGap:
    revenue_growth_pct: float
    ebitda_growth_pct: float
    pat_growth_pct: Optional[float] = None
    interpretation: str = ""
    details: List[str] = field(default_factory=list)


@dataclass
class AssetEfficiency:
    asset_turnover_current: float
    asset_turnover_previous: float
    fixed_asset_turnover_current: Optional[float] = None
    fixed_asset_turnover_previous: Optional[float] = None
    direction: str = "stable"
    narrative: str = ""


@dataclass
class CrossMetricReport:
    margin_shifts: List[MarginShift] = field(default_factory=list)
    growth_gaps: List[GrowthGap] = field(default_factory=list)
    asset_efficiency: Optional[AssetEfficiency] = None
    key_observations: List[str] = field(default_factory=list)
    narrative_brief: str = ""


class CrossMetricAnalyzer:
    """
    Deterministic cross-metric findings for the narrative LLM.

        report = CrossMetricAnalyzer.analyze(annual_data, quarterly_data, pl, bs)
    """

    @staticmethod
    def analyze(
        annual_data: Dict[str, Any],
        quarterly_data: Dict[str, Any],
        pl: Any,
        bs: Any = None,
    ) -> CrossMetricReport:
        report = CrossMetricReport()
        annual = CrossMetricAnalyzer._merge_packets(annual_data or {}, pl, bs)
        quarterly = quarterly_data if isinstance(quarterly_data, dict) else {}

        report.margin_shifts = CrossMetricAnalyzer._detect_margin_shifts(
            annual, quarterly
        )
        report.growth_gaps = CrossMetricAnalyzer._detect_growth_gaps(
            annual, quarterly
        )
        report.asset_efficiency = CrossMetricAnalyzer._analyze_asset_efficiency(
            annual, bs
        )
        report.key_observations = CrossMetricAnalyzer._synthesize_observations(report)
        report.narrative_brief = CrossMetricAnalyzer._build_narrative_brief(report)
        return report

    # ── Packet fallbacks ─────────────────────────────────────────────────────

    @staticmethod
    def _line_actuals(item: Any) -> Dict[str, float]:
        if item is None:
            return {}
        if hasattr(item, "actual_year_values"):
            try:
                return dict(item.actual_year_values() or {})
            except Exception:
                return {}
        return {}

    @staticmethod
    def _merge_packets(
        annual: Dict[str, Any], pl: Any, bs: Any
    ) -> Dict[str, Any]:
        merged = dict(annual)
        if pl is not None:
            for dest, attr in (
                ("revenue", "revenue"),
                ("ebitda", "ebitda"),
                ("pat", "pat"),
                ("interest", "interest"),
                ("depreciation", "depreciation"),
            ):
                if not CrossMetricAnalyzer._numeric_series(merged.get(dest)):
                    filled = CrossMetricAnalyzer._line_actuals(getattr(pl, attr, None))
                    if filled:
                        merged[dest] = filled
        if bs is not None:
            for dest, attr in (
                ("total_assets", "total_assets"),
                ("net_fixed_assets", "gross_fixed_assets"),
            ):
                if not CrossMetricAnalyzer._numeric_series(merged.get(dest)):
                    filled = CrossMetricAnalyzer._line_actuals(getattr(bs, attr, None))
                    if filled:
                        merged[dest] = filled
        return merged

    # ── Series / year helpers ────────────────────────────────────────────────

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            if hasattr(val, "value"):
                val = val.value
            if val in (None, "[N/A]", "", "—", "None", "null"):
                return None
            return float(str(val).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_margin(profit: Any, revenue: Any) -> Optional[float]:
        p = CrossMetricAnalyzer._safe_float(profit)
        r = CrossMetricAnalyzer._safe_float(revenue)
        if p is None or r in (None, 0, 0.0):
            return None
        return p / r

    @staticmethod
    def _growth_pct(current: Any, previous: Any) -> Optional[float]:
        cur = CrossMetricAnalyzer._safe_float(current)
        prev = CrossMetricAnalyzer._safe_float(previous)
        if cur is None or prev in (None, 0, 0.0):
            return None
        return ((cur - prev) / prev) * 100.0

    @staticmethod
    def _numeric_series(series: Any) -> Dict[str, Any]:
        if not isinstance(series, dict):
            return {}
        out = {}
        for key, val in series.items():
            if CrossMetricAnalyzer._safe_float(val) is not None:
                out[str(key)] = val
        return out

    @staticmethod
    def _pick_series(data: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
        for key in keys:
            series = CrossMetricAnalyzer._numeric_series(data.get(key))
            if series:
                return series
        return {}

    @staticmethod
    def _is_actual_fy(key: str) -> bool:
        return bool(_ANNUAL_ACTUAL_RE.match(str(key).strip()))

    @staticmethod
    def _year_num(key: str) -> int:
        nums = re.findall(r"\d+", str(key or ""))
        if not nums:
            return -1
        num = int(nums[0])
        return num % 100 if num > 100 else num

    @staticmethod
    def _actual_years(series: Dict[str, Any]) -> List[str]:
        years = [
            key for key in CrossMetricAnalyzer._numeric_series(series)
            if CrossMetricAnalyzer._is_actual_fy(key)
        ]
        return sorted(years, key=lambda y: (CrossMetricAnalyzer._year_num(y), y))

    @staticmethod
    def _pair_years(
        left: Dict[str, Any], right: Dict[str, Any]
    ) -> Optional[Tuple[str, str]]:
        common = [
            y for y in CrossMetricAnalyzer._actual_years(left)
            if y in CrossMetricAnalyzer._actual_years(right)
        ]
        if len(common) >= 2:
            return common[-2], common[-1]
        return None

    @staticmethod
    def _quarter_pair(
        quarterly: Dict[str, Any], left_key: str, right_key: str
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], str, str]]:
        left = CrossMetricAnalyzer._numeric_series(quarterly.get(left_key))
        right = CrossMetricAnalyzer._numeric_series(quarterly.get(right_key))
        if not left or not right:
            return None
        quarters = [str(q) for q in (quarterly.get("quarters") or [])]
        if len(quarters) >= 2:
            prev, cur = quarters[0], quarters[-1]
            if prev in left and cur in left and prev in right and cur in right:
                return left, right, prev, cur
        if (
            "q_prev_year" in left and "q_current" in left
            and "q_prev_year" in right and "q_current" in right
        ):
            return left, right, "q_prev_year", "q_current"
        return None

    @staticmethod
    def _lookup(series: Dict[str, Any], year: str) -> Any:
        if year in series:
            return series[year]
        for key, val in series.items():
            if str(key) == str(year):
                return val
        return None

    # ── Margin Shifts ────────────────────────────────────────────────────────

    @staticmethod
    def _detect_margin_shifts(
        annual_data: Dict, quarterly_data: Dict
    ) -> List[MarginShift]:
        shifts: List[MarginShift] = []
        revenue = CrossMetricAnalyzer._pick_series(annual_data, _REVENUE_KEYS)
        ebitda = CrossMetricAnalyzer._pick_series(annual_data, _EBITDA_KEYS)
        pat = CrossMetricAnalyzer._pick_series(annual_data, _PAT_KEYS)

        pair = CrossMetricAnalyzer._pair_years(revenue, ebitda)
        if pair:
            shifts.extend(CrossMetricAnalyzer._margin_for_pair(
                "EBITDA margin", ebitda, revenue, pair[0], pair[1],
                annual_data, min_bps=20,
            ))
        pair = CrossMetricAnalyzer._pair_years(revenue, pat)
        if pair:
            shifts.extend(CrossMetricAnalyzer._margin_for_pair(
                "PAT margin", pat, revenue, pair[0], pair[1],
                annual_data, min_bps=15,
            ))

        if shifts:
            return shifts

        q_ebitda = CrossMetricAnalyzer._quarter_pair(
            quarterly_data, "ebitda", "revenue"
        )
        if q_ebitda:
            left, right, prev, cur = q_ebitda
            shifts.extend(CrossMetricAnalyzer._margin_for_pair(
                "EBITDA margin", left, right, prev, cur, {}, min_bps=20,
            ))
        q_pat = CrossMetricAnalyzer._quarter_pair(quarterly_data, "pat", "revenue")
        if q_pat:
            left, right, prev, cur = q_pat
            shifts.extend(CrossMetricAnalyzer._margin_for_pair(
                "PAT margin", left, right, prev, cur, {}, min_bps=15,
            ))
        return shifts

    @staticmethod
    def _margin_for_pair(
        metric: str,
        profit: Dict[str, Any],
        revenue: Dict[str, Any],
        prev_y: str,
        cur_y: str,
        annual_data: Dict,
        min_bps: float,
    ) -> List[MarginShift]:
        prev_margin = CrossMetricAnalyzer._safe_margin(
            CrossMetricAnalyzer._lookup(profit, prev_y),
            CrossMetricAnalyzer._lookup(revenue, prev_y),
        )
        cur_margin = CrossMetricAnalyzer._safe_margin(
            CrossMetricAnalyzer._lookup(profit, cur_y),
            CrossMetricAnalyzer._lookup(revenue, cur_y),
        )
        if prev_margin is None or cur_margin is None:
            return []
        change_bps = round((cur_margin - prev_margin) * 100, 1)
        if abs(change_bps) < min_bps:
            return []
        return [MarginShift(
            metric=metric,
            current_value=round(cur_margin * 100, 1),
            previous_value=round(prev_margin * 100, 1),
            change_bps=change_bps,
            direction="expanded" if change_bps > 0 else "contracted",
            attribution=CrossMetricAnalyzer._attribute_margin_shift(
                annual_data, cur_y, prev_y
            ) if metric.startswith("EBITDA") else [],
            magnitude=(
                "significant" if abs(change_bps) >= 100
                else "moderate" if abs(change_bps) >= 50
                else "minor"
            ),
        )]

    @staticmethod
    def _attribute_margin_shift(
        annual_data: Dict, cur_year: str, prev_year: str
    ) -> List[str]:
        attributions = []
        revenue = CrossMetricAnalyzer._pick_series(annual_data, _REVENUE_KEYS)
        revenue_cur = CrossMetricAnalyzer._safe_float(
            CrossMetricAnalyzer._lookup(revenue, cur_year)
        )
        revenue_prev = CrossMetricAnalyzer._safe_float(
            CrossMetricAnalyzer._lookup(revenue, prev_year)
        )
        if not revenue_cur or not revenue_prev:
            return attributions

        cost_lines = dict(_COST_LABELS)
        for key in annual_data.keys():
            low = str(key).lower()
            if key in cost_lines:
                continue
            if any(token in low for token in ("cost", "expense", "cogs")):
                cost_lines[key] = str(key).replace("_", " ")

        for key, label in cost_lines.items():
            series = CrossMetricAnalyzer._numeric_series(annual_data.get(key))
            val_cur = CrossMetricAnalyzer._safe_float(
                CrossMetricAnalyzer._lookup(series, cur_year)
            )
            val_prev = CrossMetricAnalyzer._safe_float(
                CrossMetricAnalyzer._lookup(series, prev_year)
            )
            if val_cur is None or val_prev is None:
                continue
            change_bps = round((val_cur / revenue_cur - val_prev / revenue_prev) * 100, 1)
            if abs(change_bps) >= 30:
                direction = "rose" if change_bps > 0 else "fell"
                attributions.append(
                    f"{label} as % of revenue {direction} by {abs(change_bps):.0f}bps"
                )
        return attributions[:3]

    # ── Growth Gaps ──────────────────────────────────────────────────────────

    @staticmethod
    def _detect_growth_gaps(
        annual_data: Dict, quarterly_data: Dict
    ) -> List[GrowthGap]:
        revenue = CrossMetricAnalyzer._pick_series(annual_data, _REVENUE_KEYS)
        ebitda = CrossMetricAnalyzer._pick_series(annual_data, _EBITDA_KEYS)
        pat = CrossMetricAnalyzer._pick_series(annual_data, _PAT_KEYS)
        pair = CrossMetricAnalyzer._pair_years(revenue, ebitda)
        if pair:
            gap = CrossMetricAnalyzer._gap_for_pair(
                revenue, ebitda, pat, pair[0], pair[1]
            )
            return [gap] if gap else []

        q = CrossMetricAnalyzer._quarter_pair(quarterly_data, "ebitda", "revenue")
        if not q:
            return []
        left, right, prev, cur = q
        pat_q = CrossMetricAnalyzer._numeric_series(quarterly_data.get("pat"))
        gap = CrossMetricAnalyzer._gap_for_pair(right, left, pat_q, prev, cur)
        return [gap] if gap else []

    @staticmethod
    def _gap_for_pair(
        revenue: Dict[str, Any],
        ebitda: Dict[str, Any],
        pat: Dict[str, Any],
        prev_y: str,
        cur_y: str,
    ) -> Optional[GrowthGap]:
        rev_g = CrossMetricAnalyzer._growth_pct(
            CrossMetricAnalyzer._lookup(revenue, cur_y),
            CrossMetricAnalyzer._lookup(revenue, prev_y),
        )
        ebitda_g = CrossMetricAnalyzer._growth_pct(
            CrossMetricAnalyzer._lookup(ebitda, cur_y),
            CrossMetricAnalyzer._lookup(ebitda, prev_y),
        )
        pat_g = CrossMetricAnalyzer._growth_pct(
            CrossMetricAnalyzer._lookup(pat, cur_y),
            CrossMetricAnalyzer._lookup(pat, prev_y),
        )
        if rev_g is None or ebitda_g is None:
            return None
        gap = round(ebitda_g - rev_g, 1)
        if abs(gap) < 2:
            return None
        interpretation = (
            "operating leverage — EBITDA growing faster than revenue"
            if gap > 0 else
            "cost pressure — EBITDA growing slower than revenue"
        )
        details = []
        if gap > 5:
            details.append(
                "Strong operating leverage: incremental revenue is flowing "
                "disproportionately to EBITDA"
            )
        elif gap < -5:
            details.append(
                f"Cost pressure evident: EBITDA growth lags revenue "
                f"by {abs(gap)}pp"
            )
        return GrowthGap(
            revenue_growth_pct=round(rev_g, 1),
            ebitda_growth_pct=round(ebitda_g, 1),
            pat_growth_pct=round(pat_g, 1) if pat_g is not None else None,
            interpretation=interpretation,
            details=details,
        )

    # ── Asset Efficiency ─────────────────────────────────────────────────────

    @staticmethod
    def _analyze_asset_efficiency(
        annual_data: Dict, bs: Any
    ) -> Optional[AssetEfficiency]:
        rev = CrossMetricAnalyzer._pick_series(annual_data, _REVENUE_KEYS)
        ta = CrossMetricAnalyzer._pick_series(annual_data, _ASSET_KEYS)
        fa = CrossMetricAnalyzer._pick_series(annual_data, _FIXED_ASSET_KEYS)
        pair = CrossMetricAnalyzer._pair_years(rev, ta)
        if not pair:
            return None
        prev_y, cur_y = pair
        rev_cur = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(rev, cur_y))
        rev_prev = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(rev, prev_y))
        ta_cur = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(ta, cur_y))
        ta_prev = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(ta, prev_y))
        if (
            rev_cur is None or rev_prev is None
            or ta_cur in (None, 0, 0.0) or ta_prev in (None, 0, 0.0)
        ):
            return None

        at_cur = rev_cur / ta_cur
        at_prev = rev_prev / ta_prev
        fa_turn_cur = None
        fa_turn_prev = None
        fa_cur = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(fa, cur_y))
        fa_prev = CrossMetricAnalyzer._safe_float(CrossMetricAnalyzer._lookup(fa, prev_y))
        if fa_cur not in (None, 0, 0.0) and fa_prev not in (None, 0, 0.0):
            fa_turn_cur = rev_cur / fa_cur
            fa_turn_prev = rev_prev / fa_prev

        change = at_cur - at_prev
        direction = (
            "improving" if change > 0.02
            else "declining" if change < -0.02
            else "stable"
        )
        narrative = ""
        if direction == "improving":
            narrative = (
                f"Asset turnover improved from {at_prev:.2f}x to {at_cur:.2f}x, "
                f"indicating more efficient use of capital."
            )
        elif direction == "declining":
            narrative = (
                f"Asset turnover declined from {at_prev:.2f}x to {at_cur:.2f}x, "
                f"suggesting capital deployment is not keeping pace with revenue."
            )
        return AssetEfficiency(
            asset_turnover_current=round(at_cur, 2),
            asset_turnover_previous=round(at_prev, 2),
            fixed_asset_turnover_current=round(fa_turn_cur, 2) if fa_turn_cur else None,
            fixed_asset_turnover_previous=round(fa_turn_prev, 2) if fa_turn_prev else None,
            direction=direction,
            narrative=narrative,
        )

    # ── Synthesis ────────────────────────────────────────────────────────────

    @staticmethod
    def _synthesize_observations(report: CrossMetricReport) -> List[str]:
        observations = []
        for ms in report.margin_shifts:
            if ms.magnitude == "significant":
                driven = (
                    f" Driven by: {'; '.join(ms.attribution)}."
                    if ms.attribution else ""
                )
                observations.append(
                    f"{ms.metric} {ms.direction} significantly by {abs(ms.change_bps)}bps "
                    f"({ms.previous_value}% → {ms.current_value}%).{driven}"
                )
            elif ms.magnitude == "moderate":
                observations.append(
                    f"{ms.metric} {ms.direction} by {abs(ms.change_bps)}bps "
                    f"({ms.previous_value}% → {ms.current_value}%)."
                )
        for gg in report.growth_gaps:
            observations.append(
                f"Revenue grew {gg.revenue_growth_pct}% while EBITDA grew "
                f"{gg.ebitda_growth_pct}% — {gg.interpretation}."
            )
            observations.extend(gg.details)
        if report.asset_efficiency and report.asset_efficiency.narrative:
            observations.append(report.asset_efficiency.narrative)
        return observations

    @staticmethod
    def _build_narrative_brief(report: CrossMetricReport) -> str:
        parts = []
        if report.margin_shifts:
            significant = [ms for ms in report.margin_shifts if ms.magnitude == "significant"]
            ms = significant[0] if significant else report.margin_shifts[0]
            if significant:
                parts.append(
                    f"{ms.metric} {ms.direction} {abs(ms.change_bps)}bps to "
                    f"{ms.current_value}%."
                )
                if ms.attribution:
                    parts.append(f"Attribution: {'; '.join(ms.attribution)}.")
            else:
                parts.append(
                    f"{ms.metric} showed a {ms.magnitude} {ms.direction} "
                    f"of {abs(ms.change_bps)}bps."
                )
        if report.growth_gaps:
            gg = report.growth_gaps[0]
            parts.append(
                f"Revenue-{gg.interpretation} pattern: revenue +{gg.revenue_growth_pct}% "
                f"vs EBITDA +{gg.ebitda_growth_pct}%."
            )
        if report.asset_efficiency and report.asset_efficiency.narrative:
            parts.append(report.asset_efficiency.narrative)
        return " ".join(parts)
