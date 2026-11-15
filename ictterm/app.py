"""Main application window."""
from __future__ import annotations

import sys
from datetime import datetime

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from . import config, data, licensing, reporting, signals
from . import settings as app_settings
from .history import from_backtest_results, from_mt5_history
from .widgets.backtest_tab import BacktestTab, ReportsTab
from .widgets.chart import ChartPanel
from .widgets.dashboard import DashboardWidget
from .widgets.auto_trade import AutoTradeTab
from .widgets.license_dialog import LicenseDialog
from .widgets.trade_report import TradeReportTab
from .widgets.panels import (
    AccountCard, ConfluenceCard, HistoryCard, HowToCard, SignalTable, ToggleCard, TradePlanPanel,
)


def _hline() -> QtWidgets.QFrame:
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    line.setStyleSheet(f"color:{config.BORDER}; background:{config.BORDER};")
    line.setFixedWidth(1)
    line.setFixedHeight(22)
    return line


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, provider: data.DataProvider):
        super().__init__()
        self.provider = provider
        self.symbol = config.DEFAULT_SYMBOL
        self.tf = "M15"
        self.signal_map: dict = {}
        self.agg: dict = {}
        self._busy = False
        self._last_update = None
        self.history_trades: list = []
        self.history_source = "Backtest"
        self.settings = QtCore.QSettings("ICT Terminal", "ICT Terminal Pro")
        self.setWindowTitle(f"{config.APP_NAME} · MT5 Smart Money Terminal")
        self.resize(1680, 980)
        self.setMinimumSize(1180, 720)
        self._build()
        self._populate_symbols()
        self._restore_settings()
        self._connect_signals()
        self._start_timers()
        self._refresh_license_badge()
        QtCore.QTimer.singleShot(120, lambda: self.refresh_all(initial=True))

    # ------------------------------------------------------------------- UI
    def _build(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        hlay = QtWidgets.QHBoxLayout(header)
        hlay.setContentsMargins(16, 9, 16, 9)
        hlay.setSpacing(10)
        brand_box = QtWidgets.QVBoxLayout()
        brand_box.setSpacing(0)
        title = QtWidgets.QLabel("ICT TERMINAL PRO")
        title.setObjectName("Title")
        subtitle = QtWidgets.QLabel("MT5 Multi-Timeframe · Multi-Symbol Auto Trade · Smart Money")
        subtitle.setObjectName("SubTitle")
        brand_box.addWidget(title)
        brand_box.addWidget(subtitle)
        hlay.addLayout(brand_box)
        hlay.addStretch(1)

        self.conn_pill = QtWidgets.QLabel("●  MENGHUBUNGKAN MT5")
        self.conn_pill.setStyleSheet(
            f"background:{config.PANEL_ALT}; color:{config.GOLD}; border:1px solid {config.BORDER};"
            "border-radius:10px; padding:4px 10px; font-size:10px; font-weight:700;"
        )
        hlay.addWidget(self.conn_pill)
        self.account_label = QtWidgets.QLabel("—")
        self.account_label.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        hlay.addWidget(self.account_label)
        self.license_pill = QtWidgets.QLabel("LISENSI")
        self.license_pill.setStyleSheet(
            f"background:{config.PANEL_ALT}; color:{config.GOLD}; border:1px solid {config.BORDER};"
            "border-radius:10px; padding:4px 10px; font-size:10px; font-weight:700;"
        )
        hlay.addWidget(self.license_pill)
        self.license_btn = QtWidgets.QPushButton("LISENSI")
        self.license_btn.setFixedWidth(84)
        self.license_btn.setToolTip("Aktivasi key / lihat masa coba gratis")
        self.license_btn.clicked.connect(self.open_license_dialog)
        hlay.addWidget(self.license_btn)
        self.clock_label = QtWidgets.QLabel("")
        self.clock_label.setStyleSheet(f"color:{config.TEXT}; font-size:10px; font-family:Consolas,monospace;")
        self.clock_label.setFixedWidth(150)
        self.clock_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        hlay.addWidget(self.clock_label)
        self.header_refresh = QtWidgets.QPushButton("Refresh")
        self.header_refresh.setFixedWidth(74)
        hlay.addWidget(self.header_refresh)
        root.addWidget(header)

        # ---------------------------------------------------------- toolbar
        toolbar = QtWidgets.QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar.setStyleSheet(
            f"QFrame#Toolbar {{ background:{config.PANEL}; border-bottom:1px solid {config.BORDER}; }}"
        )
        tlay = QtWidgets.QHBoxLayout(toolbar)
        tlay.setContentsMargins(16, 7, 16, 7)
        tlay.setSpacing(7)
        sym_label = QtWidgets.QLabel("SIMBOL")
        sym_label.setObjectName("SectionTitle")
        tlay.addWidget(sym_label)
        self.symbol_combo = QtWidgets.QComboBox()
        self.symbol_combo.setEditable(True)
        self.symbol_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.symbol_combo.setFixedWidth(168)
        self.symbol_combo.setMaxVisibleItems(20)
        tlay.addWidget(self.symbol_combo)
        tlay.addSpacing(8)

        tf_label = QtWidgets.QLabel("TIMEFRAME")
        tf_label.setObjectName("SectionTitle")
        tlay.addWidget(tf_label)
        self.tf_group = QtWidgets.QButtonGroup(self)
        self.tf_group.setExclusive(True)
        self.tf_buttons: dict[str, QtWidgets.QPushButton] = {}
        for tf in config.TF_ORDER:
            btn = QtWidgets.QPushButton(tf)
            btn.setCheckable(True)
            btn.setObjectName("TfButton")
            btn.setFixedSize(48, 30)
            btn.setProperty("tf", tf)
            self.tf_group.addButton(btn)
            self.tf_buttons[tf] = btn
            tlay.addWidget(btn)
        self.tf_buttons["M15"].setChecked(True)
        tlay.addWidget(_hline())

        self.long_btn = QtWidgets.QPushButton("Long")
        self.long_btn.setObjectName("BuyButton")
        self.long_btn.setToolTip("Klik lalu klik chart untuk menaruh order box long")
        self.short_btn = QtWidgets.QPushButton("Short")
        self.short_btn.setObjectName("SellButton")
        self.short_btn.setToolTip("Klik lalu klik chart untuk menaruh order box short")
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.fit_btn = QtWidgets.QPushButton("Fit")
        tlay.addWidget(self.long_btn)
        tlay.addWidget(self.short_btn)
        tlay.addWidget(self.clear_btn)
        tlay.addWidget(self.fit_btn)
        self.autofc_check = QtWidgets.QCheckBox("Auto forecast")
        self.autofc_check.setChecked(True)
        tlay.addWidget(self.autofc_check)
        tlay.addWidget(_hline())
        self.auto_check = QtWidgets.QCheckBox("Auto refresh 20s")
        self.auto_check.setChecked(True)
        tlay.addWidget(self.auto_check)
        tlay.addStretch(1)
        hint = QtWidgets.QLabel("Drag garis Entry / SL / TP untuk mengatur order")
        hint.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        tlay.addWidget(hint)
        root.addWidget(toolbar)

        # ------------------------------------------------------------ tabs
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs, 1)

        chart_tab = QtWidgets.QWidget()
        chart_lay = QtWidgets.QVBoxLayout(chart_tab)
        chart_lay.setContentsMargins(0, 0, 0, 0)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(1)
        chart_lay.addWidget(self.splitter)

        # left
        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(322)
        left_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        left_widget = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_widget)
        left.setContentsMargins(10, 10, 8, 10)
        left.setSpacing(9)
        self.confluence = ConfluenceCard()
        self.signal_table = SignalTable()
        self.toggles = ToggleCard()
        self.history_card = HistoryCard()
        self.account = AccountCard()
        left.addWidget(self.confluence)
        left.addWidget(self.signal_table)
        left.addWidget(self.toggles)
        left.addWidget(self.history_card)
        left.addWidget(self.account)
        left.addStretch(1)
        left_scroll.setWidget(left_widget)
        self.splitter.addWidget(left_scroll)

        # center
        self.chart_panel = ChartPanel()
        self.chart_panel.setMinimumWidth(600)
        self.splitter.addWidget(self.chart_panel)

        # right
        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFixedWidth(336)
        right_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        right_widget = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(right_widget)
        right.setContentsMargins(8, 10, 10, 10)
        right.setSpacing(9)
        self.plan_panel = TradePlanPanel()
        right.addWidget(self.plan_panel)
        right.addWidget(HowToCard())
        right.addStretch(1)
        right_scroll.setWidget(right_widget)
        self.splitter.addWidget(right_scroll)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([322, 1000, 336])
        self.chart_tab = chart_tab
        self.tabs.addTab(chart_tab, "CHART & SIGNAL")

        self.dashboard = DashboardWidget()
        self.tabs.addTab(self.dashboard, "DASHBOARD 7 TF")

        self.backtest_tab = BacktestTab(self.provider)
        self.tabs.addTab(self.backtest_tab, "BACKTEST ICT")
        self.auto_trade = AutoTradeTab(self.provider)
        self.tabs.addTab(self.auto_trade, "AUTO TRADE")
        self.trade_report = TradeReportTab(self.provider, auto_trade=self.auto_trade)
        self.tabs.addTab(self.trade_report, "TRADE REPORT")
        self.gallery = ReportsTab()
        self.tabs.addTab(self.gallery, "GALLERY LAPORAN")

        # status bar
        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QtWidgets.QLabel("Siap.")
        self.status_label.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        self.status.addWidget(self.status_label, 1)
        self.source_status = QtWidgets.QLabel("")
        self.source_status.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        self.status.addPermanentWidget(self.source_status)
        disclaimer = QtWidgets.QLabel("Bukan nasihat investasi · gunakan manajemen risiko")
        disclaimer.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        self.status.addPermanentWidget(disclaimer)

    # --------------------------------------------------------------- wiring
    def _populate_symbols(self) -> None:
        syms = self.provider.symbols() or config.MAJOR_SYMBOLS
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        seen = set()
        for sym in config.MAJOR_SYMBOLS:
            if sym in syms or not self.provider.connected:
                self.symbol_combo.addItem(sym)
                seen.add(sym)
        for sym in syms:
            if sym not in seen:
                self.symbol_combo.addItem(sym)
        completer = QtWidgets.QCompleter(self.symbol_combo.model(), self)
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        self.symbol_combo.setCompleter(completer)
        index = self.symbol_combo.findText(self.symbol)
        if index >= 0:
            self.symbol_combo.setCurrentIndex(index)
        self.symbol_combo.blockSignals(False)

    def _restore_settings(self) -> None:
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        sym = str(self.settings.value("symbol", self.symbol))
        if self.symbol_combo.findText(sym) >= 0:
            self.symbol = sym
            self.symbol_combo.setCurrentText(sym)
        tf = str(self.settings.value("tf", self.tf))
        if tf in self.tf_buttons:
            self.tf = tf
            self.tf_buttons[tf].setChecked(True)
        auto = self.settings.value("auto_refresh", "true") in (True, "true", "1")
        self.auto_check.setChecked(bool(auto))
        self.autofc_check.setChecked(self.settings.value("auto_forecast", "true") in (True, "true", "1"))
        self.chart_panel.chart.set_auto_forecast(self.autofc_check.isChecked())
        self.backtest_tab.set_symbol(self.symbol)
        self.auto_trade.set_symbol(self.symbol)
        self.trade_report.set_symbol(self.symbol)

    def _connect_signals(self) -> None:
        self.symbol_combo.activated.connect(self._symbol_activated)
        if self.symbol_combo.lineEdit() is not None:
            self.symbol_combo.lineEdit().returnPressed.connect(self._symbol_entered)
        self.tf_group.buttonClicked.connect(self._tf_button_clicked)
        self.signal_table.timeframe_selected.connect(self.set_timeframe)
        self.header_refresh.clicked.connect(lambda: self.refresh_all(manual=True))
        self.long_btn.clicked.connect(lambda: self._arm_order("long"))
        self.short_btn.clicked.connect(lambda: self._arm_order("short"))
        self.chart_panel.chart.order_mode_changed.connect(self._order_mode_changed)
        self.clear_btn.clicked.connect(self._clear_tools)
        self.fit_btn.clicked.connect(self.chart_panel.chart.fit_view)
        self.autofc_check.stateChanged.connect(self._auto_forecast_changed)
        self.auto_check.stateChanged.connect(self._auto_refresh_changed)
        self.plan_panel.draw_requested.connect(self._draw_forecast)
        self.plan_panel.backtest_requested.connect(self._backtest_current)
        self.toggles.visibility_changed.connect(self._toggles_changed)
        self.backtest_tab.reports_ready.connect(self.gallery.refresh)
        self.backtest_tab.results_ready.connect(self._on_backtest_results)
        self.gallery.dashboard_requested.connect(self._generate_dashboard)
        self.dashboard.tf_selected.connect(self._dashboard_tf_selected)
        self.history_card.history_toggled.connect(self._history_visibility)
        self.history_card.reload_requested.connect(self._load_history)
        self.history_card.replay_requested.connect(self._start_replay)
        self.history_card.replay_pause.connect(self.chart_panel.chart.pause_replay)
        self.history_card.replay_step.connect(self.chart_panel.chart.step_replay)
        self.history_card.replay_stop.connect(self.chart_panel.chart.stop_replay)
        self.chart_panel.chart.replay_state.connect(self.history_card.set_replay_state)
        self.tabs.currentChanged.connect(self._tab_changed)

    def _start_timers(self) -> None:
        self.clock_timer = QtCore.QTimer(self)
        self.clock_timer.timeout.connect(self._tick_clock)
        self.clock_timer.start(1000)
        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.timeout.connect(self._auto_refresh)
        self.auto_timer.start(20_000)
        self._tick_clock()

    # --------------------------------------------------------------- actions
    def _tick_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%d %b %Y  %H:%M:%S"))

    def _auto_refresh(self) -> None:
        active = self.tabs.currentWidget()
        if self.chart_panel.chart.is_replaying():
            return
        if self.auto_check.isChecked() and active in (self.chart_tab, self.dashboard) and not self._busy:
            self.refresh_all(silent=True)

    def _auto_refresh_changed(self) -> None:
        if self.auto_check.isChecked():
            self.auto_timer.start(20_000)
        else:
            self.auto_timer.stop()

    def _auto_forecast_changed(self) -> None:
        enabled = self.autofc_check.isChecked()
        chart = self.chart_panel.chart
        chart.set_auto_forecast(enabled)
        if enabled and self.signal_map.get(self.tf) is not None:
            chart.create_forecast_tool(self.signal_map[self.tf], auto=True)

    def _symbol_activated(self, _index: int) -> None:
        self.set_symbol(self.symbol_combo.currentText())

    def _symbol_entered(self) -> None:
        text = self.symbol_combo.currentText().strip().upper()
        if text:
            self.set_symbol(text)

    def set_symbol(self, symbol: str) -> None:
        symbol = symbol.strip().upper()
        if not symbol:
            return
        if self.provider.connected and self.symbol_combo.findText(symbol) < 0:
            if self.provider.select_symbol(symbol):
                self.provider.refresh_symbols()
                self._populate_symbols()
            else:
                self.status_label.setText(f"Simbol {symbol} tidak ditemukan di broker.")
                self.symbol_combo.setCurrentText(self.symbol)
                return
        self.symbol = symbol
        self.symbol_combo.setCurrentText(symbol)
        self.backtest_tab.set_symbol(symbol)
        self.auto_trade.set_symbol(symbol)
        self.trade_report.set_symbol(symbol)
        self.history_trades = []
        self._apply_history()
        self.refresh_all(manual=True)

    def _tf_button_clicked(self, button: QtWidgets.QPushButton) -> None:
        self.set_timeframe(button.property("tf"))

    def set_timeframe(self, tf: str) -> None:
        if tf not in config.TF_ORDER:
            return
        self.tf = tf
        if tf in self.tf_buttons:
            self.tf_buttons[tf].setChecked(True)
        self.signal_table.select_tf(tf)
        sig = self.signal_map.get(tf)
        if sig is None:
            self.refresh_all()
            return
        self._update_chart(tf, sig, keep_view=False)
        self._update_plan(sig)
        self.status_label.setText(f"Timeframe {tf} · {sig.signal} · skor {sig.score:+.0f}")

    def _update_chart(self, tf: str, sig, keep_view: bool = True) -> None:
        meta = self.provider.meta(self.symbol)
        df = sig.context.get("df") if sig is not None else None
        if df is None or len(df) < 20:
            df = self.provider.rates(self.symbol, tf, config.TF_BARS[tf], ttl=0)
        self.chart_panel.set_data(self.symbol, tf, df, sig, meta.digits, meta.point, keep_view=keep_view)

    def _update_plan(self, sig) -> None:
        self.plan_panel.update_data(sig, self.provider.meta(self.symbol))

    def _on_backtest_results(self, results: dict) -> None:
        try:
            self.history_trades = from_backtest_results(results)
            self.history_source = "Backtest"
            self.history_card.source.setCurrentIndex(0)
            self._apply_history()
            self.status_label.setText(f"History backtest dimuat: {len(self.history_trades)} trade.")
        except Exception as exc:
            self.status_label.setText(f"History error: {type(exc).__name__}: {exc}")

    def _load_history(self) -> None:
        try:
            if self.history_card.source.currentIndex() == 0:
                results = self.backtest_tab.results
                if not results:
                    self.status_label.setText("Belum ada hasil backtest. Jalankan backtest dulu.")
                    return
                trades = from_backtest_results(results)
                source = "Backtest"
            else:
                QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
                try:
                    trades = from_mt5_history(
                        self.symbol,
                        magic_base=app_settings.magic_base(),
                        magic_bases=app_settings.magic_bases(),
                        days=90,
                    )
                finally:
                    QtWidgets.QApplication.restoreOverrideCursor()
                source = "Auto Trade MT5"
            self.history_trades = trades
            self.history_source = source
            self._apply_history()
            self.status_label.setText(f"History dimuat: {len(trades)} trade dari {source}.")
        except Exception as exc:
            self.status_label.setText(f"Gagal memuat history: {type(exc).__name__}: {exc}")

    def _apply_history(self) -> None:
        visible = self.history_card.visible()
        self.chart_panel.chart.set_history_trades(self.history_trades)
        self.chart_panel.chart.set_history_visible(visible)
        self.dashboard.set_history(self.history_trades, visible)
        self.history_card.set_count(len(self.history_trades), self.history_source)

    def _history_visibility(self, visible: bool) -> None:
        self.chart_panel.chart.set_history_visible(visible)
        self.dashboard.set_history(self.history_trades, visible)

    def _start_replay(self, interval_ms: int) -> None:
        self.tabs.setCurrentWidget(self.chart_tab)
        chart = self.chart_panel.chart
        chart.remove_auto_tools()
        chart.start_replay(interval_ms=interval_ms)
        self.status_label.setText(
            "Replay berjalan. Pause/Step/Stop ada di panel History & Replay."
        )

    def _arm_order(self, direction: str) -> None:
        chart = self.chart_panel.chart
        if chart.order_mode == direction:
            chart.set_order_mode(None)
        else:
            chart.set_order_mode(direction)
        if direction == "long":
            self.long_btn.setText("Klik chart…" if chart.order_mode == "long" else "Long")
        else:
            self.short_btn.setText("Klik chart…" if chart.order_mode == "short" else "Short")
        self.status_label.setText("Klik pada chart untuk menaruh order box, lalu drag Entry/SL/TP.")

    def _order_mode_changed(self, active: bool) -> None:
        self.long_btn.setText("Klik chart…" if active and self.chart_panel.chart.order_mode == "long" else "Long")
        self.short_btn.setText("Klik chart…" if active and self.chart_panel.chart.order_mode == "short" else "Short")

    def _clear_tools(self) -> None:
        self.chart_panel.chart.clear_tools()
        self.status_label.setText("Semua order box dihapus.")

    def _toggles_changed(self, flags: dict) -> None:
        chart = self.chart_panel.chart
        chart.show_flags.update(flags)
        chart._draw_emas()
        chart._draw_volume()
        chart._draw_overlays()
        chart._update_volume_axis()
        chart._autoscale_y()

    def _draw_forecast(self) -> None:
        sig = self.signal_map.get(self.tf)
        if sig is None:
            return
        chart = self.chart_panel.chart
        chart.remove_auto_tools()
        chart.create_forecast_tool(sig, auto=False)
        self.status_label.setText(f"Forecast {sig.direction.upper()} {self.tf} digambar. Drag garis untuk menyesuaikan.")

    def _backtest_current(self) -> None:
        self.backtest_tab.set_symbol(self.symbol)
        index = self.backtest_tab.tf_combo.findText(self.tf)
        if index >= 0:
            self.backtest_tab.tf_combo.setCurrentIndex(index)
        self.tabs.setCurrentWidget(self.backtest_tab)
        self.backtest_tab.start_backtest()

    def _tab_changed(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is self.gallery:
            self.gallery.refresh()
        elif widget is self.trade_report:
            self.trade_report.load_data()

    def _dashboard_tf_selected(self, tf: str) -> None:
        self.tabs.setCurrentWidget(self.chart_tab)
        self.set_timeframe(tf)

    def _generate_dashboard(self) -> None:
        try:
            meta = self.provider.meta(self.symbol)
            sigs = signals.analyze_symbol(self.symbol, self.provider, meta.digits)
            if not sigs:
                self.status_label.setText("Dashboard gagal: data sinyal kosong.")
                return
            out = config.REPORT_DIR / f"ict_dashboard_{self.symbol}_{datetime.now():%Y%m%d_%H%M%S}.png"
            reporting.render_dashboard(self.symbol, sigs, out)
            self.gallery.refresh()
            self.status_label.setText(f"Dashboard baru dibuat: {out.name}")
        except Exception as exc:
            self.status_label.setText(f"Dashboard gagal: {type(exc).__name__}: {exc}")

    # --------------------------------------------------------------- refresh
    def refresh_all(self, initial: bool = False, manual: bool = False, silent: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        if not silent:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            if manual or initial:
                if not self.provider.connected:
                    self.provider.initialize()
            elif not self.provider.connected:
                self.provider.initialize()
            if self.provider.connected:
                self.provider.select_symbol(self.symbol)
            meta = self.provider.meta(self.symbol)
            started = datetime.now()
            self.signal_map = signals.analyze_symbol(self.symbol, self.provider, meta.digits)
            if not self.signal_map:
                self.status_label.setText("Tidak ada data untuk simbol ini.")
                return
            self.agg = signals.aggregate(self.signal_map)
            if self.tf not in self.signal_map:
                self.tf = next(iter(self.signal_map))
                self.tf_buttons[self.tf].setChecked(True)
            sig = self.signal_map[self.tf]
            self.signal_table.populate(self.signal_map)
            self.signal_table.select_tf(self.tf)
            self.confluence.update_data(self.agg)
            self._update_plan(sig)
            self._update_chart(self.tf, sig, keep_view=not initial)
            self.dashboard.update_data(self.signal_map, self.symbol)
            self.dashboard.set_history(self.history_trades, self.history_card.visible())
            self.auto_trade._refresh_mode()
            self.account.update_data(self.provider, "MetaTrader 5" if self.provider.connected else "DEMO")
            self._update_header()
            elapsed = (datetime.now() - started).total_seconds()
            src = "MT5" if self.provider.connected else "DEMO"
            self.source_status.setText(
                f"Data: {src} · {len(sig.context.get('df', []))} candles · refresh {elapsed:.2f}s "
                f"· {datetime.now():%H:%M:%S}"
            )
            if not silent:
                self.status_label.setText(
                    f"{self.symbol} {self.tf} · {sig.signal} · konfluensi {self.agg['signal']} "
                    f"({self.agg['score']:+.0f}) · {self.agg['buy']} buy / {self.agg['sell']} sell / "
                    f"{self.agg['wait']} wait"
                )
            self._last_update = datetime.now()
        except Exception as exc:
            self.status_label.setText(f"Error: {type(exc).__name__}: {exc}")
        finally:
            self._busy = False
            if not silent:
                QtWidgets.QApplication.restoreOverrideCursor()

    def _update_header(self) -> None:
        connected = self.provider.connected
        if connected:
            self.conn_pill.setText("●  MT5 CONNECTED")
            self.conn_pill.setStyleSheet(
                f"background:rgba(38,166,154,0.13); color:{config.BULL}; border:1px solid rgba(38,166,154,0.4);"
                "border-radius:10px; padding:4px 10px; font-size:10px; font-weight:700;"
            )
            acc = self.provider.account or {}
            self.account_label.setText(
                f"{acc.get('server', 'MT5')} · {acc.get('login', '—')} · "
                f"{acc.get('currency', 'USD')} {acc.get('balance', 0):,.0f}"
            )
        else:
            self.conn_pill.setText("●  DEMO DATA")
            self.conn_pill.setStyleSheet(
                f"background:rgba(245,196,81,0.12); color:{config.GOLD}; border:1px solid rgba(245,196,81,0.4);"
                "border-radius:10px; padding:4px 10px; font-size:10px; font-weight:700;"
            )
            self.account_label.setText(self.provider.error or "MT5 offline")

    # --------------------------------------------------------------- licence
    def _refresh_license_badge(self) -> None:
        state = licensing.current_state(force=True)
        if state.edition == "PRO":
            color, bg = config.BULL, "rgba(38,166,154,0.15)"
        elif state.bot_locked:
            color, bg = config.BEAR, "rgba(239,83,80,0.15)"
        elif state.tier == "pro":
            color, bg = config.ACCENT, "rgba(79,156,249,0.15)"
        else:
            color, bg = config.GOLD, "rgba(245,196,81,0.12)"
        self.license_pill.setText(state.badge)
        self.license_pill.setStyleSheet(
            f"background:{bg}; color:{color}; border:1px solid {color};"
            "border-radius:10px; padding:4px 10px; font-size:10px; font-weight:700;"
        )
        self.license_pill.setToolTip(licensing.license_text(state))
        self.license_btn.setText("LISENSI" if state.edition != "PRO" else "PRO")
        self.license_btn.setToolTip(
            "Klik untuk melihat detail lisensi / memperpanjang" if state.edition == "PRO"
            else "Klik untuk memasukkan key aktivasi"
        )

    def open_license_dialog(self) -> None:
        dlg = LicenseDialog(self)
        dlg.activated.connect(self._license_activated)
        dlg.exec()
        self._refresh_license_badge()

    def _license_activated(self) -> None:
        self._refresh_license_badge()
        try:
            self.auto_trade.refresh_license_limits()
        except Exception:
            pass
        state = licensing.current_state(force=True)
        try:
            self.settings.setValue("license/notified_phase", state.phase)
        except Exception:
            pass
        self.statusBar().showMessage(f"Lisensi aktif: {state.plan} · {state.badge}", 8000)

    def after_startup_license(self) -> None:
        """Notifikasi saat pertama dibuka dan setiap kali tahap berubah.

        Tahap: ``trial_pro`` (7 hari PRO) -> ``trial_lite`` (23 hari terbatas)
        -> ``locked`` (bot terkunci, chart & sinyal tetap jalan).
        """
        state = licensing.current_state(force=True)
        try:
            notified = str(self.settings.value("license/notified_phase", "") or "")
        except Exception:
            notified = ""
        if not (state.welcome or state.phase != notified):
            return
        dlg = LicenseDialog(self, welcome=state.welcome)
        dlg.activated.connect(self._license_activated)
        dlg.exec()
        licensing.mark_welcome_shown()
        state = licensing.current_state(force=True)
        try:
            self.settings.setValue("license/notified_phase", state.phase)
        except Exception:
            pass
        self._refresh_license_badge()

    # ---------------------------------------------------------------- close
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        try:
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.setValue("symbol", self.symbol)
            self.settings.setValue("tf", self.tf)
            self.settings.setValue("auto_refresh", self.auto_check.isChecked())
            self.settings.setValue("auto_forecast", self.autofc_check.isChecked())
        except Exception:
            pass
        try:
            self.auto_timer.stop()
            self.clock_timer.stop()
            self.auto_trade.shutdown()
            if self.backtest_tab.worker is not None and self.backtest_tab.worker.isRunning():
                self.backtest_tab.worker.requestInterruption()
            self.provider.shutdown()
        except Exception:
            pass
        super().closeEvent(event)


def apply_windows_taskbar_icon(window, icon_path) -> None:
    """Paksa ikon taskbar lewat Win32.

    Qt men-set ikon jendela sebelum ``show()``, tetapi kalau aplikasi memakai
    AppUserModelID sendiri, Windows sering tetap menampilkan ikon generik di
    taskbar. Men-set WM_SETICON + ikon kelas setelah jendela tampil membuat
    taskbar memakai logo aplikasi.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        LR_LOADFROMFILE = 0x0010
        IMAGE_ICON = 1
        WM_SETICON = 0x0080
        ICON_SMALL, ICON_BIG = 0, 1
        GCLP_HICON, GCLP_HICONSM = -14, -34

        def load(size: int):
            return user32.LoadImageW(None, str(icon_path), IMAGE_ICON, size, size, LR_LOADFROMFILE)

        small = load(16) or load(32)
        big = load(32) or load(48) or load(64)
        if small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
            user32.SetClassLongPtrW(hwnd, GCLP_HICONSM, small)
        if big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, big)
        user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    except Exception:
        pass


def run_app(provider: data.DataProvider, selftest: bool = False) -> int:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName("ICT Terminal")
    app.setStyle("Fusion")
    app.setStyleSheet(config.APP_QSS)
    icon_path = config.ASSET_DIR / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))
    window = MainWindow(provider)
    if icon_path.exists():
        window.setWindowIcon(QtGui.QIcon(str(icon_path)))
    window.show()
    if icon_path.exists():
        QtCore.QTimer.singleShot(0, lambda: apply_windows_taskbar_icon(window, icon_path))
        QtCore.QTimer.singleShot(1500, lambda: apply_windows_taskbar_icon(window, icon_path))
    if not selftest:
        QtCore.QTimer.singleShot(700, window.after_startup_license)
    if selftest:
        def capture():
            try:
                shot = None
                screen = QtGui.QGuiApplication.primaryScreen()
                if screen is not None:
                    # Grab from the real screen so fonts render exactly as the
                    # user sees them (widget.grab() can fall back to a font
                    # with no glyphs on some Windows setups).
                    shot = screen.grabWindow(int(window.winId()))
                if shot is None or shot.isNull():
                    shot = window.grab()
                path = config.REPORT_DIR / "app_screenshot.png"
                shot.save(str(path))
                print(f"SELFTEST_OK {path} {shot.width()}x{shot.height()}")
            except Exception as exc:
                print(f"SELFTEST_FAIL {exc}")
            app.quit()
        QtCore.QTimer.singleShot(6500, capture)
    return app.exec()
