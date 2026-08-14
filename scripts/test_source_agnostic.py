"""Offline regression checks for source- and sector-driven behavior.

These checks intentionally use companies and metrics that are not part of the
four sample PDFs. They do not call the external OCR/LLM services.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.csv_txt_handler import parse_csv
from pipeline.sectors import get_sector_config

generate_all_charts = importlib.import_module(
    "pipeline.11_chart_generator"
).generate_all_charts


def main() -> None:
    csv_text = """Metric,Q2FY25,Q1FY26,Q2FY26
NII,200.48,216.35,215.29
PBT,154.90,169.31,163.84
PAT,117.46,127.68,123.59
EPS,66.2,71.6,69.2
NIM,4.27,4.34,4.30
GNPA,1.97,1.67,1.58
"""
    parsed = parse_csv(csv_text)
    assert parsed["pbt"]["q_current"] == 163.84
    assert parsed["nii"]["q_current"] == 215.29

    banking = get_sector_config("Banking")
    energy = get_sector_config("Energy")
    assert banking.pl_label.startswith("NII")
    assert banking.revenue_chart_label == "NII"
    assert energy.pl_label.startswith("Revenue")

    banking_charts = generate_all_charts(
        annual_data={
            "revenue": {"FY25": 811.65},
            "revenue_est": {"FY26E": 872.0},
            "pat": {"FY25": 472.27},
            "pat_est": {"FY26E": 496.0},
            "eps": {"FY25": 67.0},
            "ebitda": {},
        },
        quarterly_data={
            "quarters": ["Q2FY25", "Q1FY26", "Q2FY26"],
            "revenue": {"Q2FY25": 200.48, "Q1FY26": 216.35, "Q2FY26": 215.29},
            "pat": {"Q2FY25": 117.46, "Q1FY26": 127.68, "Q2FY26": 123.59},
            "nim": {"Q2FY25": 4.27, "Q1FY26": 4.34, "Q2FY26": 4.30},
            "gnpa": {"Q2FY25": 1.97, "Q1FY26": 1.67, "Q2FY26": 1.58},
        },
        sector_cfg=banking,
    )
    assert "chart_asset_quality" in banking_charts
    assert "chart_margin" not in banking_charts

    energy_charts = generate_all_charts(
        annual_data={
            "revenue": {"FY25": 1000.0, "FY24": 900.0},
            "revenue_est": {},
            "pat": {"FY25": 100.0, "FY24": 80.0},
            "pat_est": {},
            "eps": {},
            "ebitda": {"FY25": 200.0, "FY24": 160.0},
        },
        quarterly_data={
            "quarters": ["Q1FY26", "Q2FY26"],
            "revenue": {"Q1FY26": 500.0, "Q2FY26": 550.0},
            "pat": {"Q1FY26": 50.0, "Q2FY26": 60.0},
        },
        sector_cfg=energy,
    )
    assert "chart_margin" in energy_charts

    print("PASS: unseen-sector configuration and CSV/chart paths are source-driven")


if __name__ == "__main__":
    main()
