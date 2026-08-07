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

# (Screener.in historical data fetcher removed — extraction + yfinance cover all needed data)


def _qval(line_item, period, default="—"):
    try:
        if line_item is None:
            return default
        v = getattr(line_item, period, None)
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
) -> Any:
    schema_mod = importlib.import_module("schema")
    stage_11_charts = importlib.import_module("pipeline.11_chart_generator")
    stage_14 = importlib.import_module("pipeline.14_report_object_model.rom_builder")

    from pipeline.sectors import get_sector_config
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

    # Prior-year same-quarter label: decrement the FY year by 1 (e.g. Q2FY26 → Q2FY25)
    _fy_match = re.search(r'FY(\d{2,4})', report_period)
    if _fy_match:
        _fy_num = int(_fy_match.group(1))
        _fy_width = len(_fy_match.group(1))
        prev_yr_label = report_period.replace(
            f"FY{_fy_num:0{_fy_width}d}", f"FY{_fy_num - 1:0{_fy_width}d}")
    else:
        prev_yr_label = report_period
    prev_qtr_label = ("Q1FY26" if "Q2FY26" in report_period else
                      "Q3FY26" if "Q4FY26" in report_period else
                      "Q2FY26")

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

    def _format_amount(value):
        symbol = _cfg_value("currency_symbol", "Rs.")
        suffix = _cfg_value("unit_suffix", "cr")
        return f"{symbol}{value} {suffix}" if symbol == "₹" else f"{symbol} {value}{suffix}"

    if rev_q_cur != "—" and rev_yoy_pct != "—":
        _rev_dir = "up" if float(rev_yoy_pct) > 0 else "down"
        verified_highlights.append(
            f"{pl_label} for {report_period} stood at {_format_amount(rev_q_cur)}, "
            f"{_rev_dir} {abs(float(rev_yoy_pct))}% YoY"
            + (f" and {rev_qoq_pct}% QoQ" if rev_qoq_pct != "—" else "") + ".")
    if pat_q_cur != "—" and pat_yoy_pct != "—":
        _pat_dir = "up" if float(pat_yoy_pct) > 0 else "down"
        verified_highlights.append(
            f"{pat_label} for {report_period} was {_format_amount(pat_q_cur)}, "
            f"{_pat_dir} {abs(float(pat_yoy_pct))}% YoY.")
    ebitda_q = _qval(pl.ebitda, "q_current")
    if ebitda_q != "—":
        verified_highlights.append(f"{ebitda_label} for the quarter was {_format_amount(ebitda_q)}.")
    # PBT highlight (works for banks and non-banks)
    pbt_q = _qval(pl.pbt, "q_current")
    if pbt_q != "—":
        verified_highlights.append(f"PBT for {report_period} was {_format_amount(pbt_q)}.")
    # Banking-specific verified metrics
    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics  # dict of {key: FinancialLineItem}
        for label, attr in [("NIM", "nim"), ("GNPA", "gnpa"), ("NNPA", "nnpa"),
                            ("CASA Ratio", "casa_ratio"), ("Capital Adequacy", "capital_adequacy")]:
            item = bm.get(attr) if isinstance(bm, dict) else getattr(bm, attr, None)
            v = _qval(item, "q_current")
            if v != "—":
                verified_highlights.append(f"{label} stood at {v}% in {report_period}.")
    # Banking advances/deposits growth (key for bank reports)
    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics
        for label, attr in [("Advances", "advances"), ("Deposits", "deposits")]:
            item = bm.get(attr) if isinstance(bm, dict) else getattr(bm, attr, None)
            cur = _qval(item, "q_current")
            prev = _qval(item, "q_prev_year")
            growth = _growth(cur, prev)
            if cur != "—" and growth != "—":
                _dir = "up" if float(growth) > 0 else "down"
                verified_highlights.append(
                    f"{label} {label.lower()} stood at {_format_amount(cur)}, "
                    f"{_dir} {abs(float(growth))}% YoY.")
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
        return {y: _qval(line_item, a) for y, a in
                [("FY22","fy22"),("FY23","fy23"),("FY24","fy24"),("FY25","fy25")]}

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
        out = {}
        for k, v in d.items():
            kk = re.sub(r"A$", "", str(k))   # "FY25A" → "FY25"
            if re.match(r"FY2[2-5]$", kk) and v is not None and v != "—":
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

    # Append annual trend to verified highlights (rev_avail/pat_avail now defined)
    if len(rev_avail) > 1:
        yrs = sorted(rev_avail.keys())
        verified_highlights.append(
            f"{pl_label} grew from {_format_amount(rev_avail[yrs[-2]])} in {yrs[-2]} "
            f"to {_format_amount(rev_avail[yrs[-1]])} in {yrs[-1]}.")
    if len(pat_avail) > 1:
        yrs = sorted(pat_avail.keys())
        verified_highlights.append(
            f"{pat_label} grew from {_format_amount(pat_avail[yrs[-2]])} in {yrs[-2]} "
            f"to {_format_amount(pat_avail[yrs[-1]])} in {yrs[-1]}.")

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

    # ── AI Forward Projections (FY26E/FY27E) ─────────────────────────────────
    # Forward estimates are deterministic and explicitly marked as estimates.
    # LLMs may explain assumptions, but they do not supply report numbers.
    print("     [Pipeline] Generating deterministic forward estimates...")
    projections = {}
    ForwardProjector = importlib.import_module(
        "pipeline.09_quant_engine.projections"
    ).ForwardProjector

    def _project_series(values):
        clean = {}
        for year, value in (values or {}).items():
            if value not in (None, "—", "[N/A]"):
                try:
                    clean[str(year).replace("A", "")] = float(value)
                except (TypeError, ValueError):
                    pass
        if "FY25" not in clean:
            return {}
        growth = 0.05
        if "FY24" in clean and clean["FY24"] != 0:
            growth = (clean["FY25"] - clean["FY24"]) / abs(clean["FY24"])
            growth = max(ForwardProjector.MIN_GROWTH_RATE,
                         min(ForwardProjector.MAX_GROWTH_RATE, growth))
        fy26 = round(clean["FY25"] * (1 + growth), 2)
        fy27 = round(fy26 * (1 + growth), 2)
        return {"FY26E": fy26, "FY27E": fy27}

    for key, values in {
        "revenue": rev_annual, "ebitda": ebitda_annual,
        "pat": pat_annual, "eps": eps_annual,
    }.items():
        estimate = _project_series(values)
        if estimate:
            projections[key] = estimate

    def est_row(line_item, proj_key: str = "") -> dict:
        result = {}
        for yr, attr in [("FY26E", "fy26e"), ("FY27E", "fy27e")]:
            if proj_key and proj_key in projections:
                v = projections[proj_key].get(yr)
                if v is not None:
                    result[yr] = v
                    continue
            v = _qval(line_item, attr)
            if v != "—":
                result[yr] = v
        return result

    # ── Add forward estimates to annual_data so charts show FY26E/FY27E bars ──
    annual_data["revenue_est"] = est_row(pl.revenue, "revenue")
    annual_data["pat_est"]     = est_row(pl.pat,     "pat")
    annual_data["ebitda_est"]  = est_row(pl.ebitda,  "ebitda")

    # ── Yahoo Finance stock price chart + performance returns + market data ────
    stock_chart_b64 = ""
    price_perf = {}
    market_data = {}
    try:
        from pipeline.stock_chart import (generate_price_chart,
                                          fetch_price_performance,
                                          fetch_market_data)
        stock_chart_b64 = generate_price_chart(derived_name) or ""
        price_perf      = fetch_price_performance(derived_name) or {}
        market_data     = fetch_market_data(derived_name) or {}
    except Exception as e:
        print(f"     [Stock Chart] Failed (non-blocking): {e}")

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

    # ── Compute FY26E/FY27E ratios from AI projections (fills page 3 ratio columns) ──
    _is_banking_sector = any(token in (industry or '').lower()
                             for token in ('bank', 'nbfc', 'financial services'))
    _rev_est = est_row(pl.revenue, "revenue")
    _pat_est = est_row(pl.pat,     "pat")
    _ebd_est = {k: v for k, v in est_row(pl.ebitda, "ebitda").items() if v and float(v) != 0}
    _eq_fy25  = _qval(bs.total_equity, "fy25")
    _ta_fy25  = _qval(bs.total_assets, "fy25")
    _td_fy25  = _qval(bs.total_debt, "fy25")
    for yr in ["FY26E", "FY27E"]:
        rv = _rev_est.get(yr)
        pv = _pat_est.get(yr)
        ev = _ebd_est.get(yr)
        if not _is_banking_sector and rv and pv and float(rv) > 0:
            ratio_net_margin[yr] = round(float(pv) / float(rv) * 100, 1)
        if rv and ev and float(rv) > 0:
            ratio_ebitda_margin[yr] = round(float(ev) / float(rv) * 100, 1)
        if pv and _eq_fy25 != "—" and float(_eq_fy25) > 0:
            ratio_roe[yr] = round(float(pv) / float(_eq_fy25) * 100, 1)
        if pv and _ta_fy25 != "—" and float(_ta_fy25) > 0:
            ratio_roa[yr] = round(float(pv) / float(_ta_fy25) * 100, 1)
        if _td_fy25 != "—" and _eq_fy25 != "—" and float(_eq_fy25) > 0:
            ratio_de[yr] = round(float(_td_fy25) / float(_eq_fy25), 2)

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

    charts = stage_11_charts.generate_all_charts(
        annual_data=annual_data, quarterly_data=quarterly_data,
        sector_cfg=cfg, segment_data={}, geo_data={})
    if not charts:
        raise ValueError(
            "No chart could be generated from validated financial data; "
            "report generation stopped."
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

    # CMP is "live market price at time of writing" (per research-report taxonomy).
    # Prefer the live yfinance price; fall back to the source-doc CMP only if
    # yfinance has no ticker/failed. Using a single consistent CMP for both the
    # price box and the rating avoids stale-price vs live-price mismatches.
    cmp_val    = _first(market_data.get("cmp"), _vnum(val_raw, "cmp"))
    target_val = _vnum(val_raw, "target_price")
    pe_now     = _first(_vnum(val_raw, "pe_ratio"), market_data.get("pe_ratio"))
    pb_now     = _first(_vnum(val_raw, "pbv_ratio"), market_data.get("pb_ratio"))

    # Sector-default P/E as last resort (so we can always derive a target)
    _SECTOR_DEFAULT_PE = {"banking": 18, "it services": 25, "it - services": 25,
                          "metals": 12, "energy": 15, "power": 14, "auto": 20}
    if pe_now is None:
        pe_now = _SECTOR_DEFAULT_PE.get(industry.lower(), 18)

    # If no analyst target in source doc, estimate: FY26E EPS × current P/E
    target_estimated = False
    if target_val is None and pe_now:
        eps_fy26e = (est_row(pl.eps, "eps") or {}).get("FY26E")
        try:
            if eps_fy26e and float(eps_fy26e) > 0:
                target_val = round(float(eps_fy26e) * pe_now, 0)
                target_estimated = True
        except Exception:
            pass

    upside_val = (round(((target_val - cmp_val) / cmp_val) * 100, 1)
                  if (cmp_val and target_val and cmp_val > 0) else None)

    if upside_val is not None:
        if target_estimated:
            # Mechanical target (P/E × EPS) is sensitive to the assumed P/E.
            # Only issue a directional call when the model and market roughly
            # agree (within ±10%). A larger divergence means the sector-default
            # P/E doesn't fit this stock, so we withhold a rating rather than
            # fabricate a BUY/HOLD/SELL from an unreliable estimate.
            if upside_val > 10:
                rec_action = "BUY"
            elif -10 <= upside_val <= 10:
                rec_action = "HOLD"
            else:
                rec_action = "NOT RATED"
        else:
            # Real analyst target from the source document — apply standard bands.
            rec_action = "BUY" if upside_val > 10 else ("HOLD" if upside_val > 0 else "SELL")
    else:
        rec_action = "NOT RATED"

    # An estimated target can support a transparent scenario, but never the
    # official source-grounded recommendation shown in the badge.
    ai_scenario_action = None
    if target_estimated and upside_val is not None:
        ai_scenario_action = ("BUY" if upside_val > 10 else
                              "HOLD" if upside_val >= -10 else "NOT RATED")
        rec_action = "NOT RATED"
    ai_scenario = {
        "available": bool(target_estimated and upside_val is not None),
        "action": ai_scenario_action,
        "target_price": target_val if target_estimated else None,
        "upside_pct": upside_val if target_estimated else None,
        "method": "FY26E EPS x P/E scenario",
        "label": "AI estimate - not analyst guidance",
    }

    # ── Banking / sector-specific extra metrics ──────────────────────────────
    extra_metrics = []
    extra_metric_periods = ["FY25", prev_yr_label, prev_qtr_label, report_period]
    _period_keys = ["fy25", "q_prev_year", "q_prev_qtr", "q_current"]

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

    def _latest_snapshot(line_item):
        current = _qval(line_item, "q_current")
        if current != "—":
            return current, report_period
        annual = _qval(line_item, "fy25")
        if annual != "—":
            return annual, "FY25"
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
    total_assets_fy25  = _qval(bs.total_assets, "fy25")
    total_equity_fy25  = _qval(bs.total_equity, "fy25")
    total_debt_fy25    = _qval(bs.total_debt, "fy25")
    cash_fy25          = _qval(bs.cash_and_equivalents, "fy25")
    pat_fy26e          = _qval(pl.pat, "fy26e")
    # Fallback: use AI-projected PAT if source extraction didn't have it
    if pat_fy26e == "—":
        pat_fy26e = (est_row(pl.pat, "pat") or {}).get("FY26E", "—")

    roe_fy26e = "—"
    # Prefer source-extracted ROE from banking_metrics (banks report ROE directly)
    if hasattr(fa_evidence, "banking_metrics") and fa_evidence.banking_metrics:
        bm = fa_evidence.banking_metrics
        roe_item = bm.get("roe") if isinstance(bm, dict) else getattr(bm, "roe", None)
        roe_q = _qval(roe_item, "q_current")
        if roe_q != "—":
            roe_fy26e = roe_q
    # Fallback: compute from PAT / equity
    if roe_fy26e == "—":
        try:
            if pat_fy26e != "—" and total_equity_fy25 != "—" and float(total_equity_fy25) > 0:
                roe_fy26e = round(float(pat_fy26e) / float(total_equity_fy25) * 100, 1)
        except Exception:
            pass
    # Fallback 2: use yfinance returnOnEquity
    if roe_fy26e == "—" and market_data and market_data.get("roe_pct") is not None:
        roe_fy26e = market_data["roe_pct"]
    # Fallback 3: compute from PAT / (bookValue per share × shares outstanding)
    if roe_fy26e == "—" and market_data and pat_fy26e != "—":
        try:
            bv = market_data.get("book_value_per_share")
            sh_cr = market_data.get("outstanding_shares_cr")
            if bv and sh_cr and float(bv) > 0 and float(sh_cr) > 0:
                equity_cr = float(bv) * float(sh_cr)
                roe_fy26e = round(float(pat_fy26e) / equity_cr * 100, 1)
        except Exception:
            pass

    # D/E for FY26E — from balance sheet (total_debt / total_equity)
    de_fy26e = "—"
    try:
        if total_debt_fy25 != "—" and total_equity_fy25 != "—" and float(total_equity_fy25) > 0:
            de_fy26e = round(float(total_debt_fy25) / float(total_equity_fy25), 2)
    except Exception:
        pass
    # Fallback: use yfinance debtToEquity ratio
    if de_fy26e == "—" and market_data and market_data.get("de_ratio") is not None:
        de_fy26e = market_data["de_ratio"]

    # ── Forward valuation multiples (P/E, P/B, EV/EBITDA for FY26E/FY27E) ──
    # Derived deterministically from CMP + AI-projected EPS/EBITDA + yfinance EV.
    eps_fy26e = (est_row(pl.eps, "eps") or {}).get("FY26E")
    eps_fy27e = (est_row(pl.eps, "eps") or {}).get("FY27E")
    ebd_fy26e = (est_row(pl.ebitda, "ebitda") or {}).get("FY26E")
    ebd_fy27e = (est_row(pl.ebitda, "ebitda") or {}).get("FY27E")
    ev_cr = market_data.get("enterprise_value_cr") if market_data else None

    pe_fy26e = "—"
    pe_fy27e = "—"
    try:
        if cmp_val and eps_fy26e and float(eps_fy26e) > 0:
            pe_fy26e = round(float(cmp_val) / float(eps_fy26e), 1)
        if cmp_val and eps_fy27e and float(eps_fy27e) > 0:
            pe_fy27e = round(float(cmp_val) / float(eps_fy27e), 1)
    except Exception:
        pass

    ev_ebitda_fy26e = "—"
    ev_ebitda_fy27e = "—"
    try:
        if ev_cr and ebd_fy26e and float(ebd_fy26e) > 0:
            ev_ebitda_fy26e = round(float(ev_cr) / float(ebd_fy26e), 1)
        if ev_cr and ebd_fy27e and float(ebd_fy27e) > 0:
            ev_ebitda_fy27e = round(float(ev_cr) / float(ebd_fy27e), 1)
    except Exception:
        pass

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

    # ── Change in Estimates (Old baseline vs New AI estimates vs Change %) ────
    # "Old" = FY25 actual grown at recent YoY rate (naive baseline)
    # "New" = AI-projected FY26E/FY27E
    # "Change %" = (New - Old) / Old × 100
    def _build_change_in_estimates():
        fc_rev = est_row(pl.revenue, "revenue")
        fc_ebitda = {k: v for k, v in est_row(pl.ebitda, "ebitda").items() if v and float(v) != 0}
        fc_pat = est_row(pl.pat, "pat")
        fc_eps = {k: v for k, v in est_row(pl.eps, "eps").items() if v and float(v) != 0}
        fy25_rev = rev_avail.get("FY25") if rev_avail else None
        fy25_pat = pat_avail.get("FY25") if pat_avail else None
        # Use quarterly YoY as the baseline growth rate, fallback to annual
        growth_rate = (float(rev_yoy_pct) / 100.0) if rev_yoy_pct != "—" else 0.10
        rows = {}
        for metric, new_vals, fy25_actual in [
            ("Revenue", fc_rev, fy25_rev),
            ("EBITDA",  fc_ebitda, None),
            ("PAT",    fc_pat, fy25_pat),
            ("EPS",    fc_eps, None),
        ]:
            old = {}
            base = fy25_actual
            for yr in ("FY26E", "FY27E"):
                if base is not None:
                    try:
                        old[yr] = round(float(base) * (1 + growth_rate), 1)
                        base = old[yr]
                    except Exception:
                        pass
            new = {yr: new_vals.get(yr) for yr in ("FY26E", "FY27E") if new_vals.get(yr) is not None}
            chg = {}
            for yr in ("FY26E", "FY27E"):
                if yr in old and yr in new and old[yr] and old[yr] != 0:
                    try:
                        chg[yr] = round((float(new[yr]) - float(old[yr])) / abs(float(old[yr])) * 100, 1)
                    except Exception:
                        pass
            if old or new:
                rows[metric] = {"old": old, "new": new, "change_pct": chg}
        return rows

    change_in_estimates = _build_change_in_estimates()
    print(f"     [Pipeline] Change in Estimates: {len(change_in_estimates)} metrics computed.")

    # Helper: prefer extracted → Screener → yfinance market_data
    def _md(key, *fallbacks):
        for f in fallbacks:
            if f is not None:
                return f
        return market_data.get(key)

    _mc = market_data  # shorthand

    # Preserve the source extractor's estimate-revision payload.  The ROM also
    # computes a deterministic revision table below, but discarding this
    # payload made the first Page 2 estimate-revision table impossible to
    # render even when the source document contained it.
    source_estimate_revision = vd.get("estimate_revision", {}) or {}
    if not isinstance(source_estimate_revision, dict):
        source_estimate_revision = {}

    from pipeline.official_sources import official_sources_for
    official_sources = official_sources_for(derived_name)

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
        "chart_period_note": (
            f"Available periods: {len(quarterly_data.get('revenue', {}))} quarterly / "
            f"{len(annual_data.get('revenue', {}))} annual; charts use validated source data only."
        ),
        "ratios":       {"ebitda_margin": ratio_ebitda_margin,
                         "net_margin":    ratio_net_margin,
                         "roe":           ratio_roe,
                         "roa":           ratio_roa,
                         "de":            ratio_de,
                         "rev_growth":   ratio_rev_growth,
                         "pat_growth":   ratio_pat_growth,
                         "roce":          {"FY25": roce_pct} if roce_pct is not None else {},
                         "pe":            _merge({"FY25": pe_now} if pe_now is not None else {},
                                                 {"FY26E": pe_fy26e if pe_fy26e != "—" else None,
                                                  "FY27E": pe_fy27e if pe_fy27e != "—" else None}),
                         "pb":            {"FY25": pb_now} if pb_now is not None else {},
                         "ev_ebitda":     _merge({},
                                                 {"FY26E": ev_ebitda_fy26e if ev_ebitda_fy26e != "—" else None,
                                                  "FY27E": ev_ebitda_fy27e if ev_ebitda_fy27e != "—" else None})},
        "balance_sheet":{"total_assets": _merge({"FY25": total_assets_fy25}, _trim(bs_total_assets),
                                                 projections.get("total_assets", {})),
                         "total_equity": _merge({"FY25": total_equity_fy25}, _trim(bs_total_equity),
                                                 projections.get("total_equity", {})),
                         "total_debt":   _merge({"FY25": total_debt_fy25},   _trim(bs_total_debt),
                                                 projections.get("total_debt", {})),
                         "cash":         _merge({"FY25": cash_fy25},         _trim(bs_cash),
                                                 projections.get("cash", {})),
                         "receivables":  _trim(bs_receivables),
                         "inventories":  _trim(bs_inventories),
                         "investments":  _trim(bs_investments),
                         "gross_fixed_assets": _trim(bs_gfa),
                         "net_fixed_assets":   _trim(bs_nfa)},
        "cash_flow":    {"operating": _merge({"FY25": _qval(cf.operating_cash_flow, "fy25")},
                                              _trim(cf_operating), projections.get("operating_cf", {})),
                         "investing":  _merge({"FY25": _qval(cf.investing_cash_flow, "fy25")},
                                              _trim(cf_investing), projections.get("investing_cf", {})),
                         "financing":  _merge({"FY25": _qval(cf.financing_cash_flow, "fy25")},
                                              _trim(cf_financing), projections.get("financing_cf", {})),
                         "free_cash_flow": _trim(cf_fcf)},
        "extra_metrics":  extra_metrics,
        "extra_metric_periods": extra_metric_periods,
        "latest_balance_sheet": latest_balance_sheet,
        "latest_cash_flow": latest_cash_flow,
        "latest_period": latest_period,
        "shareholding":   sh_data,
        "valuation_table":{"multiples": {
            "metric": ["P/E", "P/B", "EV/EBITDA", "ROE (%)", "D/E"],
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
    }
    _na_valuation = _qval(None, "fy25")
    valuation_metrics = ["P/E", "P/B", "ROE (%)", "D/E"]
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
                cmp=_first(cmp_val, _mc.get("cmp")),
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
                # New fields from yfinance
                stock_type=_mc.get("stock_type", "Mid Cap"),
                face_value=_mc.get("face_value"),
                nse_code=_mc.get("nse_code"),
                bse_code=_mc.get("bse_code"),
                sensex_value=_mc.get("sensex_value"),
                avg_volume_6m=_mc.get("avg_volume_6m"),
            ),
            "business_description": narrative_sections["business_description"],
            "key_highlights":       narrative_sections["key_highlights"],
            "report_subtitle":      narrative_sections["report_subtitle"],
            "outlook_valuation":    narrative_sections["outlook_valuation"],
            "executive_summary":    narrative_sections["business_description"],
            "risks": [b for b in narrative_sections["key_highlights"]
                      if any(w in b.lower() for w in
                             ["risk","decline","fell","pressure","concern","weak"])]
                     or ["Sector-specific risks apply. Refer to source document."],
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
            },
            "scorecard": schema_mod.AIScorecard(
                growth=7, financial_health=7, profitability=7,
                innovation=7, ai_readiness=7, execution=7,
                risk_level="Medium",
                confidence_pct=round(
                    float(fact_check_report.verified_count or 0) /
                    float(fact_check_report.total or 1) * 100, 1)),
            "segment_breakdown":    schema_mod.SegmentBreakdown(),
            "geography_breakdown":  schema_mod.GeographyBreakdown(),
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
    return report_data
