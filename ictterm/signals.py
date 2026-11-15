"""Multi-timeframe confluence scoring and trade planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import config, ict


@dataclass
class TimeframeSignal:
    symbol: str
    tf: str
    signal: str = "WAIT"               # BUY / SELL / WAIT
    score: float = 0.0
    confidence: int = 50
    direction: str = "long"            # long / short (scenario even for WAIT)
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    rr: float = 0.0
    rsi: float = 50.0
    trend: int = 0
    structure: str = "-"
    pd_zone: str = "-"
    zone: str = "-"
    reasons: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    def as_row(self, digits: int = 2) -> list[str]:
        arrow = {"BUY": "BUY", "SELL": "SELL"}.get(self.signal, "WAIT")
        return [
            self.tf,
            arrow,
            f"{self.score:+.0f}",
            self.structure,
            f"{self.rsi:.0f}",
            self.zone,
            config.fmt_price(self.entry, digits),
            config.fmt_price(self.stop, digits),
            config.fmt_price(self.target, digits),
            f"{self.rr:.1f}R",
        ]


def _structure_label(ctx: dict) -> str:
    ev = ctx.get("last_event")
    if not ev:
        return "Range"
    prefix = "BOS" if ev["kind"] == "BOS" else "CHoCH"
    return f"{prefix} {'Bull' if ev['dir'] == 'bull' else 'Bear'}"


def _nearest_zone(zones, price: float, direction: str, max_distance: float) -> Any:
    candidates = []
    for z in zones:
        if z.mitigated is not None:
            continue
        if z.direction != direction:
            continue
        if direction == "bull":
            if z.bottom <= price + max_distance:
                candidates.append(z)
        else:
            if z.top >= price - max_distance:
                candidates.append(z)
    if not candidates:
        return None
    if direction == "bull":
        return max(candidates, key=lambda z: (z.top, z.created))
    return min(candidates, key=lambda z: (z.bottom, -z.created))


def build_plan(symbol: str, tf: str, ctx: dict, direction: str, atr_value: float,
               digits: int) -> tuple[float, float, float, float, str]:
    df = ctx["df"]
    close = float(df["close"].iloc[-1])
    obs = [z for z in ctx["order_blocks"] if z.mitigated is None]
    fvgs = [z for z in ctx["fvgs"] if z.mitigated is None]
    atr_v = max(atr_value, 1e-9)
    zone = _nearest_zone(obs + fvgs, close, direction, atr_v * 3)
    zone_txt = zone.label if zone else "Swing structure"

    if direction == "long":
        swing_low = float(df["low"].tail(20).min())
        base_stop = min(swing_low, zone.bottom if zone else swing_low)
        stop = base_stop - atr_v * 0.30
        if close - stop < atr_v * 0.6:
            stop = close - atr_v * 1.5
        entry = close
        target = float(ctx["liquidity_above"])
        risk = max(entry - stop, 1e-9)
        if target - entry < risk * 1.5:
            target = entry + risk * 2.2
        if target - entry > risk * 6:
            target = entry + risk * 3.5
    else:
        swing_high = float(df["high"].tail(20).max())
        base_stop = max(swing_high, zone.top if zone else swing_high)
        stop = base_stop + atr_v * 0.30
        if stop - close < atr_v * 0.6:
            stop = close + atr_v * 1.5
        entry = close
        target = float(ctx["liquidity_below"])
        risk = max(stop - entry, 1e-9)
        if entry - target < risk * 1.5:
            target = entry - risk * 2.2
        if entry - target > risk * 6:
            target = entry - risk * 3.5

    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = reward / risk if risk > 0 else 0.0
    return entry, stop, target, rr, zone_txt


def analyze_timeframe(symbol: str, tf: str, df: pd.DataFrame, digits: int = 2) -> TimeframeSignal:
    ctx = ict.analyze(df)
    enriched = ctx["df"]
    last = enriched.iloc[-1]
    close = float(last["close"])
    atr_v = max(float(last.get("atr", ctx["atr"]) or ctx["atr"]), 1e-9)
    rsi = float(last.get("rsi", 50))
    macd_hist = float(last.get("macd_hist", 0) or 0)
    ema20 = float(last.get("ema20", close))
    ema50 = float(last.get("ema50", close))
    ema200 = float(last.get("ema200", close))
    st_dir = int(last.get("st_dir", 0) or 0)
    adx = float(last.get("adx", 0) or 0)

    score = 0.0
    reasons: list[str] = []

    trend = int(ctx["trend"])
    if trend > 0:
        score += 24
        reasons.append("Market structure bullish (BOS/CHoCH)")
    elif trend < 0:
        score -= 24
        reasons.append("Market structure bearish (BOS/CHoCH)")

    if close > ema50:
        score += 12
        reasons.append("Harga di atas EMA50")
    else:
        score -= 12
        reasons.append("Harga di bawah EMA50")
    if ema20 > ema50:
        score += 7
    else:
        score -= 7
    if close > ema200:
        score += 8
    else:
        score -= 8
    if st_dir > 0:
        score += 8
        reasons.append("Supertrend bullish")
    elif st_dir < 0:
        score -= 8
        reasons.append("Supertrend bearish")

    if 55 <= rsi <= 72:
        score += 6
        reasons.append(f"RSI {rsi:.0f} mendukung momentum beli")
    elif 28 <= rsi <= 45:
        score -= 6
        reasons.append(f"RSI {rsi:.0f} mendukung momentum jual")
    elif rsi > 78:
        score -= 4
        reasons.append("RSI overbought (risiko pullback)")
    elif rsi < 22:
        score += 4
        reasons.append("RSI oversold (potensi rebound)")

    if macd_hist > 0:
        score += 7
    elif macd_hist < 0:
        score -= 7

    pd_zone = ctx["pd_zone"]
    if pd_zone == "discount":
        score += 8
        reasons.append("Harga di area discount (bawah equilibrium)")
    elif pd_zone == "premium":
        score -= 8
        reasons.append("Harga di area premium (atas equilibrium)")

    demand = ctx["last_ob_bull"]
    supply = ctx["last_ob_bear"]
    demand_fvg = ctx["last_fvg_bull"]
    supply_fvg = ctx["last_fvg_bear"]
    pad = atr_v * 0.15
    if demand and demand.contains(close, pad):
        score += 12
        reasons.append("Reaksi di demand order block")
    if supply and supply.contains(close, pad):
        score -= 12
        reasons.append("Reaksi di supply order block")
    if demand_fvg and demand_fvg.contains(close, pad):
        score += 6
        reasons.append("Harga mengisi bullish FVG")
    if supply_fvg and supply_fvg.contains(close, pad):
        score -= 6
        reasons.append("Harga mengisi bearish FVG")

    sweep = ctx["last_sweep"]
    if sweep and len(enriched) - 1 - sweep["index"] <= 6:
        if sweep["dir"] == "bull":
            score += 11
            reasons.append("Liquidity sweep di bawah swing low")
        else:
            score -= 11
            reasons.append("Liquidity sweep di atas swing high")

    kz = ctx["killzone"]
    if kz:
        reasons.append(f"Killzone aktif: {kz['name']}")

    if adx > 22 and abs(score) >= 30:
        score *= 1.08
    score = float(np.clip(score, -100, 100))

    if score >= 30:
        signal = "BUY"
    elif score <= -30:
        signal = "SELL"
    else:
        signal = "WAIT"

    direction = "long" if score >= 0 else "short"
    entry, stop, target, rr, zone_txt = build_plan(symbol, tf, ctx, direction, atr_v, digits)
    confidence = int(np.clip(45 + abs(score) * 0.55, 45, 97)) if signal != "WAIT" else int(np.clip(40 + abs(score) * 0.3, 40, 65))
    structure = _structure_label(ctx)

    if signal == "BUY":
        reasons.insert(0, f"BUY setup · skor {score:+.0f} · RR {rr:.1f}")
    elif signal == "SELL":
        reasons.insert(0, f"SELL setup · skor {score:+.0f} · RR {rr:.1f}")
    else:
        reasons.insert(0, f"WAIT · skor {score:+.0f} · belum ada konfluensi cukup")

    return TimeframeSignal(
        symbol=symbol, tf=tf, signal=signal, score=score, confidence=confidence,
        direction=direction, entry=entry, stop=stop, target=target, rr=rr,
        rsi=rsi, trend=trend, structure=structure, pd_zone=pd_zone,
        zone=zone_txt, reasons=reasons, context=ctx,
    )


def analyze_symbol(symbol: str, provider, digits: int = 2,
                   timeframes: list[str] | None = None) -> dict[str, TimeframeSignal]:
    out: dict[str, TimeframeSignal] = {}
    for tf in timeframes or config.TF_ORDER:
        try:
            df = provider.rates(symbol, tf, config.TF_BARS[tf])
            if df is None or len(df) < 80:
                continue
            out[tf] = analyze_timeframe(symbol, tf, df, digits)
        except Exception as exc:  # keep one bad TF from killing the panel
            out[tf] = TimeframeSignal(symbol=symbol, tf=tf, signal="WAIT",
                                      reasons=[f"Data error: {type(exc).__name__}: {exc}"])
    return out


def aggregate(signals: dict[str, TimeframeSignal]) -> dict[str, Any]:
    if not signals:
        return {"signal": "WAIT", "score": 0, "confidence": 0, "buy": 0, "sell": 0, "wait": 0}
    total_w = 0.0
    weighted = 0.0
    buy = sell = wait = 0
    for tf, sig in signals.items():
        w = config.TF_WEIGHT.get(tf, 1.0)
        weighted += sig.score * w
        total_w += w
        if sig.signal == "BUY":
            buy += 1
        elif sig.signal == "SELL":
            sell += 1
        else:
            wait += 1
    score = weighted / total_w if total_w else 0.0
    if score >= 20:
        label = "BUY"
    elif score <= -20:
        label = "SELL"
    else:
        label = "WAIT"
    confidence = int(np.clip(40 + abs(score) * 0.6, 40, 97)) if label != "WAIT" else int(np.clip(35 + abs(score) * 0.4, 35, 65))
    best_tf = max(signals, key=lambda t: abs(signals[t].score) * config.TF_WEIGHT.get(t, 1.0))
    return {
        "signal": label, "score": score, "confidence": confidence,
        "buy": buy, "sell": sell, "wait": wait, "best_tf": best_tf,
        "best": signals[best_tf],
    }


def forecast_path(signal: TimeframeSignal, steps: int = 36) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Projected path + cone for the chart's forecasting layer."""
    entry, stop, target = signal.entry, signal.stop, signal.target
    if abs(entry - stop) < 1e-12:
        stop = entry - 1.0 if signal.direction == "long" else entry + 1.0
    risk = abs(entry - stop)
    if signal.direction == "long":
        retest = entry - risk * 0.45
        if signal.rr >= 1.5:
            path_main = np.concatenate([
                np.linspace(entry, retest, max(2, steps // 4)),
                np.linspace(retest, target, steps - max(2, steps // 4)),
            ])
        else:
            path_main = np.linspace(entry, target, steps)
    else:
        retest = entry + risk * 0.45
        path_main = np.concatenate([
            np.linspace(entry, retest, max(2, steps // 4)),
            np.linspace(retest, target, steps - max(2, steps // 4)),
        ])
    x = np.arange(steps)
    wobble = np.sin(np.linspace(0, np.pi * 2.4, steps)) * risk * 0.08
    wobble[0] = 0
    path = path_main + wobble
    band = np.linspace(risk * 0.10, risk * 0.30, steps)
    return x, path, path + band, path - band
