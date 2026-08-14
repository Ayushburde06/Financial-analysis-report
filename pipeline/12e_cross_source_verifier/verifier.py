"""Deterministic cross-source verification and research-quality scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CrossSourceCheck:
    field: str
    primary_value: Optional[float]
    secondary_value: Optional[float]
    primary_source: str
    secondary_source: str
    status: str
    difference_pct: Optional[float] = None
    note: str = ""


@dataclass
class CrossSourceReport:
    checks: List[CrossSourceCheck] = field(default_factory=list)
    review_flags: List[str] = field(default_factory=list)
    score: float = 0.0
    summary: str = ""

    @property
    def confirmed_count(self) -> int:
        return sum(c.status == "confirmed" for c in self.checks)

    @property
    def comparable_count(self) -> int:
        return sum(c.status in ("confirmed", "conflict") for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "summary": self.summary,
            "confirmed_count": self.confirmed_count,
            "comparable_count": self.comparable_count,
            "review_flags": list(self.review_flags),
            "checks": [c.__dict__.copy() for c in self.checks],
        }


def _number(value: Any) -> Optional[float]:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


class CrossSourceVerifier:
    """Compare overlapping facts without mutating report data."""

    MARKET_FIELDS = (
        ("cmp", "cmp", "Current market price"),
        ("market_cap_cr", "market_cap_cr", "Market capitalisation"),
        ("enterprise_value_cr", "enterprise_value_cr", "Enterprise value"),
        ("week52_high", "week52_high", "52-week high"),
        ("week52_low", "week52_low", "52-week low"),
    )

    @staticmethod
    def verify(primary_valuation=None, secondary_market=None, *, tolerance_pct: float = 5.0):
        primary = primary_valuation or {}
        secondary = secondary_market or {}
        report = CrossSourceReport()
        for field, secondary_key, label in CrossSourceVerifier.MARKET_FIELDS:
            pv = _number(primary.get(field))
            sv = _number(secondary.get(secondary_key))
            if pv is None or sv is None:
                report.checks.append(CrossSourceCheck(
                    field, pv, sv, "uploaded source document", "verified external market data",
                    "unavailable", note=f"{label} was not available from both sources."))
                continue
            diff = abs(pv - sv) / max(abs(pv), 1e-9) * 100.0
            status = "confirmed" if diff <= tolerance_pct else "conflict"
            report.checks.append(CrossSourceCheck(
                field, pv, sv, "uploaded source document", "verified external market data",
                status, round(diff, 2),
                f"{label} {'agrees' if status == 'confirmed' else 'differs'} by {diff:.1f}%."))
            if status == "conflict":
                report.review_flags.append(f"Cross-source conflict: {field} ({diff:.1f}% difference)")
        comparable = report.comparable_count
        report.score = report.confirmed_count / comparable if comparable else 0.0
        report.summary = (
            f"{report.confirmed_count}/{comparable} comparable market facts agree within "
            f"{tolerance_pct:.1f}% tolerance."
            if comparable else "No overlapping secondary market facts were available for comparison."
        )
        if not comparable:
            report.review_flags.append("No independent secondary market facts available for comparison.")
        return report
