"""ICT / Smart-Money concepts: structure, order blocks, FVG, liquidity."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np
import pandas as pd

from . import indicators


@dataclass
class Zone:
    kind: str            # "OB" | "FVG"
    direction: str       # "bull" | "bear"
    top: float
    bottom: float
    created: int
    mitigated: int | None = None
    strength: float = 1.0
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2

    def contains(self, price: float, pad: float = 0.0) -> bool:
        return (self.bottom - pad) <= price <= (self.top + pad)


def find_swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> list[dict]:
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)
    out: list[dict] = []
    if n < left + right + 1:
        return out
    for i in range(left, n - right):
        window_hi = highs[i - left:i + right + 1]
        window_lo = lows[i - left:i + right + 1]
        if highs[i] >= window_hi.max() - 1e-12:
            out.append({"index": i, "price": float(highs[i]), "kind": "high"})
        elif lows[i] <= window_lo.min() + 1e-12:
            out.append({"index": i, "price": float(lows[i]), "kind": "low"})
    return out


def market_structure(df: pd.DataFrame, swings: list[dict], right: int = 2) -> tuple[list[dict], int, list[dict]]:
    """Causal BOS/CHoCH detection. Returns events, final trend and swing timeline."""
    n = len(df)
    close = df["close"].to_numpy()
    sorted_sw = sorted(swings, key=lambda s: s["index"])
    events: list[dict] = []
    timeline: list[dict] = []
    last_high: dict | None = None
    last_low: dict | None = None
    ptr = 0
    trend = 0
    for i in range(n):
        while ptr < len(sorted_sw) and sorted_sw[ptr]["index"] + right <= i:
            s = sorted_sw[ptr]
            timeline.append(s)
            if s["kind"] == "high":
                last_high = s
            else:
                last_low = s
            ptr += 1
        if last_high is not None and close[i] > last_high["price"]:
            kind = "BOS" if trend >= 0 else "CHoCH"
            events.append({
                "index": i, "price": float(last_high["price"]), "kind": kind,
                "dir": "bull", "swing_index": last_high["index"],
            })
            trend = 1
            last_high = None
        if last_low is not None and close[i] < last_low["price"]:
            kind = "BOS" if trend <= 0 else "CHoCH"
            events.append({
                "index": i, "price": float(last_low["price"]), "kind": kind,
                "dir": "bear", "swing_index": last_low["index"],
            })
            trend = -1
            last_low = None
    return events, trend, timeline


def _mark_mitigation(zones: list[Zone], df: pd.DataFrame) -> None:
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    n = len(df)
    for z in zones:
        start = z.created + 1
        if start >= n:
            continue
        if z.direction == "bull":
            for j in range(start, n):
                if close[j] < z.bottom or low[j] <= z.bottom:
                    z.mitigated = j
                    break
        else:
            for j in range(start, n):
                if close[j] > z.top or high[j] >= z.top:
                    z.mitigated = j
                    break


def order_blocks(df: pd.DataFrame, atr_: pd.Series, lookback: int = 8, limit: int | None = 60) -> list[Zone]:
    n = len(df)
    if n < 20:
        return []
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    atr_v = atr_.to_numpy()
    body = np.abs(c - o)
    zones: list[Zone] = []
    for i in range(6, n):
        a = atr_v[i - 1]
        if not np.isfinite(a) or a <= 0:
            continue
        if body[i] < a * 0.95:
            continue
        bullish = c[i] > o[i]
        # Displacement must break the recent micro range.
        if bullish:
            if c[i] <= h[max(0, i - 4):i].max() + a * 0.05:
                continue
            for j in range(i - 1, max(-1, i - lookback - 1), -1):
                if c[j] < o[j]:
                    top, bottom = h[j], l[j]
                    if (top - bottom) <= a * 2.4:
                        zones.append(Zone("OB", "bull", float(top), float(bottom), i,
                                          strength=float(body[i] / a), label="Demand OB"))
                    break
        else:
            if c[i] >= l[max(0, i - 4):i].min() - a * 0.05:
                continue
            for j in range(i - 1, max(-1, i - lookback - 1), -1):
                if c[j] > o[j]:
                    top, bottom = h[j], l[j]
                    if (top - bottom) <= a * 2.4:
                        zones.append(Zone("OB", "bear", float(top), float(bottom), i,
                                          strength=float(body[i] / a), label="Supply OB"))
                    break
    _mark_mitigation(zones, df)
    return zones if limit is None else zones[-limit:]


def fair_value_gaps(df: pd.DataFrame, atr_: pd.Series, min_atr: float = 0.12, limit: int | None = 60) -> list[Zone]:
    n = len(df)
    if n < 5:
        return []
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    o = df["open"].to_numpy()
    c = df["close"].to_numpy()
    atr_v = atr_.to_numpy()
    zones: list[Zone] = []
    for i in range(2, n):
        a = atr_v[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if l[i] > h[i - 2] and c[i - 1] > o[i - 1]:
            gap = l[i] - h[i - 2]
            if gap >= a * min_atr:
                zones.append(Zone("FVG", "bull", float(l[i]), float(h[i - 2]), i,
                                  strength=float(gap / a), label="Bullish FVG"))
        elif h[i] < l[i - 2] and c[i - 1] < o[i - 1]:
            gap = l[i - 2] - h[i]
            if gap >= a * min_atr:
                zones.append(Zone("FVG", "bear", float(l[i - 2]), float(h[i]), i,
                                  strength=float(gap / a), label="Bearish FVG"))
    _mark_mitigation(zones, df)
    return zones if limit is None else zones[-limit:]


def liquidity_sweeps(df: pd.DataFrame, swings: list[dict], lookback: int | None = 30) -> list[dict]:
    n = len(df)
    if n < 10 or not swings:
        return []
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    by_index_high = {s["index"]: s for s in swings if s["kind"] == "high"}
    by_index_low = {s["index"]: s for s in swings if s["kind"] == "low"}
    last_high: dict | None = None
    last_low: dict | None = None
    ordered = sorted(swings, key=lambda s: s["index"])
    ptr = 0
    sweeps: list[dict] = []
    last_sweep_i = -10
    for i in range(n):
        while ptr < len(ordered) and ordered[ptr]["index"] + 2 <= i:
            s = ordered[ptr]
            if s["kind"] == "high":
                last_high = s
            else:
                last_low = s
            ptr += 1
        if i - last_sweep_i < 3:
            continue
        if last_high is not None and h[i] > last_high["price"] and c[i] < last_high["price"]:
            sweeps.append({"index": i, "price": float(h[i]), "level": last_high["price"],
                           "dir": "bear", "label": "Sweep highs"})
            last_sweep_i = i
        elif last_low is not None and l[i] < last_low["price"] and c[i] > last_low["price"]:
            sweeps.append({"index": i, "price": float(l[i]), "level": last_low["price"],
                           "dir": "bull", "label": "Sweep lows"})
            last_sweep_i = i
    return sweeps if lookback is None else sweeps[-lookback:]


def equal_levels(swings: list[dict], atr_value: float, max_levels: int = 10) -> tuple[list[dict], list[dict]]:
    tol = max(atr_value * 0.12, 1e-9)
    highs = [s for s in swings if s["kind"] == "high"]
    lows = [s for s in swings if s["kind"] == "low"]
    out_h, out_l = [], []
    for source, target in ((highs, out_h), (lows, out_l)):
        used: set[int] = set()
        for i, s in enumerate(source):
            if i in used:
                continue
            cluster = [s]
            for j in range(i + 1, len(source)):
                if j in used:
                    continue
                if abs(source[j]["price"] - s["price"]) <= tol:
                    cluster.append(source[j])
                    used.add(j)
            if len(cluster) >= 2:
                target.append({
                    "price": float(np.mean([c["price"] for c in cluster])),
                    "count": len(cluster),
                    "indices": [c["index"] for c in cluster],
                })
    return out_h[-max_levels:], out_l[-max_levels:]


def killzone_info(ts: pd.Timestamp) -> dict | None:
    """Approximate broker-time killzones (Exness server is UTC+2/+3)."""
    h = ts.hour + ts.minute / 60
    sessions = [
        ("Asia", 0.0, 4.0),
        ("London Open", 8.0, 11.0),
        ("New York AM", 13.0, 16.0),
        ("New York PM", 18.0, 21.0),
    ]
    for name, start, end in sessions:
        if start <= h < end:
            return {"name": name, "start": start, "end": end}
    return None


def analyze(df: pd.DataFrame, left: int = 2, right: int = 2, zone_limit: int | None = 60, sweep_limit: int | None = 30) -> dict[str, Any]:
    """Full ICT snapshot used by charts, signals and backtests."""
    enriched = indicators.add_indicators(df) if "ema20" not in df.columns else df.copy()
    atr_series = enriched["atr"] if "atr" in enriched.columns else indicators.atr(df)
    swings = find_swings(enriched, left, right)
    events, trend, timeline = market_structure(enriched, swings, right)
    obs = order_blocks(enriched, atr_series, limit=zone_limit)
    fvgs = fair_value_gaps(enriched, atr_series, limit=zone_limit)
    sweeps = liquidity_sweeps(enriched, swings, lookback=sweep_limit)
    eq_highs, eq_lows = equal_levels(swings, float(atr_series.iloc[-1] or 0))
    n = len(enriched)
    close = float(enriched["close"].iloc[-1])
    atr_now = float(atr_series.iloc[-1]) if len(atr_series) else 0.0
    recent = enriched.tail(80)
    range_high = float(recent["high"].max())
    range_low = float(recent["low"].min())
    span = max(range_high - range_low, 1e-9)
    ratio = (close - range_low) / span
    if ratio >= 0.55:
        pd_zone = "premium"
    elif ratio <= 0.45:
        pd_zone = "discount"
    else:
        pd_zone = "equilibrium"

    # Nearest liquidity above/below current price (unswept swing points).
    highs = sorted({round(s["price"], 8) for s in swings if s["price"] > close and s["index"] < n - right})
    lows = sorted({round(s["price"], 8) for s in swings if s["price"] < close and s["index"] < n - right})
    liq_above = min(highs) if highs else range_high
    liq_below = max(lows) if lows else range_low
    sweep_now = sweeps[-1] if sweeps else None
    kz = killzone_info(enriched["time"].iloc[-1]) if "time" in enriched.columns else None

    return {
        "df": enriched,
        "atr": atr_now,
        "swings": swings,
        "swing_timeline": timeline,
        "events": events,
        "trend": trend,
        "order_blocks": obs,
        "fvgs": fvgs,
        "sweeps": sweeps,
        "equal_highs": eq_highs,
        "equal_lows": eq_lows,
        "range_high": range_high,
        "range_low": range_low,
        "range_ratio": ratio,
        "pd_zone": pd_zone,
        "liquidity_above": float(liq_above),
        "liquidity_below": float(liq_below),
        "last_sweep": sweep_now,
        "killzone": kz,
        "last_event": events[-1] if events else None,
        "last_ob_bull": next((z for z in reversed(obs) if z.direction == "bull" and z.mitigated is None), None),
        "last_ob_bear": next((z for z in reversed(obs) if z.direction == "bear" and z.mitigated is None), None),
        "last_fvg_bull": next((z for z in reversed(fvgs) if z.direction == "bull" and z.mitigated is None), None),
        "last_fvg_bear": next((z for z in reversed(fvgs) if z.direction == "bear" and z.mitigated is None), None),
    }


def active_zones(zones: list[Zone], index: int) -> list[Zone]:
    """Zones created before ``index`` and not mitigated before it (causal)."""
    return [z for z in zones if z.created < index and (z.mitigated is None or z.mitigated >= index)]


def zone_at_price(zones: list[Zone], low: float, high: float, index: int, pad: float = 0.0) -> Zone | None:
    best = None
    for z in active_zones(zones, index):
        if z.top >= low - pad and z.bottom <= high + pad:
            if best is None or z.created > best.created:
                best = z
    return best
