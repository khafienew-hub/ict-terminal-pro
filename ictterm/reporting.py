"""Matplotlib report renderer for ICT backtests and forecast snapshots."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter, MaxNLocator

from . import config, ict
from .backtest import BacktestResult
from .signals import TimeframeSignal, forecast_path


def _hex(color, alpha=None):
    if isinstance(color, tuple):
        if len(color) == 4:
            r, g, b, a = color
            return (r / 255, g / 255, b / 255, a / 255)
        return tuple(c / 255 for c in color)
    if alpha is None:
        return color
    from matplotlib.colors import to_rgba
    return to_rgba(color, alpha)


def _style_ax(ax, show_x: bool = True) -> None:
    ax.set_facecolor(config.BG)
    ax.grid(color=config.GRID, linewidth=0.6, alpha=0.7)
    ax.tick_params(colors=config.MUTED, labelsize=8, length=3)
    for spine in ax.spines.values():
        spine.set_color(config.BORDER)
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    if not show_x:
        ax.tick_params(axis="x", labelbottom=False)


def _time_formatter(times: pd.Series, tf: str):
    stamps = list(times)
    n = len(stamps)

    def fmt(value, _pos):
        i = int(round(value))
        if i < 0 or i >= n:
            return ""
        ts = stamps[i]
        if tf in ("M1", "M5", "M15", "M30"):
            return ts.strftime("%d %b\n%H:%M")
        if tf in ("H1", "H4"):
            return ts.strftime("%d %b\n%H:%M")
        return ts.strftime("%d %b\n%Y")

    return FuncFormatter(fmt)


def _draw_candles(ax, df: pd.DataFrame, start: int, end: int, width: float = 0.62) -> None:
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    c = df["close"].to_numpy()
    for i in range(start, end):
        up = c[i] >= o[i]
        color = config.BULL if up else config.BEAR
        ax.vlines(i, l[i], h[i], color=color, linewidth=0.7, alpha=0.95, zorder=3)
        body_low = min(o[i], c[i])
        body_h = abs(c[i] - o[i])
        if body_h <= 0:
            body_h = max((h[i] - l[i]) * 0.01, 1e-9)
        ax.add_patch(Rectangle((i - width / 2, body_low), width, body_h,
                               facecolor=color, edgecolor=color, linewidth=0.4, zorder=4))


def _draw_zones(ax, result: BacktestResult, start: int, end: int, labels: bool = True) -> None:
    ctx = result.context
    if not ctx:
        return
    n = len(result.df)
    obs = [z for z in ctx.get("order_blocks", []) if z.created <= end and (z.mitigated is None or z.mitigated >= start)]
    fvgs = [z for z in ctx.get("fvgs", []) if z.created <= end and (z.mitigated is None or z.mitigated >= start)]
    for idx, z in enumerate(obs[-10:]):
        x0 = max(start, z.created)
        x1 = min(end + 8, z.mitigated if z.mitigated else end + 8)
        if x1 <= x0:
            continue
        face = config.LONG_ZONE if z.direction == "bull" else config.SHORT_ZONE
        ax.add_patch(Rectangle((x0, z.bottom), x1 - x0, z.top - z.bottom,
                               facecolor=_hex(face), edgecolor=_hex(face, 1.0),
                               linewidth=0.6, zorder=1))
        if labels and idx >= len(obs[-10:]) - 2:
            ax.text(x0, z.top, " OB", color=config.MUTED, fontsize=6, va="bottom", ha="left", zorder=6)
    for idx, z in enumerate(fvgs[-7:]):
        x0 = max(start, z.created)
        x1 = min(end + 8, z.mitigated if z.mitigated else end + 8)
        if x1 <= x0:
            continue
        face = config.FVG_BULL if z.direction == "bull" else config.FVG_BEAR
        ax.add_patch(Rectangle((x0, z.bottom), x1 - x0, z.top - z.bottom,
                               facecolor=_hex(face), edgecolor=_hex(face, 1.0),
                               linewidth=0.5, linestyle="--", zorder=1))
        if labels and idx >= len(fvgs[-7:]) - 2:
            ax.text(x0, z.bottom, " FVG", color=config.MUTED, fontsize=6, va="top", ha="left", zorder=6)


def _draw_structure(ax, result: BacktestResult, start: int, end: int) -> None:
    ctx = result.context or {}
    events = [e for e in ctx.get("events", []) if start <= e["index"] <= end]
    for e in events[-5:]:
        color = config.BULL if e["dir"] == "bull" else config.BEAR
        ax.plot([e["swing_index"], e["index"]], [e["price"], e["price"]],
                color=color, linewidth=0.8, linestyle=(0, (2, 1)), alpha=0.8, zorder=5)
        marker = "▲" if e["dir"] == "bull" else "▼"
        ax.annotate(f"{e['kind']} {marker}", xy=(e["index"], e["price"]),
                    xytext=(3, 7 if e["dir"] == "bull" else -12), textcoords="offset points",
                    color=color, fontsize=7, fontweight="bold", zorder=7)
    for s in ctx.get("sweeps", [])[-4:]:
        if not (start <= s["index"] <= end):
            continue
        ax.scatter([s["index"]], [s["price"]], marker="x", s=30, color=config.GOLD,
                   linewidth=1.2, zorder=8)


def _draw_trades(ax, result: BacktestResult, start: int, end: int) -> None:
    visible = [t for t in result.trades if start <= t.entry_index <= end]
    for idx, t in enumerate(visible):
        color = config.BULL if t.r > 0 else config.BEAR
        ax.plot([t.entry_index, t.exit_index], [t.entry, t.exit_price],
                color=color, linewidth=1.1, alpha=0.65, zorder=8)
        marker = "^" if t.direction == "long" else "v"
        ax.scatter([t.entry_index], [t.entry], marker=marker, s=38,
                   color=config.BULL if t.direction == "long" else config.BEAR,
                   edgecolor="#ffffff", linewidth=0.4, zorder=9)
        ax.scatter([t.exit_index], [t.exit_price], marker="o", s=16, color=color, zorder=9)
        if idx >= len(visible) - 10:
            ax.annotate(f"{t.r:+.1f}R", xy=(t.exit_index, t.exit_price), xytext=(4, 4),
                        textcoords="offset points", color=color, fontsize=6.5,
                        fontweight="bold", zorder=9)


def _draw_equity(ax, result: BacktestResult) -> None:
    eq = result.equity
    if eq is None or len(eq) == 0:
        ax.text(0.5, 0.5, "No trades", color=config.MUTED, ha="center", va="center", transform=ax.transAxes)
        return
    y = eq.to_numpy()
    x = np.arange(len(y))
    ax.plot(x, y, color=config.ACCENT, linewidth=1.4)
    ax.fill_between(x, 10_000, y, color=config.ACCENT, alpha=0.12)
    ax.axhline(10_000, color=config.MUTED, linewidth=0.6, linestyle="--", alpha=0.6)
    ax.set_xlim(0, max(1, len(y) - 1))
    lo, hi = float(np.min(y)), float(np.max(y))
    pad = max((hi - lo) * 0.15, 10_000 * 0.005)
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_ylabel("Equity ($)", color=config.MUTED, fontsize=7)
    ax.tick_params(axis="y", labelsize=7)
    state = "PROFIT" if y[-1] >= 10_000 else "LOSS"
    ax.text(0.01, 0.9, f"Equity curve · {state}", transform=ax.transAxes,
            color=config.MUTED, fontsize=7, va="top")


def _stat_card(fig, x, y, label, value, color=None):
    fig.text(x, y, label.upper(), color=config.MUTED, fontsize=7, fontweight="bold", va="top")
    fig.text(x, y - 0.035, value, color=color or config.TEXT, fontsize=12, fontweight="bold", va="top")


def render_backtest(result: BacktestResult, out_path: Path, last_bars: int = 260) -> Path:
    df = result.df
    ctx = result.context or {}
    if df is None or len(df) == 0:
        raise ValueError("Data kosong")
    n = len(df)
    start = max(0, n - last_bars)
    end = n - 1
    times = df["time"]
    digits = 2
    fig = plt.figure(figsize=(13.2, 8.0), facecolor=config.BG)
    gs = fig.add_gridspec(2, 1, height_ratios=[3.4, 1.0], hspace=0.08,
                          left=0.045, right=0.94, top=0.86, bottom=0.075)
    ax = fig.add_subplot(gs[0])
    axe = fig.add_subplot(gs[1], sharex=None)
    _style_ax(ax)
    _style_ax(axe, show_x=False)
    _draw_zones(ax, result, start, end)
    _draw_candles(ax, df, start, end)
    _draw_structure(ax, result, start, end)
    ax.plot(np.arange(n), df["ema20"].to_numpy(), color=config.GOLD, linewidth=0.8, alpha=0.8, label="EMA20")
    ax.plot(np.arange(n), df["ema50"].to_numpy(), color=config.ACCENT, linewidth=0.8, alpha=0.8, label="EMA50")
    ax.plot(np.arange(n), df["ema200"].to_numpy(), color=config.VIOLET, linewidth=0.9, alpha=0.7, label="EMA200")
    _draw_trades(ax, result, start, end)
    ax.set_xlim(start - 1, end + 2)
    lo = float(df["low"].iloc[start:].min())
    hi = float(df["high"].iloc[start:].max())
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_ylabel("")
    ax.legend(loc="upper left", frameon=False, fontsize=7, labelcolor=config.MUTED,
              ncol=3, bbox_to_anchor=(0, 1.02))
    ax.xaxis.set_major_locator(MaxNLocator(7))
    ax.xaxis.set_major_formatter(_time_formatter(times, result.tf))
    ax.tick_params(axis="x", labelbottom=False)
    # last price tag
    last_close = float(df["close"].iloc[-1])
    ax.annotate(f"{last_close:,.2f}", xy=(end, last_close), xytext=(4, 0),
                textcoords="offset points", color="#07110f", fontsize=7, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.2", fc=config.ACCENT, ec="none"), va="center")

    _draw_equity(axe, result)
    axe.xaxis.set_major_locator(MaxNLocator(7))

    # --------------------------------------------------------------- header
    s = result.stats
    fig.text(0.045, 0.955, "ICT TERMINAL PRO", color=config.ACCENT, fontsize=9, fontweight="bold")
    fig.text(0.045, 0.915, f"{result.symbol} · {result.tf} · ICT Confluence Backtest",
             color="#ffffff", fontsize=17, fontweight="bold")
    period = f"{df['time'].iloc[start].strftime('%d %b %Y')} → {df['time'].iloc[-1].strftime('%d %b %Y')}"
    fig.text(0.045, 0.885, f"{period}  ·  {n} candles  ·  RR {s.get('rr', 1.5):.1f}  ·  data MetaTrader 5",
             color=config.MUTED, fontsize=8)
    stat_y = 0.955
    _stat_card(fig, 0.47, stat_y, "Trades", str(s.get("trades", 0)))
    _stat_card(fig, 0.54, stat_y, "Win rate", f"{s.get('win_rate', 0):.1f}%",
               config.BULL if s.get("win_rate", 0) >= 50 else config.GOLD)
    _stat_card(fig, 0.62, stat_y, "Profit factor", f"{s.get('profit_factor', 0):.2f}",
               config.BULL if s.get("profit_factor", 0) >= 1 else config.BEAR)
    _stat_card(fig, 0.70, stat_y, "Expectancy", f"{s.get('expectancy_r', 0):+.2f}R",
               config.BULL if s.get("expectancy_r", 0) >= 0 else config.BEAR)
    _stat_card(fig, 0.78, stat_y, "Net", f"{s.get('net_r', 0):+.1f}R",
               config.BULL if s.get("net_r", 0) >= 0 else config.BEAR)
    _stat_card(fig, 0.86, stat_y, "Max DD", f"{s.get('max_dd', 0):.1f}%")
    fig.text(0.045, 0.028, "Sumber data: MetaTrader 5 · Entry pada open candle berikutnya · SL dicek sebelum TP · "
             "spread & komisi diperhitungkan · bukan nasihat investasi.",
             color=config.MUTED, fontsize=6.5)
    fig.savefig(out_path, dpi=150, facecolor=config.BG)
    plt.close(fig)
    return out_path


def render_summary(results: dict[str, BacktestResult], symbol: str, out_path: Path) -> Path:
    tfs = [tf for tf in config.TF_ORDER if tf in results]
    if not tfs:
        raise ValueError("Tidak ada hasil backtest")
    fig = plt.figure(figsize=(14, 9), facecolor=config.BG)
    gs = fig.add_gridspec(2, 3, height_ratios=[1.25, 1.0], width_ratios=[1.5, 1.1, 1.1],
                          left=0.055, right=0.955, top=0.84, bottom=0.07, hspace=0.3, wspace=0.28)
    ax_eq = fig.add_subplot(gs[0, 0])
    ax_bar = fig.add_subplot(gs[0, 1])
    ax_win = fig.add_subplot(gs[0, 2])
    ax_tbl = fig.add_subplot(gs[1, :])
    for ax in (ax_eq, ax_bar, ax_win):
        _style_ax(ax)
        ax.tick_params(axis="x", labelbottom=True)
    palette = [config.ACCENT, config.BULL, config.GOLD, config.VIOLET, config.BEAR, "#4dd0e1", "#ff8a65"]
    for idx, tf in enumerate(tfs):
        r = results[tf]
        if r.equity is None or len(r.equity) == 0:
            continue
        y = r.equity.to_numpy()
        x = np.linspace(0, 1, len(y))
        ax_eq.plot(x * 100, y, color=palette[idx % len(palette)], linewidth=1.3, label=tf)
    ax_eq.axhline(10_000, color=config.MUTED, linewidth=0.6, linestyle="--", alpha=0.5)
    ax_eq.set_title("Equity curve per timeframe", color=config.TEXT, fontsize=9, loc="left")
    ax_eq.set_xlabel("Trade progress (%)", color=config.MUTED, fontsize=7)
    ax_eq.set_ylabel("Equity ($)", color=config.MUTED, fontsize=7)
    ax_eq.legend(fontsize=6, frameon=False, labelcolor=config.MUTED, ncol=2, loc="lower left")

    tfs_present = [tf for tf in tfs]
    net = [results[tf].stats.get("net_r", 0) for tf in tfs_present]
    colors = [config.BULL if v >= 0 else config.BEAR for v in net]
    ax_bar.barh(tfs_present, net, color=colors, alpha=0.85)
    ax_bar.axvline(0, color=config.MUTED, linewidth=0.7)
    ax_bar.set_title("Net R per timeframe", color=config.TEXT, fontsize=9, loc="left")
    ax_bar.tick_params(axis="y", labelsize=8)
    ax_bar.set_xlabel("R", color=config.MUTED, fontsize=7)

    win = [results[tf].stats.get("win_rate", 0) for tf in tfs_present]
    ax_win.barh(tfs_present, win, color=config.ACCENT, alpha=0.75)
    ax_win.axvline(50, color=config.GOLD, linewidth=0.8, linestyle="--")
    ax_win.set_xlim(0, 100)
    ax_win.set_title("Win rate (%)", color=config.TEXT, fontsize=9, loc="left")
    ax_win.set_xlabel("%", color=config.MUTED, fontsize=7)

    # ------------------------------------------------------------- table
    ax_tbl.axis("off")
    headers = ["TF", "Trades", "Win %", "PF", "Expectancy", "Net R", "Max DD", "Avg bars"]
    cell_text = [results[tf].summary_row() for tf in tfs_present]
    table = ax_tbl.table(cellText=cell_text, colLabels=headers, loc="upper center",
                         cellLoc="center", colLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.45)
    for (row, col), cell in table.get_celld().items():
        cell.set_facecolor(config.PANEL if row % 2 == 0 else config.PANEL_ALT)
        cell.set_edgecolor(config.BORDER)
        cell.get_text().set_color(config.TEXT if row > 0 else config.MUTED)
        if row == 0:
            cell.get_text().set_fontweight("bold")
        if col == 5 and row > 0:
            val = net[row - 1]
            cell.get_text().set_color(config.BULL if val >= 0 else config.BEAR)
    ax_tbl.set_title("Ringkasan backtest ICT per timeframe", color=config.TEXT, fontsize=10,
                     loc="left", pad=12)

    totals = [sum(results[tf].stats.get("trades", 0) for tf in tfs_present),
              sum(results[tf].stats.get("net_r", 0) for tf in tfs_present)]
    fig.text(0.055, 0.955, "ICT TERMINAL PRO", color=config.ACCENT, fontsize=9, fontweight="bold")
    fig.text(0.055, 0.912, f"{symbol} · Multi-Timeframe ICT Backtest",
             color="#ffffff", fontsize=19, fontweight="bold")
    fig.text(0.055, 0.882, f"Order Blocks + FVG + Liquidity Sweeps + Market Structure  ·  "
             f"{totals[0]} trades  ·  net {totals[1]:+.1f}R  ·  risk 1% per trade",
             color=config.MUTED, fontsize=8.5)
    fig.text(0.055, 0.028, "Backtest bersifat riset. Hasil masa lalu tidak menjamin performa masa depan. "
             "Data: MetaTrader 5.", color=config.MUTED, fontsize=6.5)
    fig.savefig(out_path, dpi=150, facecolor=config.BG)
    plt.close(fig)
    return out_path


def render_forecast(signal: TimeframeSignal, out_path: Path, last_bars: int = 200) -> Path:
    ctx = signal.context
    df = ctx["df"]
    n = len(df)
    start = max(0, n - last_bars)
    end = n - 1
    steps = 38
    fx, fy, fhi, flo = forecast_path(signal, steps)
    future_x = np.arange(n, n + steps)

    fig = plt.figure(figsize=(13.2, 7.6), facecolor=config.BG)
    ax = fig.add_axes([0.045, 0.09, 0.90, 0.76])
    _style_ax(ax)
    pseudo = BacktestResult(symbol=signal.symbol, tf=signal.tf, context=ctx, df=df)
    _draw_zones(ax, pseudo, start, end)
    _draw_candles(ax, df, start, end)
    _draw_structure(ax, pseudo, start, end)
    ax.plot(np.arange(n), df["ema20"].to_numpy(), color=config.GOLD, linewidth=0.8, alpha=0.8)
    ax.plot(np.arange(n), df["ema50"].to_numpy(), color=config.ACCENT, linewidth=0.8, alpha=0.8)
    ax.plot(np.arange(n), df["ema200"].to_numpy(), color=config.VIOLET, linewidth=0.8, alpha=0.7)
    ax.axvline(end, color=config.BORDER, linewidth=0.8, linestyle="--")

    color = config.BULL if signal.direction == "long" else config.BEAR
    ax.fill_between(future_x, flo, fhi, color=color, alpha=0.13, zorder=2)
    ax.plot(future_x, fy, color=color, linewidth=1.6, linestyle=(0, (4, 2)), zorder=8)
    ax.axhline(signal.entry, xmin=(start) / (n + steps), xmax=1.0,
               color=config.ACCENT, linewidth=0.9, linestyle="--", alpha=0.9)
    ax.axhline(signal.stop, xmin=(start) / (n + steps), xmax=1.0,
               color=config.BEAR, linewidth=0.9, linestyle="--", alpha=0.9)
    ax.axhline(signal.target, xmin=(start) / (n + steps), xmax=1.0,
               color=config.BULL, linewidth=0.9, linestyle="--", alpha=0.9)
    box_x = end + 1
    box_w = steps - 2
    ax.add_patch(Rectangle((box_x, min(signal.entry, signal.stop)), box_w,
                           abs(signal.entry - signal.stop), facecolor=_hex(config.SHORT_ZONE),
                           edgecolor="none", zorder=1))
    ax.add_patch(Rectangle((box_x, min(signal.entry, signal.target)), box_w,
                           abs(signal.entry - signal.target), facecolor=_hex(config.LONG_ZONE),
                           edgecolor="none", zorder=1))
    ax.text(box_x + box_w * 0.55, signal.entry, f"ENTRY {signal.entry:,.2f}",
            color=config.ACCENT, fontsize=8, fontweight="bold", va="bottom", ha="center",
            bbox=dict(boxstyle="round,pad=0.22", fc=config.PANEL, ec=config.ACCENT, lw=0.6))
    ax.text(box_x + box_w * 0.55, signal.stop, f"SL {signal.stop:,.2f}",
            color=config.BEAR, fontsize=7.5, va="top", ha="center",
            bbox=dict(boxstyle="round,pad=0.2", fc=config.PANEL, ec=config.BEAR, lw=0.5))
    ax.text(box_x + box_w * 0.55, signal.target, f"TP {signal.target:,.2f}",
            color=config.BULL, fontsize=7.5, va="bottom", ha="center",
            bbox=dict(boxstyle="round,pad=0.2", fc=config.PANEL, ec=config.BULL, lw=0.5))
    ax.text(box_x + box_w * 0.5, (signal.entry + signal.target) / 2,
            f"R:R {signal.rr:.1f}\n{signal.signal}", color=color, fontsize=11,
            fontweight="bold", ha="center", va="center", alpha=0.95)

    lo = float(min(df["low"].iloc[start:].min(), signal.stop, flo.min()))
    hi = float(max(df["high"].iloc[start:].max(), signal.target, fhi.max()))
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(start - 1, n + steps + 2)
    ax.set_ylabel("")
    ax.xaxis.set_major_locator(MaxNLocator(8))
    ax.xaxis.set_major_formatter(_time_formatter(df["time"], signal.tf))

    fig.text(0.045, 0.955, "ICT TERMINAL PRO", color=config.ACCENT, fontsize=9, fontweight="bold")
    fig.text(0.045, 0.905, f"{signal.symbol} · {signal.tf} · {signal.signal} FORECAST",
             color=color, fontsize=20, fontweight="bold")
    fig.text(0.045, 0.87, f"Score {signal.score:+.0f} / 100  ·  Confidence {signal.confidence}%  ·  "
             f"{signal.structure}  ·  {signal.pd_zone.title()}  ·  {signal.zone}",
             color=config.MUTED, fontsize=8.5)
    reason_text = "\n".join(f"• {r}" for r in signal.reasons[1:6])
    fig.text(0.78, 0.955, reason_text, color=config.TEXT, fontsize=7.5, va="top",
             bbox=dict(boxstyle="round,pad=0.6", fc=config.PANEL, ec=config.BORDER, alpha=0.95))
    fig.text(0.045, 0.025, "Garis proyeksi adalah skenario teknikal, bukan jaminan arah harga. "
             "Gunakan manajemen risiko.", color=config.MUTED, fontsize=6.5)
    fig.savefig(out_path, dpi=150, facecolor=config.BG)
    plt.close(fig)
    return out_path


def render_dashboard(symbol: str, signals: dict[str, TimeframeSignal], out_path: Path) -> Path:
    """Screen-friendly 16:9 dashboard (3 columns) across timeframes."""
    tfs = [tf for tf in config.TF_ORDER if tf in signals]
    fig = plt.figure(figsize=(16, 9), facecolor=config.BG)
    gs = fig.add_gridspec(3, 3, left=0.035, right=0.965, top=0.825, bottom=0.055,
                          hspace=0.52, wspace=0.17)
    for idx, tf in enumerate(tfs):
        sig = signals[tf]
        ax = fig.add_subplot(gs[idx // 3, idx % 3])
        _style_ax(ax, show_x=False)
        ctx = sig.context
        df = ctx["df"]
        n = len(df)
        # 16 candles per panel with very wide gaps.
        start = max(0, n - 16)
        end = n - 1
        pseudo = BacktestResult(symbol=symbol, tf=tf, context=ctx, df=df)
        _draw_zones(ax, pseudo, start, end, labels=False)
        _draw_candles(ax, df, start, end, width=0.40)
        ax.plot(np.arange(n), df["ema20"].to_numpy(), color=config.GOLD, linewidth=0.55, alpha=0.75)
        ax.plot(np.arange(n), df["ema50"].to_numpy(), color=config.ACCENT, linewidth=0.55, alpha=0.75)
        color = config.BULL if sig.signal == "BUY" else (config.BEAR if sig.signal == "SELL" else config.MUTED)
        ax.set_xlim(start - 1, n + 1)
        lo = float(df["low"].iloc[start:].min())
        hi = float(df["high"].iloc[start:].max())
        pad = (hi - lo) * 0.08
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_title(f"{tf}  ·  {sig.signal}  ·  {sig.score:+.0f}",
                     color=color, fontsize=9.5, fontweight="bold", loc="left")
        ax.text(0.99, 0.05, f"R:R {sig.rr:.1f}  ·  {sig.confidence}%", transform=ax.transAxes,
                color=config.MUTED, fontsize=6.5, ha="right")
        ax.set_xticks([])
        ax.tick_params(axis="y", labelsize=6.5)

    # Legend / summary fills the last two cells of the 3x3 grid.
    if len(tfs) < 9:
        legend_row = len(tfs) // 3
        legend_col = 1 if len(tfs) % 3 == 1 else 0
        ax_leg = fig.add_subplot(gs[legend_row, legend_col:])
        ax_leg.set_xlim(0, 1)
        ax_leg.set_ylim(0, 1)
        ax_leg.axis("off")
        ax_leg.add_patch(Rectangle((0, 0), 1, 1, facecolor=config.PANEL_ALT,
                                   edgecolor=config.BORDER, linewidth=0.8,
                                   transform=ax_leg.transAxes))
        ax_leg.text(0.045, 0.88, "CARA BACA DASHBOARD", color=config.ACCENT,
                    fontsize=8.5, fontweight="bold", transform=ax_leg.transAxes)
        items = [
            (config.BULL, "Demand Order Block / candle bullish"),
            (config.BEAR, "Supply Order Block / candle bearish"),
            (config.ACCENT, "FVG biru = bullish, oranye = bearish"),
            (config.GOLD, "Garis liquidity BSL / SSL / EQH / EQL"),
            (config.BULL, "BOS / CHoCH bullish (hijau), bearish (merah)"),
        ]
        for i, (color, text) in enumerate(items):
            col = 0 if i < 3 else 1
            row = i if i < 3 else i - 3
            x = 0.045 if col == 0 else 0.515
            y = 0.66 - row * 0.16
            ax_leg.add_patch(Rectangle((x, y - 0.018), 0.045, 0.045,
                                       facecolor=color, edgecolor="none",
                                       transform=ax_leg.transAxes))
            ax_leg.text(x + 0.065, y + 0.003, text, color=config.TEXT, fontsize=7.2,
                        va="center", transform=ax_leg.transAxes)
        ax_leg.plot([0.045, 0.955], [0.245, 0.245], color=config.BORDER, linewidth=0.7,
                    transform=ax_leg.transAxes)
        buy = sum(1 for s in signals.values() if s.signal == "BUY")
        sell = sum(1 for s in signals.values() if s.signal == "SELL")
        wait = sum(1 for s in signals.values() if s.signal == "WAIT")
        ax_leg.text(0.045, 0.16, f"KONFLUENSI  {buy} BUY  ·  {sell} SELL  ·  {wait} WAIT",
                    color=config.TEXT, fontsize=8.2, fontweight="bold", transform=ax_leg.transAxes)
        ax_leg.text(0.045, 0.09, "Panah EMA20/EMA50 · label sinyal dihitung ulang saat export.",
                    color=config.MUTED, fontsize=6.5, transform=ax_leg.transAxes)
        ax_leg.text(0.045, 0.03, "Sinyal bersifat probabilistik — bukan rekomendasi investasi.",
                    color=config.MUTED, fontsize=6.2, transform=ax_leg.transAxes)

    fig.text(0.035, 0.955, "ICT TERMINAL PRO", color=config.ACCENT, fontsize=9, fontweight="bold")
    fig.text(0.035, 0.91, f"{symbol} · Multi-Timeframe Signal Dashboard",
             color="#ffffff", fontsize=19, fontweight="bold")
    fig.text(0.035, 0.872, f"V4 · 16 candles/panel  ·  Generated {datetime.now():%d %b %Y %H:%M}  ·  server time",
             color=config.MUTED, fontsize=8)
    fig.text(0.965, 0.951, "V4", color=config.GOLD, fontsize=11, fontweight="bold", ha="right")
    fig.text(0.035, 0.018, "Sinyal bersifat teknikal dan probabilistik. Bukan rekomendasi investasi.",
             color=config.MUTED, fontsize=6.5)
    fig.savefig(out_path, dpi=150, facecolor=config.BG)
    plt.close(fig)
    return out_path
