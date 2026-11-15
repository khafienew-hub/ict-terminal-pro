"""Vectorised technical indicators (pandas/numpy only)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().bfill()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(series, fast) - ema(series, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = line - sig
    return pd.DataFrame({"macd": line, "signal": sig, "hist": hist})


def bollinger(series: pd.Series, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(series, period)
    sd = series.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + mult * sd, "lower": mid - mult * sd})


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    lowest = df["low"].rolling(k, min_periods=k).min()
    highest = df["high"].rolling(k, min_periods=k).max()
    rng = (highest - lowest).replace(0, np.nan)
    fast = 100 * (df["close"] - lowest) / rng
    slow = fast.rolling(d, min_periods=1).mean()
    return pd.DataFrame({"k": fast.fillna(50), "d": slow.fillna(50)})


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up = high.diff()
    down = -low.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().fillna(0)


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    hl2 = (df["high"] + df["low"]) / 2
    atr_ = atr(df, period)
    upper = hl2 + multiplier * atr_
    lower = hl2 - multiplier * atr_
    n = len(df)
    st = np.zeros(n)
    direction = np.ones(n, dtype=int)
    final_upper = upper.to_numpy(copy=True)
    final_lower = lower.to_numpy(copy=True)
    close = df["close"].to_numpy()
    for i in range(1, n):
        if close[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(final_upper[i], final_upper[i - 1])
        if close[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(final_lower[i], final_lower[i - 1])
        if close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
    return pd.DataFrame({"line": st, "dir": direction}, index=df.index)


def pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """Classic daily pivot levels derived from the previous candle."""
    prev = df.shift(1)
    p = (prev["high"] + prev["low"] + prev["close"]) / 3
    return pd.DataFrame({
        "pivot": p,
        "r1": 2 * p - prev["low"],
        "s1": 2 * p - prev["high"],
        "r2": p + (prev["high"] - prev["low"]),
        "s2": p - (prev["high"] - prev["low"]),
    })


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the standard indicator columns used by the UI."""
    out = df.copy()
    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi"] = rsi(out["close"], 14)
    out["atr"] = atr(out, 14)
    m = macd(out["close"])
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]
    bb = bollinger(out["close"])
    out["bb_mid"] = bb["mid"]
    out["bb_upper"] = bb["upper"]
    out["bb_lower"] = bb["lower"]
    st = supertrend(out)
    out["st_line"] = st["line"]
    out["st_dir"] = st["dir"]
    out["adx"] = adx(out)
    return out
