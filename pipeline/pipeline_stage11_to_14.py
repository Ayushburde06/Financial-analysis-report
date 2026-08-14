"""
pipeline_stage11_to_14.py
Encapsulates Stages 11-14: Analyst → Narrative Parsing → Chart Generation → ROM Building.
Called from main.py to keep the endpoint function clean.
"""
import importlib, re, os
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

# Source-document extraction is the sole factual input for this stage.


def _qval(line_item, period, default="—"):
    try:
        if line_item is None:
            return default
        # Try fixed field first (fy22, fy23, q_current, etc.)
        v = getattr(line_item, period, None)
        # If not found in fixed fields, check the dynamic annual dict
        if v is None and hasattr(line_item, "annual") and line_item.annual:
            v = line_item.annual.get(period)
        if hasattr(v, "value"):
            v = v.value
        if v is None or str(v).strip() in ("[N/A]", "None", ""):
            return default
        return round(float(v), 2)
    except Exception:
        return default



def _growth(curr, prev, default="—"):
    try:
        if curr == default or prev == default or prev == 0:
            return default
        return round(((float(curr) - float(prev)) / abs(float(prev))) * 100, 1)
    except Exception:
        return default


def _to_float(val):
    if val in (None, "—", "", "None"):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fy_year_num(label: str) -> int:
    nums = re.findall(r"\d+", str(label or ""))
    if not nums:
        return 0
    n = int(nums[0])
    return n % 100 if n > 100 else n


def _is_estimate_year(label: str) -> bool:
    s = str(label or "").strip().upper().replace(" ", "")
    return bool(re.match(r"^FY\d{2,4}E$", s))


def _is_actual_year(label: str) -> bool:
    s = str(label or "").strip().upper().replace(" ", "")
    return bool(re.match(r"^FY\d{2,4}A?$", s)) and not s.endswith("E")


def _period_attr(label: str) -> str:
    return str(label or "").strip().lower().replace(" ", "")


def _display_fy(key: str) -> str:
    s = str(key or "").strip().upper().replace(" ", "")
    if s and not s.startswith("FY") and re.match(r"^\d{2,4}[AE]?$", s):
        s = f"FY{s}"
    return s


def _latest_actual_label(year_map) -> Optional[str]:
    actuals = [
        _display_fy(k)
        for k, v in (year_map or {}).items()
        if _is_actual_year(_display_fy(k)) and v not in (None, "—", "", "None")
    ]
    if not actuals:
        return None
    return sorted(actuals, key=_fy_year_num)[-1]


def _first_estimate_labels(est_dict, n: int = 2) -> list:
    labels = [_display_fy(k) for k in (est_dict or {}) if _is_estimate_year(_display_fy(k))]
    labels.sort(key=_fy_year_num)
    return labels[:n]


def _item_latest_actual(line_item):
    """Latest actual FY label and value on a FinancialLineItem."""
    if line_item is None:
        return None, "—"
    raw = {}
    if hasattr(line_item, "actual_year_values"):
        try:
            raw = line_item.actual_year_values() or {}
        except Exception:
            raw = {}
    display = {_display_fy(k): v for k, v in raw.items()}
    label = _latest_actual_label(display)
    if not label:
        return None, "—"
    return label, _qval(line_item, _period_attr(label))


def _signed_pct(val):
    num = _to_float(val)
    if num is None:
        return None
    return f"{'+' if num > 0 else ''}{num}%"


def _bps_delta(curr, prev):
    cur_n, prev_n = _to_float(curr), _to_float(prev)
    if cur_n is None or prev_n is None:
        return None
    return int(round((cur_n - prev_n) * 100))


def _signed_bps(bps):
    if bps is None or bps == 0:
        return None
    return f"{'+' if bps > 0 else ''}{bps}bps"


def _growth_caption(name, yoy, qoq):
    """One-line chart takeaway so the reader does not have to calculate."""
    y_n, q_n = _to_float(yoy), _to_float(qoq)
    bits = []
    if y_n is not None:
        bits.append(("increased" if y_n > 0 else "declined") + f" {abs(y_n)}% YoY")
    if q_n is not None:
        bits.append(("rose" if q_n > 0 else "declined") + f" {abs(q_n)}% QoQ")
    if not bits:
        return None
    join = " but " if (y_n is not None and q_n is not None and (y_n > 0) != (q_n > 0)) else " and "
    return f"{name} {join.join(bits)}."


def _build_presentation(quarterly_data, charts, cfg, report_period, prev_qtr_label,
                        annual_data=None):
    """Page-1 KPIs from whatever the filing actually contains.

    Missing metrics are skipped, never shown as blank NIM/GNPA cells.
    Banks prefer PAT/NII/NIM/GNPA. Corporates prefer PAT/Revenue/EBITDA/EPS.
    """
    qd = quarterly_data or {}
    annual = annual_data or {}
    pl_label = getattr(cfg, "pl_label", "Revenue") if cfg else "Revenue"
    ebitda_label = getattr(cfg, "ebitda_label", "EBITDA") if cfg else "EBITDA"
    unit = getattr(cfg, "unit_label", "Rs. cr") if cfg else "Rs. cr"
    sector = str(getattr(cfg, "sector_name", "") if cfg else "").lower()
    is_bank = any(token in sector for token in ("bank", "nbfc", "financial"))

    quarters = list(qd.get("quarters") or [])

    def _series_val(metric, period):
        return _to_float((qd.get(metric) or {}).get(period))

    def _period_has_data(period):
        return any(_series_val(m, period) is not None
                   for m in ("pat", "revenue", "eps", "ebitda", "nim", "pbt"))

    period = report_period if _period_has_data(report_period) else None
    if period is None:
        for q in reversed(quarters):
            if _period_has_data(q):
                period = q
                break

    def _annual_level(metric):
        series = annual.get(metric) or {}
        actuals = [k for k in series if not str(k).upper().endswith("E")]
        if not actuals:
            return None
        last = actuals[-1]
        return _to_float(series.get(last))

    def _level(metric):
        if period:
            val = (qd.get(metric) or {}).get(period)
            if _to_float(val) is not None:
                return val
        return _annual_level(metric)

    def _yoy(metric):
        if period:
            return (qd.get(f"{metric}_yoy") or {}).get(period)
        return None

    def _qoq(metric):
        if period:
            return (qd.get(f"{metric}_qoq") or {}).get(period)
        return None

    if is_bank:
        spec = [
            ("pat", "PAT", "amount"),
            ("revenue", pl_label, "amount"),
            ("nim", "NIM", "rate"),
            ("gnpa", "GNPA", "rate"),
            ("eps", "EPS", "eps"),
            ("nnpa", "NNPA", "rate"),
        ]
    else:
        spec = [
            ("pat", "PAT", "amount"),
            ("revenue", pl_label, "amount"),
            ("ebitda", ebitda_label, "amount"),
            ("eps", "EPS", "eps"),
            ("ebitda_margin", "EBITDA Margin", "rate"),
            ("pat_margin", "PAT Margin", "rate"),
            ("pbt", "PBT", "amount"),
        ]

    kpis = []
    changed = []
    for metric, label, kind in spec:
        val = _level(metric)
        num = _to_float(val)
        if num is None:
            continue
        chg = ""
        if kind == "rate":
            display = f"{num:.2f}%"
            prior = (qd.get(metric) or {}).get(prev_qtr_label) if prev_qtr_label else None
            signed = _signed_bps(_bps_delta(val, prior))
            if signed:
                chg = f"{signed} QoQ"
        elif kind == "eps":
            display = f"{num:.1f}"
            yoy_n = _to_float(_yoy(metric))
            if yoy_n:
                chg = f"{_signed_pct(yoy_n)} YoY"
        else:
            display = f"{num:,.1f}" if abs(num) < 10000 else f"{num:,.0f}"
            yoy_n = _to_float(_yoy(metric))
            if yoy_n:
                chg = f"{_signed_pct(yoy_n)} YoY"
        is_down = bool(chg) and chg.startswith("-")
        worse_if_down = metric not in ("gnpa", "nnpa")
        economically_bad = is_down if worse_if_down else bool(chg) and not is_down
        kpis.append({
            "label": label,
            "value": display,
            "unit": unit if kind == "amount" else "",
            "change": chg,
            "negative": economically_bad,
        })
        if chg:
            arrow = "↓" if is_down else "↑"
            changed.append({
                "label": label,
                "text": f"{arrow} {chg.lstrip('+-')}",
                "negative": economically_bad,
            })
        if len(kpis) >= 4:
            break

    pat_yoy = _to_float(_yoy("pat"))
    rev_yoy = _to_float(_yoy("revenue"))
    nim_bps = _bps_delta(_level("nim"), (qd.get("nim") or {}).get(prev_qtr_label) if prev_qtr_label else None)
    gnpa_bps = _bps_delta(_level("gnpa"), (qd.get("gnpa") or {}).get(prev_qtr_label) if prev_qtr_label else None)
    takeaway = None
    if pat_yoy is not None and pat_yoy > 0 and nim_bps is not None and nim_bps < 0:
        takeaway = "Earnings remained healthy, while margin compressed."
        if gnpa_bps is not None and gnpa_bps < 0:
            takeaway = "Earnings remained healthy; margin compressed while asset quality improved."
    elif (pat_yoy is not None and rev_yoy is not None
          and (pat_yoy > 0) != (rev_yoy > 0)):
        takeaway = "Top line and earnings moved in different directions this quarter."
    elif pat_yoy is not None and pat_yoy > 0:
        takeaway = "Earnings remained healthy this quarter."
    elif pat_yoy is not None and pat_yoy < 0:
        takeaway = "Earnings declined this quarter."
    elif rev_yoy is not None and rev_yoy > 0:
        takeaway = "Top line grew this quarter."
    elif rev_yoy is not None and rev_yoy < 0:
        takeaway = "Top line declined this quarter."

    captions = {}
    if charts:
        if "chart_quarterly" in charts:
            cap = _growth_caption(pl_label, _yoy("revenue"), _qoq("revenue"))
            if cap:
                captions["chart_quarterly"] = cap
        if "chart_pat_trend" in charts:
            cap = _growth_caption("PAT", _yoy("pat"), _qoq("pat"))
            captions["chart_pat_trend"] = cap or "Navy = actual; hatched = AI estimate, not guidance."
        if "chart_revenue_trend" in charts:
            captions["chart_revenue_trend"] = (
                f"{pl_label}: navy = actual; hatched = AI estimate, not company guidance."
            )
        if "chart_asset_quality" in charts:
            bits = []
            nim_s = _signed_bps(nim_bps)
            gnpa_s = _signed_bps(gnpa_bps)
            if nim_s:
                bits.append(f"NIM {nim_s} QoQ")
            if gnpa_s:
                bits.append(f"GNPA {gnpa_s} QoQ")
            captions["chart_asset_quality"] = (
                "; ".join(bits) + "." if bits else "NIM and asset quality from the result."
            )
        if "chart_margin" in charts:
            captions["chart_margin"] = "Operating and PAT margins from verified annual figures."

    return {
        "kpis": kpis,
        "what_changed": changed,
        "what_changed_takeaway": takeaway,
        "chart_captions": captions,
        "unit_label": unit,
    }


def _repair_narrative(text):
    """Drop clipped 'target of The…' fragments so the quality gate sees complete sentences."""
    if not text:
        return text
    s = str(text)
    s = re.sub(
        r"[^.!?]*\btarget(?: price)? of\s+(?:The |the |—|-|&mdash;)[^.!?]*[.!]?",
        " ",
        s,
        flags=re.I,
    )
    s = re.sub(r"(?:target(?: price)? of|upside of)\s*[—\-–…]*\s*$", "", s, flags=re.I)
    s = re.sub(r"^\s*(?:cr|bn|mn)\)\s*", "", s, flags=re.I)
    return re.sub(r"\s{2,}", " ", s).strip(" ,;")


def _vnum(val_raw, key):
    try:
        v = val_raw.get(key)
        return round(float(v), 2) if v is not None else None
    except Exception:
        return None


def _source_unit_display(source_text: str, fallback: tuple[str, str, str]) -> tuple[str, str, str]:
    """Detect the source reporting unit for display.

    Million-denominated source values are normalized to crores before this
    stage, so they must display as crores. Billion and crore sources retain
    their original unit in the report.
    """
    text = (source_text or "").lower()
    counts = {
        "bn": len(re.findall(r"\b(?:bn|billion)\b", text)),
        "cr": len(re.findall(r"\b(?:cr|crore|crores)\b", text)),
        "million": len(re.findall(r"\b(?:million|mn)\b", text)),
    }
    if counts["bn"] > max(counts["cr"], counts["million"]):
        return ("₹", "bn", "₹ bn")
    if counts["million"] > counts["cr"]:
        return ("Rs.", "cr", "Rs. cr")
    if counts["cr"] > 0:
        return ("Rs.", "cr", "Rs. cr")
    return fallback


def _label_with_unit(label: str, unit_label: str) -> str:
    """Replace any sector-default unit suffix with the source unit."""
    clean = re.sub(
        r"\s*\([^)]*(?:₹|rs\.?|bn|billion|cr|crore|million)[^)]*\)",
        "",
        str(label or ""),
        flags=re.IGNORECASE,
    ).strip()
    return f"{clean} ({unit_label})"


# yfinance industry strings → pipeline sector names.
# Keys are matched case-insensitively as substrings.
_YFINANCE_INDUSTRY_MAP = {
    "bank": "Banking", "banking": "Banking",
    "software": "IT Services", "information technology": "IT Services",
    "it services": "IT Services", "it-services": "IT Services",
    "consulting": "IT Services",
    "oil": "Energy", "gas": "Energy", "refin": "Energy",
    "power": "Energy", "energy": "Energy", "electric": "Energy",
    "utilities": "Energy",
    "pharma": "Pharma", "pharmaceutical": "Pharma", "drug": "Pharma",
    "biotech": "Pharma", "life sciences": "Pharma",
    "automobile": "Auto", "auto": "Auto", "vehicle": "Auto",
    "two wheeler": "Auto", "four wheeler": "Auto",
    "metal": "Metals", "steel": "Metals", "iron": "Metals",
    "aluminium": "Metals", "aluminum": "Metals",
    "cement": "Cement", "construction materials": "Cement",
    "building materials": "Cement",
    "telecom": "Telecom", "telecommunication": "Telecom",
    "wireless": "Telecom",
    "retail": "Internet & Retail", "e-commerce": "Internet & Retail",
    "internet": "Internet & Retail", "consumer discretionary": "Internet & Retail",
    "fmcg": "FMCG", "consumer goods": "FMCG",
    "consumer staples": "FMCG",
    "financial services": "Banking", "non-banking": "NBFC",
    "nbfc": "NBFC",
    "chemical": "Chemicals", "specialty chemicals": "Chemicals",
    "infrastructure": "Infrastructure", "construction": "Infrastructure",
    "engineering": "Infrastructure",
}


def _map_yfinance_industry(yf_industry: str) -> str:
    """Map a yfinance info['industry'] string to a pipeline sector name."""
    if not yf_industry:
        return ""
    text = str(yf_industry).strip().lower()
    for key, sector in _YFINANCE_INDUSTRY_MAP.items():
        if key in text:
            return sector
    return ""


def run(
    fa_evidence,
    fa_narrative_raw: str,
    stage_12,
    stage_08b_valuation_data: dict,
    kg: dict,
    industry: str,
    derived_name: str,
    report_period: str,
    safe_filename: str,
    file_filename: str,
    fact_check_report,
    ocr_text: str,
    raw_financials: dict = None,
    source_value_factor: float = 1.0,
) -> Any:
    schema_mod = importlib.import_module("schema")
    stage_11_charts = importlib.import_module("pipeline.11_chart_generator")
    stage_14 = importlib.import_module("pipeline.14_report_object_model.rom_builder")

    from pipeline.sectors import get_sector_config
    from pipeline.utils.company_identity import canonicalize_display_name
    derived_name = canonicalize_display_name(derived_name, safe_filename or file_filename)
    from pipeline.utils.llm_client import call_azure_deepseek  # noqa
    _base_agent_mod = importlib.import_module("pipeline.11_specialist_agents.base_agent")
    parse_narrative_sections = _base_agent_mod.parse_narrative_sections

    cfg = get_sector_config(industry)
    fallback_unit = (
        getattr(cfg, "currency_symbol", "Rs."),
        getattr(cfg, "unit_suffix", "cr"),
        getattr(cfg, "unit_label", "Rs. cr"),
    )
    currency_symbol, unit_suffix, unit_label = _source_unit_display(ocr_text, fallback_unit)
    cfg = replace(
        cfg,
        currency_symbol=currency_symbol,
        unit_suffix=unit_suffix,
        unit_label=unit_label,
        pl_label=_label_with_unit(getattr(cfg, "pl_label", "Revenue"), unit_label),
        pat_label=_label_with_unit(getattr(cfg, "pat_label", "PAT"), unit_label),
    )

    # ── Parse narrative sections ─────────────────────────────────────────────
    narrative_sections = parse_narrative_sections(fa_narrative_raw)

    # ── Extract financial values ─────────────────────────────────────────────
    pl, bs, cf = fa_evidence.pl, fa_evidence.bs, fa_evidence.cf

    # ── Period labels: prefer LLM-extracted headers, else derive from report_period ─
    period_labels = (raw_financials or {}).get("period_labels") or {}
    prev_yr_label = None
    prev_qtr_label = None
    if isinstance(period_labels, dict):
        _pl_qc = period_labels.get("q_current")
        _pl_qp = period_labels.get("q_prev_qtr")
        _pl_py = period_labels.get("q_prev_year")
        if _pl_qc and str(_pl_qc).strip() and str(_pl_qc).strip().lower() not in ("null", "none", "—", "-"):
            report_period = str(_pl_qc).strip().upper().replace(" ", "")
        if _pl_py and str(_pl_py).strip() and str(_pl_py).strip().lower() not in ("null", "none", "—", "-"):
            prev_yr_label = str(_pl_py).strip().upper().replace(" ", "")
        if _pl_qp and str(_pl_qp).strip() and str(_pl_qp).strip().lower() not in ("null", "none", "—", "-"):
            prev_qtr_label = str(_pl_qp).strip().upper().replace(" ", "")

    # Fallback derivation only when LLM labels are missing.
    if not prev_yr_label:
        _fy_match = re.search(r'FY(\d{2,4})', report_period)
        if _fy_match:
            _fy_num = int(_fy_match.group(1))
            _fy_width = len(_fy_match.group(1))
            prev_yr_label = report_period.replace(
                f"FY{_fy_num:0{_fy_width}d}", f"FY{_fy_num - 1:0{_fy_width}d}")
        else:
            prev_yr_label = report_period
    if not prev_qtr_label:
        _qm = re.search(r'Q([1-4])', report_period, re.IGNORECASE)
        _fm = re.search(r'FY(\d{2,4})', report_period, re.IGNORECASE)
        if _qm and _fm:
            qn = int(_qm.group(1))
            fy = _fm.group(1)
            if qn == 1:
                prev_qtr_label = f"Q4FY{int(fy) - 1:0{len(fy)}d}"
            else:
                prev_qtr_label = f"Q{qn - 1}FY{fy}"
        else:
            prev_qtr_label = report_period

    if isinstance(period_labels, dict) and period_labels.get("q_current"):
        print(
            f"     [Pipeline] Period labels: "
            f"{prev_yr_label} | {prev_qtr_label} | {report_period}"
        )

    rev_q_cur   = _qval(pl.revenue, "q_current")
    rev_q_prev  = _qval(pl.revenue, "q_prev_qtr")
    rev_q_yoy   = _qval(pl.revenue, "q_prev_year")
    pat_q_cur   = _qval(pl.pat, "q_current")
    pat_q_prev  = _qval(pl.pat, "q_prev_qtr")
    pat_q_yoy   = _qval(pl.pat, "q_prev_year")

    rev_yoy_pct = _growth(rev_q_cur, rev_q_yoy)
    rev_qoq_pct = _growth(rev_q_cur, rev_q_prev)
    pat_yoy_pct = _growth(pat_q_cur, pat_q_yoy)

    # ── Deterministic highlights from VERIFIED evidence (no LLM, no hallucination) ─
    # Every number in these bullets is traceable to fa_evidence (Stage 08 extracted + Stage 12b verified)
    verified_highlights = []
    # SectorConfig is a dataclass, not a dict.  Read labels from either shape so
    # banking reports preserve NII and other sectors keep their own terminology.
    def _cfg_value(name, default):
        if isinstance(cfg, dict):
            return cfg.get(name, default)
        return getattr(cfg, name, default)

    pl_label = _cfg_value("pl_label", "Revenue")
    pat_label = _cfg_value("pat_label", "PAT")
    ebitda_label = _cfg_value("ebitda_label", "EBITDA")
    pl_label_short = re.sub(r"\s*\([^)]*\)\s*$", "", str(pl_label)).strip() or "Revenue"
    pat_label_short = re.sub(r"\s*\([^)]*\)\s*$", "", str(pat_label)).strip() or "PAT"

    def _format_amount(value):
        symbol = _cfg_value("currency_symbol", "Rs.")
        suffix = _cfg_value("unit_suffix", "cr")
        return f"{symbol}{value} {suffix}" if symbol == "₹" else f"{symbol} {value}{suffix}"

    def _yoy_bullet(metric, cur, yoy_pct, period, qoq_pct="—", as_percent=False):
        if cur == "—":
            return None
        shown = f"{cur}%" if as_percent else _format_amount(cur)
        if yoy_pct == "—":
            return f"{metric} stood at {shown} in {period}."
        try:
            ch = float(yoy_pct)
        except (TypeError, ValueError):
            return f"{metric} stood at {shown} in {period}."
        if abs(ch) < 0.05:
            return f"{metric} was unchanged YoY in {period} at {shown}."
        verb = "rose" if ch > 0 else "fell"
        qoq_bit = ""
        if qoq_pct not in ("—", None, ""):
            try:
                qch = float(qoq_pct)
                if abs(qch) >= 0.05:
                    qoq_bit = f" ({abs(qch)}% QoQ)"
            except (TypeError, ValueError):
                qoq_bit = ""
        return f"{metric} {verb} {abs(ch)}% YoY in {period} to {shown}{qoq_bit}."

    bullet = _yoy_bullet(pl_label_short, rev_q_cur, rev_yoy_pct, report_period, rev_qoq_pct)
    if bullet:
        verified_highlights.append(bullet)
    bullet = _yoy_bullet(pat_label_short, pat_q_cur, pat_yoy_pct, report_period)
    if bullet:
        verified_highlights.append(bullet)
    ebitda_q = _qval(pl.ebitda, "q_current")
    ebitda_yoy = _growth(ebitda_q, _qval(pl.ebitda, "q_prev_year"))
    bullet = _yoy_bullet(ebitda_label, ebitda_q, ebitda_yoy, report_period)
    if bullet:
        verified_highlights.append(bullet)
    pbt_q = _qval(pl.pbt, "q_current")
    pbt_yoy = _growth(pbt_q, _qval(pl.pbt, "q_prev_year"))
    bullet = _yoy_bullet("PBT", pbt_q, pbt_yoy, report_period)
    if bullet:
        verified_highlights.append(bullet)
    extras = getattr(fa_evidence, "banking_metrics", None) or {}
    if isinstance(extras, dict):
        _pct_keys = {
            "nim": "NIM", "gnpa": "GNPA", "nnpa": "NNPA",
            "casa_ratio": "CASA", "capital_adequacy": "Capital adequacy",
            "roe": "RoE", "roa": "RoA",
        }
        for key, item in extras.items():
            if key in ("revenue", "pat", "ebitda", "pbt", "nii"):
                continue
            cur = _qval(item, "q_current")
            yoy = _growth(cur, _qval(item, "q_prev_year"))
            if key in _pct_keys:
                bullet = _yoy_bullet(_pct_keys[key], cur, yoy, report_period, as_percent=True)
            else:
                label = str(key).replace("_", " ").strip().title()
                bullet = _yoy_bullet(label, cur, yoy, report_period)
            if bullet:
                verified_highlights.append(bullet)
            if len(verified_highlights) >= 8:
                break
    # Annual trend (added later after rev_avail/pat_avail are defined — see below)
    # Use verified highlights if we generated enough; fall back to LLM highlights otherwise
    # (annual trend bullets appended after Screener merge)

    def _source_page_for_highlight(highlight: str):
        """Return a page only when the exact verified value is traceable."""
        numeric_tokens = []
        for token in re.findall(r"(?<![A-Za-z])[-+]?\d[\d,]*(?:\.\d+)?", highlight or ""):
            try:
                numeric_tokens.append(float(token.replace(",", "")))
            except ValueError:
                pass
        if not numeric_tokens:
            return None
        for verification in getattr(fact_check_report, "verified", []) or []:
            try:
                extracted = float(verification.extracted)
            except (TypeError, ValueError):
                continue
            if not any(abs(extracted - token) <= max(0.01, abs(token) * 0.001)
                       for token in numeric_tokens):
                continue
            page_match = re.search(
                r"(?:SOURCE PAGE|PAGE_BREAK page=|Page\s+)(\d+)",
                verification.snippet or "", re.IGNORECASE,
            )
            if page_match:
                return int(page_match.group(1))
        return None

    def _annotate_source_pages(highlights):
        annotated = []
        for highlight in highlights:
            page = _source_page_for_highlight(highlight)
            annotated.append(
                f"{highlight} (Source: uploaded document, page {page})"
                if page else highlight
            )
        return annotated

    def annual_row(line_item):
        """Read ALL annual years from a FinancialLineItem — both fixed fields
        (fy22-fy25) and the dynamic `annual` dict (fy20, fy21, fy26a, etc.)."""
        result = {}
        # Fixed fields (backward compat)
        for y, a in [("FY22","fy22"),("FY23","fy23"),("FY24","fy24"),("FY25","fy25")]:
            val = _qval(line_item, a)
            if val != "—":
                result[y] = val
        # Dynamic annual dict — captures any other fiscal year
        if hasattr(line_item, "annual") and line_item.annual:
            for yk, v in line_item.annual.items():
                display_yr = _display_fy(yk)
                if _is_estimate_year(display_yr):
                    continue
                if display_yr not in result:
                    val = _qval(line_item, yk)
                    if val != "—":
                        result[display_yr] = val
        return result

    rev_annual    = annual_row(pl.revenue)
    ebitda_annual = annual_row(pl.ebitda)
    pat_annual    = annual_row(pl.pat)
    eps_annual    = annual_row(pl.eps)
    # Additional P&L line items (already extracted by Stage 08, just not rendered before)
    dep_annual    = annual_row(pl.depreciation)
    ebit_annual   = annual_row(pl.ebit)
    interest_ann  = annual_row(pl.interest)
    pbt_annual    = annual_row(pl.pbt)
    tax_annual    = annual_row(pl.tax)
    # Balance Sheet line items
    bs_cash       = annual_row(bs.cash_and_equivalents)
    bs_receivables= annual_row(bs.accounts_receivable)
    bs_inventories= annual_row(bs.inventories)
    bs_investments= annual_row(bs.investments)
    bs_gfa        = annual_row(bs.gross_fixed_assets)
    bs_nfa        = annual_row(bs.net_fixed_assets)
    bs_ta         = annual_row(bs.total_assets)
    bs_te         = annual_row(bs.total_equity)
    bs_td         = annual_row(bs.total_debt)
    # Cash Flow line items
    cf_operating  = annual_row(cf.operating_cash_flow)
    cf_investing  = annual_row(cf.investing_cash_flow)
    cf_financing  = annual_row(cf.financing_cash_flow)
    cf_fcf        = annual_row(cf.free_cash_flow)

    # ── Merge Screener.in historical data ────────────────────────────────────
    def _merge(*dicts) -> dict:
        merged = {}
        for d in dicts:
            if isinstance(d, dict):
                merged.update({k: v for k, v in d.items() if v is not None and v != "—"})
        return merged

    def _trim(d):
        """Keep any fiscal year with valid data — no longer restricted to FY22-FY25."""
        out = {}
        for k, v in d.items():
            kk = re.sub(r"A$", "", str(k))   # "FY25A" → "FY25"
            # Accept ANY FY year (FY20, FY21, FY22, ..., FY30, etc.)
            if re.match(r"FY\d{2,4}$", kk) and v is not None and v != "—":
                out[kk] = v
        return out

    rev_annual    = _trim(rev_annual)
    ebitda_annual = _trim(ebitda_annual)
    pat_annual    = _trim(pat_annual)
    eps_annual    = _trim(eps_annual)

    bs_total_assets = _trim(bs_ta)
    bs_total_equity = _trim(bs_te)
    bs_total_debt   = _trim(bs_td)
    bs_cash         = _trim(bs_cash)
    cf_operating    = _trim(cf_operating)
    cf_investing    = _trim(cf_investing)
    cf_financing    = _trim(cf_financing)

    rev_avail  = {k: v for k, v in rev_annual.items()  if v != "—"}
    pat_avail  = {k: v for k, v in pat_annual.items()  if v != "—"}
    latest_actual_fy = (
        _latest_actual_label(rev_avail)
        or _latest_actual_label(pat_avail)
        or _latest_actual_label(bs_total_assets)
        or _latest_actual_label(bs_total_equity)
    )

    # Append annual trend to verified highlights (rev_avail/pat_avail now defined)
    if len(rev_avail) > 1:
        yrs = [y for y in sorted(rev_avail.keys()) if not str(y).upper().endswith("E")]
        if len(yrs) >= 2:
            prev_v, cur_v = rev_avail[yrs[-2]], rev_avail[yrs[-1]]
            try:
                verb = "rose" if float(cur_v) >= float(prev_v) else "fell"
            except (TypeError, ValueError):
                verb = "moved"
            verified_highlights.append(
                f"{pl_label_short} {verb} from {_format_amount(prev_v)} in {yrs[-2]} "
                f"to {_format_amount(cur_v)} in {yrs[-1]}."
            )
    if len(pat_avail) > 1:
        yrs = [y for y in sorted(pat_avail.keys()) if not str(y).upper().endswith("E")]
        if len(yrs) >= 2:
            prev_v, cur_v = pat_avail[yrs[-2]], pat_avail[yrs[-1]]
            try:
                verb = "rose" if float(cur_v) >= float(prev_v) else "fell"
            except (TypeError, ValueError):
                verb = "moved"
            verified_highlights.append(
                f"{pat_label_short} {verb} from {_format_amount(prev_v)} in {yrs[-2]} "
                f"to {_format_amount(cur_v)} in {yrs[-1]}."
            )

    # Add page references only where the verification snippet retained an
    # unambiguous source-page marker; never guess a page number.
    verified_highlights = _annotate_source_pages(verified_highlights)

    # Override LLM highlights with verified ones (no hallucinated numbers)
    # Even 2 verified highlights are better than LLM highlights with stripped-number placeholders
    if len(verified_highlights) >= 2:
        narrative_sections["key_highlights"] = verified_highlights
        print(f"     [Pipeline] Using {len(verified_highlights)} verified highlights (no LLM numbers).")
    else:
        print(f"     [Pipeline] Only {len(verified_highlights)} verified highlights — keeping LLM highlights.")

    # Strip placeholder / empty bullets before ROM build
    from pipeline.report_quality import validate_bullets
    _b_errs, _b_warns = validate_bullets(narrative_sections.get("key_highlights", []))
    if _b_errs:
        clean = [
            b for b in narrative_sections.get("key_highlights", [])
            if b and not any(p in b for p in (
                "grew + YoY", "+% YoY", "[VERIFIED]", "[N/A]", "KEY_HIGHLIGHTS",
            ))
        ]
        narrative_sections["key_highlights"] = clean or verified_highlights
        print(f"     [Pipeline] Filtered {len(_b_errs)} bad highlight(s).")

    def growth_row(d):
        years = sorted(d.keys())
        result = {}
        for i, y in enumerate(years):
            result[y] = "—" if i == 0 else _growth(d[y], d[years[i-1]])
        return result

    rev_growth = growth_row(rev_avail) if len(rev_avail) > 1 else {}
    pat_growth = growth_row(pat_avail) if len(pat_avail) > 1 else {}

    annual_data = {
        "revenue": {k: v for k, v in rev_annual.items()    if v != "—"},
        "ebitda":  {k: v for k, v in ebitda_annual.items() if v != "—"},
        "pat":     {k: v for k, v in pat_annual.items()    if v != "—"},
        "eps":     {k: v for k, v in eps_annual.items()    if v != "—"},
    }
    if not annual_data["revenue"] and rev_q_cur != "—":
        annual_data["revenue"] = {report_period: rev_q_cur}
    if not annual_data["pat"] and pat_q_cur != "—":
        annual_data["pat"] = {report_period: pat_q_cur}

    # ── Forward estimates: source first; model only if two actuals exist ──────
    # Labels follow this filing (FY{n+1}E / FY{n+2}E). No 5% default.
    print("     [Pipeline] Generating deterministic forward estimates...")
    projections = {}
    ForwardProjector = importlib.import_module(
        "pipeline.09_quant_engine.projections"
    ).ForwardProjector

    def _project_series(values):
        """Next two estimate years from the latest actual — only with two actuals."""
        clean = {}
        for year, value in (values or {}).items():
            if value not in (None, "—", "[N/A]"):
                try:
                    label = _display_fy(year)
                    if _is_estimate_year(label):
                        continue
                    clean[label] = float(value)
                except (TypeError, ValueError):
                    pass
        actual_years = [y for y in clean if _is_actual_year(y)]
        if len(actual_years) < 2:
            return {}
        actual_years.sort(key=_fy_year_num)
        latest_yr = actual_years[-1]
        latest_val = clean[latest_yr]
        second_val = clean[actual_years[-2]]
        if second_val == 0:
            return {}
        growth = (latest_val - second_val) / abs(second_val)
        growth = max(ForwardProjector.MIN_GROWTH_RATE,
                     min(ForwardProjector.MAX_GROWTH_RATE, growth))
        latest_num = _fy_year_num(latest_yr)
        est1_label = f"FY{latest_num + 1:02d}E"
        est2_label = f"FY{latest_num + 2:02d}E"
        est1 = round(latest_val * (1 + growth), 2)
        est2 = round(est1 * (1 + growth), 2)
        return {est1_label: est1, est2_label: est2}

    for key, values in {
        "revenue": rev_annual, "ebitda": ebitda_annual,
        "pat": pat_annual, "eps": eps_annual,
    }.items():
        estimate = _project_series(values)
        if estimate:
            projections[key] = estimate

    def est_row(line_item, proj_key: str = "") -> dict:
        """Source estimate years first; model projections fill gaps only."""
        result = {}
        if hasattr(line_item, "annual") and line_item.annual:
            for yk, v in line_item.annual.items():
                display_yr = _display_fy(yk)
                if not _is_estimate_year(display_yr):
                    continue
                val = _qval(line_item, yk)
                if val != "—":
                    result[display_yr] = val
        for yr, attr in [("FY26E", "fy26e"), ("FY27E", "fy27e")]:
            if yr not in result:
                v = _qval(line_item, attr)
                if v != "—":
                    result[yr] = v
        if proj_key and proj_key in projections:
            for yr, v in projections[proj_key].items():
                if yr not in result and v is not None:
                    result[yr] = v
        return result

    # Forward estimate series for charts — years come from this filing.
    annual_data["revenue_est"] = est_row(pl.revenue, "revenue")
    annual_data["pat_est"]     = est_row(pl.pat,     "pat")
    annual_data["ebitda_est"]  = est_row(pl.ebitda,  "ebitda")

    # Market data is intentionally absent until a verified provider is configured.
    # Source-document facts must not be mixed with unverified ticker lookups.
    stock_chart_b64 = ""
    price_perf = {}
    market_data = {}

    # Independent secondary-source check.  Never overwrite primary extracted
    # values; record disagreements as explicit review flags instead.
    cross_source_mod = importlib.import_module("pipeline.12e_cross_source_verifier.verifier")
    primary_valuation = (stage_08b_valuation_data or {}).get("valuation", {}) or {}
    cross_source_report = cross_source_mod.CrossSourceVerifier.verify(primary_valuation, market_data)
    print(f"     [Cross-Source QA] {cross_source_report.summary}")
    for flag in cross_source_report.review_flags:
        print(f"     [Cross-Source QA] REVIEW: {flag}")

    # ── Derived annual ratios (ROE, margins) from data we already have ───────
    def _norm_keys(d):
        # Screener gives "FY25A", extraction gives "FY25" — unify to "FY25"
        out = {}
        for k, v in d.items():
            kk = re.sub(r"A$", "", str(k))
            if v != "—" and v is not None:
                out[kk] = v
        return out

    rev_n  = _norm_keys(rev_annual)
    ebd_n  = _norm_keys(ebitda_annual)
    pat_n  = _norm_keys(pat_annual)
    eq_n   = _norm_keys(bs_total_equity)
    ta_n   = _norm_keys(bs_total_assets)
    td_n   = _norm_keys(bs_total_debt)

    # ── Unit normalization verifier ─────────────────────────────────────────
    # Screener returns values in crores. Extraction may return in billions or
    # other units. Detect mismatches by comparing overlapping values and by
    # sanity-checking computed ratios. Self-heal by applying conversion factor.
    def _detect_unit_factor(numerator_dict, denominator_dict, label=""):
        """If num/den ratio is absurd, find a factor that makes it sensible."""
        common_years = set(numerator_dict.keys()) & set(denominator_dict.keys())
        if not common_years:
            return 1.0
        try:
            # Try the latest common year
            y = sorted(common_years)[-1]
            num = float(numerator_dict[y])
            den = float(denominator_dict[y])
            if den <= 0 or num <= 0:
                return 1.0
            raw_ratio = num / den
            # For ROE: sensible range is 0.05-0.50 (5%-50%)
            # For D/E: sensible range is 0.01-10x
            # For margins: sensible range is 0.01-0.60 (1%-60%)
            if label == "roe" and raw_ratio > 2.0:
                # Try multiplying denominator by 100 (billions → crores)
                if raw_ratio / 100 < 1.0:
                    print(f"     [Verifier] {label} unit mismatch detected (raw={raw_ratio:.1f}). Applying 100x correction to denominator.")
                    return 100.0
            if label == "de" and raw_ratio > 50:
                if raw_ratio / 100 < 10:
                    print(f"     [Verifier] {label} unit mismatch detected (raw={raw_ratio:.1f}). Applying 100x correction to denominator.")
                    return 100.0
        except Exception:
            pass
        return 1.0

    # Apply unit corrections
    eq_factor = _detect_unit_factor(pat_n, eq_n, "roe")
    ta_factor = _detect_unit_factor(pat_n, ta_n, "roa")
    if eq_factor != 1.0:
        eq_n = {k: v * eq_factor for k, v in eq_n.items()}
    if ta_factor != 1.0:
        ta_n = {k: v * ta_factor for k, v in ta_n.items()}
    td_factor = _detect_unit_factor(td_n, eq_n, "de")
    if td_factor != 1.0:
        td_n = {k: v * td_factor for k, v in td_n.items()}

    def _pct_row(num_d, den_d):
        out = {}
        for y in num_d:
            try:
                d = float(den_d.get(y, 0))
                if d > 0:
                    out[y] = round(float(num_d[y]) / d * 100, 1)
            except Exception:
                continue
        return out

    ratio_net_margin    = _pct_row(pat_n, rev_n)
    ratio_ebitda_margin = _pct_row(ebd_n, rev_n)
    ratio_roe           = _pct_row(pat_n, eq_n)
    ratio_roa           = _pct_row(pat_n, ta_n)
    ratio_de            = {}
    for y in td_n:
        try:
            e = float(eq_n.get(y, 0))
            if e > 0:
                ratio_de[y] = round(float(td_n[y]) / e, 2)
        except Exception:
            continue
    # Growth ratios (already computed as rev_growth / pat_growth above)
    ratio_rev_growth = rev_growth
    ratio_pat_growth = pat_growth

    # Generic corporate net margin is misleading for banks because NII is not
    # equivalent to corporate revenue. EV/EBITDA is handled similarly below.
    _is_banking_sector = any(token in (industry or '').lower()
                             for token in ('bank', 'nbfc', 'financial services'))
    if _is_banking_sector:
        ratio_net_margin = {}

    # Forward ratios use this filing's estimate years and latest actual BS.
    _is_banking_sector = any(token in (industry or '').lower()
                             for token in ('bank', 'nbfc', 'financial services'))
    _rev_est = est_row(pl.revenue, "revenue")
    _pat_est = est_row(pl.pat,     "pat")
    _ebd_est = {k: v for k, v in est_row(pl.ebitda, "ebitda").items() if v and float(v) != 0}
    _eq_label, _eq_latest = _item_latest_actual(bs.total_equity)
    _ta_label, _ta_latest = _item_latest_actual(bs.total_assets)
    _td_label, _td_latest = _item_latest_actual(bs.total_debt)
    for yr in sorted(_rev_est.keys(), key=_fy_year_num):
        rv = _rev_est.get(yr)
        pv = _pat_est.get(yr)
        ev = _ebd_est.get(yr)
        if not _is_banking_sector and rv and pv and float(rv) > 0:
            ratio_net_margin[yr] = round(float(pv) / float(rv) * 100, 1)
        if rv and ev and float(rv) > 0:
            ratio_ebitda_margin[yr] = round(float(ev) / float(rv) * 100, 1)
        if pv and _eq_latest != "—" and float(_eq_latest) > 0:
            ratio_roe[yr] = round(float(pv) / float(_eq_latest) * 100, 1)
        if pv and _ta_latest != "—" and float(_ta_latest) > 0:
            ratio_roa[yr] = round(float(pv) / float(_ta_latest) * 100, 1)
        if _td_latest != "—" and _eq_latest != "—" and float(_eq_latest) > 0:
            ratio_de[yr] = round(float(_td_latest) / float(_eq_latest), 2)

    quarterly_data = {
        "quarters": [prev_yr_label, prev_qtr_label, report_period],
        "revenue": {k: v for k, v in {
            prev_yr_label: rev_q_yoy, prev_qtr_label: rev_q_prev,
            report_period: rev_q_cur}.items() if v != "—"},
        "ebitda": {k: v for k, v in {
            prev_yr_label: _qval(pl.ebitda, "q_prev_year"),
            prev_qtr_label: _qval(pl.ebitda, "q_prev_qtr"),
            report_period: _qval(pl.ebitda, "q_current")}.items() if v != "—"},
        "ebit": {k: v for k, v in {
            prev_yr_label: _qval(pl.ebit, "q_prev_year"),
            prev_qtr_label: _qval(pl.ebit, "q_prev_qtr"),
            report_period: _qval(pl.ebit, "q_current")}.items() if v != "—"},
        "pbt": {k: v for k, v in {
            prev_yr_label: _qval(pl.pbt, "q_prev_year"),
            prev_qtr_label: _qval(pl.pbt, "q_prev_qtr"),
            report_period: _qval(pl.pbt, "q_current")}.items() if v != "—"},
        "pat": {k: v for k, v in {
            prev_yr_label: pat_q_yoy, prev_qtr_label: pat_q_prev,
            report_period: pat_q_cur}.items() if v != "—"},
        "eps": {k: v for k, v in {
            prev_yr_label: _qval(pl.eps, "q_prev_year"),
            prev_qtr_label: _qval(pl.eps, "q_prev_qtr"),
            report_period: _qval(pl.eps, "q_current")}.items() if v != "—"},
        "revenue_yoy": {report_period: rev_yoy_pct} if rev_yoy_pct != "—" else {},
        "revenue_qoq": {report_period: rev_qoq_pct} if rev_qoq_pct != "—" else {},
        "pat_yoy":     {report_period: pat_yoy_pct} if pat_yoy_pct != "—" else {},
    }

    # Derived quarter comparisons.  Keep missing values as missing rather than
    # turning an unavailable comparison into a misleading zero.
    def _comparison_row(values):
        current = values.get(report_period, "—")
        prior_year = values.get(prev_yr_label, "—")
        prior_qtr = values.get(prev_qtr_label, "—")
        return {
            "yoy": _growth(current, prior_year),
            "qoq": _growth(current, prior_qtr),
        }

    for metric in ("ebitda", "ebit", "pbt", "pat", "eps"):
        cmp = _comparison_row(quarterly_data.get(metric, {}))
        quarterly_data[f"{metric}_yoy"] = ({report_period: cmp["yoy"]}
                                             if cmp["yoy"] != "—" else {})
        quarterly_data[f"{metric}_qoq"] = ({report_period: cmp["qoq"]}
                                             if cmp["qoq"] != "—" else {})
    # EBITDA margin % per quarter (computed deterministically)
    _ebm = {}
    for q in [prev_yr_label, prev_qtr_label, report_period]:
        r = quarterly_data["revenue"].get(q)
        e = quarterly_data["ebitda"].get(q)
        if r and e and r not in ("—", None) and e not in ("—", None):
            try:
                rv, ev = float(r), float(e)
                if rv > 0:
                    _ebm[q] = round(ev / rv * 100, 1)
            except Exception:
                pass
    if _ebm:
        quarterly_data["ebitda_margin"] = _ebm
    # PAT margin % per quarter
    _pm = {}
    for q in [prev_yr_label, prev_qtr_label, report_period]:
        r = quarterly_data["revenue"].get(q)
        p = quarterly_data["pat"].get(q)
        if r and p and r not in ("—", None) and p not in ("—", None):
            try:
                rv, pv = float(r), float(p)
                if rv > 0:
                    _pm[q] = round(pv / rv * 100, 1)
            except Exception:
                pass
    if _pm:
        quarterly_data["pat_margin"] = _pm
        cmp = _comparison_row(_pm)
        quarterly_data["pat_margin_yoy"] = ({report_period: cmp["yoy"]}
                                             if cmp["yoy"] != "—" else {})
        quarterly_data["pat_margin_qoq"] = ({report_period: cmp["qoq"]}
                                             if cmp["qoq"] != "—" else {})

    # Add banking metrics to quarterly_data for banking quality chart
    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics
        for label, attr in [("nim", "nim"), ("gnpa", "gnpa"), ("nnpa", "nnpa")]:
            item = bm.get(attr) if isinstance(bm, dict) else getattr(bm, attr, None)
            vals = {}
            for q, k in [(prev_yr_label, "q_prev_year"), (prev_qtr_label, "q_prev_qtr"), (report_period, "q_current")]:
                v = _qval(item, k)
                if v != "—":
                    vals[q] = v
            if vals:
                quarterly_data[label] = vals
                cmp = _comparison_row(vals)
                quarterly_data[f"{label}_yoy"] = ({report_period: cmp["yoy"]}
                                                   if cmp["yoy"] != "—" else {})
                quarterly_data[f"{label}_qoq"] = ({report_period: cmp["qoq"]}
                                                   if cmp["qoq"] != "—" else {})

    # ── Extract segment & geography data from raw_financials (if available) ──
    # This enables segment/geo pie charts for companies like Reliance that
    # report segment-wise revenue breakdown.
    segment_data = {}
    geo_data = {}
    if raw_financials and isinstance(raw_financials, dict):
        # Look for segment data under common key patterns
        for seg_key in ("segments", "segment_revenue", "segment_breakdown",
                        "segment_data", "business_segment"):
            seg = raw_financials.get(seg_key)
            if isinstance(seg, dict):
                for k, v in seg.items():
                    try:
                        fv = float(v)
                        if fv != 0:
                            segment_data[str(k)] = fv
                    except (TypeError, ValueError):
                        pass
                if segment_data:
                    break
        # Look for geography data under common key patterns
        for geo_key in ("geography", "geography_revenue", "geography_breakdown",
                        "geo_revenue", "geo_breakdown", "regional_revenue"):
            geo = raw_financials.get(geo_key)
            if isinstance(geo, dict):
                for k, v in geo.items():
                    try:
                        fv = float(v)
                        if fv != 0:
                            geo_data[str(k)] = fv
                    except (TypeError, ValueError):
                        pass
                if geo_data:
                    break

    if segment_data:
        print(f"     [Pipeline] Found segment data: {list(segment_data.keys())}")
    if geo_data:
        print(f"     [Pipeline] Found geography data: {list(geo_data.keys())}")

    charts = stage_11_charts.generate_all_charts(
        annual_data=annual_data, quarterly_data=quarterly_data,
        sector_cfg=cfg, segment_data=segment_data, geo_data=geo_data)
    if not charts:
        print("     [Pipeline] No chartable history in this filing — continuing without charts.")
    presentation = _build_presentation(
        quarterly_data, charts, cfg, report_period, prev_qtr_label,
        annual_data=annual_data,
    )

    # ── Valuation data ───────────────────────────────────────────────────────
    vd       = stage_08b_valuation_data or {}
    val_raw  = vd.get("valuation", {}) or {}
    sh_data  = vd.get("shareholding", {}) or {}

    def _first(*vals):
        for v in vals:
            if v is not None:
                return v
        return None

    # CMP is used only when explicitly present in the source document.
    cmp_val    = _vnum(val_raw, "cmp")
    target_val = _vnum(val_raw, "target_price")
    pe_now     = _first(_vnum(val_raw, "pe_ratio"), market_data.get("pe_ratio"))
    pb_now     = _first(_vnum(val_raw, "pbv_ratio"), market_data.get("pb_ratio"))

    # Target only if printed in the source (Stage 08b). Never invent EPS × P/E.
    target_estimated = False
    upside_val = (round(((target_val - cmp_val) / cmp_val) * 100, 1)
                  if (cmp_val and target_val and cmp_val > 0) else None)

    if target_val is not None and upside_val is not None:
        rec_action = "BUY" if upside_val > 10 else ("HOLD" if upside_val > 0 else "SELL")
    else:
        rec_action = "NOT RATED"

    ai_scenario = {
        "available": False,
        "action": None,
        "target_price": None,
        "upside_pct": None,
        "eps_fy26e": None,
        "pe_used": None,
        "formula": None,
        "method": None,
        "label": "AI estimate — not analyst guidance",
    }

    # ── Stage 10g: Analytical Engine (cross-metric, quality, scenarios, mgmt) ─
    analytical_result = None
    try:
        _ae_mod = importlib.import_module("pipeline.10g_analytical_engine.engine")
        AnalyticalEngine = _ae_mod.AnalyticalEngine

        annual_data_for_analysis = {
            **annual_data,
            "depreciation": {k: v for k, v in dep_annual.items() if v != "—"},
            "interest": {k: v for k, v in interest_ann.items() if v != "—"},
            "pbt": {k: v for k, v in pbt_annual.items() if v != "—"},
            "tax": {k: v for k, v in tax_annual.items() if v != "—"},
            "total_assets": {k: v for k, v in bs_total_assets.items() if v != "—"},
            "net_fixed_assets": {k: v for k, v in bs_nfa.items() if v != "—"},
        }

        sector_name = getattr(cfg, "sector_name", industry) if cfg else industry
        analytical_result, refreshed_sections = AnalyticalEngine.run(
            fa_evidence=fa_evidence,
            annual_data=annual_data_for_analysis,
            quarterly_data=quarterly_data,
            company_name=derived_name,
            industry=industry,
            report_period=report_period,
            ocr_text=ocr_text or "",
            cmp=cmp_val,
            target_price=target_val,
            outlook_text=narrative_sections.get("outlook_valuation", ""),
            sector_name=sector_name,
            llm_client=call_azure_deepseek,
            refresh_narrative=True,
        )

        if refreshed_sections:
            # Merge analytical narrative with verified numeric highlights
            for key in ("business_description", "report_subtitle", "outlook_valuation"):
                if refreshed_sections.get(key):
                    narrative_sections[key] = refreshed_sections[key]

            analytical_bullets = refreshed_sections.get("key_highlights", []) or []
            if analytical_bullets:
                # Keep only analytical bullets that still contain a number —
                # Result Highlights must stay data-first after Stage 12b.
                numeric_analytical = [
                    b for b in analytical_bullets
                    if b and re.search(r"\d", b)
                    and not any(p in b for p in (
                        "grew + YoY", "+% YoY", "[VERIFIED]", "[N/A]", "KEY_HIGHLIGHTS",
                    ))
                ]
                combined = list(verified_highlights)
                for bullet in numeric_analytical:
                    if bullet not in combined:
                        combined.append(bullet)
                # Re-run bullet validation after the merge.
                _ae_errs, _ae_warns = validate_bullets(combined)
                if _ae_errs:
                    combined = [
                        b for b in combined
                        if b and not any(p in b for p in (
                            "grew + YoY", "+% YoY", "[VERIFIED]", "[N/A]", "KEY_HIGHLIGHTS",
                        ))
                    ] or list(verified_highlights)
                narrative_sections["key_highlights"] = combined[:8]
                skipped = len(analytical_bullets) - len(numeric_analytical)
                print(
                    f"     [Analytical Engine] Merged {len(numeric_analytical)} "
                    f"numeric analytical bullets with {len(verified_highlights)} "
                    f"verified highlights"
                    + (f" (skipped {skipped} numberless)." if skipped else ".")
                )

        if analytical_result and analytical_result.cross_metric_observations:
            print(
                f"     [Analytical Engine] {len(analytical_result.cross_metric_observations)} "
                f"cross-metric observations; quality={analytical_result.earnings_quality_score}"
            )
    except Exception as exc:
        print(f"     [Analytical Engine] Failed (non-fatal): {exc}")

    # ── Sector extra metrics (latest actual FY + this filing's quarters) ──────
    extra_metrics = []
    extra_metric_periods = []
    _period_keys = []
    _qtr_key = {
        prev_yr_label: "q_prev_year",
        prev_qtr_label: "q_prev_qtr",
        report_period: "q_current",
    }
    for display in (latest_actual_fy, prev_yr_label, prev_qtr_label, report_period):
        if not display or display in extra_metric_periods:
            continue
        extra_metric_periods.append(display)
        _period_keys.append(_qtr_key.get(display, _period_attr(display)))

    def _display_value(value):
        if value is None or str(value).strip() in {"", "None", "—", "â€”", "-"}:
            return "—"
        return value

    def _raw_metric_value(raw_key, period_key):
        item = (raw_financials or {}).get(raw_key, {})
        if isinstance(item, dict) and item.get(period_key) is not None:
            return _display_value(item.get(period_key))
        if raw_key == "ebitda_margin":
            revenue_item = (raw_financials or {}).get("revenue", {})
            ebitda_item = (raw_financials or {}).get("ebitda", {})
            revenue = revenue_item.get(period_key) if isinstance(revenue_item, dict) else None
            ebitda = ebitda_item.get(period_key) if isinstance(ebitda_item, dict) else None
            try:
                if revenue and ebitda and float(revenue) > 0:
                    return round(float(ebitda) / float(revenue) * 100, 1)
            except Exception:
                pass
        return "—"

    def _append_metric(label, raw_key, source_item=None):
        values = {}
        for display_period, period_key in zip(extra_metric_periods, _period_keys):
            value = _qval(source_item, period_key) if source_item is not None else _raw_metric_value(raw_key, period_key)
            values[display_period] = _display_value(value)
        if any(value != "—" for value in values.values()):
            extra_metrics.append({"metric": label, **values})

    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics  # dict of {key: FinancialLineItem}
        for label, attr in [
            ("NIM (%)", "nim"), ("GNPA (%)", "gnpa"), ("NNPA (%)", "nnpa"),
            ("PCR (%)", "pcr"), ("CASA Ratio (%)", "casa_ratio"),
            ("Capital Adequacy (%)", "capital_adequacy"), ("ROE (%)", "roe"),
            ("ROA (%)", "roa"), ("Credit Growth (%)", "credit_growth"),
        ]:
            item = bm.get(attr) if isinstance(bm, dict) else getattr(bm, attr, None)
            _append_metric(label, attr, source_item=item)

    existing_labels = {row["metric"] for row in extra_metrics}
    for label, raw_key in getattr(cfg, "extra_metrics", []) or []:
        if label not in existing_labels:
            before = len(extra_metrics)
            _append_metric(label, raw_key)
            if len(extra_metrics) > before:
                existing_labels.add(label)

    from pipeline.utils.adaptive_schema import discover_extra_metrics
    _used_keys = [raw_key for _, raw_key in (getattr(cfg, "extra_metrics", []) or [])]
    _used_keys += [
        "nim", "gnpa", "nnpa", "pcr", "casa_ratio", "capital_adequacy",
        "roe", "roa", "credit_growth", "tier1_ratio",
    ]
    _discovered = discover_extra_metrics(
        raw_financials or {},
        existing_labels,
        _used_keys,
        list(zip(extra_metric_periods, _period_keys)),
    )
    if _discovered:
        extra_metrics.extend(_discovered[:4])
        print(
            f"     [Adaptive schema] Kept {min(4, len(_discovered))} extra source metric(s) "
            f"(capped so the Geojit 4-page frame does not overflow)."
        )

    def _latest_snapshot(line_item):
        current = _qval(line_item, "q_current")
        if current != "—":
            return current, report_period
        label, annual = _item_latest_actual(line_item)
        if annual != "—":
            return annual, label
        return "—", None

    latest_balance_sheet = []
    for label, item in [("Cash", bs.cash_and_equivalents), ("Accounts Receivable", bs.accounts_receivable),
                        ("Investments", bs.investments), ("Total Assets", bs.total_assets),
                        ("Total Debt", bs.total_debt), ("Shareholder Funds", bs.total_equity)]:
        value, period = _latest_snapshot(item)
        if value != "—":
            latest_balance_sheet.append({"metric": label, "value": value, "period": period})

    latest_cash_flow = []
    for label, item in [("Operating Cash Flow", cf.operating_cash_flow), ("Investing Cash Flow", cf.investing_cash_flow),
                        ("Financing Cash Flow", cf.financing_cash_flow), ("Free Cash Flow", cf.free_cash_flow)]:
        value, period = _latest_snapshot(item)
        if value != "—":
            latest_cash_flow.append({"metric": label, "value": value, "period": period})
    latest_periods = [row["period"] for row in latest_balance_sheet + latest_cash_flow if row.get("period")]
    latest_period = report_period if report_period in latest_periods else (latest_periods[0] if latest_periods else report_period)

    # ── Build ROM ────────────────────────────────────────────────────────────
    def _year_slot(label, value):
        if not label or value in (None, "—"):
            return {}
        return {label: value}

    bs_year = (
        _item_latest_actual(bs.total_assets)[0]
        or _item_latest_actual(bs.total_equity)[0]
        or latest_actual_fy
    )
    total_assets_latest = _qval(bs.total_assets, _period_attr(bs_year)) if bs_year else "—"
    total_equity_latest = _qval(bs.total_equity, _period_attr(bs_year)) if bs_year else "—"
    total_debt_latest   = _qval(bs.total_debt, _period_attr(bs_year)) if bs_year else "—"
    cash_latest         = _qval(bs.cash_and_equivalents, _period_attr(bs_year)) if bs_year else "—"

    _pat_est_map = est_row(pl.pat, "pat") or {}
    _eps_est_map = est_row(pl.eps, "eps") or {}
    _ebd_est_map = {
        k: v for k, v in (est_row(pl.ebitda, "ebitda") or {}).items()
        if v not in (None, "—") and float(v) != 0
    }
    estimate_years = (
        _first_estimate_labels(_eps_est_map)
        or _first_estimate_labels(_pat_est_map)
        or _first_estimate_labels(est_row(pl.revenue, "revenue"))
    )
    est1 = estimate_years[0] if len(estimate_years) > 0 else None
    est2 = estimate_years[1] if len(estimate_years) > 1 else None

    pat_est1 = _pat_est_map.get(est1, "—") if est1 else "—"
    if pat_est1 in (None, "—"):
        pat_est1 = _qval(pl.pat, _period_attr(est1)) if est1 else "—"

    roe_slot = "—"
    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics
        roe_item = bm.get("roe") if isinstance(bm, dict) else getattr(bm, "roe", None)
        roe_q = _qval(roe_item, "q_current")
        if roe_q != "—":
            roe_slot = roe_q
    if roe_slot == "—":
        try:
            if pat_est1 != "—" and total_equity_latest != "—" and float(total_equity_latest) > 0:
                roe_slot = round(float(pat_est1) / float(total_equity_latest) * 100, 1)
        except Exception:
            pass
    if roe_slot == "—" and market_data and market_data.get("roe_pct") is not None:
        roe_slot = market_data["roe_pct"]
    if roe_slot == "—" and market_data and pat_est1 != "—":
        try:
            bv = market_data.get("book_value_per_share")
            sh_cr = market_data.get("outstanding_shares_cr")
            if bv and sh_cr and float(bv) > 0 and float(sh_cr) > 0:
                equity_cr = float(bv) * float(sh_cr)
                roe_slot = round(float(pat_est1) / equity_cr * 100, 1)
        except Exception:
            pass

    de_slot = "—"
    try:
        if total_debt_latest != "—" and total_equity_latest != "—" and float(total_equity_latest) > 0:
            de_slot = round(float(total_debt_latest) / float(total_equity_latest), 2)
    except Exception:
        pass
    if de_slot == "—" and market_data and market_data.get("de_ratio") is not None:
        de_slot = market_data["de_ratio"]

    ev_cr = market_data.get("enterprise_value_cr") if market_data else None

    def _implied_pe(eps_val):
        try:
            if cmp_val and eps_val not in (None, "—") and float(eps_val) > 0:
                return round(float(cmp_val) / float(eps_val), 1)
        except (TypeError, ValueError):
            pass
        return "—"

    def _ev_to_ebitda(ebd_val):
        try:
            if ev_cr and ebd_val not in (None, "—") and float(ebd_val) > 0:
                return round(float(ev_cr) / float(ebd_val), 1)
        except (TypeError, ValueError):
            pass
        return "—"

    pe_slot1 = _implied_pe(_eps_est_map.get(est1) if est1 else None)
    pe_slot2 = _implied_pe(_eps_est_map.get(est2) if est2 else None)
    ev_ebitda_slot1 = _ev_to_ebitda(_ebd_est_map.get(est1) if est1 else None)
    ev_ebitda_slot2 = _ev_to_ebitda(_ebd_est_map.get(est2) if est2 else None)
    # Keep fy26e/fy27e aliases for the two Geojit valuation columns.
    pe_fy26e, pe_fy27e = pe_slot1, pe_slot2
    ev_ebitda_fy26e, ev_ebitda_fy27e = ev_ebitda_slot1, ev_ebitda_slot2
    roe_fy26e, de_fy26e = roe_slot, de_slot

    # ROCE — not available from extraction/yfinance; leave None (template skips empty)
    roce_pct = None


    # ── Stage 12c: Sanity Verifier — check computed values before PDF ────────
    # Catches absurd ratios (ROE 3829%, D/E 1854x) from unit mismatches and
    # nullifies them so the report shows "—" instead of a wrong number.
    try:
        sanity_mod = importlib.import_module("pipeline.12c_sanity_verifier.sanity_checker")
        _sanity_rom = {
            "ratios": {
                "roe": ratio_roe, "roa": ratio_roa,
                "net_margin": ratio_net_margin, "ebitda_margin": ratio_ebitda_margin,
                "de": ratio_de,
            },
            "rev_growth": rev_growth, "pat_growth": pat_growth,
        }
        sanity_report = sanity_mod.SanityVerifier.verify(_sanity_rom, sector=industry)
        if not sanity_report.passed:
            # Apply corrections in-place to the ratio/growth dicts
            _corrected = sanity_mod.SanityVerifier.apply_corrections(_sanity_rom, sanity_report)
            ratio_roe            = _corrected["ratios"]["roe"]
            ratio_roa            = _corrected["ratios"]["roa"]
            ratio_net_margin     = _corrected["ratios"]["net_margin"]
            ratio_ebitda_margin  = _corrected["ratios"]["ebitda_margin"]
            ratio_de             = _corrected["ratios"]["de"]
            rev_growth           = _corrected["rev_growth"]
            pat_growth           = _corrected["pat_growth"]
        print(f"     [Pipeline] Sanity gate: {'PASSED' if sanity_report.passed else 'CORRECTED'} "
              f"— {sanity_report.summary}")
    except Exception as e:
        print(f"     [Sanity Verifier] Failed (non-blocking): {e}")

    # ── Stage 12f: Evidence + chart gate before report construction ──────────
    # Verify the exact source-backed inputs consumed by the charts and ROM.
    # Estimates/live market fields remain outside this source-document gate.
    evidence_audit = None
    try:
        evidence_mod = importlib.import_module(
            "pipeline.12f_report_evidence_verifier.verifier"
        )
        evidence_audit = evidence_mod.verify_report_inputs(
            ocr_text=ocr_text or "",
            raw_financials=raw_financials or {},
            annual_data=annual_data,
            quarterly_data=quarterly_data,
            charts=charts,
            source_value_factor=source_value_factor,
            output_stem=Path(safe_filename or file_filename or derived_name).stem,
        )
        if evidence_audit.blocked:
            raise ValueError(
                "Stage 12f evidence gate blocked PDF generation: "
                + "; ".join(evidence_audit.warnings[:3])
            )
    except ValueError:
        raise
    except Exception as e:
        print(f"     [Evidence Verifier] Failed (blocking): {e}")
        raise RuntimeError("Stage 12f evidence verification failed.") from e

    # Source old-vs-new lives in estimate_revision (Stage 08b). Do not invent
    # an "old" baseline from YoY or a 10% default.
    change_in_estimates = {}

    # Helper: use source-extracted values only.
    def _md(key, *fallbacks):
        for f in fallbacks:
            if f is not None:
                return f
        return None

    _mc = market_data  # shorthand

    # Preserve the source extractor's estimate-revision payload.  The ROM also
    # computes a deterministic revision table below, but discarding this
    # payload made the first Page 2 estimate-revision table impossible to
    # render even when the source document contained it.
    source_estimate_revision = vd.get("estimate_revision", {}) or {}
    if not isinstance(source_estimate_revision, dict):
        source_estimate_revision = {}

    from pipeline.official_sources import official_sources_for
    official_sources = official_sources_for(
        derived_name,
        period=report_period,
        ocr_text=ocr_text or "",
        source_filename=safe_filename or file_filename or "",
    )

    _financials = {
        "sector_cfg":   cfg,
        "is_banking_sector": _is_banking_sector,
        "annual":       {"revenue": rev_annual, "ebitda": ebitda_annual,
                         "pat": pat_annual, "eps": eps_annual,
                         "depreciation": dep_annual, "ebit": ebit_annual,
                         "interest": interest_ann, "pbt": pbt_annual,
                         "tax": tax_annual},
        "forecasts":    {"revenue": est_row(pl.revenue, "revenue"),
                         "ebitda":  {k: v for k, v in est_row(pl.ebitda, "ebitda").items() if v and float(v) != 0},
                         "pat":     est_row(pl.pat,     "pat"),
                         "eps":     {k: v for k, v in est_row(pl.eps, "eps").items() if v and float(v) != 0},
                         "depreciation": est_row(pl.depreciation, "depreciation"),
                         "ebit":    {k: v for k, v in est_row(pl.ebit, "ebit").items() if v and float(v) != 0},
                         "interest":est_row(pl.interest,"interest"),
                         "pbt":     est_row(pl.pbt,     "pbt"),
                         "tax":     est_row(pl.tax,     "tax")},
        "annual_growth":{"revenue": rev_growth, "pat": pat_growth},
        "change_in_estimates": change_in_estimates,
        "quarterly":    quarterly_data,
        "presentation": presentation,
        "chart_period_note": (
            f"Available periods: {len(quarterly_data.get('revenue', {}))} quarterly / "
            f"{len(annual_data.get('revenue', {}))} annual; charts use validated source data only."
        ),
        "evidence_audit": evidence_audit.to_dict() if evidence_audit else {},
        "ratios":       {"ebitda_margin": ratio_ebitda_margin,
                         "net_margin":    ratio_net_margin,
                         "roe":           ratio_roe,
                         "roa":           ratio_roa,
                         "de":            ratio_de,
                         "rev_growth":   ratio_rev_growth,
                         "pat_growth":   ratio_pat_growth,
                         "roce":          _year_slot(latest_actual_fy, roce_pct),
                         "pe":            _merge(_year_slot(latest_actual_fy, pe_now),
                                                 _year_slot(est1, pe_fy26e if pe_fy26e != "—" else None),
                                                 _year_slot(est2, pe_fy27e if pe_fy27e != "—" else None)),
                         "pb":            _year_slot(latest_actual_fy, pb_now),
                         "ev_ebitda":     _merge(_year_slot(est1, ev_ebitda_fy26e if ev_ebitda_fy26e != "—" else None),
                                                 _year_slot(est2, ev_ebitda_fy27e if ev_ebitda_fy27e != "—" else None))},
        "balance_sheet":{"total_assets": _merge(_year_slot(bs_year, total_assets_latest), _trim(bs_total_assets),
                                                 projections.get("total_assets", {})),
                         "total_equity": _merge(_year_slot(bs_year, total_equity_latest), _trim(bs_total_equity),
                                                 projections.get("total_equity", {})),
                         "total_debt":   _merge(_year_slot(bs_year, total_debt_latest),   _trim(bs_total_debt),
                                                 projections.get("total_debt", {})),
                         "cash":         _merge(_year_slot(bs_year, cash_latest),         _trim(bs_cash),
                                                 projections.get("cash", {})),
                         "receivables":  _trim(bs_receivables),
                         "inventories":  _trim(bs_inventories),
                         "investments":  _trim(bs_investments),
                         "gross_fixed_assets": _trim(bs_gfa),
                         "net_fixed_assets":   _trim(bs_nfa)},
        "cash_flow":    {"operating": _merge(_year_slot(bs_year, _qval(cf.operating_cash_flow, _period_attr(bs_year)) if bs_year else "—"),
                                              _trim(cf_operating), projections.get("operating_cf", {})),
                         "investing":  _merge(_year_slot(bs_year, _qval(cf.investing_cash_flow, _period_attr(bs_year)) if bs_year else "—"),
                                              _trim(cf_investing), projections.get("investing_cf", {})),
                         "financing":  _merge(_year_slot(bs_year, _qval(cf.financing_cash_flow, _period_attr(bs_year)) if bs_year else "—"),
                                              _trim(cf_financing), projections.get("financing_cf", {})),
                         "free_cash_flow": _trim(cf_fcf)},
        "extra_metrics":  extra_metrics,
        "extra_metric_periods": extra_metric_periods,
        "estimate_years": estimate_years,
        "latest_balance_sheet": latest_balance_sheet,
        "latest_cash_flow": latest_cash_flow,
        "latest_period": latest_period,
        "shareholding":   sh_data,
        "valuation_table":{"years": estimate_years,
                           "multiples": {
            "metric": ["Implied P/E at CMP (x)", "P/B", "EV/EBITDA", "ROE (%)", "D/E"],
            "fy26e":  [pe_fy26e if pe_fy26e != "—" else "—",
                       pb_now if pb_now is not None else "—",
                       ev_ebitda_fy26e if ev_ebitda_fy26e != "—" else "—",
                       roe_fy26e, de_fy26e],
            "fy27e":  [pe_fy27e if pe_fy27e != "—" else "—",
                       pb_now if pb_now is not None else "—",
                       ev_ebitda_fy27e if ev_ebitda_fy27e != "—" else "—",
                       roe_fy26e, de_fy26e],
        }},
        "estimate_revision": source_estimate_revision,
        "fact_check": fact_check_report.to_dict(),
        "scenarios": analytical_result.scenarios if analytical_result else [],
        "analytical_observations": (
            analytical_result.cross_metric_observations if analytical_result else []
        ),
        "earnings_quality_score": (
            analytical_result.earnings_quality_score if analytical_result else ""
        ),
        "segment_breakdown": (
            {"labels": list(segment_data.keys()), "values": list(segment_data.values())}
            if segment_data else {}
        ),
    }
    _na_valuation = _qval(None, "fy25")
    valuation_metrics = ["Implied P/E at CMP (x)", "P/B", "ROE (%)", "D/E"]
    valuation_fy26e = [
        pe_fy26e if pe_fy26e != _na_valuation else _na_valuation,
        pb_now if pb_now is not None else _na_valuation,
        roe_fy26e,
        de_fy26e,
    ]
    valuation_fy27e = [
        pe_fy27e if pe_fy27e != _na_valuation else _na_valuation,
        pb_now if pb_now is not None else _na_valuation,
        roe_fy26e,
        de_fy26e,
    ]
    if not _is_banking_sector:
        valuation_metrics.insert(2, "EV/EBITDA")
        valuation_fy26e.insert(2, ev_ebitda_fy26e if ev_ebitda_fy26e != _na_valuation else _na_valuation)
        valuation_fy27e.insert(2, ev_ebitda_fy27e if ev_ebitda_fy27e != _na_valuation else _na_valuation)
    _financials["valuation_table"]["years"] = estimate_years
    _financials["valuation_table"]["multiples"] = {
        "metric": valuation_metrics,
        "fy26e": valuation_fy26e,
        "fy27e": valuation_fy27e,
    }

    from pipeline.report_quality import build_all_columns
    _financials["all_columns"] = build_all_columns(_financials)
    print(f"     [Pipeline] Table columns: {_financials['all_columns']}")

    report_data = stage_14.ROMBuilder.run(
        fa_narrative=fa_narrative_raw,
        fa_evidence=fa_evidence,
        source_context={
            "company": schema_mod.CompanyInfo(
                name=derived_name, sector=industry,
                report_date=datetime.now().strftime("%B %d, %Y"),
                period=report_period,
                cmp=cmp_val,
                target_price=target_val, upside_pct=upside_val,
                market_cap_cr=_md("market_cap_cr",
                                   _vnum(val_raw, "market_cap_cr")),
                enterprise_value_cr=_md("enterprise_value_cr",
                                         _vnum(val_raw, "enterprise_value_cr")),
                week52_high=_md("week52_high",
                                _vnum(val_raw, "week52_high")),
                week52_low=_md("week52_low",
                               _vnum(val_raw, "week52_low")),
                beta=_md("beta", _vnum(val_raw, "beta")),
                free_float_pct=_md("free_float_pct",
                                   _vnum(val_raw, "free_float_pct")),
                outstanding_shares_cr=_md("outstanding_shares_cr",
                                         _vnum(val_raw, "outstanding_shares_cr")),
                dividend_yield_pct=_md("dividend_yield_pct",
                                       _vnum(val_raw, "dividend_yield_pct")),
                stock_type=None,
                face_value=_vnum(val_raw, "face_value"),
                nse_code=None,
                bse_code=None,
                sensex_value=None,
                avg_volume_6m=None,
            ),
            "business_description": _repair_narrative(narrative_sections["business_description"]),
            "key_highlights": [
                h for h in (
                    _repair_narrative(x) for x in (narrative_sections["key_highlights"] or []) if x
                )
                if h and not re.match(r"^\s*(cr|bn|mn)\)", h, re.I)
            ],
            "report_subtitle": _repair_narrative(narrative_sections["report_subtitle"]),
            "outlook_valuation": _repair_narrative(narrative_sections["outlook_valuation"]),
            "executive_summary": _repair_narrative(narrative_sections["business_description"]),
            "risks": [b for b in narrative_sections["key_highlights"]
                      if any(w in b.lower() for w in
                             ["risk","decline","fell","pressure","concern","weak"])]
                     or list(kg.get("risks_and_challenges") or []),
            "management_commentary": (kg.get("management_commentary") or [""])[0],
            "investment_view": narrative_sections["outlook_valuation"],
            "recommendation": schema_mod.RecommendationNode(
                action=rec_action,
                target_price=target_val, cmp=cmp_val, expected_return_pct=upside_val,
                rationale=narrative_sections["outlook_valuation"] or
                          "CMP and target price not available in source document.",
            ),
            "financials": _financials,
            "charts": charts,
            "appendix": {
                "source": file_filename or safe_filename,
                "verified_count": fact_check_report.verified_count,
                "total_count": fact_check_report.total,
                "provenance_labels": {
                    "source_fact": "Extracted from uploaded source and source-verified",
                    "calculated": "Derived deterministically from verified values",
                    "ai_narrative": "AI-written qualitative synthesis; not a human analyst opinion",
                    "ai_estimate": "Model projection marked E; not company guidance",
                    "not_available": "Field not present or not supportable from the source",
                },
                "stock_chart": stock_chart_b64,
                "price_performance": price_perf,
                "target_estimated": target_estimated,
                "ai_scenario": ai_scenario,
                "sanity_check": sanity_report.to_dict() if 'sanity_report' in dir() else {},
                "cross_source_verification": cross_source_report.to_dict(),
                "official_sources": official_sources,
                "research_quality": {
                    "primary_source_score": round(fact_check_report.score, 3),
                    "secondary_source_score": round(cross_source_report.score, 3),
                    "review_flags": list(cross_source_report.review_flags),
                },
                "analytical_insights": (
                    analytical_result.appendix if analytical_result else {}
                ),
            },
            "source_coverage": {
                "source": file_filename or safe_filename,
                "verified_count": fact_check_report.verified_count,
                "total_count": fact_check_report.total,
                "method": "uploaded-source verification",
            },
            "scorecard": (
                importlib.import_module("pipeline.09_quant_engine.scorecard_engine")
                .ScorecardEngine.compute(
                    fa_evidence,
                    {
                        "industry": industry,
                        "fact_check": {
                            "total": getattr(fact_check_report, "total", 0),
                            "verified_count": getattr(fact_check_report, "verified_count", 0),
                        },
                    },
                )
            ),
            "segment_breakdown":    schema_mod.SegmentBreakdown(
                                        labels=list(segment_data.keys()),
                                        values=list(segment_data.values())),
            "geography_breakdown":  schema_mod.GeographyBreakdown(
                                        regions=list(geo_data.keys()),
                                        percentages=list(geo_data.values()),
                                        strongest_region=max(geo_data, key=geo_data.get) if geo_data else None,
                                        weakest_region=min(geo_data, key=geo_data.get) if geo_data else None),
            "swot":                 schema_mod.SWOTMatrix(),
            "red_flags":            schema_mod.RedFlagsReport(),
            "ceo_outlook":          schema_mod.CEOOutlook(),
            "client_profile":       schema_mod.ClientProfile(),
            "employee_stats":       schema_mod.EmployeeStats(),
            "investment_snapshot":  schema_mod.InvestmentSnapshot(
                                        report_date=report_period, industry=industry),
            "ai_investment_thesis": schema_mod.AIInvestmentThesis(),
            "evidence_summary":     schema_mod.EvidenceSummary(),
            "business_drivers":     schema_mod.BusinessDrivers(),
            "trend_indicators":     schema_mod.TrendIndicators(),
            "chart_commentary":     schema_mod.AIChartCommentary(),
            "ai_deep_research":     schema_mod.AIDeepResearch(
                business_quality=narrative_sections["business_description"],
                risk="\n".join(narrative_sections["key_highlights"]),
                outlook=narrative_sections["outlook_valuation"],
            ),
        },
    )

    # ── Stage 16: hide empty Geojit boxes; do not invent a new page map ──
    try:
        _planner_mod = importlib.import_module("pipeline.16_adaptive_section_planner.planner")
        AdaptiveSectionPlanner = _planner_mod.AdaptiveSectionPlanner

        # Build narrative sections dict for the planner
        planner_narratives = {
            "business_description": narrative_sections.get("business_description", ""),
            "report_subtitle": narrative_sections.get("report_subtitle", ""),
            "outlook_valuation": narrative_sections.get("outlook_valuation", ""),
            "key_highlights": narrative_sections.get("key_highlights", []),
        }

        # Build market data dict for the planner
        planner_market_data = {
            "cmp": _first(cmp_val, _mc.get("cmp")),
            "market_cap_cr": _md("market_cap_cr", _vnum(val_raw, "market_cap_cr")),
            "enterprise_value_cr": _md("enterprise_value_cr", _vnum(val_raw, "enterprise_value_cr")),
            "week52_high": _md("week52_high", _vnum(val_raw, "week52_high")),
            "week52_low": _md("week52_low", _vnum(val_raw, "week52_low")),
            "beta": _md("beta", _vnum(val_raw, "beta")),
            "free_float_pct": _md("free_float_pct", _vnum(val_raw, "free_float_pct")),
            "dividend_yield_pct": _md("dividend_yield_pct", _vnum(val_raw, "dividend_yield_pct")),
            "outstanding_shares_cr": _md("outstanding_shares_cr", _vnum(val_raw, "outstanding_shares_cr")),
            "stock_type": _mc.get("stock_type"),
            "face_value": _mc.get("face_value"),
            "nse_code": _mc.get("nse_code"),
            "bse_code": _mc.get("bse_code"),
            "sensex_value": _mc.get("sensex_value"),
            "avg_volume_6m": _mc.get("avg_volume_6m"),
        }

        # Build recommendation object for the planner
        planner_recommendation = schema_mod.RecommendationNode(
            action=rec_action,
            target_price=target_val, cmp=cmp_val, expected_return_pct=upside_val,
        )

        # Get unit label from sector config
        planner_unit_label = getattr(cfg, "unit_label", "Rs. cr") if cfg else "Rs. cr"

        # Run the adaptive section planner
        report_data.sections = AdaptiveSectionPlanner.plan(
            financials=_financials,
            company_name=derived_name,
            industry=industry,
            report_period=report_period,
            recommendation=planner_recommendation,
            narrative_sections=planner_narratives,
            market_data=planner_market_data,
            charts=charts,
            fact_check_report=fact_check_report,
            appendix=report_data.appendix,
            unit_label=planner_unit_label,
            currency_symbol="Rs.",
            segment_data=segment_data,
            geo_data=geo_data,
        )
        print(f"     [Pipeline] Adaptive section planner: {len(report_data.sections)} sections built")
    except Exception as e:
        print(f"     [Pipeline] Adaptive section planner failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()

    return report_data
