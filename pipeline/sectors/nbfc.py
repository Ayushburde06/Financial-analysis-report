"""NBFC / Microfinance sector configuration."""
from dataclasses import dataclass, field
from typing import List
from .base import SectorConfig


@dataclass
class NBFCConfig(SectorConfig):
    sector_name: str = "NBFC"
    sector_aliases: List[str] = field(default_factory=lambda: ["nbfc", "microfinance", "housing finance", "mfi"])

    revenue_keys: List[str] = field(default_factory=lambda: ["nii", "net_interest_income", "aum", "total_income"])
    ebitda_keys:  List[str] = field(default_factory=lambda: ["ppop", "operating_profit", "ebitda"])
    pat_keys:     List[str] = field(default_factory=lambda: ["pat", "net_profit"])

    extra_metrics: List[tuple] = field(default_factory=lambda: [
        ("AUM (₹ Cr)",             "aum"),
        ("Disbursements (₹ Cr)",   "disbursements"),
        ("GNPA (%)",               "gnpa"),
        ("NNPA (%)",               "nnpa"),
        ("PCR (%)",                "pcr"),
        ("Yield on Advances (%)",  "yield_on_advances"),
        ("Cost of Funds (%)",      "cost_of_funds"),
        ("Capital Adequacy (%)",   "capital_adequacy"),
        ("ROE (%)",                "roe"),
        ("ROA (%)",                "roa"),
    ])

    pl_label:        str = "NII / AUM (₹ Cr)"
    ebitda_label:    str = "Operating Profit"
    pat_label:       str = "PAT"
    chart_title:     str = "AUM & PAT Trend"
    revenue_chart_label: str = "AUM"
    margin_chart_title:  str = "Asset Quality (%)"

    extraction_keys: str = (
        "aum, disbursements, gnpa, nnpa, pcr, roe, roa, "
        "pat, eps, net_interest_income, cost_of_funds, yield_on_advances, "
        "capital_adequacy, total_assets"
    )
    extraction_hints: str = (
        "Look for: AUM (Assets Under Management), Disbursements, "
        "GNPA%, NNPA%, PCR%, Yield on Advances, Cost of Funds, "
        "Capital Adequacy, PAT, EPS, ROE%, ROA%."
    )
