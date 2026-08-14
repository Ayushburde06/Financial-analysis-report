"""
AnalyticalEngine — Runs 10b–10f on this filing, then optionally refreshes narrative.

  1. CrossMetricAnalyzer
  2. EarningsQualityScorer (JSON + OCR markdown)
  3. ScenarioBuilder (source target only)
  4. MgmtRealityCrossReferencer (commentary vs actuals)
  5. Analytical prompt / narrative refresh
"""
import importlib
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class AnalyticalEngineResult:
    cross_metric_observations: List[str] = field(default_factory=list)
    cross_metric_brief: str = ""
    earnings_quality_score: str = ""
    earnings_quality_flags: List[str] = field(default_factory=list)
    earnings_quality_narrative: str = ""
    scenario_brief: str = ""
    scenarios: List[Dict[str, Any]] = field(default_factory=list)
    expected_value: Optional[float] = None
    mgmt_reality_assessment: str = ""
    mgmt_reality_gaps: List[str] = field(default_factory=list)
    narrative_refreshed: bool = False
    appendix: Dict[str, Any] = field(default_factory=dict)


class AnalyticalEngine:
    @staticmethod
    def run(
        fa_evidence: Any,
        annual_data: Dict[str, Any],
        quarterly_data: Dict[str, Any],
        company_name: str,
        industry: str,
        report_period: str,
        ocr_text: str = "",
        cmp: Optional[float] = None,
        target_price: Optional[float] = None,
        outlook_text: str = "",
        sector_name: str = "",
        llm_client=None,
        refresh_narrative: bool = True,
    ) -> Tuple[AnalyticalEngineResult, Optional[Dict[str, Any]]]:
        """
        Run analytical modules and optionally return refreshed narrative_sections dict.

        Returns (result, narrative_sections_or_none).
        """
        result = AnalyticalEngineResult()
        pl = fa_evidence.pl
        bs = fa_evidence.bs

        # Keep every series this filing produced. Do not drop other_income,
        # exceptional items, or extra metrics before 10b/10c see them.
        annual_for_analysis = dict(annual_data or {})
        extras = getattr(fa_evidence, "banking_metrics", None) or {}
        if isinstance(extras, dict):
            for key, item in extras.items():
                if key in annual_for_analysis:
                    continue
                if hasattr(item, "actual_year_values"):
                    filled = item.actual_year_values() or {}
                    if filled:
                        annual_for_analysis[key] = filled

        # ── 1. Cross-metric analysis ─────────────────────────────────────────
        try:
            CrossMetricAnalyzer = importlib.import_module(
                "pipeline.10b_cross_metric_analyzer.analyzer"
            ).CrossMetricAnalyzer
            cm_report = CrossMetricAnalyzer.analyze(
                annual_for_analysis, quarterly_data, pl, bs
            )
            result.cross_metric_brief = cm_report.narrative_brief
            result.cross_metric_observations = cm_report.key_observations
        except Exception as exc:
            print(f"     [Analytical Engine] Cross-metric analysis failed: {exc}")

        # ── 2. Earnings quality ────────────────────────────────────────────
        try:
            EarningsQualityScorer = importlib.import_module(
                "pipeline.10c_earnings_quality.scorer"
            ).EarningsQualityScorer
            eq = EarningsQualityScorer.score(
                annual_for_analysis,
                pl,
                quarterly_data=quarterly_data,
                cf=getattr(fa_evidence, "cf", None),
                ocr_text=ocr_text or "",
            )
            result.earnings_quality_score = eq.score
            result.earnings_quality_flags = eq.flags
            result.earnings_quality_narrative = eq.narrative
        except Exception as exc:
            print(f"     [Analytical Engine] Earnings quality failed: {exc}")

        # ── 3. Scenarios ─────────────────────────────────────────────────────
        if cmp and target_price:
            try:
                ScenarioBuilder = importlib.import_module(
                    "pipeline.10d_scenario_builder.builder"
                ).ScenarioBuilder
                rev_est = annual_data.get("revenue_est", {}) or {}
                pat_est = annual_data.get("pat_est", {}) or {}

                mgmt_text = outlook_text or ""
                scenario_report = ScenarioBuilder.build(
                    base_target=float(target_price),
                    cmp=float(cmp),
                    revenue_estimates=rev_est,
                    pat_estimates=pat_est,
                    ocr_text=ocr_text or "",
                    management_commentary=mgmt_text,
                    sector=sector_name or industry,
                )
                result.scenario_brief = scenario_report.narrative_brief
                result.expected_value = scenario_report.expected_value
                result.scenarios = [
                    {
                        "label": s.label,
                        "probability_pct": s.probability_pct,
                        "target_price": s.target_price,
                        "upside_pct": s.upside_pct,
                        "catalysts": s.catalysts,
                    }
                    for s in scenario_report.scenarios
                ]
            except Exception as exc:
                print(f"     [Analytical Engine] Scenario builder failed: {exc}")

        # ── 4. Management vs reality ─────────────────────────────────────────
        try:
            MgmtRealityCrossReferencer = importlib.import_module(
                "pipeline.10e_mgmt_reality.cross_referencer"
            ).MgmtRealityCrossReferencer
            mgmt_report = MgmtRealityCrossReferencer.analyze(
                management_text=outlook_text or "",
                annual_data=annual_for_analysis,
                sector=sector_name or industry,
                ocr_text=ocr_text or "",
            )
            result.mgmt_reality_assessment = mgmt_report.overall_assessment
            result.mgmt_reality_gaps = [
                f"{g.claim} — however, {g.evidence} ({g.gap}, {g.confidence} confidence)"
                for g in mgmt_report.gaps
            ]
        except Exception as exc:
            print(f"     [Analytical Engine] Mgmt reality check failed: {exc}")

        # ── 5. Peer / sector benchmark ───────────────────────────────────────
        peer_benchmark_data: Dict[str, Any] = {}
        try:
            PeerBenchmark = importlib.import_module(
                "pipeline.10c_peer_context.benchmark"
            ).PeerBenchmark
            rev_g = None
            rev_series = annual_for_analysis.get("revenue", {})
            if len(rev_series) >= 2:
                yrs = sorted(rev_series.keys())
                cur = rev_series.get(yrs[-1])
                prev = rev_series.get(yrs[-2])
                try:
                    if cur and prev and float(prev) != 0:
                        rev_g = round((float(cur) - float(prev)) / abs(float(prev)) * 100, 1)
                except (TypeError, ValueError):
                    pass
            peer = PeerBenchmark.compare(rev_g, sector_name or industry)
            if peer.narrative:
                result.cross_metric_observations.append(peer.narrative)
                if not result.cross_metric_brief:
                    result.cross_metric_brief = peer.narrative
                else:
                    result.cross_metric_brief += " " + peer.narrative
            peer_benchmark_data = {
                "vs_sector": peer.revenue_growth_vs_sector,
                "gap_pp": peer.revenue_growth_gap_pp,
                "narrative": peer.narrative,
            }
        except Exception as exc:
            print(f"     [Analytical Engine] Peer benchmark failed: {exc}")

        result.appendix = {
            "cross_metric_brief": result.cross_metric_brief,
            "cross_metric_observations": result.cross_metric_observations,
            "earnings_quality": {
                "score": result.earnings_quality_score,
                "flags": result.earnings_quality_flags,
                "narrative": result.earnings_quality_narrative,
            },
            "scenarios": result.scenarios,
            "expected_value": result.expected_value,
            "mgmt_reality": {
                "assessment": result.mgmt_reality_assessment,
                "gaps": result.mgmt_reality_gaps,
            },
            "peer_benchmark": peer_benchmark_data,
        }

        narrative_sections = None
        if refresh_narrative:
            rev_series = (
                annual_for_analysis.get("revenue")
                or annual_for_analysis.get("nii")
                or {}
            )
            annual_years = 0
            if isinstance(rev_series, dict):
                annual_years = sum(
                    1 for k in rev_series
                    if re.match(r"^fy\d{2,4}a?$", str(k).strip(), re.I)
                )
            has_bs = False
            assets = getattr(bs, "total_assets", None)
            if assets is not None and hasattr(assets, "actual_year_values"):
                has_bs = bool(assets.actual_year_values())
            narrative_sections = AnalyticalEngine._refresh_narrative(
                fa_evidence=fa_evidence,
                result=result,
                company_name=company_name,
                industry=industry,
                report_period=report_period,
                sector_name=sector_name,
                annual_years=annual_years,
                has_quarterly=bool((quarterly_data or {}).get("quarters")),
                has_balance_sheet=has_bs,
            )
            if narrative_sections:
                result.narrative_refreshed = True

        return result, narrative_sections

    @staticmethod
    def _refresh_narrative(
        fa_evidence: Any,
        result: AnalyticalEngineResult,
        company_name: str,
        industry: str,
        report_period: str,
        sector_name: str,
        annual_years: int,
        has_quarterly: bool,
        has_balance_sheet: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Call LLM with pre-computed analytical conclusions."""
        try:
            AnalyticalPromptBuilder = importlib.import_module(
                "pipeline.10f_analytical_prompt.builder"
            ).AnalyticalPromptBuilder
            AnalyticalContext = importlib.import_module(
                "pipeline.10f_analytical_prompt.builder"
            ).AnalyticalContext
            _base_agent_mod = importlib.import_module(
                "pipeline.11_specialist_agents.base_agent"
            )
            _narrative_evidence_cues = _base_agent_mod._narrative_evidence_cues
            parse_narrative_sections = _base_agent_mod.parse_narrative_sections
            _strip_thinking_blocks = _base_agent_mod._strip_thinking_blocks
            _strip_numbers_from_narrative = _base_agent_mod._strip_numbers_from_narrative
            FinancialAnalyst = importlib.import_module(
                "pipeline.11_specialist_agents.financial_analyst"
            ).FinancialAnalyst
            call_azure_deepseek = importlib.import_module(
                "pipeline.utils.llm_client"
            ).call_azure_deepseek

            ctx = AnalyticalContext(
                cross_metric_brief=result.cross_metric_brief,
                margin_observations=result.cross_metric_observations,
                earnings_quality_score=result.earnings_quality_score,
                earnings_quality_flags=result.earnings_quality_flags,
                earnings_quality_narrative=result.earnings_quality_narrative,
                scenario_brief=result.scenario_brief,
                expected_value=result.expected_value,
                mgmt_reality_assessment=result.mgmt_reality_assessment,
                mgmt_reality_gaps=result.mgmt_reality_gaps,
                sector=sector_name or industry,
                years_available=annual_years,
                has_quarterly=has_quarterly,
                has_segments=False,
                has_balance_sheet=has_balance_sheet,
            )

            cues = _narrative_evidence_cues(fa_evidence)
            system_prompt = AnalyticalPromptBuilder.build_system_prompt(
                ctx, company_name, industry, sector_name or industry
            )
            user_prompt = AnalyticalPromptBuilder.build_user_prompt(
                ctx, company_name, report_period, cues
            )

            print("     [Analytical Engine] Refreshing narrative with analytical context...")
            raw = call_azure_deepseek(system_prompt, user_prompt, max_tokens=4096, temperature=0.35)
            narrative = _strip_thinking_blocks(raw or "")
            if narrative.strip():
                narrative = _strip_numbers_from_narrative(narrative)

            if not narrative.strip():
                agent = FinancialAnalyst()
                narrative = agent.generate(fa_evidence)
                if not narrative.strip():
                    return None

            sections = parse_narrative_sections(narrative)
            print("     [Analytical Engine] Analytical narrative refresh complete.")
            return sections
        except Exception as exc:
            print(f"     [Analytical Engine] Narrative refresh failed (non-fatal): {exc}")
            return None
