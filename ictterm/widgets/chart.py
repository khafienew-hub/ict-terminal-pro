"""Candlestick chart widget with ICT overlays and draggable order boxes."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config, ict
from ..history import HistoryTrade, index_for_time
from .order_tool import PositionTool

pg.setConfigOptions(antialias=True, background=config.BG, foreground=config.MUTED)


def _enum(name: str) -> Any:
    """Small compatibility shim for PyQt5/PyQt6 enum access."""
    scope = getattr(QtCore.Qt, "PenStyle", None)
    if scope is not None:
        return getattr(scope, name)
    return getattr(QtCore.Qt, name)


class BarDateAxis(pg.AxisItem):
    """Date axis driven by bar index instead of timestamps (no weekend gaps)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timestamps: list[pd.Timestamp] = []
        self.tf = "M15"

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        out = []
        for value in values:
            i = int(round(value))
            if 0 <= i < len(self.timestamps):
                ts = self.timestamps[i]
                if self.tf in ("M1", "M5", "M15", "M30"):
                    out.append(ts.strftime("%d %b\n%H:%M"))
                elif self.tf in ("H1", "H4"):
                    out.append(ts.strftime("%d %b\n%H:%M"))
                else:
                    out.append(ts.strftime("%d %b\n%Y"))
            else:
                out.append("")
        return out


class CandlestickItem(pg.GraphicsObject):
    def __init__(self, df: pd.DataFrame, width: float = 0.66):
        super().__init__()
        self.df = df
        self.width = width
        self._bounds = QtCore.QRectF()
        self.set_data(df)

    def set_data(self, df: pd.DataFrame) -> None:
        self.df = df
        if df is None or len(df) == 0:
            self._bounds = QtCore.QRectF()
            self.update()
            return
        h = df["high"].to_numpy()
        l = df["low"].to_numpy()
        n = len(df)
        pad = (h.max() - l.min()) * 0.03 + 1e-9
        self._bounds = QtCore.QRectF(-1.0, float(l.min()) - pad, n + 1.0,
                                     float(h.max() - l.min()) + pad * 2)
        self.prepareGeometryChange()
        self.informViewBoundsChanged()
        self.update()

    def paint(self, painter: QtGui.QPainter, *args) -> None:
        if self.df is None or len(self.df) == 0:
            return
        o = self.df["open"].to_numpy()
        h = self.df["high"].to_numpy()
        l = self.df["low"].to_numpy()
        c = self.df["close"].to_numpy()
        n = len(self.df)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
        bull = QtGui.QColor(config.BULL)
        bear = QtGui.QColor(config.BEAR)
        width = self.width

        # Draw only the visible bars; avoids repainting hundreds of off-screen candles.
        x0, x1 = 0, n
        vb = self.getViewBox()
        if vb is not None:
            try:
                xr = vb.viewRange()[0]
                x0 = max(0, int(np.floor(xr[0])) - 1)
                x1 = min(n, int(np.ceil(xr[1])) + 2)
            except Exception:
                pass
        for i in range(x0, x1):
            color = bull if c[i] >= o[i] else bear
            pen = QtGui.QPen(color)
            pen.setCosmetic(True)   # 1 px at any zoom; not 1 whole price bar
            pen.setWidthF(0.0)
            painter.setPen(pen)
            painter.drawLine(QtCore.QPointF(i, l[i]), QtCore.QPointF(i, h[i]))
            body_low = min(o[i], c[i])
            body_high = max(o[i], c[i])
            if body_high - body_low < 1e-12:
                painter.drawLine(QtCore.QPointF(i - width / 2, body_low),
                                 QtCore.QPointF(i + width / 2, body_low))
            else:
                painter.setBrush(QtGui.QBrush(color))
                painter.drawRect(QtCore.QRectF(i - width / 2, body_low, width, body_high - body_low))

    def boundingRect(self) -> QtCore.QRectF:  # noqa: N802
        return self._bounds


class ChartWidget(pg.GraphicsLayoutWidget):
    crosshair_info = QtCore.pyqtSignal(str)
    order_mode_changed = QtCore.pyqtSignal(bool)
    tool_added = QtCore.pyqtSignal()
    replay_state = QtCore.pyqtSignal(bool, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground(config.BG)
        self.date_axis = BarDateAxis(orientation="bottom")
        self.vol_axis = BarDateAxis(orientation="bottom")
        self.plot: pg.PlotItem = self.addPlot(row=0, col=0, axisItems={"bottom": self.date_axis})
        self.vol: pg.PlotItem = self.addPlot(row=1, col=0, axisItems={"bottom": self.vol_axis})
        self.vol.setXLink(self.plot)
        self.ci.layout.setRowStretchFactor(0, 4)
        self.ci.layout.setRowStretchFactor(1, 1)
        self.ci.layout.setSpacing(2)
        for p in (self.plot, self.vol):
            p.setMenuEnabled(False)
            p.hideButtons()
            p.showGrid(x=True, y=True, alpha=0.16)
            p.getViewBox().setBackgroundColor(config.BG)
            p.hideAxis("left")
            p.getAxis("right").setWidth(64)
            p.getAxis("right").setPen(pg.mkPen(config.BORDER))
            p.getAxis("right").setTextPen(pg.mkPen(config.MUTED))
            p.getAxis("bottom").setPen(pg.mkPen(config.BORDER))
            p.getAxis("bottom").setTextPen(pg.mkPen(config.MUTED))
        self.plot.showAxis("right")
        self.vol.hideAxis("right")
        self.plot.getAxis("bottom").setStyle(showValues=False)
        self.vol.getAxis("bottom").setStyle(showValues=True)
        self.vol.setFixedHeight(112)
        self.vol.setMaximumHeight(150)
        self.vol.showGrid(x=True, y=True, alpha=0.10)

        self.symbol = ""
        self.tf = "M15"
        self.df = pd.DataFrame()
        self.ctx: dict = {}
        self.signal_obj = None
        self.digits = 2
        self.point = 0.01
        self.overlay_items: list[Any] = []
        self.history_trades: list[HistoryTrade] = []
        self.history_items: list[Any] = []
        self.show_history = True
        self.replay_active = False
        self.replay_index = 0
        self.replay_timer = QtCore.QTimer(self)
        self.replay_timer.timeout.connect(self._replay_tick)
        self.tools: list[PositionTool] = []
        self.auto_tool: PositionTool | None = None
        self.order_mode: str | None = None
        self.auto_forecast = True
        self.show_flags = {
            "ema": True, "ob": True, "fvg": True, "structure": True,
            "liquidity": True, "volume": True, "killzones": False,
        }
        self._adjusting_y = False
        self._last_key: tuple[str, str] | None = None
        self._hover_index: int | None = None

        self.candles = CandlestickItem(pd.DataFrame(columns=["open", "high", "low", "close"]))
        self.plot.addItem(self.candles)
        self.candles.setZValue(5)
        self.volume_item = pg.BarGraphItem(x=[], height=[], width=0.66, brush=config.BULL)
        self.vol.addItem(self.volume_item)
        self.ema20 = pg.PlotDataItem(pen=pg.mkPen(config.GOLD, width=1.1))
        self.ema50 = pg.PlotDataItem(pen=pg.mkPen(config.ACCENT, width=1.1))
        self.ema200 = pg.PlotDataItem(pen=pg.mkPen(config.VIOLET, width=1.2))
        for item in (self.ema20, self.ema50, self.ema200):
            item.setZValue(10)
            self.plot.addItem(item)

        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen((200, 215, 230, 70), width=0.8, style=_enum("DashLine")))
        self.hline = pg.InfiniteLine(angle=0, movable=False,
                                     pen=pg.mkPen((200, 215, 230, 70), width=0.8, style=_enum("DashLine")))
        for line in (self.vline, self.hline):
            line.setZValue(18)
            self.plot.addItem(line)
            line.hide()
        self.price_tag = pg.InfLineLabel(self.hline, "", position=0.985,
                                         color=config.TEXT, fill=(24, 34, 47, 230),
                                         movable=False)
        try:
            self.price_tag.setFont(QtGui.QFont("Segoe UI", 8))
        except Exception:
            pass

        self._mouse_proxy = pg.SignalProxy(self.plot.scene().sigMouseMoved,
                                           rateLimit=30, slot=self._on_mouse_move)
        self.plot.scene().sigMouseClicked.connect(self._on_scene_click)
        self.plot.vb.sigRangeChangedManually.connect(lambda *_: self._autoscale_y())

    # ------------------------------------------------------------------ data
    def set_data(self, symbol: str, tf: str, df: pd.DataFrame, signal_obj=None,
                 digits: int = 2, point: float = 0.01, keep_view: bool = True) -> None:
        key = (symbol, tf)
        reset = key != self._last_key or not keep_view
        if reset and self.replay_active:
            self.stop_replay()
        self.symbol = symbol
        self.tf = tf
        self.df = df
        self.signal_obj = signal_obj
        self.digits = digits
        self.point = point
        if signal_obj is not None and getattr(signal_obj, "context", None):
            self.ctx = signal_obj.context
        else:
            self.ctx = ict.analyze(df)
        enriched = self.ctx.get("df", df)
        if enriched is not None and len(enriched) == len(df):
            self.df = enriched
        self.date_axis.timestamps = list(self.df["time"])
        self.date_axis.tf = tf
        self.vol_axis.timestamps = self.date_axis.timestamps
        self.vol_axis.tf = tf
        self.candles.set_data(self.df)
        self._draw_emas()
        self._draw_volume()
        self._update_volume_axis()
        if reset:
            self.clear_tools()
        n = len(self.df)
        if reset or not self.plot.vb.viewRange()[0][1]:
            self.plot.setXRange(max(0, n - 175), n + 34, padding=0)
        self._draw_overlays()
        self._draw_history()
        self._autoscale_y()
        if reset:
            self._last_key = key
        if self.auto_forecast and self.signal_obj is not None and self.auto_tool is None:
            self.create_forecast_tool(self.signal_obj, auto=True)

    # -------------------------------------------------------------- overlays
    def _clear_overlays(self) -> None:
        for item in self.overlay_items:
            try:
                if item.scene() is self.plot.scene():
                    self.plot.removeItem(item)
                else:
                    self.vol.removeItem(item)
            except Exception:
                pass
        self.overlay_items.clear()

    def _draw_emas(self) -> None:
        x = np.arange(len(self.df))
        for item, col in ((self.ema20, "ema20"), (self.ema50, "ema50"), (self.ema200, "ema200")):
            if col in self.df.columns and self.show_flags["ema"]:
                item.setData(x, self.df[col].to_numpy(), connect="finite")
                item.show()
            else:
                item.setData([], [])
                item.hide()
        for item in (self.ema20, self.ema50, self.ema200):
            item.setVisible(item is not None and self.show_flags["ema"] and len(self.df) > 0)

    def _draw_volume(self) -> None:
        if len(self.df) == 0:
            self.volume_item.setOpts(x=[], height=[])
            return
        x = np.arange(len(self.df))
        h = self.df["tick_volume"].to_numpy(dtype=float)
        up = (self.df["close"] >= self.df["open"]).to_numpy()
        brushes = [pg.mkBrush(config.BULL + "88" if up[i] else config.BEAR + "88") for i in range(len(x))]
        self.volume_item.setOpts(x=x, height=h, width=0.66, brushes=brushes)
        self.volume_item.setVisible(self.show_flags["volume"])
        self.vol.setVisible(self.show_flags["volume"])

    def _draw_overlays(self) -> None:
        self._clear_overlays()
        if len(self.df) == 0:
            return
        n = len(self.df)
        ctx = self.ctx
        x_view = self.plot.vb.viewRange()[0]
        vis_start = max(0, int(x_view[0]) - 20)
        vis_end = min(n + 40, int(x_view[1]) + 40)

        if self.show_flags["ob"]:
            obs = [z for z in ctx.get("order_blocks", []) if z.created <= vis_end][-8:]
            for idx, z in enumerate(obs):
                x0 = max(vis_start, z.created)
                x1 = min(max(vis_end, n + 20), z.mitigated if z.mitigated else n + 20)
                if x1 <= x0:
                    continue
                face = config.LONG_ZONE if z.direction == "bull" else config.SHORT_ZONE
                rect = QtWidgets.QGraphicsRectItem(x0, z.bottom, x1 - x0, max(z.top - z.bottom, 1e-9))
                rect.setBrush(pg.mkBrush(face))
                rect.setPen(pg.mkPen((*face[:3], 150), width=0.7))
                rect.setZValue(-6)
                self.plot.addItem(rect)
                self.overlay_items.append(rect)
                if idx >= len(obs) - 2:
                    label = pg.TextItem("OB", color=(200, 212, 225, 150), anchor=(0, 0))
                    label.setPos(x0, z.top)
                    label.setZValue(-4)
                    self.plot.addItem(label)
                    self.overlay_items.append(label)

        if self.show_flags["fvg"]:
            fvgs = [z for z in ctx.get("fvgs", []) if z.created <= vis_end][-6:]
            for idx, z in enumerate(fvgs):
                x0 = max(vis_start, z.created)
                x1 = min(max(vis_end, n + 20), z.mitigated if z.mitigated else n + 20)
                if x1 <= x0:
                    continue
                face = config.FVG_BULL if z.direction == "bull" else config.FVG_BEAR
                rect = QtWidgets.QGraphicsRectItem(x0, z.bottom, x1 - x0, max(z.top - z.bottom, 1e-9))
                rect.setBrush(pg.mkBrush(face))
                rect.setPen(pg.mkPen((*face[:3], 160), width=0.6, style=_enum("DashLine")))
                rect.setZValue(-7)
                self.plot.addItem(rect)
                self.overlay_items.append(rect)
                if idx >= len(fvgs) - 2:
                    label = pg.TextItem("FVG", color=(200, 212, 225, 130), anchor=(0, 1))
                    label.setPos(x0, z.bottom)
                    label.setZValue(-4)
                    self.plot.addItem(label)
                    self.overlay_items.append(label)

        if self.show_flags["structure"]:
            events = [e for e in ctx.get("events", []) if vis_start <= e["index"] <= vis_end][-4:]
            for e in events:
                color = config.BULL if e["dir"] == "bull" else config.BEAR
                line = pg.PlotDataItem(
                    [e["swing_index"], e["index"]], [e["price"], e["price"]],
                    pen=pg.mkPen(color, width=0.8, style=_enum("DashLine")),
                )
                line.setZValue(12)
                self.plot.addItem(line)
                self.overlay_items.append(line)
                text = pg.TextItem(f"{e['kind']} {'▲' if e['dir'] == 'bull' else '▼'}",
                                   color=color, anchor=(0, 1))
                text.setPos(e["index"], e["price"])
                text.setZValue(13)
                self.plot.addItem(text)
                self.overlay_items.append(text)

            for s in [s for s in ctx.get("sweeps", []) if vis_start <= s["index"] <= vis_end][-3:]:
                marker = pg.ScatterPlotItem(
                    [s["index"]], [s["price"]], symbol="x", size=9,
                    pen=pg.mkPen(config.GOLD, width=1.3),
                )
                marker.setZValue(14)
                self.plot.addItem(marker)
                self.overlay_items.append(marker)

        if self.show_flags["liquidity"]:
            levels = []
            for lv in ctx.get("equal_highs", [])[-2:]:
                levels.append(("EQH", lv["price"], config.GOLD))
            for lv in ctx.get("equal_lows", [])[-2:]:
                levels.append(("EQL", lv["price"], config.GOLD))
            levels.append(("BSL", ctx.get("liquidity_above", 0.0), config.GOLD))
            levels.append(("SSL", ctx.get("liquidity_below", 0.0), config.GOLD))
            used = set()
            for name, price, color in levels:
                if not price or round(price, 6) in used:
                    continue
                used.add(round(price, 6))
                line = pg.InfiniteLine(
                    pos=price, angle=0, movable=False,
                    pen=pg.mkPen(color, width=0.8, style=_enum("DotLine")),
                )
                line.setZValue(3)
                self.plot.addItem(line)
                self.overlay_items.append(line)
                label = pg.TextItem(f"{name} {price:,.{self.digits}f}", color=color,
                                    anchor=(0, 0.5), fill=(11, 15, 20, 190))
                label.setPos(max(0, x_view[0] + 2), price)
                label.setZValue(13)
                self.plot.addItem(label)
                self.overlay_items.append(label)

        if self.show_flags["killzones"]:
            self._draw_killzones(vis_start, vis_end)

    def _draw_killzones(self, vis_start: int, vis_end: int) -> None:
        if "time" not in self.df.columns:
            return
        active = [ict.killzone_info(ts) for ts in self.df["time"]]
        color_map = {
            "Asia": (79, 156, 249, 16),
            "London Open": (179, 136, 255, 18),
            "New York AM": (38, 166, 154, 16),
            "New York PM": (245, 196, 81, 16),
        }
        run_start = None
        run_name = None
        for i in range(vis_start, min(vis_end, len(active))):
            kz = active[i]
            name = kz["name"] if kz else None
            if name != run_name:
                if run_name and run_start is not None and i - run_start > 1:
                    region = pg.LinearRegionItem(values=(run_start, i), movable=False,
                                                 brush=pg.mkBrush(color_map.get(run_name, (100, 100, 100, 12))))
                    region.setZValue(-12)
                    self.plot.addItem(region)
                    self.overlay_items.append(region)
                run_start = i if name else None
                run_name = name
        if run_name and run_start is not None:
            region = pg.LinearRegionItem(values=(run_start, min(vis_end, len(active))), movable=False,
                                         brush=pg.mkBrush(color_map.get(run_name, (100, 100, 100, 12))))
            region.setZValue(-12)
            self.plot.addItem(region)
            self.overlay_items.append(region)

    # ------------------------------------------------------------- history
    def set_history_trades(self, trades: list[HistoryTrade]) -> None:
        self.history_trades = list(trades or [])
        self._draw_history()

    def set_history_visible(self, visible: bool) -> None:
        self.show_history = bool(visible)
        self._draw_history()

    def _clear_history(self) -> None:
        for item in self.history_items:
            try:
                self.plot.removeItem(item)
            except Exception:
                pass
        self.history_items.clear()

    def _draw_history(self) -> None:
        self._clear_history()
        if not self.show_history or len(self.df) == 0 or not self.history_trades:
            return
        trades = [t for t in self.history_trades if t.symbol == self.symbol and t.tf == self.tf]
        if not trades:
            return
        n = len(self.df)
        for t in trades[-80:]:
            entry_i = index_for_time(self.df, t.entry_time)
            exit_i = index_for_time(self.df, t.exit_time)
            if entry_i is None:
                continue
            if exit_i is None:
                exit_i = min(n - 1, entry_i + 1)
            if exit_i <= entry_i:
                exit_i = min(n - 1, entry_i + 1)
            if exit_i <= entry_i:
                continue
            width = max(0.7, exit_i - entry_i)
            direction_color = config.BULL if t.is_long else config.BEAR
            if t.stop > 0:
                risk = QtWidgets.QGraphicsRectItem(
                    entry_i, min(t.entry, t.stop), width, max(abs(t.entry - t.stop), 1e-9)
                )
                risk.setBrush(pg.mkBrush((239, 83, 80, 26)))
                risk.setPen(pg.mkPen((239, 83, 80, 75), width=0.6))
                risk.setZValue(-5)
                self.plot.addItem(risk)
                self.history_items.append(risk)
            if t.target > 0:
                reward = QtWidgets.QGraphicsRectItem(
                    entry_i, min(t.entry, t.target), width, max(abs(t.target - t.entry), 1e-9)
                )
                reward.setBrush(pg.mkBrush((38, 166, 154, 20)))
                reward.setPen(pg.mkPen((38, 166, 154, 70), width=0.6))
                reward.setZValue(-5)
                self.plot.addItem(reward)
                self.history_items.append(reward)

            line_color = QtGui.QColor(direction_color)
            line_color.setAlpha(150)
            line = pg.PlotDataItem(
                [entry_i, exit_i], [t.entry, t.exit],
                pen=pg.mkPen(line_color, width=0.9, style=_enum("DashLine")),
            )
            line.setZValue(14)
            self.plot.addItem(line)
            self.history_items.append(line)

            entry_marker = pg.ScatterPlotItem(
                [entry_i], [t.entry], symbol="t" if t.is_long else "t1", size=10,
                brush=pg.mkBrush(direction_color), pen=pg.mkPen("#ffffff", width=0.6),
            )
            entry_marker.setZValue(16)
            self.plot.addItem(entry_marker)
            self.history_items.append(entry_marker)

            pnl = t.r if abs(t.r) > 1e-9 else t.profit
            win = pnl >= 0
            exit_color = config.BULL if win else config.BEAR
            exit_marker = pg.ScatterPlotItem(
                [exit_i], [t.exit], symbol="o", size=7,
                brush=pg.mkBrush(exit_color), pen=pg.mkPen("#ffffff", width=0.5),
            )
            exit_marker.setZValue(16)
            self.plot.addItem(exit_marker)
            self.history_items.append(exit_marker)
            label_text = f"{t.r:+.1f}R" if abs(t.r) > 1e-9 else f"{t.profit:+.2f}"
            label = pg.TextItem(label_text, color=exit_color, anchor=(0, 1))
            label.setPos(exit_i + 0.2, t.exit)
            label.setZValue(17)
            self.plot.addItem(label)
            self.history_items.append(label)

    # -------------------------------------------------------------- replay
    def is_replaying(self) -> bool:
        return self.replay_active

    def start_replay(self, interval_ms: int = 800, start_index: int | None = None) -> None:
        n = len(self.df)
        if n < 40:
            return
        if self.replay_active:
            self.replay_timer.stop()
        self.replay_active = True
        self.replay_index = max(20, int(start_index)) if start_index is not None else max(60, n - 300)
        self.replay_timer.start(max(200, int(interval_ms)))
        self._apply_replay_view()
        self.replay_state.emit(True, self.replay_index, n)

    def _apply_replay_view(self) -> None:
        n = len(self.df)
        if n == 0:
            return
        idx = max(0, min(self.replay_index, n - 1))
        self.plot.setXRange(max(0, idx - 120), min(n + 2, idx + 3), padding=0)
        self._autoscale_y()
        self.replay_state.emit(self.replay_active, idx, n)

    def _replay_tick(self) -> None:
        n = len(self.df)
        if not self.replay_active or n == 0:
            return
        if self.replay_index >= n - 1:
            self.pause_replay()
            return
        self.replay_index += 1
        self._apply_replay_view()

    def pause_replay(self) -> None:
        self.replay_timer.stop()
        self.replay_state.emit(self.replay_active, self.replay_index, len(self.df))

    def step_replay(self) -> None:
        self.replay_timer.stop()
        if not self.replay_active:
            self.start_replay()
            self.pause_replay()
            return
        if self.replay_index < len(self.df) - 1:
            self.replay_index += 1
            self._apply_replay_view()

    def stop_replay(self) -> None:
        self.replay_timer.stop()
        self.replay_active = False
        n = len(self.df)
        if n:
            self.plot.setXRange(max(0, n - 175), n + 34, padding=0)
            self._autoscale_y()
        self.replay_state.emit(False, n - 1 if n else 0, n)

    def _update_volume_axis(self) -> None:
        if len(self.df) == 0:
            return
        h = self.df["tick_volume"].to_numpy(dtype=float)
        hi = float(h[-300:].max()) if len(h) else 1.0
        self.vol.setYRange(0, max(hi * 1.15, 1), padding=0)

    def _autoscale_y(self) -> None:
        if self._adjusting_y or len(self.df) == 0:
            return
        x0, x1 = self.plot.vb.viewRange()[0]
        start = max(0, int(np.floor(x0)))
        end = min(len(self.df), int(np.ceil(x1)) + 1)
        if end <= start:
            return
        lo = float(self.df["low"].iloc[start:end].min())
        hi = float(self.df["high"].iloc[start:end].max())
        for tool in self.tools:
            if tool.x1 >= x0 and tool.x0 <= x1:
                lo = min(lo, tool.stop, tool.entry, tool.target)
                hi = max(hi, tool.stop, tool.entry, tool.target)
        pad = max((hi - lo) * 0.08, (self.point or 0.01) * 10)
        self._adjusting_y = True
        try:
            self.plot.setYRange(lo - pad, hi + pad, padding=0)
        finally:
            self._adjusting_y = False

    # --------------------------------------------------------------- tools
    def set_auto_forecast(self, enabled: bool) -> None:
        self.auto_forecast = enabled
        if not enabled:
            self.remove_auto_tools()

    def create_forecast_tool(self, signal_obj, auto: bool = True) -> PositionTool | None:
        if len(self.df) == 0:
            return None
        if auto:
            self.remove_auto_tools()
        n = len(self.df)
        x0 = n - 1
        x1 = n + 30
        tool = PositionTool(
            self.plot, x0, x1, signal_obj.entry, signal_obj.stop, signal_obj.target,
            signal_obj.direction, digits=self.digits, auto=auto, tag="forecast",
        )
        self.tools.append(tool)
        if auto:
            self.auto_tool = tool
        self._autoscale_y()
        self.tool_added.emit()
        return tool

    def create_manual_tool(self, x: float, price: float, direction: str) -> PositionTool:
        n = len(self.df)
        atr = float(self.ctx.get("atr", 0) or 0)
        if atr <= 0:
            atr = float((self.df["high"].tail(20) - self.df["low"].tail(20)).mean())
        atr = max(atr, (self.point or 0.01) * 20)
        risk = max(atr * 1.5, (self.point or 0.01) * 30)
        stop = price - risk if direction == "long" else price + risk
        target = price + risk * 2.0 if direction == "long" else price - risk * 2.0
        x0 = max(0, min(n - 1, float(x)))
        tool = PositionTool(self.plot, x0, x0 + 32, price, stop, target, direction,
                            digits=self.digits, tag="manual")
        self.tools.append(tool)
        self._autoscale_y()
        self.tool_added.emit()
        return tool

    def remove_auto_tools(self) -> None:
        if self.auto_tool is not None:
            try:
                self.auto_tool.remove()
                self.tools.remove(self.auto_tool)
            except ValueError:
                pass
            self.auto_tool = None

    def clear_tools(self) -> None:
        for tool in self.tools:
            tool.remove()
        self.tools.clear()
        self.auto_tool = None

    def set_order_mode(self, direction: str | None) -> None:
        self.order_mode = direction
        if direction:
            self.plot.setCursor(QtCore.Qt.CursorShape.CrossCursor)
        else:
            self.plot.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        self.order_mode_changed.emit(bool(direction))

    def fit_view(self) -> None:
        if self.replay_active:
            self.stop_replay()
            return
        n = len(self.df)
        if n:
            self.plot.setXRange(max(0, n - 175), n + 34, padding=0)
            self._autoscale_y()

    # ---------------------------------------------------------------- mouse
    def _on_scene_click(self, event) -> None:
        if not self.order_mode or event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        if not self.plot.sceneBoundingRect().contains(event.scenePos()):
            return
        point = self.plot.vb.mapSceneToView(event.scenePos())
        self.create_manual_tool(point.x(), point.y(), self.order_mode)
        self.set_order_mode(None)

    def _on_mouse_move(self, event) -> None:
        if len(self.df) == 0:
            return
        pos = event[0]
        if not self.plot.sceneBoundingRect().contains(pos):
            return
        point = self.plot.vb.mapSceneToView(pos)
        i = int(round(point.x()))
        if i < 0 or i >= len(self.df):
            self.vline.hide()
            self.hline.hide()
            return
        row = self.df.iloc[i]
        self.vline.setPos(i)
        self.hline.setPos(point.y())
        self.vline.show()
        self.hline.show()
        try:
            self.price_tag.setText(f"{point.y():,.{self.digits}f}")
        except Exception:
            pass
        stamp = row["time"].strftime("%d %b %Y %H:%M")
        change = row["close"] - row["open"]
        pct = (change / row["open"] * 100) if row["open"] else 0
        color = config.BULL if change >= 0 else config.BEAR
        html = (
            f"<span style='color:{config.MUTED}'>{stamp}</span> &nbsp; "
            f"O <span style='color:{color}'>{row['open']:,.{self.digits}f}</span> "
            f"H <span style='color:{color}'>{row['high']:,.{self.digits}f}</span> "
            f"L <span style='color:{color}'>{row['low']:,.{self.digits}f}</span> "
            f"C <span style='color:{color}'>{row['close']:,.{self.digits}f}</span> "
            f"<span style='color:{color}'>{pct:+.2f}%</span>"
        )
        self.crosshair_info.emit(html)

    def hide_crosshair(self) -> None:
        self.vline.hide()
        self.hline.hide()


class ChartPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QtWidgets.QFrame()
        header.setObjectName("ChartHeader")
        header.setStyleSheet(
            f"QFrame#ChartHeader {{ background:{config.PANEL}; border-bottom:1px solid {config.BORDER}; }}"
        )
        hlayout = QtWidgets.QHBoxLayout(header)
        hlayout.setContentsMargins(12, 6, 12, 6)
        hlayout.setSpacing(12)
        self.symbol_label = QtWidgets.QLabel("—")
        self.symbol_label.setStyleSheet("font-size:15px; font-weight:700; color:#ffffff;")
        self.ohlc_label = QtWidgets.QLabel("")
        self.ohlc_label.setStyleSheet(f"color:{config.MUTED}; font-family:Consolas,monospace; font-size:11px;")
        self.ohlc_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.badge = QtWidgets.QLabel("WAIT")
        self.badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.badge.setFixedWidth(76)
        self.badge.setStyleSheet(
            f"background:{config.PANEL_ALT}; color:{config.MUTED}; border:1px solid {config.BORDER};"
            "border-radius:5px; padding:3px 8px; font-weight:700;"
        )
        self.meta_label = QtWidgets.QLabel("")
        self.meta_label.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        hlayout.addWidget(self.symbol_label)
        hlayout.addWidget(self.badge)
        hlayout.addWidget(self.ohlc_label, 1)
        hlayout.addWidget(self.meta_label)
        layout.addWidget(header)

        self.chart = ChartWidget()
        layout.addWidget(self.chart, 1)

        footer = QtWidgets.QFrame()
        footer.setObjectName("ChartFooter")
        footer.setStyleSheet(
            f"QFrame#ChartFooter {{ background:{config.PANEL}; border-top:1px solid {config.BORDER}; }}"
        )
        flayout = QtWidgets.QHBoxLayout(footer)
        flayout.setContentsMargins(12, 4, 12, 4)
        hint = QtWidgets.QLabel(
            "Drag Entry / SL / TP lines · scroll to zoom · drag chart to pan · "
            "OB hijau = demand · OB merah = supply · FVG = imbalance"
        )
        hint.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        flayout.addWidget(hint)
        flayout.addStretch(1)
        self.source_label = QtWidgets.QLabel("MT5")
        self.source_label.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        flayout.addWidget(self.source_label)
        layout.addWidget(footer)

        self.chart.crosshair_info.connect(self.ohlc_label.setText)

    def set_data(self, symbol: str, tf: str, df: pd.DataFrame, signal_obj, digits: int,
                 point: float, keep_view: bool = True) -> None:
        self.symbol_label.setText(f"{symbol} · {tf}")
        self.meta_label.setText(f"{len(df)} candles · server time")
        badge_text = "WAIT" if signal_obj is None else signal_obj.signal
        self.badge.setText(badge_text)
        if signal_obj is None:
            color, bg = config.MUTED, config.PANEL_ALT
        elif badge_text == "BUY":
            color, bg = "#07110f", config.BULL
        elif badge_text == "SELL":
            color, bg = "#180707", config.BEAR
        else:
            color, bg = config.TEXT, config.PANEL_ALT
        self.badge.setStyleSheet(
            f"background:{bg}; color:{color}; border:1px solid {config.BORDER};"
            "border-radius:5px; padding:3px 8px; font-weight:700;"
        )
        if signal_obj is not None:
            self.meta_label.setText(
                f"score {signal_obj.score:+.0f} · conf {signal_obj.confidence}% · {signal_obj.structure}"
            )
        self.chart.set_data(symbol, tf, df, signal_obj, digits, point, keep_view=keep_view)
        if len(df):
            last = df.iloc[-1]
            color = config.BULL if last["close"] >= last["open"] else config.BEAR
            self.ohlc_label.setText(
                f"O {last['open']:,.{digits}f}   H {last['high']:,.{digits}f}   "
                f"L {last['low']:,.{digits}f}   C <span style='color:{color}'>{last['close']:,.{digits}f}</span>"
            )
            self.ohlc_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
