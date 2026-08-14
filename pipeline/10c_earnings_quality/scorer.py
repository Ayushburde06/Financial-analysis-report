"""
Stage 10c — Earnings quality from this filing.

JSON (Stage 08 packets) selects the line items and years.
OCR markdown (Stage 01) is the source of truth: a JSON number is used
only if it appears in the markdown. Derived ratios are computed in Python
and are not required to be printed in the filing.

Estimate years (fyNNe) are ignored. Empty or unverified filings stay unscored.
"""
import importlib
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass, field


_ANNUAL_ACTUAL_RE = re.compile(r"^fy\d{2,4}a?$", re.IGNORECASE)

_REVENUE_KEYS = (
    "revenue", "nii", "net_interest_income", "total_income",
    "net_sales", "operating_revenue", "gmv",
)
_PBT_KEYS = ("pbt", "profit_before_tax")
_PAT_KEYS = ("pat", "net_profit", "profit_after_tax")
_TAX_KEYS = ("tax", "income_tax")
_TAX_RATE_KEYS = ("tax_rate",)
_OI_KEYS = ("other_income",)
_DEP_KEYS = ("depreciation", "amortization")
_EXCEPTIONAL_KEYS = ("exceptional_items", "exceptional", "one_off", "one_time")
_OCF_KEYS = ("operating_cash_flow", "cfo")

_PL_FIELDS = (
    "other_income", "pbt", "tax", "tax_rate", "depreciation",
    "revenue", "pat", "ebitda", "interest",
)
_CF_FIELDS = ("operating_cash_flow", "free_cash_flow")


@dataclass
class EarningsQuality:
    score: str = ""  # HIGH / MEDIUM / LOW, or "" when not enough source
    flags: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    checks_run: List[str] = field(default_factory=list)


class EarningsQualityScorer:
    HIGH_OI_THRESHOLD = 0.15
    MEDIUM_OI_THRESHOLD = 0.10
    TAX_SHIFT_THRESHOLD = 0.03
    DEPRECIATION_DECLINE_THRESHOLD = -0.20
    OCF_PAT_WEAK = 0.50
    EXCEPTIONAL_REVENUE_SHARE = 0.01

    @staticmethod
    def score(
        annual_data: Dict[str, Any],
        pl: Any = None,
        prev_pl: Optional[Dict[str, float]] = None,
        quarterly_data: Optional[Dict[str, Any]] = None,
        cf: Any = None,
        ocr_text: str = "",
        source_value_factor: float = 1.0,
    ) -> EarningsQuality:
        ocr = (ocr_text or "").strip()
        if not ocr:
            return EarningsQuality(details={"ocr_missing": True})

        data = EarningsQualityScorer._merge(annual_data, pl, cf)
        quarterly = quarterly_data if isinstance(quarterly_data, dict) else {}
        data, dropped = EarningsQualityScorer._keep_ocr_values(
            data, ocr, source_value_factor
        )
        quarterly, dropped_q = EarningsQualityScorer._keep_ocr_values(
            quarterly, ocr, source_value_factor
        )
        flags: List[str] = []
        details: Dict[str, Any] = {
            "ocr_verified": True,
            "ocr_dropped": dropped + dropped_q,
        }
        checks: List[str] = []
        penalty = 0

        penalty += EarningsQualityScorer._check_other_income(
            data, quarterly, flags, details, checks
        )
        penalty += EarningsQualityScorer._check_tax_rate(
            data, flags, details, checks
        )
        penalty += EarningsQualityScorer._check_depreciation(
            data, flags, details, checks
        )
        penalty += EarningsQualityScorer._check_exceptional(
            data, flags, details, checks
        )
        penalty += EarningsQualityScorer._check_cash_conversion(
            data, flags, details, checks
        )

        if prev_pl:
            details["prev_pl_supplied"] = True

        if not checks:
            return EarningsQuality(details=details)

        if penalty == 0:
            score = "HIGH"
        elif penalty <= 2:
            score = "MEDIUM"
        else:
            score = "LOW"

        narrative = EarningsQualityScorer._build_narrative(score, flags, checks)
        return EarningsQuality(
            score=score,
            flags=flags,
            details=details,
            narrative=narrative,
            checks_run=checks,
        )

    # ── Merge packets ────────────────────────────────────────────────────────

    @staticmethod
    def _line_actuals(item: Any) -> Dict[str, float]:
        if item is None or not hasattr(item, "actual_year_values"):
            return {}
        try:
            return dict(item.actual_year_values() or {})
        except Exception:
            return {}

    @staticmethod
    def _merge(annual: Optional[Dict[str, Any]], pl: Any, cf: Any) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(annual or {})
        if pl is not None:
            for name in _PL_FIELDS:
                if not EarningsQualityScorer._numeric_series(merged.get(name)):
                    filled = EarningsQualityScorer._line_actuals(getattr(pl, name, None))
                    if filled:
                        merged[name] = filled
        if cf is not None:
            for name in _CF_FIELDS:
                if not EarningsQualityScorer._numeric_series(merged.get(name)):
                    filled = EarningsQualityScorer._line_actuals(getattr(cf, name, None))
                    if filled:
                        merged[name] = filled
        return merged

    @staticmethod
    def _number_in_markdown(
        value: float, ocr_text: str, source_value_factor: float = 1.0
    ) -> bool:
        fact = importlib.import_module("pipeline.12b_source_verifier.fact_checker")
        found, _, _ = fact._search_ocr(value, ocr_text)
        if found:
            return True
        factor = float(source_value_factor or 1.0)
        if factor not in (0.0, 1.0):
            found, _, _ = fact._search_ocr(value / factor, ocr_text)
            return found
        return False

    @staticmethod
    def _keep_ocr_values(
        payload: Dict[str, Any],
        ocr_text: str,
        source_value_factor: float,
    ) -> Tuple[Dict[str, Any], int]:
        """Keep JSON period values that also appear in the OCR markdown."""
        kept: Dict[str, Any] = {}
        dropped = 0
        for key, series in (payload or {}).items():
            if key == "quarters" or not isinstance(series, dict):
                kept[key] = series
                continue
            filtered: Dict[str, Any] = {}
            for year, val in series.items():
                num = EarningsQualityScorer._safe_float(val)
                if num is None:
                    continue
                if EarningsQualityScorer._number_in_markdown(
                    num, ocr_text, source_value_factor
                ):
                    filtered[str(year)] = val
                else:
                    dropped += 1
            kept[key] = filtered
        return kept, dropped

    # ── Series helpers ───────────────────────────────────────────────────────

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
    def _as_rate(val: Any) -> Optional[float]:
        num = EarningsQualityScorer._safe_float(val)
        if num is None:
            return None
        if abs(num) > 1.0:
            return num / 100.0
        return num

    @staticmethod
    def _numeric_series(series: Any) -> Dict[str, Any]:
        if not isinstance(series, dict):
            return {}
        out: Dict[str, Any] = {}
        for key, val in series.items():
            if EarningsQualityScorer._safe_float(val) is not None:
                out[str(key)] = val
        return out

    @staticmethod
    def _pick(data: Dict[str, Any], keys: Sequence[str]) -> Dict[str, Any]:
        for key in keys:
            series = EarningsQualityScorer._numeric_series(data.get(key))
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
            key for key in EarningsQualityScorer._numeric_series(series)
            if EarningsQualityScorer._is_actual_fy(key)
        ]
        return sorted(years, key=lambda y: (EarningsQualityScorer._year_num(y), y))

    @staticmethod
    def _common_years(*series: Dict[str, Any]) -> List[str]:
        groups = [EarningsQualityScorer._actual_years(s) for s in series]
        if not groups or any(not g for g in groups):
            return []
        common = set(groups[0])
        for group in groups[1:]:
            common &= set(group)
        return sorted(common, key=lambda y: (EarningsQualityScorer._year_num(y), y))

    @staticmethod
    def _lookup(series: Dict[str, Any], year: str) -> Optional[float]:
        if year in series:
            return EarningsQualityScorer._safe_float(series[year])
        for key, val in series.items():
            if str(key) == str(year):
                return EarningsQualityScorer._safe_float(val)
        return None

    @staticmethod
    def _quarter_current(
        quarterly: Dict[str, Any], keys: Sequence[str]
    ) -> Optional[float]:
        series: Dict[str, Any] = {}
        for key in keys:
            series = EarningsQualityScorer._numeric_series(quarterly.get(key))
            if series:
                break
        if not series:
            return None
        quarters = [str(q) for q in (quarterly.get("quarters") or [])]
        if quarters and quarters[-1] in series:
            return EarningsQualityScorer._safe_float(series[quarters[-1]])
        if "q_current" in series:
            return EarningsQualityScorer._safe_float(series["q_current"])
        return None

    # ── Checks ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_other_income(
        data: Dict[str, Any],
        quarterly: Dict[str, Any],
        flags: List[str],
        details: Dict[str, Any],
        checks: List[str],
    ) -> int:
        oi = EarningsQualityScorer._pick(data, _OI_KEYS)
        pbt = EarningsQualityScorer._pick(data, _PBT_KEYS)
        years = EarningsQualityScorer._common_years(oi, pbt)
        oi_v = pbt_v = None
        if years:
            year = years[-1]
            oi_v = EarningsQualityScorer._lookup(oi, year)
            pbt_v = EarningsQualityScorer._lookup(pbt, year)
            details["other_income_year"] = year
        else:
            oi_v = EarningsQualityScorer._quarter_current(quarterly, _OI_KEYS)
            pbt_v = EarningsQualityScorer._quarter_current(quarterly, _PBT_KEYS)

        if oi_v is None or pbt_v is None or pbt_v <= 0:
            return 0

        checks.append("other income vs PBT")
        ratio = oi_v / pbt_v
        details["other_income_to_pbt"] = round(ratio * 100, 1)
        if ratio > EarningsQualityScorer.HIGH_OI_THRESHOLD:
            flags.append(
                f"Other income is {ratio * 100:.0f}% of PBT — reported PAT is "
                f"materially supported by non-operating income."
            )
            return 2
        if ratio > EarningsQualityScorer.MEDIUM_OI_THRESHOLD:
            flags.append(
                f"Other income is {ratio * 100:.0f}% of PBT — elevated versus "
                f"a typical operating mix; sustainability is uncertain."
            )
            return 1
        return 0

    @staticmethod
    def _check_tax_rate(
        data: Dict[str, Any],
        flags: List[str],
        details: Dict[str, Any],
        checks: List[str],
    ) -> int:
        explicit = EarningsQualityScorer._pick(data, _TAX_RATE_KEYS)
        years = EarningsQualityScorer._actual_years(explicit)
        rate_cur = rate_prev = None
        if len(years) >= 2:
            prev_y, cur_y = years[-2], years[-1]
            rate_prev = EarningsQualityScorer._as_rate(
                EarningsQualityScorer._lookup(explicit, prev_y)
            )
            rate_cur = EarningsQualityScorer._as_rate(
                EarningsQualityScorer._lookup(explicit, cur_y)
            )
            details["tax_rate_years"] = [prev_y, cur_y]
        else:
            tax = EarningsQualityScorer._pick(data, _TAX_KEYS)
            pbt = EarningsQualityScorer._pick(data, _PBT_KEYS)
            pair = EarningsQualityScorer._common_years(tax, pbt)
            if len(pair) >= 2:
                prev_y, cur_y = pair[-2], pair[-1]
                tax_cur = EarningsQualityScorer._lookup(tax, cur_y)
                tax_prev = EarningsQualityScorer._lookup(tax, prev_y)
                pbt_cur = EarningsQualityScorer._lookup(pbt, cur_y)
                pbt_prev = EarningsQualityScorer._lookup(pbt, prev_y)
                if (
                    tax_cur is not None and tax_prev is not None
                    and pbt_cur not in (None, 0, 0.0)
                    and pbt_prev not in (None, 0, 0.0)
                    and pbt_cur > 0 and pbt_prev > 0
                ):
                    rate_cur = tax_cur / pbt_cur
                    rate_prev = tax_prev / pbt_prev
                    details["tax_rate_years"] = [prev_y, cur_y]

        if rate_cur is None or rate_prev is None:
            return 0

        checks.append("tax rate")
        details["tax_rate_current"] = round(rate_cur * 100, 1)
        details["tax_rate_previous"] = round(rate_prev * 100, 1)
        shift = rate_cur - rate_prev
        if abs(shift) <= EarningsQualityScorer.TAX_SHIFT_THRESHOLD:
            return 0
        direction = "lower" if shift < 0 else "higher"
        extra = (
            "PAT growth is partly tax-driven, not operating."
            if shift < 0 else
            "A higher tax burden is compressing PAT."
        )
        flags.append(
            f"Tax rate moved {direction} from {rate_prev * 100:.0f}% to "
            f"{rate_cur * 100:.0f}% ({abs(shift) * 100:.0f}pp). {extra}"
        )
        return 1 if shift < 0 else 0

    @staticmethod
    def _check_depreciation(
        data: Dict[str, Any],
        flags: List[str],
        details: Dict[str, Any],
        checks: List[str],
    ) -> int:
        dep = EarningsQualityScorer._pick(data, _DEP_KEYS)
        years = EarningsQualityScorer._actual_years(dep)
        if len(years) < 2:
            return 0
        prev_y, cur_y = years[-2], years[-1]
        dep_cur = EarningsQualityScorer._lookup(dep, cur_y)
        dep_prev = EarningsQualityScorer._lookup(dep, prev_y)
        if dep_cur is None or dep_prev in (None, 0, 0.0):
            return 0

        checks.append("depreciation")
        change = (dep_cur - dep_prev) / dep_prev
        details["depreciation_change_pct"] = round(change * 100, 1)
        details["depreciation_years"] = [prev_y, cur_y]
        if change < EarningsQualityScorer.DEPRECIATION_DECLINE_THRESHOLD:
            flags.append(
                f"Depreciation fell {abs(change) * 100:.0f}% YoY — possible asset "
                f"sale or policy change supporting reported PAT."
            )
            return 1
        return 0

    @staticmethod
    def _check_exceptional(
        data: Dict[str, Any],
        flags: List[str],
        details: Dict[str, Any],
        checks: List[str],
    ) -> int:
        exceptional = EarningsQualityScorer._pick(data, _EXCEPTIONAL_KEYS)
        years = EarningsQualityScorer._actual_years(exceptional)
        if not years:
            return 0
        year = years[-1]
        value = EarningsQualityScorer._lookup(exceptional, year)
        if value is None or value == 0:
            return 0

        checks.append("exceptional items")
        details["exceptional_items"] = value
        details["exceptional_year"] = year
        revenue = EarningsQualityScorer._pick(data, _REVENUE_KEYS)
        rev = EarningsQualityScorer._lookup(revenue, year)
        if rev not in (None, 0, 0.0) and abs(value) / abs(rev) > EarningsQualityScorer.EXCEPTIONAL_REVENUE_SHARE:
            share = abs(value) / abs(rev) * 100
            flags.append(
                f"Exceptional items of {value:.1f} ({share:.1f}% of top-line) "
                f"affect reported PAT in {year}."
            )
            return 1
        if rev in (None, 0, 0.0):
            flags.append(
                f"Exceptional items of {value:.1f} are present in {year}; "
                f"share of top-line cannot be computed from this filing."
            )
            return 1
        return 0

    @staticmethod
    def _check_cash_conversion(
        data: Dict[str, Any],
        flags: List[str],
        details: Dict[str, Any],
        checks: List[str],
    ) -> int:
        ocf = EarningsQualityScorer._pick(data, _OCF_KEYS)
        pat = EarningsQualityScorer._pick(data, _PAT_KEYS)
        years = EarningsQualityScorer._common_years(ocf, pat)
        if not years:
            return 0
        year = years[-1]
        ocf_v = EarningsQualityScorer._lookup(ocf, year)
        pat_v = EarningsQualityScorer._lookup(pat, year)
        if ocf_v is None or pat_v is None or pat_v <= 0:
            return 0

        checks.append("cash conversion")
        conversion = ocf_v / pat_v
        details["ocf_to_pat"] = round(conversion * 100, 1)
        details["ocf_pat_year"] = year
        if conversion < EarningsQualityScorer.OCF_PAT_WEAK:
            flags.append(
                f"Operating cash flow is {conversion * 100:.0f}% of PAT in {year} "
                f"— reported earnings are converting poorly into cash."
            )
            return 1
        return 0

    @staticmethod
    def _build_narrative(score: str, flags: List[str], checks: List[str]) -> str:
        checked = ", ".join(checks)
        parts = [f"Earnings quality: {score} (checked {checked})."]
        if flags:
            parts.append(" ".join(flags[:3]))
        else:
            parts.append(f"No material distortion on: {checked}.")
        return " ".join(parts)
