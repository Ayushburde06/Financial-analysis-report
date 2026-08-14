"""
projections.py — Forward estimates for the Geojit E columns.

Python only. Marks is_estimate=True. Never sent as source facts.

- Keep numbers already extracted from the filing.
- Project the next two years only when two annual actuals exist
  (historical growth, capped ±30%).
- No 5% default. No run-rate (q_current × 4).
"""
import re
from typing import Optional, Tuple

from .evidence_packets import FinancialLineItem, VerifiedNumber


class ForwardProjector:
    MAX_GROWTH_RATE = 0.30
    MIN_GROWTH_RATE = -0.30

    @staticmethod
    def _year_num(key: str) -> int:
        nums = re.findall(r"\d+", key or "")
        return int(nums[0]) if nums else 0

    @staticmethod
    def _latest_actual_year(line_item: FinancialLineItem):
        candidates = line_item.actual_year_values() if hasattr(line_item, "actual_year_values") else {}
        if not candidates:
            return None, None
        latest_key = max(candidates.keys(), key=ForwardProjector._year_num)
        return latest_key, candidates[latest_key]

    @staticmethod
    def _second_latest_actual_year(line_item: FinancialLineItem, latest_key: str):
        candidates = {
            k: v for k, v in (line_item.actual_year_values() or {}).items()
            if k != latest_key
        }
        if not candidates:
            return None, None
        second_key = max(candidates.keys(), key=ForwardProjector._year_num)
        return second_key, candidates[second_key]

    @staticmethod
    def _estimate_year_labels(latest_key: str) -> Tuple[str, str]:
        yr = ForwardProjector._year_num(latest_key)
        return f"fy{yr + 1}e", f"fy{yr + 2}e"

    @staticmethod
    def _existing_estimate(line_item: FinancialLineItem, key: str) -> Optional[VerifiedNumber]:
        vn = line_item.get_annual_value(key)
        if vn and isinstance(vn.value, (int, float)):
            return vn
        return None

    @staticmethod
    def _store(line_item: FinancialLineItem, key: str, vn: VerifiedNumber) -> None:
        if line_item.annual is None:
            line_item.annual = {}
        line_item.annual[key] = vn
        if key == "fy26e":
            line_item.fy26e = vn
        elif key == "fy27e":
            line_item.fy27e = vn

    @staticmethod
    def project_next_two_years(
        metric_name: str,
        line_item: FinancialLineItem,
        guidance: str = None,
    ) -> FinancialLineItem:
        latest_key, latest_val = ForwardProjector._latest_actual_year(line_item)
        if latest_key is None or not isinstance(latest_val, (int, float)):
            return line_item

        est_key_1, est_key_2 = ForwardProjector._estimate_year_labels(latest_key)
        have_1 = ForwardProjector._existing_estimate(line_item, est_key_1)
        have_2 = ForwardProjector._existing_estimate(line_item, est_key_2)
        if have_1 and have_2:
            ForwardProjector._store(line_item, est_key_1, have_1)
            ForwardProjector._store(line_item, est_key_2, have_2)
            return line_item

        second_key, second_val = ForwardProjector._second_latest_actual_year(
            line_item, latest_key
        )
        if second_key is None or not isinstance(second_val, (int, float)) or float(second_val) == 0:
            return line_item

        growth_rate = (float(latest_val) - float(second_val)) / abs(float(second_val))
        growth_rate = max(
            ForwardProjector.MIN_GROWTH_RATE,
            min(ForwardProjector.MAX_GROWTH_RATE, growth_rate),
        )
        if guidance:
            matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", guidance)
            if matches:
                g = float(matches[0]) / 100.0
                growth_rate = max(
                    ForwardProjector.MIN_GROWTH_RATE,
                    min(ForwardProjector.MAX_GROWTH_RATE, g),
                )

        base = float(latest_val)
        if have_1 is None:
            ForwardProjector._store(
                line_item,
                est_key_1,
                VerifiedNumber(value=round(base * (1 + growth_rate), 2), is_estimate=True),
            )
            have_1 = line_item.get_annual_value(est_key_1)
        if have_2 is None and have_1 and isinstance(have_1.value, (int, float)):
            ForwardProjector._store(
                line_item,
                est_key_2,
                VerifiedNumber(
                    value=round(float(have_1.value) * (1 + growth_rate), 2),
                    is_estimate=True,
                ),
            )
        return line_item
