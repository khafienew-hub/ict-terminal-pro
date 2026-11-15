"""Trade history helpers for chart overlays and replay."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from . import config


@dataclass
class HistoryTrade:
    symbol: str
    tf: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    exit: float
    stop: float
    target: float
    volume: float
    profit: float
    r: float
    ticket: int = 0
    source: str = "Backtest"

    @property
    def is_long(self) -> bool:
        return self.direction.lower() in ("long", "buy")


def from_backtest_results(results: dict[str, Any]) -> list[HistoryTrade]:
    out: list[HistoryTrade] = []
    for tf, result in results.items():
        for tr in getattr(result, "trades", []):
            out.append(HistoryTrade(
                symbol=result.symbol,
                tf=getattr(tr, "tf", tf),
                direction="BUY" if tr.direction == "long" else "SELL",
                entry_time=pd.Timestamp(tr.entry_time),
                exit_time=pd.Timestamp(tr.exit_time),
                entry=float(tr.entry), exit=float(tr.exit_price),
                stop=float(tr.stop), target=float(tr.target),
                volume=0.0, profit=0.0, r=float(tr.r),
                source="Backtest",
            ))
    out.sort(key=lambda t: t.entry_time)
    return out


def _parse_level(comment: str, key: str) -> float:
    match = re.search(rf"\[{key}\s+([0-9.]+)\]", comment or "", re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def from_mt5_history(symbol: str | None = None, magic_base: int = 770000, days: int = 90,
                     start: datetime | None = None,
                     end: datetime | None = None,
                     symbols: list[str] | None = None,
                     magic_bases: list[int] | None = None) -> list[HistoryTrade]:
    """Read closed positions created by this app (magic range) from MT5 history.

    ``symbol=None`` reads every symbol traded by this app.  Pass ``symbols`` to
    restrict an all-symbol report to a selected list.  ``magic_bases`` adds the
    other bases that were configured over time (the magic number is editable in
    Auto Trade settings), so old trades stay visible in reports.
    """
    try:
        import MetaTrader5 as mt5
    except Exception:
        return []
    try:
        if start is None:
            end_dt = end or (datetime.now() + timedelta(days=1))
            start_dt = end_dt - timedelta(days=days)
        else:
            start_dt = start - timedelta(days=90)
            # Include positions opened in range that close later.
            end_dt = end + timedelta(days=1) if end else datetime.now() + timedelta(days=1)
        deals = mt5.history_deals_get(start_dt, end_dt) or []
    except Exception:
        return []

    magics: dict[int, str] = {}
    bases = [magic_base]
    for extra in magic_bases or []:
        if extra not in bases:
            bases.append(extra)
    for base in bases:
        for i, tf in enumerate(config.TF_ORDER):
            offset = i + 1
            magics[base + offset] = tf              # legacy / BUY lama
            magics[base + 1000 + offset] = tf       # BUY baru
            magics[base + 1100 + offset] = tf       # SELL baru
    grouped: dict[tuple[str, int], list[Any]] = {}
    allowed = {s for s in symbols if s} if symbols else None
    for d in deals:
        if symbol and d.symbol != symbol:
            continue
        if allowed is not None and d.symbol not in allowed:
            continue
        if d.magic not in magics:
            continue
        grouped.setdefault((d.symbol, d.position_id), []).append(d)

    out: list[HistoryTrade] = []
    for (_symbol, pid), rows in grouped.items():
        rows.sort(key=lambda x: x.time)
        entries = [x for x in rows if x.entry == 0]
        exits = [x for x in rows if x.entry in (1, 2, 3)]
        if not entries or not exits:
            continue
        entry_deal = entries[0]
        exit_deal = exits[-1]
        tf = magics.get(entry_deal.magic, "?")
        sl = tp = 0.0
        for row in rows:
            sl = sl or _parse_level(row.comment, "sl")
            tp = tp or _parse_level(row.comment, "tp")
        direction = "BUY" if entry_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
        risk = abs(float(entry_deal.price) - sl) if sl > 0 else 0.0
        raw = (float(exit_deal.price) - float(entry_deal.price)) if direction == "BUY" else (
            float(entry_deal.price) - float(exit_deal.price)
        )
        r_value = (raw / risk) if risk > 0 else 0.0
        profit = sum(float(x.profit) + float(x.swap) + float(x.commission) for x in rows)
        out.append(HistoryTrade(
            symbol=_symbol, tf=tf, direction=direction,
            entry_time=pd.Timestamp(entry_deal.time, unit="s"),
            exit_time=pd.Timestamp(exit_deal.time, unit="s"),
            entry=float(entry_deal.price), exit=float(exit_deal.price),
            stop=sl, target=tp, volume=float(entry_deal.volume),
            profit=profit, r=float(r_value), ticket=int(pid), source="Auto Trade",
        ))
    out.sort(key=lambda t: (t.exit_time, t.symbol))
    return out


def index_for_time(df: pd.DataFrame, stamp: pd.Timestamp) -> int | None:
    if df is None or len(df) == 0:
        return None
    stamp = pd.Timestamp(stamp)
    ts = np_datetime(stamp)
    values = df["time"].to_numpy()
    idx = int(values.searchsorted(ts))
    if idx < 0 or idx >= len(df):
        return None
    # Allow a small tolerance for broker/server timestamp offsets.
    delta = abs((pd.Timestamp(values[idx]) - stamp).total_seconds())
    if delta <= 180:
        return idx
    if idx > 0:
        prev_delta = abs((pd.Timestamp(values[idx - 1]) - stamp).total_seconds())
        if prev_delta <= 180:
            return idx - 1
    return None


def np_datetime(stamp: pd.Timestamp):
    import numpy as np
    return np.datetime64(pd.Timestamp(stamp).to_datetime64())
