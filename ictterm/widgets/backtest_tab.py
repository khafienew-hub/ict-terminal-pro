"""Backtest lab and report gallery tabs."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config, reporting, signals
from ..backtest import BacktestResult, run_backtest
from .panels import Card

pg.setConfigOptions(antialias=True, background=config.BG, foreground=config.MUTED)


class BacktestWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int, str)
    finished_ok = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, data: dict, params: dict, parent=None):
        super().__init__(parent)
        self.data = data
        self.params = params

    def run(self) -> None:
        try:
            results: dict[str, BacktestResult] = {}
            total = max(1, len(self.data))
            for idx, (tf, df) in enumerate(self.data.items()):
                self.progress.emit(int(idx / total * 90), tf)
                results[tf] = run_backtest(
                    self.params["symbol"], tf, df,
                    digits=self.params["digits"], point=self.params["point"],
                    spread_points=self.params["spread"], rr=self.params["rr"],
                    threshold=self.params["threshold"], risk_pct=self.params["risk"],
                    session_filter=self.params["session"],
                    max_bars=self.params.get("max_bars_by_tf", {}).get(
                        tf, self.params.get("max_bars", 45)
                    ),
                )
            self.progress.emit(100, "selesai")
            self.finished_ok.emit(results)
        except Exception as exc:  # pragma: no cover - defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class ExportWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int, str)
    finished_ok = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, results: dict[str, BacktestResult], symbol: str, digits: int, parent=None):
        super().__init__(parent)
        self.results = results
        self.symbol = symbol
        self.digits = digits

    def run(self) -> None:
        paths: list[Path] = []
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        try:
            tfs = [tf for tf in config.TF_ORDER if tf in self.results]
            total = len(tfs) + 3
            for idx, tf in enumerate(tfs):
                self.progress.emit(int(idx / total * 100), f"chart {tf}")
                out = config.REPORT_DIR / f"ict_backtest_{self.symbol}_{tf}_{stamp}.png"
                paths.append(reporting.render_backtest(self.results[tf], out))
            self.progress.emit(int((len(tfs) + 0.3) / total * 100), "summary")
            paths.append(reporting.render_summary(
                self.results, self.symbol, config.REPORT_DIR / f"ict_summary_{self.symbol}_{stamp}.png"
            ))
            self.progress.emit(int((len(tfs) + 1) / total * 100), "forecast")
            from ..data import provider as get_provider
            prov = get_provider()
            sigs = signals.analyze_symbol(self.symbol, prov, self.digits)
            best = sigs.get("H1") or (next(iter(sigs.values())) if sigs else None)
            if best is not None:
                paths.append(reporting.render_forecast(
                    best, config.REPORT_DIR / f"ict_forecast_{self.symbol}_{stamp}.png"
                ))
            if sigs:
                paths.append(reporting.render_dashboard(
                    self.symbol, sigs, config.REPORT_DIR / f"ict_dashboard_{self.symbol}_{stamp}.png"
                ))
            self.progress.emit(100, "laporan selesai")
            self.finished_ok.emit(paths)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class _StatCard(QtWidgets.QFrame):
    def __init__(self, label: str, value: str = "—", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(1)
        self.label = QtWidgets.QLabel(label.upper())
        self.label.setObjectName("SectionTitle")
        self.value = QtWidgets.QLabel(value)
        self.value.setStyleSheet("font-size:18px; font-weight:800; color:#ffffff;")
        lay.addWidget(self.label)
        lay.addWidget(self.value)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size:18px; font-weight:800; color:{color or '#ffffff'};")


class BacktestTab(QtWidgets.QWidget):
    reports_ready = QtCore.pyqtSignal()
    results_ready = QtCore.pyqtSignal(object)

    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.symbol = config.DEFAULT_SYMBOL
        self.results: dict[str, BacktestResult] = {}
        self.worker = None
        self.exporter = None
        self._build()

    # ------------------------------------------------------------------- UI
    def _build(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(305)
        left_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        left_wrap = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_wrap)
        left.setContentsMargins(0, 0, 4, 0)
        left.setSpacing(10)

        settings = Card("PENGATURAN BACKTEST")
        form = QtWidgets.QFormLayout()
        form.setSpacing(7)
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.tf_combo = QtWidgets.QComboBox()
        self.tf_combo.addItem("Semua timeframe")
        for tf in config.TF_ORDER:
            self.tf_combo.addItem(tf)
        self.bars_spin = QtWidgets.QSpinBox()
        self.bars_spin.setRange(500, 50_000)
        self.bars_spin.setSingleStep(500)
        self.bars_spin.setValue(3000)
        self.rr_spin = QtWidgets.QDoubleSpinBox()
        self.rr_spin.setRange(0.5, 5.0)
        self.rr_spin.setSingleStep(0.1)
        self.rr_spin.setValue(2.0)
        self.threshold_spin = QtWidgets.QDoubleSpinBox()
        self.threshold_spin.setRange(3.0, 10.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(10.0)
        self.risk_spin = QtWidgets.QDoubleSpinBox()
        self.risk_spin.setRange(0.1, 5.0)
        self.risk_spin.setSingleStep(0.1)
        self.risk_spin.setValue(1.0)
        self.risk_spin.setSuffix(" %")
        self.session_check = QtWidgets.QCheckBox("Filter killzone sesi")
        form.addRow("Timeframe", self.tf_combo)
        form.addRow("Jumlah candle", self.bars_spin)
        form.addRow("Target RR", self.rr_spin)
        form.addRow("Skor minimum", self.threshold_spin)
        form.addRow("Risiko / trade", self.risk_spin)
        form.addRow("", self.session_check)
        settings.body.addLayout(form)

        self.run_btn = QtWidgets.QPushButton("Jalankan Backtest")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self.start_backtest)
        self.export_btn = QtWidgets.QPushButton("Export Gambar Laporan")
        self.export_btn.setObjectName("BuyButton")
        self.export_btn.clicked.connect(self.export_reports)
        self.export_btn.setEnabled(False)
        self.open_btn = QtWidgets.QPushButton("Buka Folder Reports")
        self.open_btn.clicked.connect(self.open_reports_folder)
        settings.body.addWidget(self.run_btn)
        settings.body.addWidget(self.export_btn)
        settings.body.addWidget(self.open_btn)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        settings.body.addWidget(self.progress)
        self.log = QtWidgets.QTextBrowser()
        self.log.setFixedHeight(138)
        self.log.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; border-radius:5px;"
            f"color:{config.MUTED}; font-size:9px; padding:4px;"
        )
        settings.body.addWidget(self.log)
        left.addWidget(settings)

        method = Card("METODE")
        info = QtWidgets.QLabel(
            "ICT Confluence:<br>"
            "• Market structure BOS / CHoCH<br>"
            "• Order block & FVG retest<br>"
            "• Liquidity sweep swing high/low<br>"
            "• Discount / premium (40 bar)<br>"
            "• EMA 20/50/200 + RSI + MACD + ADX<br><br>"
            "Entry di open candle berikutnya, SL di luar zona, TP = RR × risiko. "
            "SL dicek lebih dulu, spread & komisi dihitung. Risiko 1% per trade."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        method.body.addWidget(info)
        left.addWidget(method)
        left.addStretch(1)
        left_scroll.setWidget(left_wrap)
        root.addWidget(left_scroll)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(8)
        self.card_trades = _StatCard("Trades")
        self.card_win = _StatCard("Win rate")
        self.card_net = _StatCard("Net R")
        self.card_pf = _StatCard("Profit factor")
        self.card_dd = _StatCard("Max drawdown")
        for card in (self.card_trades, self.card_win, self.card_net, self.card_pf, self.card_dd):
            cards.addWidget(card)
        right.addLayout(cards)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["TF", "TRADES", "WIN %", "PF", "EXPECTANCY", "NET R", "MAX DD", "AVG BARS"]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        for i in range(8):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        self.table.setFixedHeight(248)
        right.addWidget(self.table)

        self.equity_plot = pg.PlotWidget()
        self.equity_plot.setBackground(config.BG)
        self.equity_plot.showGrid(x=True, y=True, alpha=0.18)
        self.equity_plot.setLabel("left", "Equity ($)", color=config.MUTED)
        self.equity_plot.setLabel("bottom", "Trade #", color=config.MUTED)
        self.equity_plot.getAxis("left").setPen(pg.mkPen(config.BORDER))
        self.equity_plot.getAxis("bottom").setPen(pg.mkPen(config.BORDER))
        self.equity_plot.getAxis("left").setTextPen(pg.mkPen(config.MUTED))
        self.equity_plot.getAxis("bottom").setTextPen(pg.mkPen(config.MUTED))
        self.equity_plot.addLegend(offset=(10, 10), labelTextColor=config.MUTED)
        self.equity_plot.setMinimumHeight(260)
        right.addWidget(self.equity_plot, 1)
        root.addLayout(right, 1)

        self.log.append("Backtest lab siap. Pilih parameter lalu klik Jalankan.")
        self.table.setRowCount(0)

    # -------------------------------------------------------------- helpers
    def set_symbol(self, symbol: str) -> None:
        self.symbol = symbol

    def _log(self, text: str) -> None:
        self.log.append(f"<span style='color:{config.ACCENT}'>[{datetime.now():%H:%M:%S}]</span> {text}")

    def _tfs(self) -> list[str]:
        if self.tf_combo.currentIndex() == 0:
            return list(config.TF_ORDER)
        return [self.tf_combo.currentText()]

    # ---------------------------------------------------------------- actions
    def start_backtest(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        if not self.provider.ensure_connected() and not self.provider._symbols:
            pass
        tfs = self._tfs()
        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress.setValue(2)
        self._log(f"mengambil data {self.symbol} untuk {', '.join(tfs)}…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        meta = self.provider.meta(self.symbol)
        data = {}
        for tf in tfs:
            df = self.provider.rates(self.symbol, tf, self.bars_spin.value(), ttl=0)
            if df is not None and len(df) > 2:
                # Backtest only closed candles; the last bar may still be forming.
                df = df.iloc[:-1].copy()
            if df is not None and len(df) >= 150:
                data[tf] = df
                self._log(
                    f"{tf}: {len(df)} candle · {df['time'].iloc[0]:%d %b %H:%M} → "
                    f"{df['time'].iloc[-1]:%d %b %H:%M}"
                )
        QtWidgets.QApplication.restoreOverrideCursor()
        if not data:
            self._log("<span style='color:#ef5350'>data tidak cukup / MT5 tidak terhubung</span>")
            self.run_btn.setEnabled(True)
            return
        self._log(
            f"menjalankan backtest: RR {self.rr_spin.value():.1f}, skor ≥{self.threshold_spin.value():.1f}, "
            f"risk {self.risk_spin.value():.1f}%"
        )
        params = {
            "symbol": self.symbol,
            "digits": meta.digits,
            "point": meta.point,
            "spread": meta.spread,
            "rr": self.rr_spin.value(),
            "threshold": self.threshold_spin.value(),
            "risk": self.risk_spin.value(),
            "session": self.session_check.isChecked(),
            "max_bars_by_tf": {
                tf: (45 if tf in ("M1", "M5", "M15") else 60)
                for tf in config.TF_ORDER
            },
        }
        self.worker = BacktestWorker(data, params, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_progress(self, value: int, label: str) -> None:
        self.progress.setValue(value)
        if label:
            self.progress.setFormat(f"{label} %p%")

    def _on_failed(self, message: str) -> None:
        self.run_btn.setEnabled(True)
        self.progress.setValue(0)
        self._log(f"<span style='color:#ef5350'>GAGAL: {message}</span>")

    def _on_finished(self, results: dict) -> None:
        self.results = results
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(bool(results))
        self.progress.setValue(100)
        self._update_results()
        total = sum(r.stats.get("trades", 0) for r in results.values())
        self._log(f"selesai: {len(results)} timeframe, {total} trade.")
        self.results_ready.emit(results)

    def _update_results(self) -> None:
        self.equity_plot.clear()
        try:
            legend = self.equity_plot.plotItem.legend
            if legend is not None:
                legend.clear()
        except Exception:
            pass
        tfs = [tf for tf in config.TF_ORDER if tf in self.results]
        self.table.setRowCount(len(tfs))
        palette = [config.ACCENT, config.BULL, config.GOLD, config.VIOLET, config.BEAR, "#4dd0e1", "#ff8a65"]
        for idx, tf in enumerate(tfs):
            result = self.results[tf]
            row = result.summary_row()
            for col, value in enumerate(row):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#ffffff")))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif col == 5:
                    val = result.stats.get("net_r", 0)
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if val >= 0 else config.BEAR)))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.MUTED)))
                self.table.setItem(idx, col, item)
            eq = result.equity
            if eq is not None and len(eq):
                x = np.arange(len(eq))
                self.equity_plot.plot(
                    x, eq.to_numpy(), pen=pg.mkPen(palette[idx % len(palette)], width=1.3),
                    name=tf,
                )
        self.equity_plot.plot([0, 1], [10_000, 10_000], pen=pg.mkPen(config.MUTED, width=0.7, style=QtCore.Qt.PenStyle.DashLine))
        if tfs:
            total_trades = sum(self.results[tf].stats.get("trades", 0) for tf in tfs)
            wins = sum(self.results[tf].stats.get("wins", 0) for tf in tfs)
            net = sum(self.results[tf].stats.get("net_r", 0) for tf in tfs)
            gp = sum(self.results[tf].stats.get("gross_profit", 0) for tf in tfs)
            gl = sum(self.results[tf].stats.get("gross_loss", 0) for tf in tfs)
            max_dd = max(self.results[tf].stats.get("max_dd", 0) for tf in tfs)
            win_rate = (wins / total_trades * 100) if total_trades else 0
            pf = (gp / gl) if gl > 0 else (999 if gp > 0 else 0)
            self.card_trades.set(str(total_trades))
            self.card_win.set(f"{win_rate:.1f}%", config.BULL if win_rate >= 50 else config.GOLD)
            self.card_net.set(f"{net:+.1f}R", config.BULL if net >= 0 else config.BEAR)
            self.card_pf.set(f"{pf:.2f}", config.BULL if pf >= 1 else config.BEAR)
            self.card_dd.set(f"{max_dd:.1f}%", config.BEAR if max_dd > 15 else config.TEXT)

    def export_reports(self) -> None:
        if not self.results or (self.exporter is not None and self.exporter.isRunning()):
            return
        self.export_btn.setEnabled(False)
        self.run_btn.setEnabled(False)
        self.progress.setValue(0)
        self._log("membuat gambar laporan (chart, summary, forecast, dashboard)…")
        meta = self.provider.meta(self.symbol)
        self.exporter = ExportWorker(self.results, self.symbol, meta.digits, self)
        self.exporter.progress.connect(self._on_progress)
        self.exporter.finished_ok.connect(self._on_exported)
        self.exporter.failed.connect(self._on_export_failed)
        self.exporter.start()

    def _on_exported(self, paths: list) -> None:
        self.export_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.progress.setValue(100)
        self._log(f"<span style='color:#26a69a'>{len(paths)} gambar disimpan di {config.REPORT_DIR}</span>")
        self.reports_ready.emit()

    def _on_export_failed(self, message: str) -> None:
        self.export_btn.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.progress.setValue(0)
        self._log(f"<span style='color:#ef5350'>export gagal: {message}</span>")

    def open_reports_folder(self) -> None:
        try:
            os.startfile(str(config.REPORT_DIR))
        except Exception as exc:
            self._log(f"tidak bisa membuka folder: {exc}")


class ImagePreview(QtWidgets.QGraphicsView):
    """Crisp zoomable image viewer: scroll = zoom, drag = pan, double-click = fit/100%."""

    zoom_changed = QtCore.pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing |
                            QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(config.PANEL)))
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        self._pixmap_item: QtWidgets.QGraphicsPixmapItem | None = None
        self._mode = "width"  # width | fit | manual
        self._zoom = 1.0
        self._adjusting = False

    def set_image(self, path: Path) -> QtGui.QPixmap:
        pix = QtGui.QPixmap(str(path))
        if pix.isNull():
            return pix
        self.scene().clear()
        self._pixmap_item = self.scene().addPixmap(pix)
        self.scene().setSceneRect(self._pixmap_item.boundingRect())
        self.fit_width()
        return pix

    def fit_width(self) -> None:
        """Fit to width; vertical scrolling keeps candles readable."""
        if self._pixmap_item is None or self._adjusting:
            return
        self._adjusting = True
        try:
            available_w = max(120, self.viewport().width() - 2)
            available_h = max(80, self.viewport().height() - 2)
            image_w = max(1, self._pixmap_item.pixmap().width())
            image_h = max(1, self._pixmap_item.pixmap().height())
            scale = available_w / image_w
            # Reserve room for the vertical scrollbar so width still fits.
            if image_h * scale > available_h:
                reserve = self.verticalScrollBar().sizeHint().width() + 2
                scale = max(0.02, (available_w - reserve) / image_w)
            transform = QtGui.QTransform()
            transform.scale(scale, scale)
            self.setTransform(transform)
            self.horizontalScrollBar().setValue(0)
            self.verticalScrollBar().setValue(0)
            self._mode = "width"
            self._zoom = scale
            self.zoom_changed.emit(scale)
        finally:
            self._adjusting = False

    def fit_view(self) -> None:
        if self._pixmap_item is None or self._adjusting:
            return
        self._adjusting = True
        try:
            self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._mode = "fit"
            self._zoom = self.transform().m11()
            self.zoom_changed.emit(self._zoom)
        finally:
            self._adjusting = False

    def actual_size(self) -> None:
        if self._pixmap_item is None:
            return
        self.resetTransform()
        self._mode = "manual"
        self._zoom = 1.0
        self.zoom_changed.emit(self._zoom)

    def zoom_by(self, factor: float) -> None:
        if self._pixmap_item is None:
            return
        new_zoom = self._zoom * factor
        if new_zoom < 0.12 or new_zoom > 6.0:
            return
        self._mode = "manual"
        self.scale(factor, factor)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.zoom_by(factor)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._mode == "manual":
            self.fit_width()
        else:
            self.actual_size()
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._adjusting:
            return
        if self._mode == "width":
            self.fit_width()
        elif self._mode == "fit":
            self.fit_view()


class ReportsTab(QtWidgets.QWidget):
    dashboard_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(7)
        title = QtWidgets.QLabel("GALERI BACKTEST & FORECAST")
        title.setObjectName("SectionTitle")
        left.addWidget(title)
        self.list = QtWidgets.QListWidget()
        self.list.setFixedWidth(310)
        self.list.setStyleSheet(
            f"QListWidget {{ background:{config.PANEL}; border:1px solid {config.BORDER}; border-radius:6px; }}"
            "QListWidget::item { padding:7px 8px; border-bottom:1px solid #1b2531; }"
            "QListWidget::item:selected { background:#1d3047; color:#ffffff; }"
        )
        self.list.currentItemChanged.connect(self._show_current)
        self.list.itemDoubleClicked.connect(self._open_item)
        left.addWidget(self.list, 1)
        hint = QtWidgets.QLabel(
            "Double-click nama file untuk membuka gambar ukuran penuh.\n"
            "Scroll = zoom · drag = geser · double-click gambar = fit width / 100%."
        )
        hint.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        hint.setWordWrap(True)
        left.addWidget(hint)
        row = QtWidgets.QHBoxLayout()
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        new_dash = QtWidgets.QPushButton("Dashboard Baru")
        new_dash.setToolTip("Buat dashboard 7 timeframe dari data terbaru")
        new_dash.clicked.connect(self.dashboard_requested.emit)
        open_btn = QtWidgets.QPushButton("Buka Folder")
        open_btn.clicked.connect(lambda: os.startfile(str(config.REPORT_DIR)))
        row.addWidget(refresh)
        row.addWidget(new_dash)
        row.addWidget(open_btn)
        left.addLayout(row)
        root.addLayout(left)

        right = QtWidgets.QVBoxLayout()
        self.info = QtWidgets.QLabel("Pilih gambar untuk melihat preview.")
        self.info.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        right.addWidget(self.info)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        width_btn = QtWidgets.QPushButton("Fit Width")
        width_btn.setToolTip("Selebar layar; scroll ke bawah untuk melihat panel lain")
        width_btn.clicked.connect(self._fit_width)
        fit_btn = QtWidgets.QPushButton("Fit")
        fit_btn.setToolTip("Tampilkan seluruh gambar")
        fit_btn.clicked.connect(self._fit)
        actual_btn = QtWidgets.QPushButton("100%")
        actual_btn.setToolTip("Ukuran asli, bisa digeser")
        actual_btn.clicked.connect(self._actual)
        zoom_out = QtWidgets.QPushButton("−")
        zoom_out.setFixedWidth(34)
        zoom_out.clicked.connect(lambda: self.preview.zoom_by(1 / 1.25))
        zoom_in = QtWidgets.QPushButton("+")
        zoom_in.setFixedWidth(34)
        zoom_in.clicked.connect(lambda: self.preview.zoom_by(1.25))
        self.zoom_label = QtWidgets.QLabel("—")
        self.zoom_label.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        open_image = QtWidgets.QPushButton("Buka Gambar")
        open_image.clicked.connect(self._open_current)
        controls.addWidget(width_btn)
        controls.addWidget(fit_btn)
        controls.addWidget(actual_btn)
        controls.addWidget(zoom_out)
        controls.addWidget(zoom_in)
        controls.addWidget(self.zoom_label)
        controls.addStretch(1)
        controls.addWidget(open_image)
        right.addLayout(controls)

        self.preview = ImagePreview()
        self.preview.zoom_changed.connect(self._zoom_changed)
        right.addWidget(self.preview, 1)
        root.addLayout(right, 1)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        files = sorted(config.REPORT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files:
            item = QtWidgets.QListWidgetItem(path.name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.list.addItem(item)
        self.info.setText(f"{len(files)} gambar · {config.REPORT_DIR}")
        if files:
            self.list.setCurrentRow(0)

    def _show_current(self, current, _previous=None) -> None:
        if current is None:
            return
        path = Path(current.data(QtCore.Qt.ItemDataRole.UserRole))
        pix = self.preview.set_image(path)
        if pix.isNull():
            self.info.setText("Gagal memuat gambar")
            return
        stat = path.stat()
        self.info.setText(
            f"{path.name}  ·  ukuran asli {pix.width()}×{pix.height()}  ·  "
            f"{stat.st_size / 1024:.0f} KB  ·  {datetime.fromtimestamp(stat.st_mtime):%d %b %Y %H:%M}"
        )
        # Re-apply once the tab/layout has its final viewport size.
        QtCore.QTimer.singleShot(0, self.preview.fit_width)

    def _fit_width(self) -> None:
        self.preview.fit_width()

    def _fit(self) -> None:
        self.preview.fit_view()

    def _actual(self) -> None:
        self.preview.actual_size()

    def _zoom_changed(self, zoom: float) -> None:
        self.zoom_label.setText(f"{zoom * 100:.0f}%")

    def _open_current(self) -> None:
        current = self.list.currentItem()
        if current is not None:
            self._open_item(current)

    def _open_item(self, current) -> None:
        if current is None:
            return
        try:
            os.startfile(current.data(QtCore.Qt.ItemDataRole.UserRole))
        except Exception:
            pass
