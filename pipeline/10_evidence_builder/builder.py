"""
Stage 10: Evidence Builder

FIX: Was hardcoded to look for 'revenue', 'ebitda' etc.
     Banking reports don't have these — they have 'nii', 'nim', 'advances' etc.
     Now uses sector-aware field mapping so bank reports are handled correctly.
"""
from typing import Dict, Any
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


def _resolve(raw_data: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """
    Try each key in order, return the first one found with numeric data.
    Falls back to empty dict so QuantEngine.build_financial_line_item gets a safe input.
    """
    for key in keys:
        val = raw_data.get(key)
        if isinstance(val, dict) and any(
            isinstance(v, (int, float)) and v is not None
            for v in val.values()
        ):
            return val
    return {}


class EvidenceBuilder:

    @staticmethod
    def build_financial_evidence(
        raw_data: Dict[str, Any], company_name: str
    ) -> FinancialAnalystEvidence:
        print("     [Evidence Builder] Validating & Wrapping raw financials into Pydantic schemas...")

        # ── Self-Improving Retry Loop ────────────────────────────────────────
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            score = FailureAnalyzerAgent.score_extraction(raw_data)
            if score >= 0.5:   # Accept partial data (0.5+) to avoid false failures
                print(f"     [Evidence Builder] Extraction validation passed (Score: {score}).")
                break
            else:
                if attempt < max_attempts:
                    raw_data = FailureAnalyzerAgent.analyze_and_retry(raw_data, attempt)
                else:
                    print("     [Evidence Builder] Max retries reached. Proceeding with available data.")
        # ────────────────────────────────────────────────────────────────────

        # ── P&L Packet — sector-aware field resolution ────────────────────
        # Banking: revenue = nii / net_interest_income
        # NBFC:    revenue = aum or nii
        # Others:  revenue = revenue / total_income / operating_revenue
        rev_raw   = _resolve(raw_data,
                             "revenue", "total_income", "operating_revenue",
                             "nii", "net_interest_income", "aum")
        ebitda_raw = _resolve(raw_data, "ebitda", "operating_profit", "ppop")
        ebit_raw   = _resolve(raw_data, "ebit")
        pbt_raw    = _resolve(raw_data, "pbt", "profit_before_tax")
        pat_raw    = _resolve(raw_data, "pat", "net_profit", "profit_after_tax")
        eps_raw    = _resolve(raw_data, "eps")

        # New Granular P&L items
        depreciation_raw = _resolve(raw_data, "depreciation", "amortization")
        interest_raw     = _resolve(raw_data, "interest", "finance_costs")
        other_income_raw = _resolve(raw_data, "other_income")
        tax_raw          = _resolve(raw_data, "tax", "income_tax")
        tax_rate_raw     = _resolve(raw_data, "tax_rate")

        rev_item   = ForwardProjector.project_next_two_years(
                        "revenue", QuantEngine.build_financial_line_item(rev_raw, "revenue"))
        ebitda_item = ForwardProjector.project_next_two_years(
                        "ebitda", QuantEngine.build_financial_line_item(ebitda_raw, "ebitda"))
        ebit_item  = ForwardProjector.project_next_two_years(
                        "ebit", QuantEngine.build_financial_line_item(ebit_raw, "ebit"))
        pbt_item   = ForwardProjector.project_next_two_years(
                        "pbt", QuantEngine.build_financial_line_item(pbt_raw, "pbt"))
        pat_item   = ForwardProjector.project_next_two_years(
                        "pat", QuantEngine.build_financial_line_item(pat_raw, "pat"))
        eps_item   = ForwardProjector.project_next_two_years(
                        "eps", QuantEngine.build_financial_line_item(eps_raw, "eps"))

        pl_packet = ProfitAndLossPacket(
            revenue=rev_item, ebitda=ebitda_item, ebit=ebit_item,
            pbt=pbt_item, pat=pat_item, eps=eps_item,
            depreciation=QuantEngine.build_financial_line_item(depreciation_raw, "depreciation"),
            interest=QuantEngine.build_financial_line_item(interest_raw, "interest"),
            other_income=QuantEngine.build_financial_line_item(other_income_raw, "other_income"),
            tax=QuantEngine.build_financial_line_item(tax_raw, "tax"),
            tax_rate=QuantEngine.build_financial_line_item(tax_rate_raw, "tax_rate")
        )

        # ── Balance Sheet Packet ─────────────────────────────────────────────
        # Banking: assets = advances + deposits proxy
        assets_raw  = _resolve(raw_data, "total_assets", "advances")
        liab_raw    = _resolve(raw_data, "total_liabilities", "deposits")
        equity_raw  = _resolve(raw_data, "total_equity", "net_worth", "shareholders_fund", "shareholders_funds")
        debt_raw    = _resolve(raw_data, "total_debt", "borrowings")
        cash_raw    = _resolve(raw_data, "cash_and_equivalents", "cash")

        # New Granular Balance Sheet items
        ar_raw = _resolve(raw_data, "accounts_receivable", "debtors")
        inv_raw = _resolve(raw_data, "inventories", "inventory")
        investments_raw = _resolve(raw_data, "investments")
        gfa_raw = _resolve(raw_data, "gross_fixed_assets", "fixed_assets")
        cl_raw = _resolve(raw_data, "current_liabilities")
        prov_raw = _resolve(raw_data, "provisions")

        bs_packet = BalanceSheetPacket(
            total_assets       = QuantEngine.build_financial_line_item(assets_raw,  "total_assets"),
            total_liabilities  = QuantEngine.build_financial_line_item(liab_raw,   "total_liabilities"),
            total_equity       = QuantEngine.build_financial_line_item(equity_raw, "total_equity"),
            total_debt         = QuantEngine.build_financial_line_item(debt_raw,   "total_debt"),
            cash_and_equivalents = QuantEngine.build_financial_line_item(cash_raw, "cash_and_equivalents"),
            accounts_receivable = QuantEngine.build_financial_line_item(ar_raw, "accounts_receivable"),
            inventories = QuantEngine.build_financial_line_item(inv_raw, "inventories"),
            investments = QuantEngine.build_financial_line_item(investments_raw, "investments"),
            gross_fixed_assets = QuantEngine.build_financial_line_item(gfa_raw, "gross_fixed_assets"),
            current_liabilities = QuantEngine.build_financial_line_item(cl_raw, "current_liabilities"),
            provisions = QuantEngine.build_financial_line_item(prov_raw, "provisions")
        )

        # ── Cash Flow Packet ─────────────────────────────────────────────────
        ocf_raw  = _resolve(raw_data, "operating_cash_flow")
        icf_raw  = _resolve(raw_data, "investing_cash_flow")
        fcf_raw  = _resolve(raw_data, "financing_cash_flow")
        fcf2_raw = _resolve(raw_data, "free_cash_flow")

        cf_packet = CashFlowPacket(
            operating_cash_flow  = QuantEngine.build_financial_line_item(ocf_raw,  "operating_cash_flow"),
            investing_cash_flow  = QuantEngine.build_financial_line_item(icf_raw,  "investing_cash_flow"),
            financing_cash_flow  = QuantEngine.build_financial_line_item(fcf_raw,  "financing_cash_flow"),
            free_cash_flow       = QuantEngine.build_financial_line_item(fcf2_raw, "free_cash_flow"),
        )

        # ── Banking metrics (NIM, GNPA, etc.) — packaged for sector-specific tables ─
        banking_metrics = None
        banking_keys = ["nim", "gnpa", "nnpa", "pcr", "casa_ratio",
                        "capital_adequacy", "tier1_ratio", "roe", "roa",
                        "credit_growth", "slippage_ratio", "provision_expense",
                        "advances", "deposits"]
        if any(k in raw_data for k in banking_keys):
            banking_metrics = {}
            for k in banking_keys:
                if k in raw_data and raw_data[k]:
                    banking_metrics[k] = QuantEngine.build_financial_line_item(raw_data[k], k)

        return FinancialAnalystEvidence(
            company_name=company_name,
            pl=pl_packet,
            bs=bs_packet,
            cf=cf_packet,
            banking_metrics=banking_metrics,
        )
