"""Event-driven ICT backtester (OB / FVG / liquidity + structure confluence)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from . import config, ict


@dataclass
class Trade:
    tf: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    exit_price: float
    r: float
    reason: str
    bars: int
    entry_index: int = 0
    exit_index: int = 0
    equity: float = 0.0
    setup: str = ""

    def as_dict(self) -> dict:
        return {
            "tf": self.tf, "direction": self.direction,
            "entry_time": self.entry_time, "exit_time": self.exit_time,
            "entry": self.entry, "stop": self.stop, "target": self.target,
            "exit": self.exit_price, "r": self.r, "reason": self.reason,
            "bars": self.bars, "equity": self.equity, "setup": self.setup,
        }


@dataclass
class BacktestResult:
    symbol: str
    tf: str
    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    context: dict = field(default_factory=dict)
    df: pd.DataFrame | None = None

    def summary_row(self, digits: int = 2) -> list[str]:
        s = self.stats
        return [
            self.tf,
            str(s.get("trades", 0)),
            f"{s.get('win_rate', 0):.1f}%",
            f"{s.get('profit_factor', 0):.2f}",
            f"{s.get('expectancy_r', 0):+.2f}R",
            f"{s.get('net_r', 0):+.1f}R",
            f"{s.get('max_dd', 0):.1f}%",
            f"{s.get('avg_bars', 0):.0f}",
        ]


def _stats(trades: list[Trade], start_balance: float = 10_000.0, risk_pct: float = 1.0) -> dict[str, Any]:
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "profit_factor": 0.0, "expectancy_r": 0.0, "net_r": 0.0,
            "max_dd": 0.0, "avg_r": 0.0, "avg_bars": 0.0,
            "max_consec_loss": 0, "equity_final": start_balance,
            "gross_profit": 0.0, "gross_loss": 0.0, "sharpe": 0.0,
        }
    rs = np.array([t.r for t in trades], dtype=float)
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    gross_profit = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    equity = start_balance
    peak = equity
    max_dd = 0.0
    consec = 0
    max_consec = 0
    curve = []
    for t in trades:
        equity *= max(0.0, 1.0 + (risk_pct / 100.0) * t.r)
        curve.append(equity)
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak else 0
        max_dd = max(max_dd, dd)
        if t.r <= 0:
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
        t.equity = equity
    sharpe = float(rs.mean() / rs.std(ddof=1) * np.sqrt(len(rs))) if len(rs) > 2 and rs.std(ddof=1) > 0 else 0.0
    return {
        "trades": len(rs), "wins": len(wins), "losses": len(losses),
        "win_rate": float(len(wins) / len(rs) * 100),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0),
        "expectancy_r": float(rs.mean()), "net_r": float(rs.sum()),
        "max_dd": max_dd, "avg_r": float(rs.mean()),
        "avg_bars": float(np.mean([t.bars for t in trades])),
        "max_consec_loss": max_consec, "equity_final": equity,
        "gross_profit": gross_profit, "gross_loss": gross_loss, "sharpe": sharpe,
        "_curve": curve,
    }


class SignalEvaluator:
    """Evaluate the exact ICT signal used by the backtest on a closed bar.

    Shared by the backtester and the live auto-trader so both use the same rules.
    """

    def __init__(self, df: pd.DataFrame, threshold: float = 7.0,
                 session_filter: bool = False, zone_limit: int | None = None,
                 sweep_limit: int | None = None):
        self.ctx = ict.analyze(df, zone_limit=zone_limit, sweep_limit=sweep_limit)
        self.data = self.ctx["df"]
        d = self.data
        self.n = len(d)
        self.o = d["open"].to_numpy()
        self.h = d["high"].to_numpy()
        self.l = d["low"].to_numpy()
        self.c = d["close"].to_numpy()
        self.t = d["time"].to_numpy()
        self.atr = d["atr"].to_numpy()
        self.ema20 = d["ema20"].to_numpy()
        self.ema50 = d["ema50"].to_numpy()
        self.ema200 = d["ema200"].to_numpy()
        self.rsi = d["rsi"].to_numpy()
        self.hist = d["macd_hist"].to_numpy()
        self.adx = d["adx"].to_numpy()
        self.threshold = threshold
        self.session_filter = session_filter
        self.obs = self.ctx["order_blocks"]
        self.fvgs = self.ctx["fvgs"]
        self.sweeps_by_index = {s["index"]: s for s in self.ctx["sweeps"]}
        self.trend = np.zeros(self.n, dtype=int)
        current = 0
        ei = 0
        events = self.ctx["events"]
        for i in range(self.n):
            while ei < len(events) and events[ei]["index"] <= i:
                current = 1 if events[ei]["dir"] == "bull" else -1
                ei += 1
            self.trend[i] = current

    def _zone_touch(self, zones, direction: str, i: int, lookback: int = 4):
        best = None
        start = max(0, i - lookback + 1)
        for z in zones:
            if z.direction != direction or z.created >= i:
                continue
            if z.mitigated is not None and z.mitigated < i:
                continue
            touched = False
            for k in range(start, i + 1):
                if z.top >= self.l[k] and z.bottom <= self.h[k]:
                    touched = True
                    break
            if touched and (best is None or z.created > best.created):
                best = z
        return best is not None, best

    def evaluate(self, i: int) -> dict | None:
        if i < 60 or i >= self.n:
            return None
        a = self.atr[i]
        if not np.isfinite(a) or a <= 0:
            return None
        if self.session_filter and not ict.killzone_info(pd.Timestamp(self.t[i])):
            return None
        win = slice(max(0, i - 40), i + 1)
        hi40 = self.h[win].max()
        lo40 = self.l[win].min()
        span = max(hi40 - lo40, 1e-9)
        ratio = (self.c[i] - lo40) / span
        touched_bull_ob, bull_ob = self._zone_touch(self.obs, "bull", i)
        touched_bear_ob, bear_ob = self._zone_touch(self.obs, "bear", i)
        touched_bull_fvg, bull_fvg = self._zone_touch(self.fvgs, "bull", i)
        touched_bear_fvg, bear_fvg = self._zone_touch(self.fvgs, "bear", i)
        sweep_bull = any(self.sweeps_by_index.get(k, {}).get("dir") == "bull" for k in range(i - 3, i + 1))
        sweep_bear = any(self.sweeps_by_index.get(k, {}).get("dir") == "bear" for k in range(i - 3, i + 1))
        trend = self.trend[i]
        ema_slope = self.ema50[i] - self.ema50[max(0, i - 5)]
        kz = 1 if ict.killzone_info(pd.Timestamp(self.t[i])) else 0

        long_score = 0.0
        long_score += 2.0 if trend > 0 else 0
        long_score += 1.0 if self.c[i] > self.ema50[i] else 0
        long_score += 1.0 if self.ema20[i] > self.ema50[i] else 0
        long_score += 1.0 if self.c[i] > self.ema200[i] else 0
        long_score += 1.0 if self.hist[i] > 0 else 0
        long_score += 1.0 if 45 <= self.rsi[i] <= 78 else 0
        long_score += 1.0 if ratio <= 0.52 else 0
        long_score += 2.0 if touched_bull_ob else 0
        long_score += 1.0 if touched_bull_fvg else 0
        long_score += 2.0 if sweep_bull else 0
        long_score += 0.5 if kz else 0
        long_score += 0.5 if ema_slope > 0 else 0

        short_score = 0.0
        short_score += 2.0 if trend < 0 else 0
        short_score += 1.0 if self.c[i] < self.ema50[i] else 0
        short_score += 1.0 if self.ema20[i] < self.ema50[i] else 0
        short_score += 1.0 if self.c[i] < self.ema200[i] else 0
        short_score += 1.0 if self.hist[i] < 0 else 0
        short_score += 1.0 if 22 <= self.rsi[i] <= 55 else 0
        short_score += 1.0 if ratio >= 0.48 else 0
        short_score += 2.0 if touched_bear_ob else 0
        short_score += 1.0 if touched_bear_fvg else 0
        short_score += 2.0 if sweep_bear else 0
        short_score += 0.5 if kz else 0
        short_score += 0.5 if ema_slope < 0 else 0

        if long_score >= self.threshold and long_score > short_score and self.c[i] > self.o[i]:
            if not (touched_bull_ob or touched_bull_fvg or sweep_bull):
                return None
            if self.adx[i] < 16:
                return None
            return {"dir": "long", "score": long_score, "zone": bull_ob or bull_fvg, "bar": i,
                    "setup": "OB+FVG" if (touched_bull_ob and touched_bull_fvg)
                    else ("OB" if touched_bull_ob else ("Sweep" if sweep_bull else "FVG"))}
        if short_score >= self.threshold and short_score > long_score and self.c[i] < self.o[i]:
            if not (touched_bear_ob or touched_bear_fvg or sweep_bear):
                return None
            if self.adx[i] < 16:
                return None
            return {"dir": "short", "score": short_score, "zone": bear_ob or bear_fvg, "bar": i,
                    "setup": "OB+FVG" if (touched_bear_ob and touched_bear_fvg)
                    else ("OB" if touched_bear_ob else ("Sweep" if sweep_bear else "FVG"))}
        return None


def run_backtest(
    symbol: str,
    tf: str,
    df: pd.DataFrame,
    digits: int = 2,
    point: float = 0.01,
    spread_points: int = 0,
    rr: float = 2.0,
    threshold: float = 5.0,
    risk_pct: float = 1.0,
    max_bars: int = 45,
    session_filter: bool = False,
    warmup: int = 120,
) -> BacktestResult:
    """Backtest the ICT confluence model on closed candles.

    Rules (long; short mirrored):
      * structure trend bullish (BOS/CHoCH)
      * price above EMA50/EMA200, EMA20 > EMA50, MACD histogram > 0
      * RSI 45-78, price in discount (< 50% of 40-bar range)
      * price taps an active bullish OB (+2) or FVG (+1)
      * liquidity sweep of a swing low within 3 bars (+2)
      * bullish confirmation candle
      * stop under the zone/swing, target = rr x risk
    """
    result = BacktestResult(symbol=symbol, tf=tf)
    if df is None or len(df) < warmup + 20:
        result.stats = _stats([])
        return result

    evaluator = SignalEvaluator(df, threshold, session_filter, zone_limit=None, sweep_limit=None)
    ctx = evaluator.ctx
    data = evaluator.data
    n = len(data)
    o = evaluator.o
    h = evaluator.h
    l = evaluator.l
    c = evaluator.c
    t = evaluator.t
    atr_v = evaluator.atr
    spread_price = spread_points * point if point else 0.0
    commission_r = 0.015

    trades: list[Trade] = []
    position: dict | None = None
    cooldown = 0

    for i in range(warmup, n):
        # ---------------------------------------------------- manage position
        if position is not None:
            pos = position
            hit_stop = hit_target = False
            if pos["dir"] == "long":
                hit_stop = l[i] <= pos["stop"]
                hit_target = h[i] >= pos["target"]
            else:
                hit_stop = h[i] >= pos["stop"]
                hit_target = l[i] <= pos["target"]
            exit_price = None
            reason = ""
            if hit_stop:  # conservative: stop is checked first
                exit_price = pos["stop"]
                reason = "SL"
            elif hit_target:
                exit_price = pos["target"]
                reason = "TP"
            elif i - pos["entry_index"] >= max_bars:
                exit_price = c[i]
                reason = "TIME"
            if exit_price is not None:
                raw = ((exit_price - pos["entry"]) if pos["dir"] == "long" else (pos["entry"] - exit_price))
                r = raw / pos["risk"] - (spread_price / pos["risk"]) - commission_r
                trades.append(Trade(
                    tf=tf, direction=pos["dir"],
                    entry_time=pd.Timestamp(t[pos["entry_index"]]),
                    exit_time=pd.Timestamp(t[i]),
                    entry=pos["entry"], stop=pos["stop"], target=pos["target"],
                    exit_price=exit_price, r=float(r), reason=reason,
                    bars=i - pos["entry_index"], entry_index=pos["entry_index"],
                    exit_index=i, setup=pos.get("setup", ""),
                ))
                position = None
                cooldown = 2
                continue

        if position is not None or i >= n - 2:
            continue
        if cooldown > 0:
            cooldown -= 1
            continue

        # ------------------------------------------------------- new signal
        sig = evaluator.evaluate(i)
        if not sig:
            continue
        entry_i = i + 1
        entry = float(o[entry_i])
        a = atr_v[i]
        zone = sig["zone"]
        if sig["dir"] == "long":
            base = zone.bottom if zone is not None else min(l[i - 2:i + 1])
            stop = min(float(base), l[i]) - a * 0.25
            risk = entry - stop
            if risk < a * 0.45:
                stop = entry - a * 0.9
                risk = entry - stop
            elif risk > a * 3.2:
                continue
            target = entry + risk * rr
        else:
            base = zone.top if zone is not None else max(h[i - 2:i + 1])
            stop = max(float(base), h[i]) + a * 0.25
            risk = stop - entry
            if risk < a * 0.45:
                stop = entry + a * 0.9
                risk = stop - entry
            elif risk > a * 3.2:
                continue
            target = entry - risk * rr
        if risk <= 0:
            continue
        position = {
            "dir": sig["dir"], "entry": entry, "stop": stop, "target": target,
            "risk": risk, "entry_index": entry_i, "setup": sig["setup"],
        }

    stats = _stats(trades, risk_pct=risk_pct)
    stats["rr"] = rr
    curve = stats.pop("_curve", [])
    if curve:
        start = pd.Timestamp(t[warmup]) if n > warmup else pd.Timestamp(t[0])
        times = [pd.Timestamp(tr.exit_time) for tr in trades]
        result.equity = pd.Series(curve, index=times, name="equity")
        result.equity.loc[start] = 10_000.0
        result.equity = result.equity.sort_index()
    else:
        start = pd.Timestamp(t[warmup]) if n > warmup else pd.Timestamp(t[0])
        result.equity = pd.Series([10_000.0], index=[start], name="equity")
    result.trades = trades
    result.stats = stats
    result.context = ctx
    result.df = data
    return result


def backtest_all(
    provider,
    symbol: str,
    timeframes: list[str] | None = None,
    bars: int | None = None,
    **kwargs,
) -> dict[str, BacktestResult]:
    meta = provider.meta(symbol)
    out: dict[str, BacktestResult] = {}
    for tf in timeframes or config.TF_ORDER:
        count = bars or config.TF_BARS.get(tf, 800)
        df = provider.rates(symbol, tf, count, ttl=0)
        if df is None or len(df) < 150:
            continue
        out[tf] = run_backtest(
            symbol, tf, df, digits=meta.digits, point=meta.point,
            spread_points=meta.spread, **kwargs,
        )
    return out
