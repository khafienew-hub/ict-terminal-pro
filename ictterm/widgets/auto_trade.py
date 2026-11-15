"""Auto-trade UI: live execution from the Python application with safety guards."""
from __future__ import annotations

import html
from datetime import datetime

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config, licensing, settings as app_settings
from ..telegram import TelegramNotifier
from ..trader import AutoTradeConfig, AutoTrader
from .panels import Card


MAX_AUTO_SYMBOLS = 12


class AutoTradeTab(QtWidgets.QWidget):
    def __init__(self, provider, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.symbol = config.DEFAULT_SYMBOL
        self.engine: AutoTrader | None = None
        self.signal_rows: dict[tuple[str, str], dict] = {}
        self._settings = QtCore.QSettings("ICT Terminal", "ICT Terminal Pro")
        self._build()

    # ------------------------------------------------------------------- UI
    def _build(self) -> None:
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        left_scroll = QtWidgets.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFixedWidth(330)
        left_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        left_wrap = QtWidgets.QWidget()
        left = QtWidgets.QVBoxLayout(left_wrap)
        left.setContentsMargins(0, 0, 4, 0)
        left.setSpacing(10)

        heading = Card("AUTO TRADE · MT5 MULTI-SYMBOL")
        self.symbol_label = QtWidgets.QLabel(f"Chart fokus: {self.symbol}")
        self.symbol_label.setStyleSheet("font-size:17px; font-weight:800; color:#ffffff;")
        self.mode_label = QtWidgets.QLabel("Akun: —")
        self.mode_label.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        warning = QtWidgets.QLabel(
            "Mode ini mengirim order pasar ke beberapa simbol di akun MT5 yang sedang login. "
            "Gunakan akun demo terlebih dahulu."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(f"color:{config.GOLD}; font-size:9px;")
        heading.body.addWidget(self.symbol_label)
        heading.body.addWidget(self.mode_label)
        heading.body.addWidget(warning)
        left.addWidget(heading)

        tf_card = Card("TIMEFRAME YANG DITRADING")
        self.tf_boxes: dict[str, QtWidgets.QCheckBox] = {}
        tf_grid = QtWidgets.QGridLayout()
        tf_grid.setSpacing(5)
        for idx, tf in enumerate(config.TF_ORDER):
            box = QtWidgets.QCheckBox(tf)
            box.setChecked(tf in ("M15", "M30", "H1"))
            self.tf_boxes[tf] = box
            tf_grid.addWidget(box, idx // 4, idx % 4)
        tf_card.body.addLayout(tf_grid)
        tf_note = QtWidgets.QLabel(
            "Magic per TF + arah: maksimal 1 BUY dan 1 SELL per TF per simbol (hedging). "
            "BUY lama tidak menghalangi SELL baru."
        )
        tf_note.setWordWrap(True)
        tf_note.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        tf_card.body.addWidget(tf_note)
        left.addWidget(tf_card)

        symbol_card = Card("SIMBOL YANG DITRADING")
        symbol_note = QtWidgets.QLabel(
            "Centang simbol yang boleh ditradingkan. Chart tetap single-symbol; "
            "engine memproses semua simbol tercentang."
        )
        symbol_note.setWordWrap(True)
        symbol_note.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        symbol_card.body.addWidget(symbol_note)
        self.symbol_search = QtWidgets.QLineEdit()
        self.symbol_search.setPlaceholderText("Cari simbol…")
        self.symbol_search.textChanged.connect(self._filter_symbol_list)
        symbol_card.body.addWidget(self.symbol_search)
        self.symbol_list = QtWidgets.QListWidget()
        self.symbol_list.setFixedHeight(150)
        self.symbol_list.itemChanged.connect(lambda _item: self._update_symbol_count())
        symbol_card.body.addWidget(self.symbol_list)
        self._populate_symbol_list()
        add_row = QtWidgets.QHBoxLayout()
        add_row.setSpacing(5)
        self.symbol_add = QtWidgets.QLineEdit()
        self.symbol_add.setPlaceholderText("Tambah simbol…")
        self.symbol_add_btn = QtWidgets.QPushButton("+")
        self.symbol_add_btn.setFixedWidth(30)
        self.symbol_add_btn.clicked.connect(self._add_custom_symbol)
        add_row.addWidget(self.symbol_add, 1)
        add_row.addWidget(self.symbol_add_btn)
        symbol_card.body.addLayout(add_row)
        pick_row = QtWidgets.QHBoxLayout()
        self.symbol_all_btn = QtWidgets.QPushButton("Pilih tampil")
        self.symbol_none_btn = QtWidgets.QPushButton("Kosongkan tampil")
        self.symbol_all_btn.clicked.connect(lambda: self._check_visible_symbols(True))
        self.symbol_none_btn.clicked.connect(lambda: self._check_visible_symbols(False))
        pick_row.addWidget(self.symbol_all_btn)
        pick_row.addWidget(self.symbol_none_btn)
        symbol_card.body.addLayout(pick_row)
        self.symbol_count = QtWidgets.QLabel("")
        self.symbol_count.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        symbol_card.body.addWidget(self.symbol_count)
        self._update_symbol_count()
        left.addWidget(symbol_card)

        settings = Card("RISK & EXIT · GLOBAL")
        form = QtWidgets.QFormLayout()
        form.setSpacing(6)
        self.risk_spin = self._spin(0.1, 5.0, 0.5, 0.1, " %")
        self.total_risk_spin = self._spin(0.5, 10.0, 2.0, 0.1, " %")
        self.max_dd_spin = self._spin(1.0, 50.0, 4.0, 0.5, " %")
        self.threshold_spin = self._spin(3.0, 10.0, 10.0, 0.5, "")
        self.rr_spin = self._spin(0.5, 5.0, 2.0, 0.1, " R")
        self.rr_spin.setToolTip("Dipakai hanya pada mode RR manual. Mode struktur memakai liquidity/swing.")
        self.spread_spin = QtWidgets.QSpinBox()
        self.spread_spin.setRange(1, 10000)
        self.spread_spin.setValue(500)
        self.spread_spin.setSuffix(" pts")
        self.bars_spin = QtWidgets.QSpinBox()
        self.bars_spin.setRange(5, 300)
        self.bars_spin.setValue(45)
        self.magic_spin = QtWidgets.QSpinBox()
        self.magic_spin.setRange(app_settings.MAGIC_BASE_MIN, app_settings.MAGIC_BASE_MAX)
        self.magic_spin.setSingleStep(1000)
        self.magic_spin.setValue(app_settings.magic_base())
        self.magic_spin.setGroupSeparatorShown(True)
        self.magic_spin.valueChanged.connect(
            lambda value: app_settings.set_magic_base(value, remember=False)
        )
        self.magic_spin.setToolTip(
            "Magic number dasar order Auto Trade.\n"
            "BUY  = magic + 1000 + nomor TF\n"
            "SELL = magic + 1100 + nomor TF\n"
            "Ubah hanya bila nomor ini bentrok dengan EA lain di akun yang sama."
        )
        self.tp_mode = QtWidgets.QComboBox()
        self.tp_mode.addItems(["RR manual", "Struktur liquidity"])
        self.tp_mode.currentIndexChanged.connect(self._tp_mode_changed)
        self.session_check = QtWidgets.QCheckBox("Filter killzone sesi")
        form.addRow("Risk / trade", self.risk_spin)
        form.addRow("Max total risk semua simbol", self.total_risk_spin)
        form.addRow("Max drawdown global", self.max_dd_spin)
        form.addRow("Skor minimum", self.threshold_spin)
        form.addRow("Mode TP", self.tp_mode)
        form.addRow("Target RR", self.rr_spin)
        form.addRow("Max spread", self.spread_spin)
        form.addRow("Max bar di trade", self.bars_spin)
        form.addRow("Magic number", self.magic_spin)
        form.addRow("", self.session_check)
        self.license_note = QtWidgets.QLabel("")
        self.license_note.setWordWrap(True)
        self.license_note.setStyleSheet(f"color:{config.GOLD}; font-size:9px; font-weight:700;")
        settings.body.addWidget(self.license_note)
        settings.body.addLayout(form)
        risk_note = QtWidgets.QLabel(
            "Total risk 2% dihitung dari seluruh posisi Auto Trade di semua simbol. "
            "Max DD 4% juga global. Magic number boleh diubah kapan saja; laporan "
            "tetap membaca order yang dibuka dengan magic lama."
        )
        risk_note.setWordWrap(True)
        risk_note.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        settings.body.addWidget(risk_note)
        left.addWidget(settings)

        telegram = Card("NOTIFIKASI TELEGRAM")
        self.tg_enable = QtWidgets.QCheckBox("Aktifkan notifikasi Telegram")
        self.tg_token = QtWidgets.QLineEdit()
        self.tg_token.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.tg_token.setPlaceholderText("Bot token dari @BotFather")
        self.tg_chat = QtWidgets.QLineEdit()
        self.tg_chat.setPlaceholderText("Chat ID / user ID Telegram")
        self.tg_status = QtWidgets.QLabel("")
        self.tg_status.setWordWrap(True)
        self.tg_status.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        tg_test = QtWidgets.QPushButton("Test Telegram")
        tg_test.clicked.connect(self.test_telegram)
        self.tg_test_btn = tg_test
        telegram.body.addWidget(self.tg_enable)
        telegram.body.addWidget(self.tg_token)
        telegram.body.addWidget(self.tg_chat)
        telegram.body.addWidget(tg_test)
        telegram.body.addWidget(self.tg_status)
        tg_note = QtWidgets.QLabel(
            "Kirim notifikasi saat sinyal ditemukan dan saat order berhasil dibuka. "
            "Token disimpan lokal di QSettings."
        )
        tg_note.setWordWrap(True)
        tg_note.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        telegram.body.addWidget(tg_note)
        left.addWidget(telegram)

        # Restore notification settings.
        self.tg_enable.setChecked(self._settings.value("tg_enabled", "false") in (True, "true", "1"))
        self.tg_token.setText(str(self._settings.value("tg_token", "")))
        self.tg_chat.setText(str(self._settings.value("tg_chat", "")))

        controls = Card("KONTROL EKSEKUSI")
        self.confirm_check = QtWidgets.QCheckBox(
            "Saya paham order akan dikirim\nke akun MT5 (demo/real)"
        )
        controls.body.addWidget(self.confirm_check)
        self.start_btn = QtWidgets.QPushButton("MULAI AUTO TRADE")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.clicked.connect(self.start_engine)
        self.stop_btn = QtWidgets.QPushButton("STOP ENGINE")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_engine)
        self.close_btn = QtWidgets.QPushButton("STOP ALL · TUTUP POSISI")
        self.close_btn.setObjectName("SellButton")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.stop_all)
        self.reset_btn = QtWidgets.QPushButton("Reset Max DD")
        self.reset_btn.clicked.connect(self.reset_halt)
        self.reset_btn.setEnabled(False)
        controls.body.addWidget(self.start_btn)
        controls.body.addWidget(self.stop_btn)
        controls.body.addWidget(self.close_btn)
        controls.body.addWidget(self.reset_btn)
        hint = QtWidgets.QLabel(
            "Entry dievaluasi saat candle baru ditutup — entry pertama bisa menunggu TF berikutnya. "
            "SL/TP dipasang di server MT5. Max DD = stop entry baru; posisi lama tetap dikelola SL/TP. "
            "Menutup aplikasi tidak menutup posisi yang sudah terbuka."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        controls.body.addWidget(hint)
        left.addWidget(controls)
        left.addStretch(1)
        left_scroll.setWidget(left_wrap)
        root.addWidget(left_scroll)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(10)
        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(8)
        self.card_equity = self._stat_card("EQUITY", "—")
        self.card_risk = self._stat_card("OPEN RISK GLOBAL", "—")
        self.card_dd = self._stat_card("DRAWDOWN GLOBAL", "—")
        self.card_status = self._stat_card("STATUS", "OFF")
        for c in (self.card_equity, self.card_risk, self.card_dd, self.card_status):
            cards.addWidget(c)
        right.addLayout(cards)

        self.account_info = QtWidgets.QLabel("Engine belum berjalan.")
        self.account_info.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        right.addWidget(self.account_info)

        pos_title = QtWidgets.QLabel("POSISI AUTO TRADE · SEMUA SIMBOL")
        pos_title.setObjectName("SectionTitle")
        right.addWidget(pos_title)
        self.positions = QtWidgets.QTableWidget()
        self.positions.setColumnCount(9)
        self.positions.setHorizontalHeaderLabels(
            ["SIMBOL", "TF", "TICKET", "ARAH", "LOT", "ENTRY", "SL", "TP", "P/L"]
        )
        self.positions.verticalHeader().hide()
        self.positions.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.positions.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.positions.setAlternatingRowColors(True)
        self.positions.setShowGrid(False)
        self.positions.verticalHeader().setDefaultSectionSize(25)
        for i in range(9):
            self.positions.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        self.positions.setFixedHeight(190)
        right.addWidget(self.positions)

        sig_row = QtWidgets.QHBoxLayout()
        sig_title = QtWidgets.QLabel("SINYAL TERAKHIR PER SIMBOL / TF")
        sig_title.setObjectName("SectionTitle")
        sig_row.addWidget(sig_title)
        sig_row.addStretch(1)
        self.halt_label = QtWidgets.QLabel("")
        self.halt_label.setStyleSheet(f"color:{config.GOLD}; font-size:9px;")
        sig_row.addWidget(self.halt_label)
        right.addLayout(sig_row)
        self.signals = QtWidgets.QTableWidget()
        self.signals.setColumnCount(5)
        self.signals.setHorizontalHeaderLabels(["SIMBOL", "TF", "SINYAL", "SKOR", "KETERANGAN"])
        self.signals.verticalHeader().hide()
        self.signals.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.signals.setShowGrid(False)
        self.signals.verticalHeader().setDefaultSectionSize(24)
        self.signals.setFixedHeight(165)
        for i in range(5):
            self.signals.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        right.addWidget(self.signals)

        log_title = QtWidgets.QLabel("LOG EKSEKUSI")
        log_title.setObjectName("SectionTitle")
        right.addWidget(log_title)
        self.log = QtWidgets.QTextBrowser()
        self.log.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; border-radius:5px;"
            f"color:{config.MUTED}; font-size:9px; padding:4px;"
        )
        try:
            self.log.document().setMaximumBlockCount(2000)
        except Exception:
            pass
        right.addWidget(self.log, 1)
        root.addLayout(right, 1)
        self._refresh_mode()
        self.refresh_license_limits()

    # ------------------------------------------------------------- licensing
    def license_state(self) -> licensing.LicenseState:
        return licensing.current_state()

    def refresh_license_limits(self) -> None:
        """Clamp the widgets to the limits of the current edition.

        The auto-trade engine itself is untouched: this only changes what the
        UI lets the user pick (and the config is clamped again in
        :meth:`start_engine`).
        """
        state = licensing.current_state(force=True)
        lim = state.limits
        self._license_max_symbols = int(lim.get("max_symbols") or MAX_AUTO_SYMBOLS)

        fixed_risk = lim.get("risk_pct")
        if fixed_risk is not None:
            self.risk_spin.setRange(float(fixed_risk), float(fixed_risk))
            self.risk_spin.setValue(float(fixed_risk))
            self.risk_spin.setEnabled(False)
            self.risk_spin.setToolTip(f"Mode {state.edition}: risk/trade dikunci {fixed_risk:.2f}%.")
        else:
            self.risk_spin.setRange(0.1, float(lim.get("risk_max", 5.0)))
            self.risk_spin.setEnabled(True)
            self.risk_spin.setToolTip("")

        self.total_risk_spin.setRange(0.5, float(lim["total_risk_max"]))
        if self.total_risk_spin.value() > float(lim["total_risk_max"]):
            self.total_risk_spin.setValue(float(lim["total_risk_max"]))
        self.total_risk_spin.setEnabled(state.is_pro)

        self.max_dd_spin.setRange(1.0, float(lim["dd_max"]))
        if self.max_dd_spin.value() > float(lim["dd_max"]):
            self.max_dd_spin.setValue(float(lim["dd_max"]))
        self.max_dd_spin.setEnabled(state.is_pro)

        if lim.get("threshold") is not None:
            self.threshold_spin.setRange(float(lim["threshold"]), float(lim["threshold"]))
            self.threshold_spin.setValue(float(lim["threshold"]))
            self.threshold_spin.setEnabled(False)
            self.threshold_spin.setToolTip(f"Mode {state.edition}: skor minimum dikunci.")
        else:
            self.threshold_spin.setRange(3.0, 10.0)
            self.threshold_spin.setEnabled(True)
            self.threshold_spin.setToolTip("")

        if lim.get("tp_mode"):
            self.tp_mode.setCurrentIndex(0)
            self.tp_mode.setEnabled(False)
        else:
            self.tp_mode.setEnabled(True)

        if lim.get("rr") is not None:
            self.rr_spin.setRange(float(lim["rr"]), float(lim["rr"]))
            self.rr_spin.setValue(float(lim["rr"]))
            self.rr_spin.setEnabled(False)
            self.rr_spin.setToolTip(f"Mode {state.edition}: target RR dikunci {lim['rr']:.2f}R.")
        else:
            self.rr_spin.setRange(0.5, 5.0)
            self.rr_spin.setEnabled(self.tp_mode.currentIndex() == 0)
            self.rr_spin.setToolTip("")

        # Masa gratis terbatas / terkunci: semua pengaturan dikunci,
        # hanya pemilihan simbol/pair yang tetap bisa dipakai.
        locked = bool(lim.get("lock_settings")) and not state.is_pro
        for widget in (self.spread_spin, self.bars_spin, self.session_check,
                       self.tg_enable, self.tg_token, self.tg_chat, self.tg_test_btn):
            widget.setEnabled(not locked)
        if locked:
            self.total_risk_spin.setValue(float(lim["total_risk_max"]))
            self.max_dd_spin.setValue(float(lim["dd_max"]))

        if hasattr(self, "start_btn"):
            self.start_btn.setEnabled(not state.bot_locked)
            self.start_btn.setToolTip(
                "Bot terkunci · beli lisensi untuk mengaktifkan bot."
                if state.bot_locked else ""
            )

        if state.bot_locked:
            self.license_note.setText(
                "BOT TERKUNCI · masa gratis sudah habis. Beli lisensi untuk "
                f"mengaktifkan bot: {config.SELLER_PHONE_DISPLAY}. "
                "Chart, sinyal, dan backtest tetap bisa dipakai."
            )
            self.license_note.setStyleSheet(
                f"color:{config.BEAR}; font-size:9px; font-weight:700;"
            )
        elif state.is_pro:
            self.license_note.setText(state.title)
            self.license_note.setStyleSheet(f"color:{config.BULL}; font-size:9px; font-weight:700;")
        else:
            self.license_note.setText(
                "MASA GRATIS TERBATAS · semua pengaturan dikunci: maks 5 simbol · "
                "risk 0.1%/trade · total risk 4% · max DD 4% · skor minimum 10.0 · "
                "RR 1.5 · TP RR. Hanya pilihan simbol yang bisa diubah. "
                "Masukkan key untuk membuka semua."
            )
            self.license_note.setStyleSheet(f"color:{config.GOLD}; font-size:9px; font-weight:700;")
        self._update_symbol_count()

    @staticmethod
    def _spin(lo: float, hi: float, value: float, step: float, suffix: str) -> QtWidgets.QDoubleSpinBox:
        box = QtWidgets.QDoubleSpinBox()
        box.setRange(lo, hi)
        box.setSingleStep(step)
        box.setDecimals(2)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

    @staticmethod
    def _stat_card(label: str, value: str) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(1)
        title = QtWidgets.QLabel(label)
        title.setObjectName("SectionTitle")
        val = QtWidgets.QLabel(value)
        val.setStyleSheet("font-size:17px; font-weight:800; color:#ffffff;")
        lay.addWidget(title)
        lay.addWidget(val)
        card.value_label = val
        return card

    # ------------------------------------------------------------- symbol list
    def _saved_auto_symbols(self) -> list[str]:
        raw = self._settings.value("auto_symbols", "")
        if isinstance(raw, (list, tuple)):
            parts = raw
        else:
            parts = str(raw or "").split(",")
        return [str(s).strip().upper() for s in parts if str(s).strip()]

    def _known_symbols(self) -> list[str]:
        out: list[str] = []
        for source in (config.MAJOR_SYMBOLS, [self.symbol], self.provider.symbols() or [],
                       self._saved_auto_symbols()):
            for sym in source:
                sym = str(sym).strip().upper()
                if sym and sym not in out:
                    out.append(sym)
        return out

    def _populate_symbol_list(self) -> None:
        if not hasattr(self, "symbol_list"):
            return
        initial = self._saved_auto_symbols() or [self.symbol]
        initial = list(dict.fromkeys(initial))
        self.symbol_list.blockSignals(True)
        self.symbol_list.clear()
        for sym in self._known_symbols():
            item = QtWidgets.QListWidgetItem(sym)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if sym in initial else QtCore.Qt.CheckState.Unchecked
            )
            self.symbol_list.addItem(item)
        self.symbol_list.blockSignals(False)
        self._filter_symbol_list(self.symbol_search.text() if hasattr(self, "symbol_search") else "")
        self._update_symbol_count()

    def _filter_symbol_list(self, text: str) -> None:
        needle = str(text or "").strip().upper()
        for i in range(self.symbol_list.count()):
            item = self.symbol_list.item(i)
            item.setHidden(bool(needle) and needle not in item.text().upper())

    def _add_custom_symbol(self) -> None:
        sym = self.symbol_add.text().strip().upper()
        if not sym:
            return
        matches = self.symbol_list.findItems(sym, QtCore.Qt.MatchFlag.MatchExactly)
        item = matches[0] if matches else None
        if item is None:
            item = QtWidgets.QListWidgetItem(sym)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            self.symbol_list.addItem(item)
        item.setCheckState(QtCore.Qt.CheckState.Checked)
        self.symbol_list.setCurrentItem(item)
        self.symbol_list.scrollToItem(item)
        self.symbol_add.clear()
        try:
            self.provider.select_symbol(sym)
        except Exception:
            pass
        self._update_symbol_count()

    def _check_visible_symbols(self, checked: bool) -> None:
        state = QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
        for i in range(self.symbol_list.count()):
            item = self.symbol_list.item(i)
            if not item.isHidden():
                item.setCheckState(state)
        self._update_symbol_count()

    def selected_symbols(self) -> list[str]:
        if not hasattr(self, "symbol_list"):
            return [self.symbol]
        out = []
        for i in range(self.symbol_list.count()):
            item = self.symbol_list.item(i)
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                out.append(item.text().strip().upper())
        return list(dict.fromkeys(s for s in out if s))

    def _update_symbol_count(self) -> None:
        if not hasattr(self, "symbol_count"):
            return
        count = len(self.selected_symbols())
        max_symbols = int(getattr(self, "_license_max_symbols", MAX_AUTO_SYMBOLS))
        if count:
            self.symbol_count.setText(
                f"{count} simbol dipilih · maks {max_symbols} · total risk global"
            )
            color = config.BULL if count <= max_symbols else config.BEAR
            self.symbol_count.setStyleSheet(f"color:{color}; font-size:9px;")
        else:
            self.symbol_count.setText("Belum ada simbol dipilih.")
            self.symbol_count.setStyleSheet(f"color:{config.GOLD}; font-size:9px;")

    def _save_symbol_settings(self) -> None:
        self._settings.setValue("auto_symbols", ",".join(self.selected_symbols()))

    def is_symbol_active(self, symbol: str) -> bool:
        if not hasattr(self, "symbol_list"):
            return False
        matches = self.symbol_list.findItems(symbol.strip().upper(), QtCore.Qt.MatchFlag.MatchExactly)
        if matches:
            return matches[0].checkState() == QtCore.Qt.CheckState.Checked
        return False

    def set_symbol_active(self, symbol: str, active: bool) -> None:
        if not hasattr(self, "symbol_list"):
            return
        sym = symbol.strip().upper()
        matches = self.symbol_list.findItems(sym, QtCore.Qt.MatchFlag.MatchExactly)
        if not matches:
            item = QtWidgets.QListWidgetItem(sym)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            self.symbol_list.addItem(item)
            matches = [item]
        state = QtCore.Qt.CheckState.Checked if active else QtCore.Qt.CheckState.Unchecked
        matches[0].setCheckState(state)
        self._update_symbol_count()
        self._save_symbol_settings()

    def _set_symbol_picker_enabled(self, enabled: bool) -> None:
        for widget in (self.symbol_search, self.symbol_list, self.symbol_add,
                       self.symbol_add_btn, self.symbol_all_btn, self.symbol_none_btn):
            widget.setEnabled(enabled)
        # The running engine keeps the magic it was started with.
        if hasattr(self, "magic_spin"):
            self.magic_spin.setEnabled(enabled)

    # ------------------------------------------------------------- symbol list
    def _tp_mode_changed(self) -> None:
        if not licensing.current_state().is_pro:
            self.rr_spin.setEnabled(False)
            return
        self.rr_spin.setEnabled(self.tp_mode.currentIndex() == 0)

    def test_telegram(self) -> None:
        token = self.tg_token.text().strip()
        chat = self.tg_chat.text().strip()
        if not token or not chat:
            QtWidgets.QMessageBox.warning(self, "Telegram", "Isi bot token dan chat ID dulu.")
            return
        self._save_telegram_settings()
        self.tg_status.setText("Mengirim test…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        ok, message = TelegramNotifier.send_now(
            token, chat,
            f"✅ ICT Terminal Pro — test notifikasi\n"
            f"Multi-symbol · chart fokus {self.symbol} · {datetime.now():%d %b %Y %H:%M:%S}",
        )
        QtWidgets.QApplication.restoreOverrideCursor()
        if ok:
            self.tg_status.setText("Test terkirim.")
            QtWidgets.QMessageBox.information(self, "Telegram", "Test notifikasi berhasil dikirim.")
        else:
            self.tg_status.setText(f"Gagal: {message}")
            QtWidgets.QMessageBox.warning(self, "Telegram", f"Gagal mengirim:\n{message}")

    def _save_telegram_settings(self) -> None:
        self._settings.setValue("tg_enabled", self.tg_enable.isChecked())
        self._settings.setValue("tg_token", self.tg_token.text().strip())
        self._settings.setValue("tg_chat", self.tg_chat.text().strip())

    # --------------------------------------------------------------- helpers
    def set_symbol(self, symbol: str) -> None:
        """Chart focus only; the multi-symbol engine keeps its own selection."""
        self.symbol = symbol.strip().upper() or self.symbol
        self.symbol_label.setText(f"Chart fokus: {self.symbol}")
        self._refresh_mode()
        if hasattr(self, "symbol_list"):
            matches = self.symbol_list.findItems(self.symbol, QtCore.Qt.MatchFlag.MatchExactly)
            if not matches:
                item = QtWidgets.QListWidgetItem(self.symbol)
                item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                self.symbol_list.addItem(item)
            if not self.selected_symbols():
                matches = self.symbol_list.findItems(
                    self.symbol, QtCore.Qt.MatchFlag.MatchExactly
                )
                if matches:
                    matches[0].setCheckState(QtCore.Qt.CheckState.Checked)
            self._update_symbol_count()

    def _refresh_mode(self) -> None:
        acc = self.provider.account or {}
        if not acc:
            self.mode_label.setText("Akun: MT5 tidak terhubung")
            return
        mode = "DEMO" if int(acc.get("trade_mode", 0)) == 0 else "REAL"
        self.mode_label.setText(
            f"Akun: {mode} · {acc.get('login', '—')} · {acc.get('server', '—')} · "
            f"{acc.get('currency', 'USD')} {acc.get('equity', 0):,.2f}"
        )

    def _log(self, text: str) -> None:
        self.log.append(f"<span style='color:{config.TEXT}'>{html.escape(text)}</span>")

    def _update_state(self, state: dict) -> None:
        self.card_equity.value_label.setText(f"${state.get('equity', 0):,.2f}")
        self.card_risk.value_label.setText(f"{state.get('open_risk_pct', 0):.2f}%")
        dd = state.get("drawdown", 0)
        self.card_dd.value_label.setText(f"{dd:.2f}%")
        self.card_dd.value_label.setStyleSheet(
            f"font-size:17px; font-weight:800; color:{config.BEAR if dd >= 3 else '#ffffff'};"
        )
        if not state.get("running"):
            status, color = "OFF", config.MUTED
        elif state.get("halted"):
            status, color = "HALTED", config.GOLD
        elif not state.get("trade_ok"):
            status, color = "WAIT MT5", config.GOLD
        else:
            status, color = "RUNNING", config.BULL
        self.card_status.value_label.setText(status)
        self.card_status.value_label.setStyleSheet(f"font-size:17px; font-weight:800; color:{color};")
        self.account_info.setText(
            f"{state.get('mode', '—')} · {state.get('login', '')} · {state.get('server', '')} · "
            f"{state.get('symbol_count', 0)} simbol · "
            f"open risk ${state.get('open_risk', 0):,.2f} · posisi {state.get('positions', 0)}"
        )
        self.halt_label.setText(state.get("halt_reason", ""))
        self.reset_btn.setEnabled(bool(state.get("halted")))

    def _update_positions(self, rows: list) -> None:
        self.positions.setRowCount(len(rows))
        for r, row in enumerate(rows):
            symbol = str(row.get("symbol", self.symbol))
            digits = self.provider.meta(symbol).digits
            values = [
                symbol, row["tf"], str(row["ticket"]), row["dir"], f"{row['volume']:.2f}",
                f"{row['price']:,.{digits}f}", f"{row['sl']:,.{digits}f}",
                f"{row['tp']:,.{digits}f}", f"{row['profit']:+,.2f}",
            ]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if c == 3:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(
                        config.BULL if row["dir"] == "BUY" else config.BEAR
                    )))
                elif c == 8:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(
                        config.BULL if row["profit"] >= 0 else config.BEAR
                    )))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.TEXT)))
                self.positions.setItem(r, c, item)

    def _update_signal(self, symbol: str, tf: str, data: dict) -> None:
        key = (symbol, tf)
        self.signal_rows[key] = data
        rows = sorted(
            self.signal_rows,
            key=lambda x: (
                x[0],
                config.TF_ORDER.index(x[1]) if x[1] in config.TF_ORDER else 99,
            ),
        )
        self.signals.setRowCount(len(rows))
        for r, key in enumerate(rows):
            d = self.signal_rows[key]
            signal = str(d.get("signal", "—"))
            color = config.BULL if signal in ("BUY", "LONG") else (
                config.BEAR if signal in ("SELL", "SHORT") else config.MUTED
            )
            values = [
                key[0], key[1], signal,
                f"{d.get('score', 0):+.1f}" if isinstance(d.get("score"), (int, float)) else "—",
                str(d.get("reason", "")),
            ]
            for c, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                item.setForeground(QtGui.QBrush(QtGui.QColor(color if c == 2 else config.MUTED)))
                self.signals.setItem(r, c, item)

    # --------------------------------------------------------------- controls
    def start_engine(self) -> None:
        lic_state = licensing.current_state()
        if lic_state.bot_locked:
            QtWidgets.QMessageBox.warning(
                self, "Bot Terkunci",
                "Masa gratis 30 hari sudah habis.\n\n"
                "Bot auto trade dinonaktifkan. Chart, sinyal, dan backtest "
                "tetap bisa dipakai seperti biasa.\n\n"
                "Beli lisensi untuk mengaktifkan bot:\n"
                f"{config.SELLER_PHONE_DISPLAY}\n\n"
                "Setelah menerima key: klik tombol LISENSI di kanan atas, "
                "tempel key, lalu AKTIFKAN."
            )
            return
        if self.engine is not None and self.engine.isRunning():
            return
        tfs = [tf for tf, box in self.tf_boxes.items() if box.isChecked()]
        if not tfs:
            QtWidgets.QMessageBox.warning(self, "Auto Trade", "Pilih minimal satu timeframe.")
            return
        symbols = self.selected_symbols()
        if not symbols:
            QtWidgets.QMessageBox.warning(
                self, "Auto Trade", "Centang minimal satu simbol yang boleh ditradingkan."
            )
            return
        if len(symbols) > MAX_AUTO_SYMBOLS:
            QtWidgets.QMessageBox.warning(
                self, "Auto Trade",
                f"Maksimal {MAX_AUTO_SYMBOLS} simbol untuk satu engine.\n"
                f"Kamu memilih {len(symbols)} simbol. Kurangi dulu agar scan tetap cepat."
            )
            return
        lic_state = licensing.current_state()
        lic_max = int(lic_state.limits.get("max_symbols") or 0)
        if lic_max and len(symbols) > lic_max:
            QtWidgets.QMessageBox.warning(
                self, "Lisensi",
                f"Mode {lic_state.edition} hanya boleh {lic_max} simbol.\n"
                f"Kamu memilih {len(symbols)} simbol.\n\n"
                "Masukkan key aktivasi lewat tombol LISENSI di header untuk "
                f"membuka hingga {MAX_AUTO_SYMBOLS} simbol."
            )
            return
        if not self.confirm_check.isChecked():
            QtWidgets.QMessageBox.warning(
                self, "Konfirmasi",
                "Centang konfirmasi bahwa kamu paham order akan dikirim ke akun MT5."
            )
            return
        if not self.provider.ensure_connected():
            QtWidgets.QMessageBox.warning(self, "MT5", "MetaTrader 5 tidak terhubung.")
            return
        invalid = [sym for sym in symbols if not self.provider.select_symbol(sym)]
        if invalid:
            QtWidgets.QMessageBox.warning(
                self, "Simbol",
                "Simbol berikut tidak ditemukan / tidak bisa dipilih di MT5:\n"
                + ", ".join(invalid),
            )
            return
        term = self.provider.terminal or {}
        acc_info = self.provider.account or {}
        try:
            if config.MT5_AVAILABLE and config.mt5 is not None:
                live_term = config.mt5.terminal_info()
                live_acc = config.mt5.account_info()
                if live_term is not None:
                    term = live_term._asdict()
                if live_acc is not None:
                    acc_info = live_acc._asdict()
        except Exception:
            pass
        if not term.get("trade_allowed") or not acc_info.get("trade_allowed"):
            QtWidgets.QMessageBox.warning(
                self, "Auto Trading",
                "AutoTrading / trade_allowed di MT5 masih OFF.\n"
                "Aktifkan tombol Algo Trading di MetaTrader 5 lalu coba lagi."
            )
            return
        if self.risk_spin.value() > self.total_risk_spin.value():
            QtWidgets.QMessageBox.warning(self, "Risk", "Risk/trade tidak boleh melebihi max total risk.")
            return
        tg_token = self.tg_token.text().strip()
        tg_chat = self.tg_chat.text().strip()
        if self.tg_enable.isChecked() and (not tg_token or not tg_chat):
            QtWidgets.QMessageBox.warning(
                self, "Telegram", "Notifikasi Telegram aktif tapi token/chat ID masih kosong."
            )
            return
        self._save_telegram_settings()
        self._save_symbol_settings()
        magic_base = app_settings.set_magic_base(self.magic_spin.value(), remember=True)
        acc = self.provider.account or {}
        mode = "DEMO" if int(acc.get("trade_mode", 0)) == 0 else "REAL"
        if mode == "REAL":
            text, ok = QtWidgets.QInputDialog.getText(
                self, "KONFIRMASI LIVE",
                f"Akun REAL {acc.get('login')} · {acc.get('server')}.\n"
                f"Simbol: {', '.join(symbols)}\n"
                f"Magic number: {magic_base}\n"
                "Ketik LIVE untuk mengaktifkan eksekusi order:",
            )
            if not ok or text.strip().upper() != "LIVE":
                return
        else:
            reply = QtWidgets.QMessageBox.question(
                self, "Mulai Auto Trade Multi-Symbol",
                f"Kirim order otomatis ke akun DEMO {acc.get('login')}?\n\n"
                f"Simbol ({len(symbols)}): {', '.join(symbols)}\n"
                f"TF: {', '.join(tfs)}\n"
                f"Risk/trade: {self.risk_spin.value():.2f}%\n"
                f"Max total risk (semua simbol): {self.total_risk_spin.value():.2f}%\n"
                f"Max DD global: {self.max_dd_spin.value():.2f}%\n"
                f"Magic number: {magic_base}",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        cfg = AutoTradeConfig(
            symbols=symbols,
            timeframes=tfs,
            risk_pct=self.risk_spin.value(),
            max_total_risk_pct=self.total_risk_spin.value(),
            max_drawdown_pct=self.max_dd_spin.value(),
            threshold=self.threshold_spin.value(),
            tp_mode="STRUCTURE" if self.tp_mode.currentIndex() == 1 else "RR",
            rr=self.rr_spin.value(),
            max_spread_points=self.spread_spin.value(),
            max_bars=self.bars_spin.value(),
            session_filter=self.session_check.isChecked(),
            magic_base=magic_base,
            execute=True,
            telegram_enabled=self.tg_enable.isChecked(),
            telegram_token=tg_token,
            telegram_chat_id=tg_chat,
        )
        cfg, lic_notes = licensing.apply_autotrade_limits(cfg, lic_state)
        self.engine = AutoTrader(self.provider, cfg, self)
        self.engine.log_message.connect(self._log)
        self.engine.state_changed.connect(self._update_state)
        self.engine.positions_changed.connect(self._update_positions)
        self.engine.signal_changed.connect(self._update_signal)
        self.engine.trade_sent.connect(lambda symbol, tf: self._log(f"{symbol} {tf}: order terkirim."))
        self.engine.finished.connect(self._engine_finished)
        self.signal_rows.clear()
        self.signals.setRowCount(0)
        self.engine.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        self._set_symbol_picker_enabled(False)
        self._log(
            f"Engine dimulai · {len(symbols)} simbol: {', '.join(symbols)} "
            f"· TF {', '.join(tfs)} · magic {magic_base} · risk global · eksekusi ON"
        )
        for note in lic_notes:
            self._log(f"<span style='color:{config.GOLD}'>Lisensi: {html.escape(note)}</span>")

    def stop_engine(self) -> None:
        if self.engine is None:
            return
        self.engine.request_stop()
        if not self.engine.wait(10000):
            self._log("Engine masih menyelesaikan evaluasi; coba STOP sekali lagi.")
            return
        self.engine = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self._set_symbol_picker_enabled(True)
        self._save_symbol_settings()
        self._log("Engine dihentikan. Posisi yang sudah terbuka tetap ada di MT5.")

    def stop_all(self) -> None:
        if self.engine is None:
            QtWidgets.QMessageBox.information(self, "STOP ALL", "Engine belum berjalan.")
            return
        engine = self.engine
        engine.request_stop()
        if not engine.wait(10000):
            self._log("Engine masih berjalan; STOP ALL dibatalkan. Coba lagi.")
            return
        count = engine.stop_all()
        self.engine = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self._set_symbol_picker_enabled(True)
        self._log(f"STOP ALL: {count} posisi ditutup. Engine dihentikan.")

    def reset_halt(self) -> None:
        if self.engine is not None:
            self.engine.reset_halt()
        else:
            self._log("Engine belum berjalan.")

    def _engine_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._set_symbol_picker_enabled(True)

    def shutdown(self) -> None:
        try:
            self._save_symbol_settings()
        except Exception:
            pass
        if self.engine is not None:
            self.engine.request_stop()
            self.engine.wait(4000)
