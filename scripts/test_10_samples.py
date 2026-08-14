"""
test_10_samples.py — Generate 10 diverse synthetic financial PDF samples
and run the full pipeline on each to test the adaptive report generation.

Creates samples covering:
  1. Reliance Industries (conglomerate - 6 years FY20-FY25 + segments)
  2. TCS (IT services - 4 years FY22-FY25)
  3. HDFC Bank (banking - 4 years + NIM/GNPA)
  4. Sun Pharma (pharmaceuticals - 5 years FY21-FY25)
  5. Tata Motors (automotive - 4 years + segment revenue)
  6. Bajaj Finance (NBFC - 4 years + AUM)
  7. Adani Ports (infrastructure - 3 years FY23-FY25)
  8. Infosys (IT services - 6 years FY20-FY25)
  9. Maruti Suzuki (automotive - 4 years + volumes)
  10. Bharti Airtel (telecom - 5 years FY21-FY25 + ARPU)

Each sample has different year ranges, metrics, and data completeness
to test the adaptive schema's ability to handle any source file.
"""
import os
import sys
import asyncio
import time
import json
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY


# ─── Sample Data Definitions ────────────────────────────────────────────────

SAMPLES = [
    {
        "name": "Reliance Industries",
        "sector": "Conglomerate",
        "period": "Q2FY26",
        "years": ["FY20", "FY21", "FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": {"Oil to Chemicals": 345678, "Jio Digital": 123456, "Retail": 78901, "Others": 12345},
        "data": {
            "revenue":      [656341, 486345, 712675, 876543, 898123, 1021456],
            "ebitda":       [98765, 81234, 125456, 156789, 178234, 201234],
            "pat":          [32456, 49128, 60705, 73321, 79265, 89542],
            "eps":          [52.3, 78.9, 96.5, 108.7, 116.8, 132.1],
        },
        "qtr_data": {
            "revenue":  [234567, 256789, 245678, 267890],
            "ebitda":   [45678, 48123, 46789, 50123],
            "pat":      [15678, 16890, 15987, 17234],
            "eps":      [24.5, 26.3, 25.1, 27.0],
        },
        "market_data": {"cmp": 2956.5, "target": 3200, "market_cap": 1998765, "52w_high": 3024, "52w_low": 2220, "beta": 1.2},
        "recommendation": "BUY",
    },
    {
        "name": "TCS",
        "sector": "IT Services",
        "period": "Q2FY26",
        "years": ["FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [191754, 225458, 240893, 251620],
            "ebitda":       [50456, 58234, 62156, 64890],
            "pat":          [38327, 42147, 45968, 48234],
            "eps":          [103.6, 114.1, 125.2, 131.8],
        },
        "qtr_data": {
            "revenue":  [59661, 61589, 62473, 63890],
            "ebitda":   [15890, 16234, 16567, 16890],
            "pat":      [12089, 12456, 12789, 13123],
            "eps":      [33.1, 34.0, 34.8, 35.8],
        },
        "market_data": {"cmp": 4156.7, "target": 4500, "market_cap": 1509876, "52w_high": 4592, "52w_low": 3625, "beta": 0.85},
        "recommendation": "BUY",
    },
    {
        "name": "HDFC Bank",
        "sector": "Banking",
        "period": "Q2FY26",
        "years": ["FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [113654, 168453, 203421, 234567],
            "ebitda":       None,
            "pat":          [36568, 48234, 62345, 73156],
            "eps":          [19.7, 25.8, 33.1, 38.5],
        },
        "qtr_data": {
            "revenue":  [56789, 61234, 64567, 67890],
            "pat":      [17234, 18956, 19567, 20123],
            "eps":      [9.1, 9.9, 10.3, 10.6],
        },
        "market_data": {"cmp": 1734.2, "target": 1950, "market_cap": 1314567, "52w_high": 1889, "52w_low": 1456, "beta": 1.1},
        "recommendation": "BUY",
        "banking_specific": {"nim": [3.8, 4.1, 4.2, 4.3], "gnpa": [1.47, 1.26, 1.17, 1.03], "gnpa_qtr": [1.02, 0.98, 0.95, 0.92]},
    },
    {
        "name": "Sun Pharma",
        "sector": "Pharmaceuticals",
        "period": "Q2FY26",
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [33456, 38123, 42678, 47123, 52345],
            "ebitda":       [8234, 9456, 10678, 11890, 13456],
            "pat":          [2890, 3456, 4123, 4987, 5789],
            "eps":          [12.1, 14.5, 17.3, 20.8, 24.2],
        },
        "qtr_data": {
            "revenue":  [12345, 12890, 13456, 13987],
            "ebitda":   [3123, 3345, 3567, 3789],
            "pat":      [1345, 1456, 1567, 1678],
            "eps":      [5.6, 6.1, 6.5, 7.0],
        },
        "market_data": {"cmp": 1789.4, "target": 2000, "market_cap": 429876, "52w_high": 1872, "52w_low": 1234, "beta": 0.72},
        "recommendation": "BUY",
    },
    {
        "name": "Tata Motors",
        "sector": "Automotive",
        "period": "Q2FY26",
        "years": ["FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": {"CV": 45678, "PV": 32145, "JLR": 71234, "EV": 5678},
        "data": {
            "revenue":      [278934, 345678, 412345, 437890],
            "ebitda":       [23456, 31234, 45678, 52345],
            "pat":          [-11456, -2345, 15678, 23456],
            "eps":          [-30.2, -6.2, 41.7, 62.5],
        },
        "qtr_data": {
            "revenue":  [102345, 108456, 112678, 115234],
            "ebitda":   [12345, 13456, 14567, 15678],
            "pat":      [5678, 6234, 6789, 7234],
            "eps":      [15.1, 16.6, 18.1, 19.3],
        },
        "market_data": {"cmp": 987.6, "target": 1100, "market_cap": 364567, "52w_high": 1179, "52w_low": 678, "beta": 1.65},
        "recommendation": "BUY",
    },
    {
        "name": "Bajaj Finance",
        "sector": "NBFC",
        "period": "Q2FY26",
        "years": ["FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [27834, 35678, 45123, 52345],
            "ebitda":       None,
            "pat":          [6734, 8234, 11234, 14567],
            "eps":          [41.1, 50.2, 68.4, 89.0],
        },
        "qtr_data": {
            "revenue":  [12890, 13456, 14567, 15234],
            "pat":      [3456, 3678, 3987, 4234],
            "eps":      [21.1, 22.5, 24.4, 25.9],
        },
        "market_data": {"cmp": 7234.5, "target": 8000, "market_cap": 445678, "52w_high": 7830, "52w_low": 6789, "beta": 1.35},
        "recommendation": "HOLD",
        "nbfc_specific": {"aum": [181234, 234567, 312345, 378901]},
    },
    {
        "name": "Adani Ports",
        "sector": "Infrastructure",
        "period": "Q2FY26",
        "years": ["FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [18923, 23456, 27890],
            "ebitda":       [9876, 12345, 15678],
            "pat":          [4567, 5234, 6789],
            "eps":          [22.1, 25.4, 32.9],
        },
        "qtr_data": {
            "revenue":  [6789, 7234, 7456, 7890],
            "ebitda":   [3789, 4012, 4234, 4456],
            "pat":      [1678, 1789, 1912, 2045],
            "eps":      [8.1, 8.7, 9.3, 9.9],
        },
        "market_data": {"cmp": 1345.6, "target": 1500, "market_cap": 291234, "52w_high": 1456, "52w_low": 987, "beta": 1.45},
        "recommendation": "BUY",
    },
    {
        "name": "Infosys",
        "sector": "IT Services",
        "period": "Q2FY26",
        "years": ["FY20", "FY21", "FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": {"Digital": 34567, "Core": 8765, "Others": 1234},
        "data": {
            "revenue":      [95128, 107356, 124567, 153456, 167890, 175678],
            "ebitda":       [23456, 28123, 32456, 38123, 41456, 43890],
            "pat":          [17456, 20890, 22987, 27890, 30123, 31890],
            "eps":          [40.5, 48.2, 53.4, 64.8, 70.1, 74.2],
        },
        "qtr_data": {
            "revenue":  [41234, 42789, 43678, 44123],
            "ebitda":   [10234, 10678, 10987, 11234],
            "pat":      [7456, 7678, 7890, 8012],
            "eps":      [17.3, 17.8, 18.3, 18.6],
        },
        "market_data": {"cmp": 1867.3, "target": 2100, "market_cap": 776543, "52w_high": 1989, "52w_low": 1456, "beta": 0.95},
        "recommendation": "BUY",
    },
    {
        "name": "Maruti Suzuki",
        "sector": "Automotive",
        "period": "Q2FY26",
        "years": ["FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": None,
        "data": {
            "revenue":      [78345, 98967, 123456, 145678],
            "ebitda":       [6789, 9234, 14567, 18923],
            "pat":          [3456, 5890, 9678, 12345],
            "eps":          [109.3, 186.2, 306.5, 390.8],
        },
        "qtr_data": {
            "revenue":  [34123, 36234, 37890, 39456],
            "ebitda":   [4567, 4890, 5234, 5567],
            "pat":      [3012, 3234, 3456, 3678],
            "eps":      [95.3, 102.4, 109.4, 116.4],
        },
        "market_data": {"cmp": 13456.7, "target": 14500, "market_cap": 422567, "52w_high": 13689, "52w_low": 10678, "beta": 0.78},
        "recommendation": "HOLD",
    },
    {
        "name": "Bharti Airtel",
        "sector": "Telecom",
        "period": "Q2FY26",
        "years": ["FY21", "FY22", "FY23", "FY24", "FY25"],
        "quarters": ["Q1FY25", "Q2FY25", "Q1FY26", "Q2FY26"],
        "segments": {"India Mobile": 45678, "Africa": 32145, "Enterprise": 8234, "Others": 2345},
        "data": {
            "revenue":      [96534, 112678, 139456, 152345, 167890],
            "ebitda":       [44567, 52345, 67890, 75678, 83456],
            "pat":          [8234, 9876, 12345, 15678, 18923],
            "eps":          [14.5, 17.3, 21.7, 27.6, 33.4],
        },
        "qtr_data": {
            "revenue":  [40123, 42345, 43678, 44567],
            "ebitda":   [20123, 21234, 21987, 22456],
            "pat":      [4890, 5123, 5345, 5567],
            "eps":      [8.6, 9.0, 9.4, 9.8],
        },
        "market_data": {"cmp": 1678.9, "target": 1850, "market_cap": 987654, "52w_high": 1789, "52w_low": 1234, "beta": 0.88},
        "recommendation": "BUY",
    },
]


# ─── PDF Generation ──────────────────────────────────────────────────────────

def generate_sample_pdf(sample: dict, output_path: str):
    """Generate a synthetic financial report PDF for a sample company."""
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=1.5*cm, leftMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='ReportTitle', parent=styles['Title'],
        fontSize=16, textColor=colors.HexColor('#1f5aa6'), spaceAfter=10
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader', parent=styles['Heading2'],
        fontSize=12, textColor=colors.HexColor('#1f5aa6'), spaceBefore=10, spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name='SmallText', parent=styles['Normal'],
        fontSize=8, alignment=TA_JUSTIFY, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        name='TableCell', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        name='TableHeader', parent=styles['Normal'],
        fontSize=8, alignment=TA_CENTER, textColor=colors.white
    ))

    story = []
    s = sample

    # Title
    story.append(Paragraph(f"{s['name']} — {s['period']} Earnings", styles['ReportTitle']))
    story.append(Paragraph(f"Sector: {s['sector']} | Period: {s['period']}", styles['SmallText']))
    story.append(Spacer(1, 10))

    # Business Overview
    story.append(Paragraph("Business Overview", styles['SectionHeader']))
    story.append(Paragraph(
        f"{s['name']} is a leading company in the {s['sector']} sector. "
        f"The company reported strong financial performance in {s['period']} "
        f"with revenue growth driven by operational efficiency and market expansion. "
        f"Management remains optimistic about future growth prospects.",
        styles['SmallText']
    ))
    story.append(Spacer(1, 8))

    # Key Highlights
    story.append(Paragraph("Key Highlights", styles['SectionHeader']))
    highlights = [
        f"Revenue for {s['period']} stood at Rs. {s['qtr_data']['revenue'][-1]:,} cr, up from Rs. {s['qtr_data']['revenue'][-2]:,} cr in the previous quarter.",
        f"PAT for {s['period']} was Rs. {s['qtr_data']['pat'][-1]:,} cr, showing improvement in profitability.",
        f"EPS for the quarter was Rs. {s['qtr_data']['eps'][-1]:.1f}.",
        f"Full year FY25 revenue was Rs. {s['data']['revenue'][-1]:,} cr.",
        f"Full year FY25 PAT was Rs. {s['data']['pat'][-1]:,} cr.",
    ]
    for h in highlights:
        story.append(Paragraph(f"• {h}", styles['SmallText']))
    story.append(Spacer(1, 8))

    # Quarterly Financials
    story.append(Paragraph("Quarterly Financials (Rs. cr)", styles['SectionHeader']))
    qtr_cols = ["Metric"] + s['quarters']
    qtr_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pat", "PAT"), ("eps", "EPS (Rs.)")]:
        vals = s['qtr_data'].get(metric)
        if vals:
            row = [label] + [f"{v:,.1f}" if isinstance(v, float) else f"{v:,}" for v in vals]
            qtr_rows.append(row)
    qtr_data = [qtr_cols] + qtr_rows
    qtr_table = Table(qtr_data, colWidths=[3.5*cm] + [3.2*cm]*len(s['quarters']))
    qtr_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f5aa6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f2f4f8')]),
    ]))
    story.append(qtr_table)
    story.append(Spacer(1, 10))

    # Annual Financials
    story.append(Paragraph("Annual Financials (Rs. cr)", styles['SectionHeader']))
    ann_cols = ["Metric"] + s['years']
    ann_rows = []
    for metric, label in [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("pat", "PAT"), ("eps", "EPS (Rs.)")]:
        vals = s['data'].get(metric)
        if vals:
            row = [label] + [f"{v:,.1f}" if isinstance(v, float) else f"{v:,}" for v in vals]
            ann_rows.append(row)
    ann_data = [ann_cols] + ann_rows
    ann_table = Table(ann_data, colWidths=[3.5*cm] + [2.5*cm]*len(s['years']))
    ann_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f5aa6')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f2f4f8')]),
    ]))
    story.append(ann_table)
    story.append(Spacer(1, 10))

    # Segment Breakdown (if available)
    if s['segments']:
        story.append(Paragraph("Segment Revenue Breakdown (Rs. cr)", styles['SectionHeader']))
        seg_cols = ["Segment", "Revenue", "% of Total"]
        total = sum(s['segments'].values())
        seg_rows = [[seg, f"{val:,}", f"{val/total*100:.1f}%"] for seg, val in s['segments'].items()]
        seg_data = [seg_cols] + seg_rows
        seg_table = Table(seg_data, colWidths=[5*cm, 4*cm, 3*cm])
        seg_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f5aa6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(seg_table)
        story.append(Spacer(1, 10))

    # Banking-specific metrics (if available)
    if s.get("banking_specific"):
        story.append(Paragraph("Asset Quality Metrics", styles['SectionHeader']))
        bk = s['banking_specific']
        bk_cols = ["Metric"] + s['years']
        bk_rows = [["NIM (%)"] + [f"{v:.2f}" for v in bk['nim']],
                    ["GNPA (%)"] + [f"{v:.2f}" for v in bk['gnpa']]]
        bk_data = [bk_cols] + bk_rows
        bk_table = Table(bk_data, colWidths=[3.5*cm] + [2.5*cm]*len(s['years']))
        bk_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f5aa6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(bk_table)
        story.append(Spacer(1, 10))

    # NBFC-specific metrics (if available)
    if s.get("nbfc_specific"):
        story.append(Paragraph("AUM Growth (Rs. cr)", styles['SectionHeader']))
        nbfc = s['nbfc_specific']
        nbfc_cols = ["Metric"] + s['years']
        nbfc_rows = [["AUM"] + [f"{v:,}" for v in nbfc['aum']]]
        nbfc_data = [nbfc_cols] + nbfc_rows
        nbfc_table = Table(nbfc_data, colWidths=[3.5*cm] + [2.5*cm]*len(s['years']))
        nbfc_table.setStyle(TableStyle([
            ('BACKGROUND', (
                0, 0), (-1, 0), colors.HexColor('#1f5aa6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))
        story.append(nbfc_table)
        story.append(Spacer(1, 10))

    doc.build(story)