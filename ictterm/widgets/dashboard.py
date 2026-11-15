"""Live 7-timeframe mini-chart dashboard rendered with pyqtgraph."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config
from ..history import HistoryTrade, index_for_time
from .chart import CandlestickItem

pg.setConfigOptions(antialias=True, background=config.BG, foreground=config.MUTED)


class MiniChart(QtWidgets.QFrame):
    clicked = QtCore.pyqtSignal(str)

    def __init__(self, tf: str, parent=None):
        super().__init__(parent)
        self.tf = tf
        self.setObjectName("MiniCard")
        self.setStyleSheet(
            f"QFrame#MiniCard {{ background:{config.PANEL}; border:1px solid {config.BORDER}; border-radius:7px; }}"
        )
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(150)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(7)
        self.tf_label = QtWidgets.QLabel(tf)
        self.tf_label.setStyleSheet("font-size:13px; font-weight:800; color:#ffffff;")
        self.signal_label = QtWidgets.QLabel("—")
        self.signal_label.setStyleSheet(f"font-size:10px; font-weight:700; color:{config.MUTED};")
        self.score_label = QtWidgets.QLabel("")
        self.score_label.setStyleSheet(f"font-size:10px; color:{config.MUTED};")
        self.rr_label = QtWidgets.QLabel("")
        self.rr_label.setStyleSheet(f"font-size:9px; color:{config.MUTED};")
        header.addWidget(self.tf_label)
        header.addWidget(self.signal_label)
        header.addWidget(self.score_label)
        header.addStretch(1)
        header.addWidget(self.rr_label)
        layout.addLayout(header)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(config.BG)
        pi = self.plot.getPlotItem()
        pi.setMenuEnabled(False)
        pi.hideButtons()
        pi.showGrid(x=True, y=True, alpha=0.14)
        pi.hideAxis("left")
        pi.showAxis("right")
        pi.getAxis("right").setWidth(42)
        pi.getAxis("right").setPen(pg.mkPen(config.BORDER))
        pi.getAxis("right").setTextPen(pg.mkPen(config.MUTED))
        pi.getAxis("right").setStyle(tickFont=QtGui.QFont("Segoe UI", 6))
        pi.getAxis("bottom").setStyle(showValues=False)
        pi.getAxis("bottom").setPen(pg.mkPen(config.BORDER))
        pi.setMouseEnabled(x=False, y=False)
        pi.getViewBox().disableAutoRange()
        self.plot.setMinimumHeight(80)
        self.plot.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Ignored)
        layout.addWidget(self.plot, 1)

        self.candles = CandlestickItem(pd.DataFrame(columns=["open", "high", "low", "close"]), width=0.28)
        self.candles.setZValue(5)
        pi.addItem(self.candles)
        self.ema20 = pg.PlotDataItem(pen=pg.mkPen(config.GOLD, width=0.9))
        self.ema50 = pg.PlotDataItem(pen=pg.mkPen(config.ACCENT, width=0.9))
        self.ema20.setZValue(8)
        self.ema50.setZValue(8)
        pi.addItem(self.ema20)
        pi.addItem(self.ema50)
        self.zone_items: list = []
        self.history_items: list = []
        self.history_trades: list[HistoryTrade] = []
        self.df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "ema20", "ema50"])
        self.show_history = True
        self.plot.scene().sigMouseClicked.connect(lambda _evt: self.clicked.emit(self.tf))
        self._pi = pi

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.tf)
        super().mousePressEvent(event)

    def set_data(self, sig) -> None:
        ctx = sig.context
        df = ctx.get("df")
        if df is None or len(df) == 0:
            return
        self.df = df
        self.candles.set_data(df)
        x = np.arange(len(df))
        self.ema20.setData(x, df["ema20"].to_numpy(), connect="finite")
        self.ema50.setData(x, df["ema50"].to_numpy(), connect="finite")
        for item in self.zone_items:
            try:
                self._pi.removeItem(item)
            except Exception:
                pass
        self.zone_items.clear()
        n = len(df)
        start = max(0, n - 30)
        for z in ctx.get("order_blocks", [])[-2:]:
            x0 = max(start, z.created)
            x1 = min(n + 1, z.mitigated if z.mitigated else n + 1)
            if x1 <= x0:
                continue
            face = config.LONG_ZONE if z.direction == "bull" else config.SHORT_ZONE
            rect = QtWidgets.QGraphicsRectItem(x0, z.bottom, x1 - x0, max(z.top - z.bottom, 1e-9))
            rect.setBrush(pg.mkBrush(face))
            rect.setPen(pg.mkPen((*face[:3], 120), width=0.5))
            rect.setZValue(-2)
            self._pi.addItem(rect)
            self.zone_items.append(rect)
        self._pi.setXRange(start - 1, n + 1, padding=0)
        lo = float(df["low"].iloc[start:].min())
        hi = float(df["high"].iloc[start:].max())
        pad = max((hi - lo) * 0.15, 1e-9)
        self._pi.setYRange(lo - pad, hi + pad, padding=0)

        color = config.BULL if sig.signal == "BUY" else (config.BEAR if sig.signal == "SELL" else config.MUTED)
        self.signal_label.setText(sig.signal)
        self.signal_label.setStyleSheet(f"font-size:10px; font-weight:700; color:{color};")
        self.score_label.setText(f"{sig.score:+.0f}")
        self.score_label.setStyleSheet(f"font-size:10px; color:{color};")
        self.rr_label.setText(f"R:R {sig.rr:.1f} · {sig.confidence}%")
        self._draw_history()

    def set_history(self, trades: list[HistoryTrade], visible: bool = True) -> None:
        self.history_trades = [t for t in (trades or []) if t.tf == self.tf]
        self.show_history = visible
        self._draw_history()

    def _clear_history(self) -> None:
        for item in self.history_items:
            try:
                self._pi.removeItem(item)
            except Exception:
                pass
        self.history_items.clear()

    def _draw_history(self) -> None:
        self._clear_history()
        if not self.show_history or not self.history_trades or len(self.df) == 0:
            return
        n = len(self.df)
        start = max(0, n - 30)
        for t in self.history_trades[-30:]:
            entry_i = index_for_time(self.df, t.entry_time)
            exit_i = index_for_time(self.df, t.exit_time)
            if entry_i is None or exit_i is None:
                continue
            if exit_i < start or entry_i > n:
                continue
            x0 = max(start, entry_i)
            x1 = max(x0 + 1, min(n, exit_i))
            direction_color = config.BULL if t.is_long else config.BEAR
            line_color = QtGui.QColor(direction_color)
            line_color.setAlpha(150)
            line = pg.PlotDataItem(
                [x0, x1], [t.entry, t.exit],
                pen=pg.mkPen(line_color, width=0.8),
            )
            line.setZValue(12)
            self._pi.addItem(line)
            self.history_items.append(line)
            entry_marker = pg.ScatterPlotItem(
                [x0], [t.entry], symbol="t" if t.is_long else "t1", size=8,
                brush=pg.mkBrush(direction_color), pen=pg.mkPen("#ffffff", width=0.4),
            )
            entry_marker.setZValue(14)
            self._pi.addItem(entry_marker)
            self.history_items.append(entry_marker)
            pnl = t.r if abs(t.r) > 1e-9 else t.profit
            exit_color = config.BULL if pnl >= 0 else config.BEAR
            exit_marker = pg.ScatterPlotItem(
                [x1], [t.exit], symbol="o", size=5,
                brush=pg.mkBrush(exit_color), pen=pg.mkPen("#ffffff", width=0.4),
            )
            exit_marker.setZValue(14)
            self._pi.addItem(exit_marker)
            self.history_items.append(exit_marker)
            label = pg.TextItem(
                f"{pnl:+.1f}R" if abs(t.r) > 1e-9 else f"{t.profit:+.2f}",
                color=exit_color, anchor=(0, 1),
            )
            label.setPos(x1 + 0.2, t.exit)
            label.setZValue(15)
            self._pi.addItem(label)
            self.history_items.append(label)


class DashboardWidget(QtWidgets.QWidget):
    tf_selected = QtCore.pyqtSignal(str)

    TFS = list(config.TF_ORDER)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QFrame()
        header.setStyleSheet(f"background:{config.PANEL}; border-bottom:1px solid {config.BORDER};")
        hlay = QtWidgets.QHBoxLayout(header)
        hlay.setContentsMargins(16, 8, 16, 8)
        title = QtWidgets.QLabel("MULTI-TIMEFRAME DASHBOARD")
        title.setStyleSheet("font-size:15px; font-weight:800; color:#ffffff;")
        sub = QtWidgets.QLabel("Live render V4 · 30 candle/panel · jarak lebar · klik panel untuk membuka chart")
        sub.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        self.symbol_label = QtWidgets.QLabel("—")
        self.symbol_label.setStyleSheet(f"color:{config.ACCENT}; font-size:12px; font-weight:700;")
        hlay.addWidget(title)
        hlay.addWidget(sub)
        hlay.addStretch(1)
        hlay.addWidget(self.symbol_label)
        root.addWidget(header)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        inner = QtWidgets.QWidget()
        inner.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        grid = QtWidgets.QGridLayout(inner)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(9)
        self.charts: dict[str, MiniChart] = {}
        self.history_trades: list[HistoryTrade] = []
        self.show_history = True
        for idx, tf in enumerate(self.TFS):
            chart = MiniChart(tf)
            chart.clicked.connect(self.tf_selected.emit)
            self.charts[tf] = chart
            grid.addWidget(chart, idx // 3, idx % 3)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        for row in range(3):
            grid.setRowStretch(row, 1)

        legend = QtWidgets.QFrame()
        legend.setObjectName("DashLegend")
        legend.setStyleSheet(
            f"QFrame#DashLegend {{ background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; border-radius:7px; }}"
        )
        lv = QtWidgets.QVBoxLayout(legend)
        lv.setContentsMargins(14, 10, 14, 10)
        lv.setSpacing(4)
        lv_title = QtWidgets.QLabel("CARA BACA")
        lv_title.setObjectName("SectionTitle")
        lv.addWidget(lv_title)
        text = QtWidgets.QLabel(
            "Hijau = candle bullish / demand OB<br>"
            "Merah = candle bearish / supply OB<br>"
            "Biru = EMA50 · kuning = EMA20<br>"
            "Kotak transparan = order block terakhir<br><br>"
            "Klik panel mana pun untuk membuka chart timeframe tersebut."
        )
        text.setWordWrap(True)
        text.setStyleSheet(f"color:{config.MUTED}; font-size:9px; line-height:1.4;")
        lv.addWidget(text)
        lv.addStretch(1)
        grid.addWidget(legend, 2, 1, 1, 2)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

    def update_data(self, signals: dict, symbol: str) -> None:
        self.symbol_label.setText(symbol)
        for tf, chart in self.charts.items():
            sig = signals.get(tf)
            if sig is not None:
                chart.set_data(sig)
                chart.set_history(self.history_trades, self.show_history)

    def set_history(self, trades: list[HistoryTrade], visible: bool = True) -> None:
        self.history_trades = list(trades or [])
        self.show_history = visible
        for chart in self.charts.values():
            chart.set_history(self.history_trades, visible)
