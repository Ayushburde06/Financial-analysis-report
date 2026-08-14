"""
Stage 10: Evidence Builder

Maps this filing's extracted JSON onto the Geojit evidence packets.
Uses the sector config for this industry, then any other numbered line
items from the source. Missing stays empty. No invented fields.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence
import re

import importlib

quant_engine_module = importlib.import_module("pipeline.09_quant_engine.engine")
QuantEngine = quant_engine_module.QuantEngine

quant_proj_module = importlib.import_module("pipeline.09_quant_engine.projections")
ForwardProjector = quant_proj_module.ForwardProjector

evidence_packets = importlib.import_module("pipeline.09_quant_engine.evidence_packets")
FinancialAnalystEvidence = evidence_packets.FinancialAnalystEvidence
ProfitAndLossPacket = evidence_packets.ProfitAndLossPacket
BalanceSheetPacket = evidence_packets.BalanceSheetPacket
CashFlowPacket = evidence_packets.CashFlowPacket

from .failure_analyzer import FailureAnalyzerAgent

_SKIP_EXTRA = {
    "period_labels", "unit", "currency", "notes", "commentary",
    "segments", "segment_revenue", "segment_breakdown", "geo", "geography",
}


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


def _resolve(raw_data: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        if not key:
            continue
        val = raw_data.get(key)
        if isinstance(val, dict) and any(_has_number(v) for v in val.values()):
            return val
    return {}


def _unique(keys: Iterable[str]) -> List[str]:
    seen: List[str] = []
    for key in keys:
        token = str(key or "").strip()
        if token and token not in seen:
            seen.append(token)
    return seen


def _line(raw: Dict[str, Any], name: str, *keys: str, project: bool = False):
    payload = _resolve(raw, *keys)
    item = QuantEngine.build_financial_line_item(payload, name)
    if project:
        item = ForwardProjector.project_next_two_years(name, item)
    return item


class EvidenceBuilder:
    @staticmethod
    def build_financial_evidence(
        raw_data: Dict[str, Any],
        company_name: str,
        industry: str = "",
        extra_keys: Optional[Sequence[str]] = None,
    ) -> FinancialAnalystEvidence:
        print("     [Evidence Builder] Wrapping source financials into evidence packets...")
        raw = raw_data if isinstance(raw_data, dict) else {}
        extra_keys = list(extra_keys or [])

        from pipeline.sectors import get_sector_config
        cfg = get_sector_config(industry or "")

        score = FailureAnalyzerAgent.score_extraction(raw, extra_keys=extra_keys)
        print(f"     [Evidence Builder] Source coverage score={score}")

        rev_keys = _unique(list(cfg.revenue_keys or []) + [
            "revenue", "total_income", "operating_revenue", "net_sales",
            "nii", "net_interest_income",
        ])
        ebitda_keys = _unique(list(cfg.ebitda_keys or []) + [
            "ebitda", "operating_profit", "ppop",
        ])
        pat_keys = _unique(list(cfg.pat_keys or []) + [
            "pat", "net_profit", "profit_after_tax",
        ])
        asset_keys = _unique(list(cfg.assets_keys or []) + ["total_assets"])
        liab_keys = _unique(list(cfg.liab_keys or []) + ["total_liabilities"])
        equity_keys = _unique(list(cfg.equity_keys or []) + [
            "total_equity", "net_worth", "shareholders_equity", "shareholders_funds",
        ])
        debt_keys = _unique(list(cfg.debt_keys or []) + ["total_debt", "borrowings"])
        cash_keys = _unique(list(cfg.cash_keys or []) + ["cash_and_equivalents", "cash"])

        pl_packet = ProfitAndLossPacket(
            revenue=_line(raw, "revenue", *rev_keys, project=True),
            ebitda=_line(raw, "ebitda", *ebitda_keys, project=True),
            ebit=_line(raw, "ebit", "ebit", project=True),
            pbt=_line(raw, "pbt", "pbt", "profit_before_tax", project=True),
            pat=_line(raw, "pat", *pat_keys, project=True),
            eps=_line(raw, "eps", "eps", project=True),
            depreciation=_line(raw, "depreciation", "depreciation", "amortization"),
            interest=_line(raw, "interest", "interest", "finance_costs"),
            other_income=_line(raw, "other_income", "other_income"),
            tax=_line(raw, "tax", "tax", "income_tax"),
            tax_rate=_line(raw, "tax_rate", "tax_rate"),
        )

        bs_packet = BalanceSheetPacket(
            total_assets=_line(raw, "total_assets", *asset_keys),
            total_liabilities=_line(raw, "total_liabilities", *liab_keys),
            total_equity=_line(raw, "total_equity", *equity_keys),
            total_debt=_line(raw, "total_debt", *debt_keys),
            cash_and_equivalents=_line(raw, "cash_and_equivalents", *cash_keys),
            accounts_receivable=_line(raw, "accounts_receivable", "accounts_receivable", "debtors"),
            inventories=_line(raw, "inventories", "inventories", "inventory"),
            investments=_line(raw, "investments", "investments"),
            gross_fixed_assets=_line(raw, "gross_fixed_assets", "gross_fixed_assets", "fixed_assets"),
            current_liabilities=_line(raw, "current_liabilities", "current_liabilities"),
            provisions=_line(raw, "provisions", "provisions"),
        )

        cf_packet = CashFlowPacket(
            operating_cash_flow=_line(raw, "operating_cash_flow", "operating_cash_flow"),
            investing_cash_flow=_line(raw, "investing_cash_flow", "investing_cash_flow"),
            financing_cash_flow=_line(raw, "financing_cash_flow", "financing_cash_flow"),
            free_cash_flow=_line(raw, "free_cash_flow", "free_cash_flow"),
        )

        used = set(rev_keys + ebitda_keys + pat_keys + asset_keys + liab_keys
                   + equity_keys + debt_keys + cash_keys)
        used.update({
            "ebit", "pbt", "profit_before_tax", "eps", "depreciation", "amortization",
            "interest", "finance_costs", "other_income", "tax", "income_tax", "tax_rate",
            "accounts_receivable", "debtors", "inventories", "inventory", "investments",
            "gross_fixed_assets", "fixed_assets", "current_liabilities", "provisions",
            "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
            "free_cash_flow",
        })

        extra: Dict[str, Any] = {}
        wanted = []
        for _label, key in getattr(cfg, "extra_metrics", []) or []:
            if key:
                wanted.append(key)
        wanted.extend(extra_keys)
        for key in _unique(wanted):
            payload = raw.get(key)
            if QuantEngine._is_period_dict(payload):
                extra[key] = QuantEngine.build_financial_line_item(payload, key)

        for key, payload in raw.items():
            if key in extra or key in used or key in _SKIP_EXTRA:
                continue
            if not QuantEngine._is_period_dict(payload):
                continue
            extra[key] = QuantEngine.build_financial_line_item(payload, key)
            if len(extra) >= 24:
                break

        if extra:
            print(f"     [Evidence Builder] Extra source metrics: {list(extra.keys())[:12]}")

        return FinancialAnalystEvidence(
            company_name=company_name,
            pl=pl_packet,
            bs=bs_packet,
            cf=cf_packet,
            banking_metrics=extra or None,
            industry=industry or "",
        )


def _plain_sentences(items: Any, limit: int = 4) -> List[str]:
    """Keep filing sentences for narrative; drop printed numbers."""
    out: List[str] = []
    if isinstance(items, str):
        items = [items]
    for raw in items or []:
        text = raw if isinstance(raw, str) else str(raw or "")
        text = re.sub(r"Rs\.?\s*", " ", text, flags=re.I)
        text = re.sub(r"[\d,]+(?:\.\d+)?%?", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" :-")
        if len(text) < 40:
            continue
        out.append(text[:320])
        if len(out) >= limit:
            break
    return out


def attach_filing_context(
    evidence: Any,
    *,
    industry: str = "",
    knowledge: Optional[Dict[str, Any]] = None,
    period_label: str = "",
    source_unit: str = "",
) -> Any:
    """Attach this filing's activity/risk sentences for Stage 11."""
    kg = knowledge if isinstance(knowledge, dict) else {}
    facts = _plain_sentences(kg.get("strategy_and_highlights"))
    facts += _plain_sentences(kg.get("management_commentary"), limit=2)
    risks = _plain_sentences(kg.get("risks_and_challenges"), limit=3)
    update = {
        "industry": industry or getattr(evidence, "industry", "") or "",
        "period_label": period_label or getattr(evidence, "period_label", "") or "",
        "source_unit": source_unit or getattr(evidence, "source_unit", "") or "",
        "business_facts": facts[:6],
        "risk_facts": risks,
    }
    if hasattr(evidence, "model_copy"):
        return evidence.model_copy(update=update)
    for key, val in update.items():
        setattr(evidence, key, val)
    return evidence
