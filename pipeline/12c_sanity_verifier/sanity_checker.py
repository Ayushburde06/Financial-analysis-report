"""
Stage 12c: Sanity Verifier — Computed-Value Fact-Checker

What it does:
  Stage 12b verifies *extracted* numbers against the OCR source text.
  Stage 12c verifies *computed* values (ratios, growth rates, margins) for
  sanity — catching absurd results like ROE = 3829% or D/E = 1854x that arise
  from unit mismatches between Screener (crores) and extraction (billions).

How it works:
  1. Receive the ROM dict (after all ratio/growth computation).
  2. For each computed ratio/margin/growth, check against sensible ranges:
       - ROE:        0% – 60%      (banks ~12-18%, best-in-class ~25%)
       - ROA:        0% – 30%
       - Net margin:  0% – 60%
       - EBITDA margin: 0% – 80%
       - D/E:        0x – 15x      (banks can be higher, up to 20x)
       - Revenue growth: -100% – +500%
       - PAT growth:   -100% – +1000%
  3. If a value is outside the sensible range:
       - Flag it in the sanity report
       - Attempt to fix: nullify the value (set to "—") so the report
         shows a blank rather than a wrong number
  4. Return a SanityReport with pass/fail and list of corrections.
  5. The pipeline logs the report and only generates the PDF if the gate passes
     (or after all fixable issues are fixed).

No LLM used — pure Python. Free, instant, deterministic.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ── Configuration ──────────────────────────────────────────────────────────────

# Sensible ranges for computed values: (min, max)
SANITY_RANGES = {
    "roe":            (0,    60),    # %
    "roa":            (0,    30),    # %
    "net_margin":     (-20,  60),    # % (can be negative for loss-making)
    "ebitda_margin":  (-10,  80),    # %
    "de":             (0,    15),    # x (banks can be higher)
    "rev_growth":     (-100, 500),   # %
    "pat_growth":     (-100, 1000),  # % (turnaround can be huge)
}

# Bank sectors have higher D/E (leveraged by nature)
BANK_SECTORS = {"Banking", "Bank", "Financial Services", "NBFC", "Insurance"}
BANK_DE_MAX = 25


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class SanityCheck:
    field_path:   str
    value:        Any
    sensible:     bool
    reason:       str
    corrected_to: Optional[Any] = None


@dataclass
class SanityReport:
    total:        int   = 0
    sensible:     int   = 0
    absurd:       int   = 0
    corrections:  List[SanityCheck] = field(default_factory=list)
    passed:       bool  = True
    summary:      str   = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total":       self.total,
            "sensible":    self.sensible,
            "absurd":      self.absurd,
            "passed":      self.passed,
            "summary":     self.summary,
            "corrections": [
                {
                    "field":       c.field_path,
                    "value":       c.value,
                    "sensible":    c.sensible,
                    "reason":      c.reason,
                    "corrected_to": c.corrected_to,
                }
                for c in self.corrections
            ],
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_number(v: Any) -> bool:
    if v is None or v == "—" or v == "":
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _to_float(v: Any) -> Optional[float]:
    if not _is_number(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _check_range(value: float, vmin: float, vmax: float, field_path: str,
                 sector: str = "") -> Tuple[bool, str]:
    """Check if value is within sensible range. Returns (sensible, reason)."""
    # Special handling for D/E in bank sectors
    if field_path.endswith(".de") or field_path == "de":
        if sector in BANK_SECTORS:
            vmax = BANK_DE_MAX

    if value < vmin:
        return False, f"{value} below sensible minimum {vmin}"
    if value > vmax:
        return False, f"{value} above sensible maximum {vmax}"
    return True, ""


# ── Main verifier ──────────────────────────────────────────────────────────────

class SanityVerifier:
    """
    Stage 12c: Sanity Verifier for computed values.

    Usage:
        report = SanityVerifier.verify(rom_dict, sector="Banking")
        if not report.passed:
            rom_dict = SanityVerifier.apply_corrections(rom_dict, report)
    """

    @staticmethod
    def verify(rom: Dict[str, Any], sector: str = "Other") -> SanityReport:
        """
        Verify all computed ratios/margins/growth in the ROM for sanity.

        Args:
            rom:    The report object model dict (after all computation)
            sector: The detected sector string (for bank-specific ranges)

        Returns:
            SanityReport with pass/fail and list of corrections needed.
        """
        print("     [Sanity Verifier] Stage 12c — Checking computed values for sanity...")

        report = SanityReport()
        checks: List[SanityCheck] = []

        # Check annual ratios
        ratios = rom.get("ratios", {})
        ratio_keys_to_check = ["roe", "roa", "net_margin", "ebitda_margin", "de"]

        for ratio_key in ratio_keys_to_check:
            ratio_dict = ratios.get(ratio_key, {})
            if not isinstance(ratio_dict, dict):
                # Some ratios might be scalar (single value)
                if _is_number(ratio_dict):
                    val = _to_float(ratio_dict)
                    if val is not None:
                        vmin, vmax = SANITY_RANGES.get(ratio_key, (None, None))
                        if vmin is not None:
                            sensible, reason = _check_range(
                                val, vmin, vmax, ratio_key, sector
                            )
                            checks.append(SanityCheck(
                                field_path=f"ratios.{ratio_key}",
                                value=val, sensible=sensible,
                                reason=reason if not sensible else "",
                            ))
                continue

            for year, val in ratio_dict.items():
                if not _is_number(val):
                    continue
                fval = _to_float(val)
                if fval is None:
                    continue
                vmin, vmax = SANITY_RANGES.get(ratio_key, (None, None))
                if vmin is None:
                    continue
                sensible, reason = _check_range(
                    fval, vmin, vmax, f"ratios.{ratio_key}.{year}", sector
                )
                checks.append(SanityCheck(
                    field_path=f"ratios.{ratio_key}.{year}",
                    value=fval, sensible=sensible,
                    reason=reason if not sensible else "",
                ))

        # Check growth rates
        for growth_key in ["rev_growth", "pat_growth"]:
            growth_dict = rom.get(growth_key, {})
            if not isinstance(growth_dict, dict):
                continue
            vmin, vmax = SANITY_RANGES.get(growth_key, (None, None))
            if vmin is None:
                continue
            for year, val in growth_dict.items():
                if not _is_number(val):
                    continue
                fval = _to_float(val)
                if fval is None:
                    continue
                sensible, reason = _check_range(
                    fval, vmin, vmax, f"{growth_key}.{year}", sector
                )
                checks.append(SanityCheck(
                    field_path=f"{growth_key}.{year}",
                    value=fval, sensible=sensible,
                    reason=reason if not sensible else "",
                ))

        # Tally
        report.total = len(checks)
        report.sensible = sum(1 for c in checks if c.sensible)
        report.absurd = sum(1 for c in checks if not c.sensible)
        report.corrections = checks
        report.passed = report.absurd == 0

        # Build summary
        if report.absurd == 0:
            report.summary = (
                f"✅ All {report.total} computed values are within sensible ranges. "
                f"Report is safe to generate."
            )
        else:
            absurd_fields = [c.field_path for c in checks if not c.sensible][:5]
            report.summary = (
                f"⚠️ {report.absurd}/{report.total} computed values are outside "
                f"sensible ranges: {', '.join(absurd_fields)}"
            )
            if report.absurd > 5:
                report.summary += f" (+{report.absurd - 5} more)"
            report.summary += ". Applying corrections (nullifying absurd values)."

        # Log
        print(f"     [Sanity Verifier] {report.sensible}/{report.total} values sensible, "
              f"{report.absurd} absurd.")
        for c in checks:
            if c.sensible:
                pass  # don't spam logs for good values
            else:
                print(f"     [Sanity Verifier]   ⚠️  {c.field_path} = {c.value} — {c.reason}")

        if report.passed:
            print(f"     [Sanity Verifier] ✅ All computed values pass sanity check.")
        else:
            print(f"     [Sanity Verifier] ⚠️  {report.absurd} absurd value(s) found — "
                  f"will be corrected.")

        return report

    @staticmethod
    def apply_corrections(rom: Dict[str, Any], report: SanityReport) -> Dict[str, Any]:
        """
        Apply corrections to the ROM: nullify absurd computed values.

        Args:
            rom:    The report object model dict
            report: SanityReport from verify()

        Returns:
            Corrected ROM dict (absurd values set to "—")
        """
        if report.passed:
            return rom

        print(f"     [Sanity Verifier] Applying {report.absurd} correction(s)...")

        for check in report.corrections:
            if check.sensible:
                continue

            # Parse field path: e.g. "ratios.roe.FY25" or "rev_growth.FY24"
            parts = check.field_path.split(".")

            if parts[0] == "ratios" and len(parts) == 3:
                ratio_key = parts[1]
                year = parts[2]
                ratio_dict = rom.get("ratios", {}).get(ratio_key)
                if isinstance(ratio_dict, dict) and year in ratio_dict:
                    old_val = ratio_dict[year]
                    ratio_dict[year] = "—"
                    print(f"     [Sanity Verifier]   📝 {check.field_path}: "
                          f"{old_val} → —")
            elif parts[0] in ("rev_growth", "pat_growth") and len(parts) == 2:
                growth_key = parts[0]
                year = parts[1]
                growth_dict = rom.get(growth_key, {})
                if isinstance(growth_dict, dict) and year in growth_dict:
                    old_val = growth_dict[year]
                    growth_dict[year] = "—"
                    print(f"     [Sanity Verifier]   📝 {check.field_path}: "
                          f"{old_val} → —")

        print(f"     [Sanity Verifier] ✅ Corrections applied. "
              f"Absurd values replaced with —.")
        return rom
