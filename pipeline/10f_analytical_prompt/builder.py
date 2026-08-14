"""
Stage 10f — Geojit four-block prompt from THIS filing's findings.

Only injects analytical blocks that were actually computed.
Does not ask the LLM to invent FY26E, bull/bear, CMP, or quality scores.
"""
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class AnalyticalContext:
    cross_metric_brief: str = ""
    margin_observations: List[str] = field(default_factory=list)
    earnings_quality_score: str = ""
    earnings_quality_flags: List[str] = field(default_factory=list)
    earnings_quality_narrative: str = ""
    scenario_brief: str = ""
    expected_value: Optional[float] = None
    mgmt_reality_assessment: str = ""
    mgmt_reality_gaps: List[str] = field(default_factory=list)
    sector: str = ""
    sector_narrative: str = ""
    years_available: int = 0
    has_quarterly: bool = False
    has_segments: bool = False
    has_balance_sheet: bool = False


class AnalyticalPromptBuilder:
    @staticmethod
    def build_system_prompt(
        context: AnalyticalContext,
        company_name: str,
        industry: str,
        sector: str = "",
    ) -> str:
        sector_str = sector or industry or "this sector"
        name = company_name or "the company"
        ctx = context or AnalyticalContext()

        prompt = f"""You are a senior equity research analyst writing a Geojit-style note on {name} ({sector_str}).

Write about THIS company and THIS filing only. Do not reuse another company's story, brands, or segments.

You may use the pre-computed findings below. If a findings block is absent, do not invent it. Do not invent numbers, targets, ratings, FY years, or peer medians.

## COMPANY CONTEXT
- Company: {name}
- Industry: {industry or "not stated"}
- Actual years in this filing: {ctx.years_available}
- Quarterly figures: {"present" if ctx.has_quarterly else "not present"}
- Balance sheet figures: {"present" if ctx.has_balance_sheet else "not present"}

## FINDINGS FROM THIS FILING
"""

        if ctx.cross_metric_brief or ctx.margin_observations:
            prompt += "\n### Cross-metric\n"
            if ctx.cross_metric_brief:
                prompt += ctx.cross_metric_brief.strip() + "\n"
            for obs in ctx.margin_observations[:5]:
                prompt += f"- {obs}\n"
        else:
            prompt += "\n### Cross-metric\nNone computed from this filing.\n"

        if ctx.earnings_quality_score:
            prompt += (
                "\n### Earnings quality\n"
                f"Score: {ctx.earnings_quality_score}\n"
                f"{(ctx.earnings_quality_narrative or '').strip()}\n"
            )
            for flag in ctx.earnings_quality_flags[:3]:
                prompt += f"- {flag}\n"
        else:
            prompt += "\n### Earnings quality\nNot scored — too little verified source.\n"

        if ctx.scenario_brief:
            prompt += (
                "\n### Source target / scenarios\n"
                f"{ctx.scenario_brief.strip()}\n"
                "Discuss only this source target. Do not invent bull/bear spreads.\n"
            )
        else:
            prompt += (
                "\n### Source target / scenarios\n"
                "No target printed in this filing. Do not invent CMP, target, or rating.\n"
            )

        if ctx.mgmt_reality_assessment:
            prompt += (
                "\n### Management vs reported actuals\n"
                f"{ctx.mgmt_reality_assessment.strip()}\n"
            )
            for gap in ctx.mgmt_reality_gaps[:3]:
                prompt += f"- {gap}\n"
        else:
            prompt += (
                "\n### Management vs reported actuals\n"
                "No comparable guidance vs actuals. Do not invent a consistency verdict.\n"
            )

        prompt += """
## OUTPUT — exactly four labelled sections, this order, no markdown headings

BUSINESS_DESCRIPTION
2-3 sentences on what this company does, tied to this filing. No financial numbers. No other company's products.

KEY_HIGHLIGHTS
Up to 6 bullets starting with •. Each bullet is one insight from the findings or evidence cues. If fewer insights exist, write fewer bullets. Do not pad. Do not invent percentages.

REPORT_SUBTITLE
One line, max 15 words: this company's driver; this company's constraint. No generic slogans.

OUTLOOK_VALUATION
2-3 short paragraphs on trajectory and risks from THIS filing.
If a source target was provided above, you may refer to it qualitatively.
If none was provided, end with a Not Rated stance and do not invent a target.
Do not write FY26E/FY27E unless those years appear in the findings or cues.

## WRITING RULES
- Analyst voice, this company only.
- Do not restate raw tables. Explain what the findings mean.
- Do not invent numbers. Python supplies figures separately.
- Missing stays missing. Never fill with "strong performance" or "well positioned".
"""
        return prompt

    @staticmethod
    def build_user_prompt(
        context: AnalyticalContext,
        company_name: str,
        report_period: str,
        evidence_cues: str,
    ) -> str:
        ctx = context or AnalyticalContext()
        period = report_period or "this reporting period"
        return (
            f"Company: {company_name or 'Unknown'}\n"
            f"Report period: {period}\n"
            f"Sector: {ctx.sector or 'not stated'}\n\n"
            f"Evidence cues from verified data:\n"
            f"{(evidence_cues or 'None.').strip()}\n\n"
            "Write the four sections now. Use only findings and cues above."
        )
