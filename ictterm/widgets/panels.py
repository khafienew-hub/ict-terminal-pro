"""Side panels: confluence, multi-timeframe table, trade plan, account, toggles."""
from __future__ import annotations

from typing import Any

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config


class Card(QtWidgets.QFrame):
    def __init__(self, title: str | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(11, 9, 11, 10)
        self.body.setSpacing(7)
        if title:
            label = QtWidgets.QLabel(title.upper())
            label.setObjectName("SectionTitle")
            self.body.addWidget(label)


class ConfluenceCard(Card):
    def __init__(self, parent=None):
        super().__init__("KONFLUENSI MULTI-TIMEFRAME", parent)
        self.big = QtWidgets.QLabel("WAIT")
        self.big.setObjectName("BigNeutral")
        self.big.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.big)
        self.score = QtWidgets.QLabel("skor 0 · confidence 0%")
        self.score.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.score.setStyleSheet(f"color:{config.MUTED}; font-size:11px;")
        self.body.addWidget(self.score)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.body.addWidget(self.bar)
        self.detail = QtWidgets.QLabel("—")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        self.body.addWidget(self.detail)
        self.best = QtWidgets.QLabel("")
        self.best.setWordWrap(True)
        self.best.setStyleSheet("font-size:10px; color:#d7e0ea;")
        self.body.addWidget(self.best)

    def update_data(self, agg: dict[str, Any]) -> None:
        sig = agg.get("signal", "WAIT")
        self.big.setText(sig)
        self.big.setObjectName({"BUY": "BigBuy", "SELL": "BigSell"}.get(sig, "BigNeutral"))
        self.big.style().unpolish(self.big)
        self.big.style().polish(self.big)
        score = agg.get("score", 0.0)
        conf = agg.get("confidence", 0)
        self.score.setText(f"skor {score:+.1f}  ·  confidence {conf}%")
        self.bar.setValue(int(conf))
        color = config.BULL if sig == "BUY" else (config.BEAR if sig == "SELL" else config.ACCENT)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background:{config.PANEL_ALT}; border:none; border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}"
        )
        self.detail.setText(
            f"{agg.get('buy', 0)} BUY · {agg.get('sell', 0)} SELL · {agg.get('wait', 0)} WAIT "
            f"dari {agg.get('buy', 0) + agg.get('sell', 0) + agg.get('wait', 0)} timeframe"
        )
        best = agg.get("best")
        if best is not None:
            self.best.setText(
                f"Setup terkuat: <b>{best.tf}</b> · {best.signal} · {best.zone} · R:R {best.rr:.1f}"
            )
        else:
            self.best.setText("")


class SignalTable(QtWidgets.QTableWidget):
    timeframe_selected = QtCore.pyqtSignal(str)

    HEADERS = ["TF", "SINYAL", "SKOR", "STRUKTUR", "SETUP"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.HEADERS))
        self.setHorizontalHeaderLabels(self.HEADERS)
        self.verticalHeader().hide()
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setFixedHeight(228)
        self.verticalHeader().setDefaultSectionSize(26)
        self.setStyleSheet("QTableWidget { font-size: 10px; } QTableWidget::item { padding: 0px; }")
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 32)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(1, 54)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(2, 38)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(3, 92)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.cellClicked.connect(self._clicked)
        self._rows: dict[str, int] = {}

    def populate(self, signals: dict) -> None:
        tfs = [tf for tf in config.TF_ORDER if tf in signals]
        self.setRowCount(len(tfs))
        self._rows = {}
        for row, tf in enumerate(tfs):
            self._rows[tf] = row
            sig = signals[tf]
            setup = "Swing" if sig.zone == "Swing structure" else sig.zone
            values = [tf, sig.signal, f"{sig.score:+.0f}", sig.structure, setup]
            color = QtGui.QColor(config.BULL if sig.signal == "BUY" else (config.BEAR if sig.signal == "SELL" else config.MUTED))
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if col == 1:
                    item.setForeground(QtGui.QBrush(color))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                elif col == 2:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if sig.score > 0 else (config.BEAR if sig.score < 0 else config.MUTED))))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.TEXT if col == 0 else config.MUTED)))
                item.setToolTip("\n".join(sig.reasons[:6]))
                self.setItem(row, col, item)

    def select_tf(self, tf: str) -> None:
        row = self._rows.get(tf)
        if row is not None:
            self.selectRow(row)

    def _clicked(self, row: int, _col: int) -> None:
        for tf, r in self._rows.items():
            if r == row:
                self.timeframe_selected.emit(tf)
                break


class TradePlanPanel(Card):
    draw_requested = QtCore.pyqtSignal()
    backtest_requested = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("TRADE PLAN", parent)
        self.badge = QtWidgets.QLabel("—")
        self.badge.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet(
            f"background:{config.PANEL_ALT}; color:{config.MUTED}; border:1px solid {config.BORDER};"
            "border-radius:7px; padding:7px; font-size:15px; font-weight:800;"
        )
        self.body.addWidget(self.badge)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)
        self.fields: dict[str, QtWidgets.QLabel] = {}
        rows = [("Entry", "entry"), ("Stop Loss", "stop"), ("Take Profit", "target"),
                ("Risk : Reward", "rr"), ("SL distance", "risk"), ("Confidence", "conf"),
                ("Zona ICT", "zone"), ("Area Harga", "pd")]
        for i, (label, key) in enumerate(rows):
            lab = QtWidgets.QLabel(label)
            lab.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
            val = QtWidgets.QLabel("—")
            val.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
            val.setStyleSheet(f"color:{config.TEXT}; font-size:11px; font-weight:600;")
            grid.addWidget(lab, i, 0)
            grid.addWidget(val, i, 1)
            self.fields[key] = val
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)

        self.conf_bar = QtWidgets.QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setTextVisible(False)
        self.conf_bar.setFixedHeight(4)
        self.body.addWidget(self.conf_bar)

        reasons_title = QtWidgets.QLabel("ALASAN SINYAL")
        reasons_title.setObjectName("SectionTitle")
        self.body.addWidget(reasons_title)
        self.reasons = QtWidgets.QTextBrowser()
        self.reasons.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; border-radius:5px;"
            f"color:{config.TEXT}; font-size:10px; padding:4px;"
        )
        self.reasons.setFixedHeight(126)
        self.body.addWidget(self.reasons)
        self.draw_btn = QtWidgets.QPushButton("Gambar Forecast di Chart")
        self.draw_btn.setObjectName("PrimaryButton")
        self.draw_btn.clicked.connect(self.draw_requested.emit)
        self.body.addWidget(self.draw_btn)
        self.backtest_btn = QtWidgets.QPushButton("Backtest TF ini")
        self.backtest_btn.clicked.connect(self.backtest_requested.emit)
        self.body.addWidget(self.backtest_btn)
        self.signal_obj = None

    def update_data(self, sig, meta) -> None:
        self.signal_obj = sig
        if sig is None:
            self.badge.setText("—")
            return
        color = config.BULL if sig.signal == "BUY" else (config.BEAR if sig.signal == "SELL" else config.MUTED)
        bg = config.BULL if sig.signal == "BUY" else (config.BEAR if sig.signal == "SELL" else config.PANEL_ALT)
        fg = "#07110f" if sig.signal == "BUY" else ("#180707" if sig.signal == "SELL" else config.TEXT)
        self.badge.setText(f"{sig.tf}  ·  {sig.signal}")
        self.badge.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {config.BORDER};"
            "border-radius:7px; padding:7px; font-size:15px; font-weight:800;"
        )
        d = meta.digits if meta is not None else 2
        point = meta.point if meta is not None else 0.01
        self.fields["entry"].setText(config.fmt_price(sig.entry, d))
        self.fields["stop"].setText(config.fmt_price(sig.stop, d))
        self.fields["target"].setText(config.fmt_price(sig.target, d))
        self.fields["rr"].setText(f"{sig.rr:.2f} R")
        self.fields["risk"].setText(config.fmt_price(abs(sig.entry - sig.stop), d))
        self.fields["risk"].setToolTip(
            f"{abs(sig.entry - sig.stop) / point:,.0f} points · stop {config.fmt_price(sig.stop, d)}"
        )
        self.fields["conf"].setText(f"{sig.confidence}%")
        self.fields["zone"].setText(sig.zone)
        self.fields["pd"].setText(sig.pd_zone.title())
        self.fields["rr"].setStyleSheet(f"color:{color}; font-size:11px; font-weight:700;")
        self.conf_bar.setValue(sig.confidence)
        self.conf_bar.setStyleSheet(
            f"QProgressBar {{ background:{config.PANEL_ALT}; border:none; border-radius:2px; }}"
            f"QProgressBar::chunk {{ background:{color}; border-radius:2px; }}"
        )
        reasons = "<br>".join(f"<span style='color:{config.ACCENT}'>•</span> {r}" for r in sig.reasons[:8])
        self.reasons.setHtml(f"<div style='line-height:1.5'>{reasons}</div>")


class AccountCard(Card):
    def __init__(self, parent=None):
        super().__init__("KONEKSI MT5", parent)
        self.status = QtWidgets.QLabel("●  MENGHUBUNGKAN…")
        self.status.setStyleSheet(f"color:{config.GOLD}; font-size:10px; font-weight:700;")
        self.body.addWidget(self.status)
        self.account = QtWidgets.QLabel("—")
        self.account.setWordWrap(True)
        self.account.setStyleSheet(f"color:{config.TEXT}; font-size:10px;")
        self.body.addWidget(self.account)
        self.balance = QtWidgets.QLabel("—")
        self.balance.setWordWrap(True)
        self.balance.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        self.body.addWidget(self.balance)
        self.clock = QtWidgets.QLabel("—")
        self.clock.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        self.body.addWidget(self.clock)

    def update_data(self, provider, source: str) -> None:
        if provider.connected:
            self.status.setText("●  MT5 TERHUBUNG")
            self.status.setStyleSheet(f"color:{config.BULL}; font-size:10px; font-weight:700;")
            acc = provider.account or {}
            term = provider.terminal or {}
            self.account.setText(
                f"<b>{acc.get('login', '—')}</b> · {acc.get('server', '—')}<br>"
                f"{acc.get('name', '')} · {term.get('company', '')}"
            )
            self.balance.setText(
                f"Balance <b>{acc.get('balance', 0):,.2f}</b> {acc.get('currency', 'USD')}<br>"
                f"Equity {acc.get('equity', 0):,.2f} · Free margin {acc.get('margin_free', 0):,.2f}"
            )
            self.clock.setText(
                f"Data: {source}  ·  terminal build {term.get('build', '—')}  ·  "
                f"{QtCore.QDateTime.currentDateTime().toString('dd MMM yyyy HH:mm:ss')}"
            )
        else:
            self.status.setText("●  MODE DEMO / MT5 OFFLINE")
            self.status.setStyleSheet(f"color:{config.GOLD}; font-size:10px; font-weight:700;")
            self.account.setText("MetaTrader 5 tidak terhubung.<br>Data candle sintetis dipakai agar UI tetap bisa diuji.")
            self.balance.setText(provider.error or "")
            self.clock.setText(QtCore.QDateTime.currentDateTime().toString("dd MMM yyyy HH:mm:ss"))


class ToggleCard(Card):
    visibility_changed = QtCore.pyqtSignal(dict)

    LABELS = [
        ("ema", "EMA 20 / 50 / 200"),
        ("ob", "Order Block (OB)"),
        ("fvg", "Fair Value Gap (FVG)"),
        ("structure", "Market Structure / BOS"),
        ("liquidity", "Liquidity (EQH/EQL)"),
        ("volume", "Volume"),
        ("killzones", "Killzone session"),
    ]

    def __init__(self, parent=None):
        super().__init__("TAMPILAN CHART", parent)
        self.boxes: dict[str, QtWidgets.QCheckBox] = {}
        for key, label in self.LABELS:
            box = QtWidgets.QCheckBox(label)
            box.setChecked(key != "killzones")
            box.stateChanged.connect(self._changed)
            self.boxes[key] = box
            self.body.addWidget(box)

    def _changed(self) -> None:
        self.visibility_changed.emit({key: box.isChecked() for key, box in self.boxes.items()})


class HowToCard(Card):
    def __init__(self, parent=None):
        super().__init__("CARA PAKAI", parent)
        text = QtWidgets.QLabel(
            "1. Pilih simbol & timeframe.<br>"
            "2. Baca konfluensi 7 TF di panel kiri.<br>"
            "3. Klik <b>Gambar Forecast</b> untuk order box.<br>"
            "4. Drag garis Entry/SL/TP untuk atur rencana.<br>"
            "5. Jalankan backtest ICT di tab Backtest."
        )
        text.setWordWrap(True)
        text.setStyleSheet(f"color:{config.MUTED}; font-size:10px; line-height:1.5;")
        self.body.addWidget(text)


class HistoryCard(Card):
    history_toggled = QtCore.pyqtSignal(bool)
    reload_requested = QtCore.pyqtSignal()
    replay_requested = QtCore.pyqtSignal(int)
    replay_pause = QtCore.pyqtSignal()
    replay_step = QtCore.pyqtSignal()
    replay_stop = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("HISTORY & REPLAY", parent)
        self.show_check = QtWidgets.QCheckBox("Tampilkan history trade di candle")
        self.show_check.setChecked(True)
        self.show_check.stateChanged.connect(
            lambda _s: self.history_toggled.emit(self.show_check.isChecked())
        )
        self.source = QtWidgets.QComboBox()
        self.source.addItems(["Backtest terakhir", "Auto Trade MT5"])
        self.reload = QtWidgets.QPushButton("Muat History")
        self.reload.clicked.connect(self.reload_requested.emit)
        self.count_label = QtWidgets.QLabel("Belum ada history.")
        self.count_label.setWordWrap(True)
        self.count_label.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        self.body.addWidget(self.show_check)
        self.body.addWidget(self.source)
        self.body.addWidget(self.reload)
        self.body.addWidget(self.count_label)

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{config.BORDER};")
        self.body.addWidget(line)

        replay_title = QtWidgets.QLabel("REPLAY CANDLE")
        replay_title.setObjectName("SectionTitle")
        self.body.addWidget(replay_title)
        speed_row = QtWidgets.QHBoxLayout()
        speed_row.addWidget(QtWidgets.QLabel("Kecepatan"))
        self.speed = QtWidgets.QComboBox()
        self.speed.addItem("0.5 detik", 500)
        self.speed.addItem("1 detik", 1000)
        self.speed.addItem("2 detik", 2000)
        self.speed.setCurrentIndex(1)
        speed_row.addWidget(self.speed, 1)
        self.body.addLayout(speed_row)
        row = QtWidgets.QHBoxLayout()
        self.play_btn = QtWidgets.QPushButton("Play")
        self.play_btn.setObjectName("PrimaryButton")
        self.pause_btn = QtWidgets.QPushButton("Pause")
        self.step_btn = QtWidgets.QPushButton("Step")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        row.addWidget(self.play_btn)
        row.addWidget(self.pause_btn)
        row.addWidget(self.step_btn)
        self.body.addLayout(row)
        self.body.addWidget(self.stop_btn)
        self.replay_status = QtWidgets.QLabel("Replay: —")
        self.replay_status.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        self.body.addWidget(self.replay_status)
        self.play_btn.clicked.connect(
            lambda: self.replay_requested.emit(int(self.speed.currentData() or 1000))
        )
        self.pause_btn.clicked.connect(self.replay_pause.emit)
        self.step_btn.clicked.connect(self.replay_step.emit)
        self.stop_btn.clicked.connect(self.replay_stop.emit)

    def visible(self) -> bool:
        return self.show_check.isChecked()

    def set_count(self, count: int, source: str) -> None:
        self.count_label.setText(f"{count} trade · sumber: {source}")
        self.count_label.setStyleSheet(
            f"color:{config.BULL if count else config.MUTED}; font-size:9px;"
        )

    def set_replay_state(self, active: bool, index: int, total: int) -> None:
        if total <= 0:
            self.replay_status.setText("Replay: —")
        elif active:
            self.replay_status.setText(f"Replay aktif · candle {index + 1}/{total}")
        else:
            self.replay_status.setText(f"Replay berhenti · candle {index + 1}/{total}")

