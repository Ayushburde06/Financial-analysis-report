"""
scorecard_engine.py — Stage 09

Python scores from verified evidence. No default 8/10 pack.
Geojit PDF does not print this card; it must still be honest if used.
"""
from typing import Any, Dict, Optional

from schema import AIScorecard


def _num(item: Any, *keys: str) -> Optional[float]:
    if item is None:
        return None
    for key in keys:
        if hasattr(item, "numeric_at"):
            val = item.numeric_at(key)
            if val is not None:
                return val
        vn = getattr(item, key, None)
        if vn is not None and hasattr(vn, "value") and isinstance(vn.value, (int, float)):
            return float(vn.value)
    if hasattr(item, "actual_year_values"):
        actuals = item.actual_year_values() or {}
        if actuals:
            def _year_num(k):
                digits = "".join(ch for ch in k if ch.isdigit())
                return int(digits) if digits else 0
            latest = max(actuals, key=_year_num)
            return actuals[latest]
    return None


def _prior(item: Any) -> Optional[float]:
    if item is None or not hasattr(item, "actual_year_values"):
        return None
    actuals = item.actual_year_values() or {}
    if len(actuals) < 2:
        return None

    def _year_num(k):
        digits = "".join(ch for ch in k if ch.isdigit())
        return int(digits) if digits else 0

    ordered = sorted(actuals, key=_year_num)
    return actuals[ordered[-2]]


class ScorecardEngine:
    @staticmethod
    def compute(fa_evidence: Any, source_context: Optional[Dict[str, Any]] = None) -> AIScorecard:
        source_context = source_context or {}
        pl = getattr(fa_evidence, "pl", None)
        bs = getattr(fa_evidence, "bs", None)
        revenue = getattr(pl, "revenue", None) if pl else None
        ebitda = getattr(pl, "ebitda", None) if pl else None
        pat = getattr(pl, "pat", None) if pl else None

        growth_score = 0.0
        curr = _num(revenue, "q_current") or _num(revenue)
        prev = _num(revenue, "q_prev_year") or _prior(revenue)
        if curr is not None and prev not in (None, 0):
            yoy_pct = ((curr - prev) / abs(prev)) * 100
            if yoy_pct >= 25:
                growth_score = 9.8
            elif yoy_pct >= 15:
                growth_score = 9.2
            elif yoy_pct >= 10:
                growth_score = 8.5
            elif yoy_pct >= 5:
                growth_score = 7.5
            elif yoy_pct >= 0:
                growth_score = 6.5
            else:
                growth_score = 4.5

        health_score = 0.0
        equity = _num(getattr(bs, "total_equity", None) if bs else None)
        debt = _num(getattr(bs, "total_debt", None) if bs else None) or 0.0
        cash = _num(getattr(bs, "cash_and_equivalents", None) if bs else None) or 0.0
        if equity and equity > 0:
            d_e = debt / equity
            if d_e < 0.1:
                health_score = 9.5
            elif d_e < 0.5:
                health_score = 8.8
            elif d_e < 1.0:
                health_score = 7.5
            else:
                health_score = 5.5
        elif cash > debt:
            health_score = 9.0

        profit_score = 0.0
        rev = _num(revenue, "q_current") or _num(revenue)
        ebitda_val = _num(ebitda, "q_current") or _num(ebitda)
        if rev and rev > 0 and ebitda_val is not None:
            mgn = (ebitda_val / rev) * 100
            if mgn >= 25:
                profit_score = 9.5
            elif mgn >= 15:
                profit_score = 8.8
            elif mgn >= 10:
                profit_score = 8.1
            elif mgn >= 5:
                profit_score = 7.2
            else:
                profit_score = 5.5
        elif rev and rev > 0:
            pat_val = _num(pat, "q_current") or _num(pat)
            if pat_val is not None:
                mgn = (pat_val / rev) * 100
                profit_score = 8.0 if mgn >= 10 else (6.5 if mgn >= 0 else 4.0)

        fact_check = source_context.get("fact_check") or {}
        total = float(fact_check.get("total") or 0)
        verified = float(fact_check.get("verified_count") or 0)
        confidence_pct = round((verified / total) * 100, 1) if total > 0 else 0.0

        measured = [s for s in (growth_score, health_score, profit_score) if s]
        execution = round(sum(measured) / len(measured), 1) if measured else 0.0
        if health_score >= 8.5 and growth_score >= 7.5:
            risk_level = "Low"
        elif (health_score and health_score < 6.5) or (growth_score and growth_score < 5.0):
            risk_level = "High"
        elif measured:
            risk_level = "Medium"
        else:
            risk_level = "Medium"

        return AIScorecard(
            growth=round(growth_score, 1),
            financial_health=round(health_score, 1),
            profitability=round(profit_score, 1),
            innovation=0.0,
            ai_readiness=0.0,
            execution=execution,
            risk_level=risk_level,
            confidence_pct=confidence_pct,
        )
