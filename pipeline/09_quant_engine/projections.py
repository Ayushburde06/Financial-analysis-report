"""
projections.py - Forward Estimates (FY26E, FY27E)

KEY CHANGE: Projections are ONLY used for chart trend lines and the
estimates table — they are marked is_estimate=True and NEVER injected
into the evidence packet that Stage 11 (DeepSeek) uses for narrative.

This prevents computed projections (125139, 131395 etc.) from appearing
as absolute numbers in the narrative and failing Stage 12b fact-check,
since those values don't exist in the source document.

Rules:
  - Only project when FY25 actual is available (real data exists)
  - Never project from run-rate alone (q_current * 4) — too speculative
  - Cap growth rate at ±30% to prevent wild extrapolations
  - Always set is_estimate=True so verifier ignores them
"""
from .evidence_packets import FinancialLineItem, VerifiedNumber

class ForwardProjector:

    MAX_GROWTH_RATE = 0.30   # cap at ±30% to prevent wild projections
    MIN_GROWTH_RATE = -0.30

    @staticmethod
    def project_next_two_years(
        metric_name: str,
        line_item: FinancialLineItem,
        guidance: str = None
    ) -> FinancialLineItem:
        """
        Calculates FY26E and FY27E ONLY when FY25 annual actual is available.
        Projections are flagged is_estimate=True — excluded from narrative verification.

        Priority:
          1. Explicit analyst guidance (if provided as string)
          2. Historical trend from FY24→FY25
          3. Conservative 5% default
          NO run-rate fallback (q_current * 4) — too unreliable
        """
        fy25_val = line_item.fy25.value
        fy24_val = line_item.fy24.value

        # Only project if we have a real FY25 annual actual
        if fy25_val in ("[N/A]", None) or not isinstance(fy25_val, (int, float)):
            # No annual data — don't guess estimates
            line_item.fy26e = VerifiedNumber(value="[N/A]", is_estimate=True)
            line_item.fy27e = VerifiedNumber(value="[N/A]", is_estimate=True)
            return line_item

        base_val    = float(fy25_val)
        growth_rate = 0.05   # conservative default

        # 1. Compute from FY24→FY25 history
        if fy24_val not in ("[N/A]", None) and isinstance(fy24_val, (int, float)) and float(fy24_val) != 0:
            raw_growth = (base_val - float(fy24_val)) / abs(float(fy24_val))
            # Cap to prevent runaway projections
            growth_rate = max(
                ForwardProjector.MIN_GROWTH_RATE,
                min(ForwardProjector.MAX_GROWTH_RATE, raw_growth)
            )

        # 2. Guidance overrides
        if guidance:
            import re
            matches = re.findall(r'(\d+(?:\.\d+)?)\s*%', guidance)
            if matches:
                g = float(matches[0]) / 100.0
                growth_rate = max(ForwardProjector.MIN_GROWTH_RATE,
                                  min(ForwardProjector.MAX_GROWTH_RATE, g))

        fy26e_val = round(base_val * (1 + growth_rate), 2)
        fy27e_val = round(fy26e_val * (1 + growth_rate), 2)

        line_item.fy26e = VerifiedNumber(value=fy26e_val, is_estimate=True)
        line_item.fy27e = VerifiedNumber(value=fy27e_val, is_estimate=True)

        return line_item
