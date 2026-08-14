"""Adaptive payload on a fixed Geojit frame.

Sector configs supply default keys. Any other numeric line item extracted
from the source is kept and printed in the extra-metrics table instead of
being dropped.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set

_SKIP_KEYS = {
    "period_labels", "unit", "currency", "notes", "commentary",
    "revenue", "total_income", "operating_revenue", "net_sales", "nii",
    "net_interest_income", "ebitda", "operating_profit", "ppop", "ebit",
    "pbt", "profit_before_tax", "pat", "net_profit", "profit_after_tax",
    "eps", "dps", "depreciation", "amortization", "interest", "finance_costs",
    "tax", "income_tax", "other_income",
    "total_assets", "total_equity", "total_debt", "cash", "cash_and_equivalents",
    "receivables", "accounts_receivable", "inventories", "investments",
    "gross_fixed_assets", "net_fixed_assets",
    "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    "free_cash_flow", "operating", "investing", "financing",
    # Already printed in P&L / latest snapshot — dumping them again blows the 4-page frame.
    "advances", "deposits", "borrowings", "net_worth", "book_value",
    "total_liabilities", "provisions", "provision_expense", "shareholders_fund",
    "shareholder_funds", "current_liabilities", "loans",
}

_SUFFIX_LABELS = (
    ("_pct", " (%)"),
    ("_bps", " (bps)"),
    ("_mw", " (MW)"),
    ("_mus", " (MUs)"),
    ("_mt", " (MT)"),
    ("_cr", " (Rs. cr)"),
    ("_ratio", " ratio"),
)


def _has_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).replace(",", "").strip())
        return str(value).strip() not in ("", "—", "None", "null")
    except (TypeError, ValueError):
        return False


def humanize_key(key: str) -> str:
    raw = str(key or "").strip()
    suffix = ""
    lower = raw.lower()
    for token, label in _SUFFIX_LABELS:
        if lower.endswith(token):
            raw = raw[: -len(token)]
            suffix = label
            break
    words = re.sub(r"[_-]+", " ", raw).strip()
    titled = " ".join(w.upper() if w.lower() in {"nim", "gnpa", "nnpa", "pcr", "roe", "roa", "eps", "pat", "nii", "casa", "plf", "aum"} else w.capitalize() for w in words.split())
    return f"{titled}{suffix}".strip() or key


def discover_extra_metrics(
    raw_financials: Dict[str, Any],
    existing_labels: Iterable[str],
    existing_keys: Iterable[str],
    period_pairs: List[tuple],
) -> List[Dict[str, Any]]:
    """Return extra-metric rows for source keys the sector config did not list."""
    if not isinstance(raw_financials, dict):
        return []
    seen_labels: Set[str] = {str(x) for x in existing_labels}
    seen_keys: Set[str] = {str(x).lower() for x in existing_keys} | _SKIP_KEYS
    rows: List[Dict[str, Any]] = []

    for key, payload in raw_financials.items():
        if not key or str(key).lower() in seen_keys:
            continue
        if not isinstance(payload, dict):
            continue
        values = {}
        for display_period, period_key in period_pairs:
            val = payload.get(period_key)
            values[display_period] = val if _has_number(val) else "—"
        if all(v == "—" for v in values.values()):
            continue
        label = humanize_key(key)
        if label in seen_labels:
            continue
        rows.append({"metric": label, **values})
        seen_labels.add(label)
        seen_keys.add(str(key).lower())
    return rows
