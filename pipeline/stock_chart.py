"""
stock_chart.py — Yahoo Finance 1Y stock price chart

Fetches 1-year daily price history for NSE-listed stocks,
plots price line + Sensex overlay, returns base64 PNG.
Falls back gracefully with a styled placeholder if ticker not found.
"""
import base64
import io
import re
from typing import Optional

# Ticker map — company name → NSE ticker (Yahoo format: TICKER.NS)
_TICKER_MAP = {
    "icici bank":                  "ICICIBANK.NS",
    "icici":                       "ICICIBANK.NS",
    "jsw energy":                  "JSWENERGY.NS",
    "jsw energy limited":          "JSWENERGY.NS",
    "l&t technology services":     "LTTS.NS",
    "ltts":                        "LTTS.NS",
    "l&t technology":              "LTTS.NS",
    "pondy oxides":                "POCL.NS",
    "pondy oxides and chemicals":  "POCL.NS",
    "pocl":                        "POCL.NS",
    "hdfc bank":                   "HDFCBANK.NS",
    "tata motors":                 "TATAMOTORS.NS",
    "infosys":                     "INFY.NS",
    "tcs":                         "TCS.NS",
    "wipro":                       "WIPRO.NS",
    "reliance":                    "RELIANCE.NS",
    "sbi":                         "SBIN.NS",
    "state bank":                  "SBIN.NS",
    "bajaj finance":               "BAJFINANCE.NS",
    "maruti":                      "MARUTI.NS",
    "asian paints":                "ASIANPAINT.NS",
    "eternal":                     "ETERNAL.NS",
    "zomato":                      "ZOMATO.NS",
}

_SENSEX_TICKER = "^BSESN"


def _resolve_ticker(company_name: str) -> Optional[str]:
    key = company_name.lower().strip()
    for name, ticker in _TICKER_MAP.items():
        if name in key or key in name:
            return ticker
    # Guess: first word + .NS
    first = re.sub(r"[^a-zA-Z]", "", key.split()[0]).upper()
    return f"{first}.NS" if first else None


def _placeholder_chart(company_name: str) -> str:
    """Return a simple 'Price data not available' placeholder as base64 PNG."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(4, 2))
        ax.text(0.5, 0.5, f"Price chart\nnot available\nfor {company_name}",
                ha="center", va="center", fontsize=9, color="#888",
                transform=ax.transAxes)
        ax.set_axis_off()
        fig.patch.set_facecolor("#f9fafa")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception:
        return ""


def fetch_price_performance(company_name: str) -> dict:
    """
    Compute 3M/6M/1Y absolute, Sensex, and relative returns.
    Returns {"3M": {"abs": x, "sensex": y, "rel": z}, "6M": {...}, "1Y": {...}}.
    Empty dict on any failure (non-blocking).
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {}

    ticker = _resolve_ticker(company_name)
    if not ticker:
        return {}

    try:
        stock_df  = yf.download(ticker, period="1y", interval="1d",
                                progress=False, auto_adjust=True)
        sensex_df = yf.download(_SENSEX_TICKER, period="1y", interval="1d",
                                progress=False, auto_adjust=True)
    except Exception as e:
        print(f"     [Perf] Download failed: {e}")
        return {}

    if stock_df is None or stock_df.empty:
        return {}

    def closes(df, tick):
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            return df["Close"][tick].dropna()
        return df["Close"].dropna()

    s_close = closes(stock_df, ticker)
    x_close = closes(sensex_df, _SENSEX_TICKER)
    if s_close is None or len(s_close) < 30:
        return {}

    def ret(series, days):
        if series is None or len(series) < 5:
            return None
        past = series.iloc[:-days] if len(series) > days else series.iloc[:1]
        if len(past) == 0:
            return None
        base = float(past.iloc[-1])
        now  = float(series.iloc[-1])
        if base <= 0:
            return None
        return round((now - base) / base * 100, 1)

    windows = {"3M": 63, "6M": 126, "1Y": min(len(s_close) - 1, 250)}
    perf = {}
    for label, days in windows.items():
        a = ret(s_close, days)
        x = ret(x_close, days) if x_close is not None else None
        if a is None:
            continue
        perf[label] = {
            "abs":    a,
            "sensex": x if x is not None else "—",
            "rel":    round(a - x, 1) if x is not None else "—",
        }
    if perf:
        print(f"     [Perf] Price performance: {perf}")
    return perf


def generate_price_chart(company_name: str) -> str:
    """
    Fetch 1Y stock price + Sensex rebased, return base64 PNG.
    Falls back to placeholder on any error.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        import yfinance as yf
        import pandas as pd
    except ImportError as e:
        print(f"     [Stock Chart] Import error: {e}")
        return _placeholder_chart(company_name)

    ticker = _resolve_ticker(company_name)
    if not ticker:
        print(f"     [Stock Chart] No ticker for '{company_name}' — using placeholder.")
        return _placeholder_chart(company_name)

    print(f"     [Stock Chart] Fetching {ticker} + Sensex 1Y history...")
    try:
        stock_df = yf.download(ticker, period="1y", interval="1d",
                               progress=False, auto_adjust=True)
        sensex_df = yf.download(_SENSEX_TICKER, period="1y", interval="1d",
                                progress=False, auto_adjust=True)
    except Exception as e:
        print(f"     [Stock Chart] Download failed: {e}")
        return _placeholder_chart(company_name)

    if stock_df is None or stock_df.empty:
        print(f"     [Stock Chart] No data for {ticker} — using placeholder.")
        return _placeholder_chart(company_name)

    # Extract close prices
    try:
        if isinstance(stock_df.columns, pd.MultiIndex):
            stock_close = stock_df["Close"][ticker]
        else:
            stock_close = stock_df["Close"]

        if not sensex_df.empty:
            if isinstance(sensex_df.columns, pd.MultiIndex):
                sensex_close = sensex_df["Close"][_SENSEX_TICKER]
            else:
                sensex_close = sensex_df["Close"]
        else:
            sensex_close = None
    except Exception as e:
        print(f"     [Stock Chart] Column extraction error: {e}")
        return _placeholder_chart(company_name)

    # Rebase both to 100 at start
    stock_rebased  = (stock_close / stock_close.iloc[0]) * 100
    if sensex_close is not None and not sensex_close.empty:
        sensex_rebased = (sensex_close / sensex_close.iloc[0]) * 100
    else:
        sensex_rebased = None

    # Plot
    fig, ax = plt.subplots(figsize=(4.2, 2.2))
    ax.plot(stock_rebased.index, stock_rebased.values,
            color="#00837a", linewidth=1.5, label=ticker.replace(".NS", ""))
    if sensex_rebased is not None:
        # Align to common dates
        common_idx = stock_rebased.index.intersection(sensex_rebased.index)
        ax.plot(sensex_rebased.loc[common_idx].index,
                sensex_rebased.loc[common_idx].values,
                color="#cccccc", linewidth=1.0, linestyle="--", label="Sensex")

    ax.axhline(100, color="#dddddd", linewidth=0.6, linestyle=":")
    ax.set_facecolor("#fafafa")
    fig.patch.set_facecolor("#fafafa")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cccccc")
    ax.tick_params(labelsize=6, colors="#555555")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=30, ha="right")
    ax.set_ylabel("Rebased (100)", fontsize=6, color="#555")
    ax.set_title(f"{company_name} vs Sensex (1Y)",
                 fontsize=7.5, color="#00837a", pad=4)
    ax.legend(fontsize=5.5, loc="upper left",
              framealpha=0.6, edgecolor="#cccccc")
    plt.tight_layout(pad=0.4)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=120)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    print(f"     [Stock Chart] Chart generated for {ticker} ({len(b64)} chars).")
    return b64


# ──────────────────────────────────────────────────────────────────────────
# Comprehensive market-data fetcher — fills all Page 1 factual fields
# ──────────────────────────────────────────────────────────────────────────

def _classify_stock_type(market_cap_cr: Optional[float]) -> Optional[str]:
    """Classify Large/Mid/Small cap from market cap in Rs. cr (SEBI-like bands)."""
    if market_cap_cr is None:
        return None
    if market_cap_cr >= 20000:
        return "Large Cap"
    if market_cap_cr >= 5000:
        return "Mid Cap"
    return "Small Cap"


def fetch_market_data(company_name: str) -> dict:
    """
    Pull comprehensive factual market data from yfinance for Page 1 fields.
    Returns a dict with keys: cmp, market_cap_cr, enterprise_value_cr,
    week52_high, week52_low, beta, free_float_pct, outstanding_shares_cr,
    dividend_yield_pct, face_value, nse_code, bse_code, sensex_value,
    avg_volume_6m, stock_type.
    Any field that cannot be fetched is omitted (caller falls back to "—").
    Non-blocking: returns {} on any failure.
    """
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {}

    ticker_sym = _resolve_ticker(company_name)
    if not ticker_sym:
        return {}

    out: dict = {}
    try:
        tk = yf.Ticker(ticker_sym)
        info = tk.info or {}
    except Exception as e:
        print(f"     [Market Data] info fetch failed for {ticker_sym}: {e}")
        return {}

    # ── CMP (current price) ──
    cmp = info.get("currentPrice") or info.get("regularMarketPrice")
    if cmp is not None:
        out["cmp"] = round(float(cmp), 2)

    # ── Market cap (convert USD→Rs. cr if needed) ──
    mcap = info.get("marketCap")
    if mcap is not None:
        # yfinance reports marketCap in USD; convert to INR cr (1 USD ≈ 83 Rs, 1 cr = 10^7)
        # If the currency is INR already, no conversion needed.
        currency = info.get("currency", "USD")
        mcap_inr = float(mcap)
        if currency != "INR":
            fx = info.get("currency_base", 83.0) or 83.0
            mcap_inr = mcap_inr * float(fx)
        out["market_cap_cr"] = round(mcap_inr / 1e7, 2)

    # ── Enterprise value ──
    ev = info.get("enterpriseValue")
    if ev is not None:
        currency = info.get("currency", "USD")
        ev_inr = float(ev)
        if currency != "INR":
            ev_inr = ev_inr * 83.0
        out["enterprise_value_cr"] = round(ev_inr / 1e7, 2)

    # ── 52-week high/low ──
    if info.get("fiftyTwoWeekHigh") is not None:
        out["week52_high"] = round(float(info["fiftyTwoWeekHigh"]), 2)
    if info.get("fiftyTwoWeekLow") is not None:
        out["week52_low"] = round(float(info["fiftyTwoWeekLow"]), 2)

    # ── Beta ──
    if info.get("beta") is not None:
        out["beta"] = round(float(info["beta"]), 2)

    # ── Free float % ──
    ff = info.get("freeFloat")
    if ff is not None:
        ff_val = float(ff)
        # yfinance freeFloat is a decimal fraction (e.g. 0.95 = 95%)
        out["free_float_pct"] = round(ff_val * 100, 2) if ff_val <= 1 else round(ff_val, 2)
    else:
        # Fallback: compute from floatShares / sharesOutstanding (common for Indian stocks)
        float_sh = info.get("floatShares")
        shares_out = info.get("sharesOutstanding")
        if float_sh and shares_out:
            out["free_float_pct"] = round(float(float_sh) / float(shares_out) * 100, 2)
        else:
            # Fallback 2: free float = 100 - insider (promoter) holding %
            insiders = info.get("heldPercentInsiders")
            if insiders is not None:
                out["free_float_pct"] = round((1 - float(insiders)) * 100, 2)

    # ── Outstanding shares (in cr) ──
    shares = info.get("sharesOutstanding")
    if shares is not None:
        out["outstanding_shares_cr"] = round(float(shares) / 1e7, 2)

    # ── Dividend yield ──
    # yfinance dividendYield is a decimal fraction (e.g. 0.0118 = 1.18%) but is
    # inconsistent across tickers — some return it as a percentage already.
    # Sanity cap: a yield > 20% is unrealistic → raw was already a percentage.
    dy = info.get("dividendYield")
    if dy is not None:
        dy_pct = float(dy) * 100
        if dy_pct > 20:        # unrealistic → raw value was already a percentage
            dy_pct = float(dy)
        out["dividend_yield_pct"] = round(dy_pct, 2)

    # ── Trailing P/E (for target-price estimation fallback) ──
    tpe = info.get("trailingPE")
    if tpe is not None:
        out["pe_ratio"] = round(float(tpe), 2)

    # ── P/B (Price to Book) — for valuation summary table ──
    ptb = info.get("priceToBook")
    if ptb is not None:
        try:
            out["pb_ratio"] = round(float(ptb), 2)
        except (TypeError, ValueError):
            pass

    # ── ROE (return on equity) — decimal fraction, e.g. 0.19 = 19% ──
    roe = info.get("returnOnEquity")
    if roe is not None:
        try:
            out["roe_pct"] = round(float(roe) * 100, 1)
        except (TypeError, ValueError):
            pass

    # ── D/E (debt to equity) — yfinance returns as percentage, convert to ratio ──
    de = info.get("debtToEquity")
    if de is not None:
        try:
            de_val = float(de)
            out["de_ratio"] = round(de_val / 100, 2) if de_val > 1 else round(de_val, 2)
        except (TypeError, ValueError):
            pass

    # ── Book value per share — for computing total equity ──
    bv = info.get("bookValue")
    if bv is not None:
        try:
            out["book_value_per_share"] = round(float(bv), 2)
        except (TypeError, ValueError):
            pass

    # ── Face value (not directly in yfinance; use symbol/parValue if available) ──
    fv = info.get("parValue") or info.get("faceValue")
    if fv is not None:
        out["face_value"] = round(float(fv), 2)

    # ── NSE / BSE codes ──
    # yfinance doesn't reliably provide BSE scrip codes; use NSE symbol for both
    nse = ticker_sym.replace(".NS", "").replace(".BO", "")
    out["nse_code"] = nse
    out["bse_code"] = nse  # fallback: same as NSE (BSE scrip code not in yfinance)

    # ── 6-month average volume (in lakh shares) ──
    try:
        hist = tk.history(period="6mo", interval="1d")
        if hist is not None and not hist.empty and "Volume" in hist:
            avg_vol = float(hist["Volume"].mean())
            out["avg_volume_6m"] = round(avg_vol / 1e5, 2)  # convert to lakhs
    except Exception:
        pass

    # ── Stock type from market cap ──
    out["stock_type"] = _classify_stock_type(out.get("market_cap_cr"))

    # ── Sensex value (live) ──
    try:
        sx = yf.Ticker(_SENSEX_TICKER)
        sx_info = sx.info or {}
        sx_price = sx_info.get("currentPrice") or sx_info.get("regularMarketPrice")
        if sx_price is None:
            sx_hist = sx.history(period="5d", interval="1d")
            if sx_hist is not None and not sx_hist.empty:
                sx_price = float(sx_hist["Close"].iloc[-1])
        if sx_price is not None:
            out["sensex_value"] = round(float(sx_price), 2)
    except Exception:
        pass

    print(f"     [Market Data] Fetched {len(out)} fields for {ticker_sym}: "
          f"CMP={out.get('cmp')}, MCap={out.get('market_cap_cr')}cr, "
          f"Type={out.get('stock_type')}, Sensex={out.get('sensex_value')}")
    return out
