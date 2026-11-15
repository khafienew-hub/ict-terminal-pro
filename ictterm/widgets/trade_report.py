"""Daily / range trade report from Auto Trade MT5 history."""
from __future__ import annotations

import calendar
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config
from .. import settings as app_settings
from ..history import HistoryTrade, from_mt5_history
from .panels import Card


class ReportStat(QtWidgets.QFrame):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(1)
        title = QtWidgets.QLabel(label.upper())
        title.setObjectName("SectionTitle")
        self.value = QtWidgets.QLabel("—")
        self.value.setStyleSheet("font-size:17px; font-weight:800; color:#ffffff;")
        lay.addWidget(title)
        lay.addWidget(self.value)

    def set(self, text: str, color: str | None = None) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"font-size:17px; font-weight:800; color:{color or '#ffffff'};")


class TradeCalendar(QtWidgets.QFrame):
    """Monthly realized P/L calendar (by exit date)."""
    date_selected = QtCore.pyqtSignal(QtCore.QDate)
    month_changed = QtCore.pyqtSignal(int, int)

    WEEKDAYS = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    MONTHS = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
              "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CalendarCard")
        self.setStyleSheet(
            f"QFrame#CalendarCard {{ background:{config.PANEL}; border:1px solid {config.BORDER};"
            "border-radius:7px; }"
        )
        self.setFixedSize(455, 500)
        self._year = QtCore.QDate.currentDate().year()
        self._month = QtCore.QDate.currentDate().month()
        self._selected: date | None = None
        self._days: dict[date, dict] = {}
        self._month_net = 0.0
        self._month_trades = 0
        self.buttons: dict[date, QtWidgets.QPushButton] = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 9)
        root.setSpacing(5)
        head = QtWidgets.QHBoxLayout()
        self.prev_btn = QtWidgets.QPushButton("‹")
        self.prev_btn.setFixedWidth(30)
        self.next_btn = QtWidgets.QPushButton("›")
        self.next_btn.setFixedWidth(30)
        self.month_label = QtWidgets.QLabel("")
        self.month_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.month_label.setStyleSheet("font-size:13px; font-weight:800; color:#ffffff;")
        today_btn = QtWidgets.QPushButton("Bulan ini")
        today_btn.setFixedWidth(80)
        head.addWidget(self.prev_btn)
        head.addWidget(self.month_label, 1)
        head.addWidget(self.next_btn)
        head.addWidget(today_btn)
        root.addLayout(head)

        week = QtWidgets.QHBoxLayout()
        week.setSpacing(3)
        for name in self.WEEKDAYS:
            label = QtWidgets.QLabel(name)
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"color:{config.MUTED}; font-size:8px; font-weight:700;")
            week.addWidget(label, 1)
        root.addLayout(week)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(3)
        for col in range(7):
            self.grid.setColumnStretch(col, 1)
        root.addLayout(self.grid)
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        root.addWidget(self.summary)
        note = QtWidgets.QLabel("Kalender berdasarkan tanggal exit (realized P/L USD). Klik tanggal untuk detail.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{config.MUTED}; font-size:8px;")
        root.addWidget(note)
        self.prev_btn.clicked.connect(lambda: self._shift(-1))
        self.next_btn.clicked.connect(lambda: self._shift(1))
        today_btn.clicked.connect(self._this_month)
        self.set_month(self._year, self._month)

    def _this_month(self) -> None:
        today = QtCore.QDate.currentDate()
        self.set_month(today.year(), today.month())
        self.month_changed.emit(self._year, self._month)

    def _shift(self, delta: int) -> None:
        month = self._month + delta
        year = self._year
        if month < 1:
            month = 12
            year -= 1
        elif month > 12:
            month = 1
            year += 1
        self.set_month(year, month)
        self.month_changed.emit(self._year, self._month)

    def set_month(self, year: int, month: int) -> None:
        self._year, self._month = year, month
        self._selected = None
        self._days = {}
        self.month_label.setText(f"{self.MONTHS[month]} {year}")
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.buttons.clear()
        weeks = calendar.monthcalendar(year, month)
        for row, week in enumerate(weeks[:6]):
            for col in range(7):
                day = week[col]
                if day == 0:
                    continue
                btn = QtWidgets.QPushButton(str(day))
                btn.setMinimumHeight(54)
                btn.setMaximumHeight(62)
                btn.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                  QtWidgets.QSizePolicy.Policy.Expanding)
                btn.setStyleSheet(
                    f"QPushButton {{ background:{config.PANEL_ALT}; border:1px solid {config.BORDER};"
                    f"border-radius:5px; color:{config.MUTED}; font-size:9px; padding:2px; text-align:center; }}"
                    "QPushButton:hover { border-color:#4f9cf9; }"
                )
                d = date(year, month, day)
                btn.clicked.connect(lambda _checked=False, dd=d: self.date_selected.emit(
                    QtCore.QDate(dd.year, dd.month, dd.day)
                ))
                self.grid.addWidget(btn, row, col)
                self.buttons[d] = btn

    def set_selected(self, selected: date | None) -> None:
        self._selected = selected
        self.set_data(self._days, self._month_net, self._month_trades)

    def set_data(self, days: dict[date, dict], month_net: float, month_trades: int) -> None:
        self._days = days
        self._month_net = month_net
        self._month_trades = month_trades
        for d, btn in self.buttons.items():
            selected = d == self._selected
            stats = days.get(d)
            if not stats or stats["trades"] == 0:
                border = "#ffffff" if selected else config.BORDER
                btn.setText(str(d.day))
                btn.setStyleSheet(
                    f"QPushButton {{ background:{config.PANEL_ALT}; border:1px solid {border};"
                    f"border-radius:5px; color:{config.MUTED}; font-size:9px; padding:2px; text-align:center; }}"
                    "QPushButton:hover { border-color:#4f9cf9; }"
                )
                continue
            net = stats["net"]
            color = config.BULL if net >= 0 else config.BEAR
            fill = "rgba(38,166,154,0.16)" if net >= 0 else "rgba(239,83,80,0.16)"
            border = "#ffffff" if selected else f"{color}88"
            btn.setText(f"{d.day}\n{net:+,.0f}\n{stats['trades']} tr")
            btn.setStyleSheet(
                f"QPushButton {{ background:{fill}; border:1px solid {border};"
                f"border-radius:5px; color:{color}; font-size:8px; font-weight:700;"
                "padding:2px; text-align:center; }}"
                "QPushButton:hover { border-color:#ffffff; }"
            )
        self.summary.setText(
            f"Bulan ini: {month_trades} trade · net "
            f"{month_net:+,.2f} · hijau profit / merah loss"
        )


class PairViabilityAnalysis:
    """Quantitative performance and viability analysis for a trading pair."""
    WEEKDAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

    def __init__(self, symbol: str, trades: list[HistoryTrade], by_exit: bool = True):
        self.symbol = symbol.upper()
        self.trades = trades
        self.total = len(trades)
        self.wins = sum(1 for t in trades if t.profit > 0)
        self.losses = sum(1 for t in trades if t.profit < 0)
        self.be = sum(1 for t in trades if t.profit == 0)
        self.win_rate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) else 0.0
        self.gross_profit = sum(t.profit for t in trades if t.profit > 0)
        self.gross_loss = abs(sum(t.profit for t in trades if t.profit < 0))
        self.net = self.gross_profit - self.gross_loss
        self.profit_factor = (self.gross_profit / self.gross_loss) if self.gross_loss > 0 else (99.0 if self.gross_profit > 0 else 0.0)
        rr_vals = [t.r for t in trades if abs(t.r) > 1e-9]
        self.avg_r = (sum(rr_vals) / len(rr_vals)) if rr_vals else 0.0

        # Day of week analysis (0=Senin, ..., 6=Minggu)
        self.dow_stats: dict[int, dict] = {
            i: {"orders": 0, "wins": 0, "losses": 0, "be": 0, "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0, "win_rate": 0.0}
            for i in range(7)
        }
        # Daily date analysis (date -> dict)
        self.daily_stats: dict[date, dict] = {}

        for t in trades:
            ts = TradeReportTab._local(t.exit_time if by_exit else t.entry_time)
            d = ts.date()
            dow = d.weekday()

            dw = self.dow_stats[dow]
            dw["orders"] += 1
            if t.profit > 0:
                dw["wins"] += 1
                dw["gross_profit"] += t.profit
            elif t.profit < 0:
                dw["losses"] += 1
                dw["gross_loss"] += abs(t.profit)
            else:
                dw["be"] += 1
            dw["net"] += t.profit

            if d not in self.daily_stats:
                self.daily_stats[d] = {
                    "date": d, "orders": 0, "wins": 0, "losses": 0, "be": 0,
                    "gross_profit": 0.0, "gross_loss": 0.0, "net": 0.0, "win_rate": 0.0
                }
            ds = self.daily_stats[d]
            ds["orders"] += 1
            if t.profit > 0:
                ds["wins"] += 1
                ds["gross_profit"] += t.profit
            elif t.profit < 0:
                ds["losses"] += 1
                ds["gross_loss"] += abs(t.profit)
            else:
                ds["be"] += 1
            ds["net"] += t.profit

        for dow, dw in self.dow_stats.items():
            dw["win_rate"] = (dw["wins"] / (dw["wins"] + dw["losses"]) * 100) if (dw["wins"] + dw["losses"]) else 0.0

        for d, ds in self.daily_stats.items():
            ds["win_rate"] = (ds["wins"] / (ds["wins"] + ds["losses"]) * 100) if (ds["wins"] + ds["losses"]) else 0.0

        # Best / Worst day among weekdays (0..4) with orders
        active_dows = [dow for dow in range(5) if self.dow_stats[dow]["orders"] > 0]
        if active_dows:
            best_dow = max(active_dows, key=lambda x: (self.dow_stats[x]["net"], self.dow_stats[x]["win_rate"]))
            worst_dow = min(active_dows, key=lambda x: (self.dow_stats[x]["net"], self.dow_stats[x]["win_rate"]))
            self.best_day_str = f"{self.WEEKDAYS_ID[best_dow]} ({self.dow_stats[best_dow]['net']:+,.0f})"
            self.worst_day_str = f"{self.WEEKDAYS_ID[worst_dow]} ({self.dow_stats[worst_dow]['net']:+,.0f})"
            self.best_dow = best_dow
            self.worst_dow = worst_dow
        else:
            self.best_day_str = "—"
            self.worst_day_str = "—"
            self.best_dow = None
            self.worst_dow = None

        self.status, self.status_color, self.recommendation, self.detailed_verdict = self._evaluate_viability()

    def get_dow_recommendation(self, dow_idx: int) -> tuple[str, str, str]:
        """Returns (status_label, color, advice) for a day of week."""
        info = self.dow_stats[dow_idx]
        orders = info["orders"]
        net = info["net"]
        wr = info["win_rate"]
        if orders == 0:
            return ("TIDAK ADA DATA", config.MUTED, "Belum ada riwayat transaksi pada hari ini.")
        if orders >= 2 and net > 0 and wr >= 50.0:
            return ("LAYAK (PROFIT)", config.BULL, "Hari konsisten menguntungkan. Pertahankan auto trade di hari ini.")
        if net > 0:
            return ("LAYAK (PROFIT)", config.BULL, "Net profit positif. Layak ditradingkan.")
        if net < 0 and orders >= 2:
            return ("HINDARI / NONAKTIF", config.BEAR, f"Hari rawan rugi (Net {net:+,.1f}, WR {wr:.0f}%). Disarankan nonaktifkan di hari ini.")
        if net < 0:
            return ("EVALUASI (LOSS)", config.GOLD, "Hasil rugi namun baru 1 order. Pantau ketat.")
        return ("EVALUASI (IMPAS)", config.GOLD, "Hasil impas / break-even. Evaluasi setup order.")

    def _evaluate_viability(self) -> tuple[str, str, str, str]:
        if self.total == 0:
            return (
                "BELUM ADA DATA",
                config.MUTED,
                "Belum ada data transaksi.",
                f"Pair {self.symbol} belum memiliki riwayat order tertutup pada filter tanggal yang dipilih.",
            )

        if self.total < 3:
            if self.net >= 0:
                status = "EVALUASI (PROFIT)"
                color = config.GOLD
                recom = "Sample data masih sedikit (< 3 order). Pantau terus sebelum menambah lot."
            else:
                status = "EVALUASI (LOSS)"
                color = config.GOLD
                recom = "Mengalami loss awal, namun sample data masih sedikit (< 3 order). Evaluasi setup."
        else:
            if self.net > 0 and self.win_rate >= 50.0:
                status = "LAYAK PROFIT"
                color = config.BULL
                recom = "Performa SANGAT LAYAK! Pair konsisten profit dengan win rate tinggi. Pertahankan aktif di Auto Trade."
            elif self.net > 0 and (self.avg_r >= 0.8 or self.profit_factor >= 1.25):
                status = "LAYAK PROFIT (HIGH RR)"
                color = config.BULL
                recom = "LAYAK DITRADINGKAN. Profit positif didukung Risk-Reward (RR) yang sehat. Pertahankan aktif."
            elif self.net <= 0:
                if self.net < 0 and (self.win_rate < 45.0 or self.profit_factor < 0.8 or self.total >= 4):
                    status = "HARUS NONAKTIFKAN"
                    color = config.BEAR
                    recom = "KONSISTEN LOSS / MERUGIKAN! Win rate rendah dan Net P/L negatif. SEGERA NONAKTIFKAN dari Auto Trade!"
                else:
                    status = "EVALUASI (LOSS)"
                    color = config.GOLD
                    recom = "Hasil negatif tipis atau impas. Evaluasi filter sesi dan TF sebelum menonaktifkan."
            else:
                status = "EVALUASI"
                color = config.GOLD
                recom = "Hasil di sekitar break-even. Pantau perkembangan lebih lanjut."

        # Detailed text verdict
        lines = []
        lines.append(
            f"ANALISA KELAYAKAN {self.symbol}:\n"
            f"• Statistik: {self.total} order closed · {self.wins} Win / {self.losses} Loss ({self.be} BE) · "
            f"Win Rate: {self.win_rate:.1f}% · Net P/L: {self.net:+,.2f} USD · Avg R: {self.avg_r:+.2f}R · Profit Factor: {self.profit_factor:.2f}"
        )
        if self.best_dow is not None and self.worst_dow is not None:
            best_info = self.dow_stats[self.best_dow]
            worst_info = self.dow_stats[self.worst_dow]
            lines.append(
                f"• Hari Terbaik: {self.WEEKDAYS_ID[self.best_dow]} (Net {best_info['net']:+,.2f} USD, WR {best_info['win_rate']:.0f}%, {best_info['orders']} order)"
            )
            if self.worst_dow != self.best_dow:
                lines.append(
                    f"• Hari Terburuk: {self.WEEKDAYS_ID[self.worst_dow]} (Net {worst_info['net']:+,.2f} USD, WR {worst_info['win_rate']:.0f}%, {worst_info['orders']} order)"
                )

        bad_days = [
            f"{self.WEEKDAYS_ID[i]} ({self.dow_stats[i]['net']:+,.1f})"
            for i in range(5)
            if self.dow_stats[i]["orders"] >= 2 and self.dow_stats[i]["net"] < 0
        ]
        if bad_days:
            lines.append(f"• [PERINGATAN] Terdeteksi performa buruk di hari {', '.join(bad_days)}. Disarankan nonaktifkan auto trade khusus di hari tersebut.")

        lines.append(f"• Rekomendasi Tindakan: {recom}")
        verdict = "\n".join(lines)
        return (status, color, recom, verdict)


class TradeReportTab(QtWidgets.QWidget):
    def __init__(self, provider, auto_trade=None, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.auto_trade = auto_trade
        self.symbol = config.DEFAULT_SYMBOL
        self.trades: list[HistoryTrade] = []
        self._pair_analyses: dict[str, PairViabilityAnalysis] = {}
        self._selected_pair: str | None = None
        self._build()

    def set_auto_trade(self, auto_trade) -> None:
        self.auto_trade = auto_trade

    def is_symbol_active(self, symbol: str) -> bool:
        sym = symbol.strip().upper()
        if self.auto_trade is not None:
            return self.auto_trade.is_symbol_active(sym)
        settings = QtCore.QSettings("ICT Terminal", "ICT Terminal Pro")
        saved = str(settings.value("auto_symbols", "")).split(",")
        return sym in [s.strip().upper() for s in saved if s.strip()]

    def set_symbol_active(self, symbol: str, active: bool) -> None:
        sym = symbol.strip().upper()
        if self.auto_trade is not None:
            self.auto_trade.set_symbol_active(sym, active)
        else:
            settings = QtCore.QSettings("ICT Terminal", "ICT Terminal Pro")
            saved = [s.strip().upper() for s in str(settings.value("auto_symbols", "")).split(",") if s.strip()]
            if active and sym not in saved:
                saved.append(sym)
            elif not active and sym in saved:
                saved.remove(sym)
            settings.setValue("auto_symbols", ",".join(saved))

    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(9)

        header = Card("TRADE REPORT · AUTO TRADE MT5 MULTI-SYMBOL")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.symbol_filter = QtWidgets.QComboBox()
        self.symbol_filter.setFixedWidth(165)
        self.symbol_filter.setMaxVisibleItems(25)
        self.symbol_filter.addItem("Semua Simbol")
        self._populate_symbol_filter()
        self.symbol_filter.currentIndexChanged.connect(self._symbol_filter_changed)
        self.date_from = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addDays(-7))
        self.date_to = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        for widget in (self.date_from, self.date_to):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("dd MMM yyyy")
            widget.setFixedWidth(120)
        self.basis = QtWidgets.QComboBox()
        self.basis.addItems(["Tanggal entry", "Tanggal exit"])
        self.basis.setFixedWidth(130)
        self.load_btn = QtWidgets.QPushButton("Tampilkan")
        self.load_btn.setObjectName("PrimaryButton")
        self.load_btn.clicked.connect(self.load_data)
        today_btn = QtWidgets.QPushButton("Hari ini")
        today_btn.clicked.connect(self._today)
        week_btn = QtWidgets.QPushButton("7 hari")
        week_btn.clicked.connect(lambda: self._range(7))
        month_btn = QtWidgets.QPushButton("30 hari")
        month_btn.clicked.connect(lambda: self._range(30))
        self.export_btn = QtWidgets.QPushButton("Export XLSX")
        self.export_btn.setToolTip("Export ringkasan, trade, rekap harian, per simbol, dan kalender ke Excel")
        self.export_btn.clicked.connect(lambda: self.export_xlsx())
        row.addWidget(QtWidgets.QLabel("Simbol"))
        row.addWidget(self.symbol_filter)
        row.addSpacing(8)
        row.addWidget(QtWidgets.QLabel("Dari"))
        row.addWidget(self.date_from)
        row.addWidget(QtWidgets.QLabel("Sampai"))
        row.addWidget(self.date_to)
        row.addWidget(self.basis)
        row.addWidget(self.load_btn)
        row.addWidget(today_btn)
        row.addWidget(week_btn)
        row.addWidget(month_btn)
        row.addWidget(self.export_btn)
        row.addStretch(1)
        header.body.addLayout(row)
        self.info = QtWidgets.QLabel("Pilih tanggal lalu klik Tampilkan. Waktu ditampilkan dalam waktu lokal.")
        self.info.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        header.body.addWidget(self.info)
        root.addWidget(header)

        cards = QtWidgets.QHBoxLayout()
        cards.setSpacing(8)
        self.card_orders = ReportStat("Orders closed")
        self.card_wins = ReportStat("Profit")
        self.card_losses = ReportStat("Loss")
        self.card_winrate = ReportStat("Win rate")
        self.card_net = ReportStat("Net P/L")
        self.card_gross = ReportStat("Gross profit / loss")
        self.card_avg = ReportStat("Avg R")
        for card in (self.card_orders, self.card_wins, self.card_losses,
                     self.card_winrate, self.card_net, self.card_gross, self.card_avg):
            cards.addWidget(card)
        root.addLayout(cards)

        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(
            ["TICKET", "SIMBOL", "TF", "ARAH", "LOT", "ENTRY TIME", "EXIT TIME",
             "ENTRY", "EXIT", "PROFIT", "R"]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setDefaultSectionSize(25)
        for i in range(11):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )

        self.calendar = TradeCalendar()
        self.calendar.date_selected.connect(self._calendar_day)
        self.calendar.month_changed.connect(self._load_month)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(9)
        body.addWidget(self.calendar, 0, QtCore.Qt.AlignmentFlag.AlignTop)

        # Tabbed container for order list and pair viability analysis
        self.report_tabs = QtWidgets.QTabWidget()
        self.report_tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {config.BORDER}; background:{config.PANEL}; border-radius:6px; }}"
            f"QTabBar::tab {{ background:{config.PANEL_ALT}; color:{config.MUTED}; padding:6px 14px; font-weight:700; "
            f"border:1px solid {config.BORDER}; border-bottom:none; border-top-left-radius:4px; border-top-right-radius:4px; font-size:11px; }}"
            f"QTabBar::tab:selected {{ background:{config.PANEL}; color:#ffffff; border-color:#4f9cf9; }}"
        )

        # Tab 1: Orders
        order_page = QtWidgets.QWidget()
        order_lay = QtWidgets.QVBoxLayout(order_page)
        order_lay.setContentsMargins(4, 6, 4, 4)
        order_lay.setSpacing(4)
        order_lay.addWidget(self.table, 1)
        self.footer = QtWidgets.QLabel("")
        self.footer.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        order_lay.addWidget(self.footer)
        self.report_tabs.addTab(order_page, "📋 DAFTAR ORDER")

        # Tab 2: Pair & Day Viability Analysis
        analysis_page = QtWidgets.QWidget()
        analysis_lay = QtWidgets.QVBoxLayout(analysis_page)
        analysis_lay.setContentsMargins(4, 6, 4, 4)
        analysis_lay.setSpacing(6)

        # Card 1: Multi-Pair Summary Table
        pair_card = Card("RINGKASAN ANALISA KELAYAKAN SETIAP PAIR (PROFIT / LOSS / NONAKTIFKAN)")
        pair_hint = QtWidgets.QLabel(
            "🟢 LAYAK PROFIT (Pertahankan) · 🟡 EVALUASI (Pantau / kurangi risk) · "
            "🔴 HARUS NONAKTIFKAN (Loss / kurangi drawdown). Klik baris untuk detail per hari."
        )
        pair_hint.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        pair_card.body.addWidget(pair_hint)

        self.pair_table = QtWidgets.QTableWidget()
        self.pair_table.setColumnCount(11)
        self.pair_table.setHorizontalHeaderLabels(
            ["SIMBOL", "ORDERS", "WIN / LOSS", "WIN RATE", "NET P/L", "AVG R",
             "HARI TERBAIK", "HARI TERBURUK", "STATUS KELAYAKAN", "AUTO TRADE", "AKSI"]
        )
        self.pair_table.verticalHeader().hide()
        self.pair_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pair_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.pair_table.setAlternatingRowColors(True)
        self.pair_table.setShowGrid(False)
        self.pair_table.verticalHeader().setDefaultSectionSize(26)
        self.pair_table.setFixedHeight(140)
        for i in range(11):
            self.pair_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        self.pair_table.itemSelectionChanged.connect(self._on_pair_table_selection)
        pair_card.body.addWidget(self.pair_table)
        analysis_lay.addWidget(pair_card)

        # Card 2: Diagnosis & Verdict for Selected Pair
        verdict_card = Card("DIAGNOSIS & REKOMENDASI PAIR TERPILIH")
        vrow = QtWidgets.QHBoxLayout()
        vrow.setSpacing(8)
        vrow.addWidget(QtWidgets.QLabel("Pair:"))
        self.pair_combo = QtWidgets.QComboBox()
        self.pair_combo.setFixedWidth(120)
        self.pair_combo.currentIndexChanged.connect(self._on_pair_combo_changed)
        vrow.addWidget(self.pair_combo)

        self.verdict_badge = QtWidgets.QLabel("PILIH PAIR")
        self.verdict_badge.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; "
            "border-radius:4px; padding:3px 10px; font-weight:800; font-size:11px;"
        )
        vrow.addWidget(self.verdict_badge)

        self.pair_auto_status = QtWidgets.QLabel("Status Auto Trade: —")
        self.pair_auto_status.setStyleSheet(f"color:{config.MUTED}; font-size:10px; font-weight:700;")
        vrow.addWidget(self.pair_auto_status)

        self.pair_toggle_btn = QtWidgets.QPushButton("Nonaktifkan Pair Ini")
        self.pair_toggle_btn.setFixedWidth(160)
        self.pair_toggle_btn.clicked.connect(self._toggle_selected_pair)
        vrow.addWidget(self.pair_toggle_btn)
        vrow.addStretch(1)
        verdict_card.body.addLayout(vrow)

        self.verdict_text = QtWidgets.QLabel("Pilih sebuah pair di atas untuk melihat analisa mendalam per hari.")
        self.verdict_text.setWordWrap(True)
        self.verdict_text.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; "
            f"border-radius:5px; padding:7px; font-size:10px; color:{config.TEXT};"
        )
        verdict_card.body.addWidget(self.verdict_text)
        analysis_lay.addWidget(verdict_card)

        # Card 3: Sub-tabs for Day-of-Week and Daily date
        self.detail_tabs = QtWidgets.QTabWidget()
        self.detail_tabs.setStyleSheet(
            f"QTabWidget::pane {{ border:1px solid {config.BORDER}; background:{config.PANEL_ALT}; border-radius:5px; }}"
            f"QTabBar::tab {{ background:{config.PANEL}; color:{config.MUTED}; padding:4px 10px; font-size:10px; font-weight:700; }}"
            f"QTabBar::tab:selected {{ color:#ffffff; border-bottom:2px solid #4f9cf9; }}"
        )

        dow_widget = QtWidgets.QWidget()
        dow_lay = QtWidgets.QVBoxLayout(dow_widget)
        dow_lay.setContentsMargins(4, 4, 4, 4)
        dow_lay.setSpacing(3)
        self.dow_table = QtWidgets.QTableWidget()
        self.dow_table.setColumnCount(10)
        self.dow_table.setHorizontalHeaderLabels(
            ["HARI", "ORDERS", "WIN", "LOSS", "WIN RATE", "GROSS PROFIT", "GROSS LOSS", "NET P/L", "STATUS HARI", "SARAN TINDAKAN"]
        )
        self.dow_table.verticalHeader().hide()
        self.dow_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dow_table.setAlternatingRowColors(True)
        self.dow_table.setShowGrid(False)
        self.dow_table.verticalHeader().setDefaultSectionSize(24)
        for i in range(10):
            self.dow_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        dow_lay.addWidget(self.dow_table)
        self.detail_tabs.addTab(dow_widget, "📅 PERFORMA HARI DALAM SEMINGGU (SENIN - JUMAT)")

        daily_widget = QtWidgets.QWidget()
        daily_lay = QtWidgets.QVBoxLayout(daily_widget)
        daily_lay.setContentsMargins(4, 4, 4, 4)
        daily_lay.setSpacing(3)
        self.daily_table = QtWidgets.QTableWidget()
        self.daily_table.setColumnCount(8)
        self.daily_table.setHorizontalHeaderLabels(
            ["TANGGAL", "HARI", "ORDERS", "WIN", "LOSS", "GROSS PROFIT", "GROSS LOSS", "NET P/L"]
        )
        self.daily_table.verticalHeader().hide()
        self.daily_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.daily_table.setAlternatingRowColors(True)
        self.daily_table.setShowGrid(False)
        self.daily_table.verticalHeader().setDefaultSectionSize(24)
        for i in range(8):
            self.daily_table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeMode.Stretch
            )
        daily_lay.addWidget(self.daily_table)
        self.detail_tabs.addTab(daily_widget, "📆 RIWAYAT HARIAN (TANGGAL)")

        analysis_lay.addWidget(self.detail_tabs, 1)
        self.report_tabs.addTab(analysis_page, "📊 ANALISA KELAYAKAN PAIR & HARI")

        body.addWidget(self.report_tabs, 1)
        root.addLayout(body, 1)
        QtCore.QTimer.singleShot(50, lambda: self._load_month(
            self.calendar._year, self.calendar._month
        ))

    # --------------------------------------------------------------- helpers
    def _populate_symbol_filter(self) -> None:
        if not hasattr(self, "symbol_filter"):
            return
        current = self.symbol_filter.currentText()
        symbols: list[str] = []
        for source in (config.MAJOR_SYMBOLS, [self.symbol], self.provider.symbols() or []):
            for sym in source:
                sym = str(sym).strip().upper()
                if sym and sym not in symbols:
                    symbols.append(sym)
        self.symbol_filter.blockSignals(True)
        existing = {self.symbol_filter.itemText(i) for i in range(self.symbol_filter.count())}
        for sym in symbols:
            if sym not in existing:
                self.symbol_filter.addItem(sym)
                existing.add(sym)
        idx = self.symbol_filter.findText(current)
        self.symbol_filter.setCurrentIndex(idx if idx >= 0 else 0)
        self.symbol_filter.blockSignals(False)

    def _selected_symbol(self) -> str | None:
        if not hasattr(self, "symbol_filter") or self.symbol_filter.currentIndex() <= 0:
            return None
        return self.symbol_filter.currentText().strip().upper() or None

    def _symbol_filter_changed(self) -> None:
        if hasattr(self, "table") and self.table.rowCount() >= 0:
            self.load_data()

    def _today(self) -> None:
        today = QtCore.QDate.currentDate()
        self.date_from.setDate(today)
        self.date_to.setDate(today)
        self.load_data()

    def _range(self, days: int) -> None:
        today = QtCore.QDate.currentDate()
        self.date_from.setDate(today.addDays(-(days - 1)))
        self.date_to.setDate(today)
        self.load_data()

    def _calendar_day(self, qdate: QtCore.QDate) -> None:
        self.date_from.setDate(qdate)
        self.date_to.setDate(qdate)
        self.basis.setCurrentIndex(1)
        self.load_data()

    def _load_month(self, year: int, month: int) -> None:
        last_day = calendar.monthrange(year, month)[1]
        start = datetime(year, month, 1, 0, 0, 0)
        end = datetime(year, month, last_day, 23, 59, 59)
        symbol = self._selected_symbol()
        try:
            trades = from_mt5_history(
                symbol, magic_base=app_settings.magic_base(),
                magic_bases=app_settings.magic_bases(),
                start=start, end=end,
                symbols=[symbol] if symbol else None,
            )
        except Exception:
            trades = []
        days: dict[date, dict] = {}
        month_net = 0.0
        month_trades = 0
        for t in trades:
            local_exit = self._local(t.exit_time).date()
            if local_exit.year != year or local_exit.month != month:
                continue
            stats = days.setdefault(local_exit, {"net": 0.0, "trades": 0})
            stats["net"] += t.profit
            stats["trades"] += 1
            month_net += t.profit
            month_trades += 1
        self.calendar.set_data(days, month_net, month_trades)

    def _default_export_path(self) -> Path:
        start = self.date_from.date().toPyDate()
        end = self.date_to.date().toPyDate()
        symbol = self._selected_symbol() or "SemuaSimbol"
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in symbol) or "SemuaSimbol"
        return config.REPORT_DIR / (
            f"ICT_Trade_Report_{safe}_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
        )

    @staticmethod
    def _trade_stats(trades: list[HistoryTrade]) -> dict:
        wins = sum(1 for t in trades if t.profit > 0)
        losses = sum(1 for t in trades if t.profit < 0)
        be = sum(1 for t in trades if t.profit == 0)
        gross_profit = sum(t.profit for t in trades if t.profit > 0)
        gross_loss = abs(sum(t.profit for t in trades if t.profit < 0))
        rr = [t.r for t in trades if abs(t.r) > 1e-9]
        return {
            "orders": len(trades),
            "wins": wins,
            "losses": losses,
            "be": be,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "net": gross_profit - gross_loss,
            "win_rate": (wins / (wins + losses)) if (wins + losses) else 0.0,
            "avg_r": (sum(rr) / len(rr)) if rr else 0.0,
            "symbols": len({t.symbol for t in trades}),
        }

    def export_xlsx(self, path: str | Path | None = None) -> Path | None:
        """Export the current report filter to a styled .xlsx workbook."""
        # QPushButton.clicked may pass a bool; never treat that as a path.
        if isinstance(path, bool):
            path = None
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export XLSX",
                f"Library openpyxl belum terpasang.\n\n{exc}\n\n"
                "Jalankan: pip install openpyxl",
            )
            return None

        start_date = self.date_from.date().toPyDate()
        end_date = self.date_to.date().toPyDate()
        if start_date > end_date:
            QtWidgets.QMessageBox.warning(self, "Export XLSX", "Tanggal 'Dari' melebihi 'Sampai'.")
            return None

        # Make sure the workbook always matches the controls currently visible.
        self.load_data()

        if path is None:
            chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Export Trade Report ke XLSX",
                str(self._default_export_path()),
                "Excel Workbook (*.xlsx)",
            )
            if not chosen:
                return None
            path = chosen
        path = Path(path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self.export_btn.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            wb = Workbook()
            ws = wb.active
            ws.title = "SUMMARY"
            ws.sheet_view.showGridLines = False

            dark = "111720"
            panel = "151D28"
            border_color = "243040"
            text_color = "D7E0EA"
            muted_color = "8291A5"
            green = "26A69A"
            red = "EF5350"
            gold = "F5C451"
            white = "FFFFFF"

            thin = Side(style="thin", color=border_color)
            border = Border(left=thin, right=thin, top=thin, bottom=thin)
            center = Alignment(horizontal="center", vertical="center", wrap_text=True)
            left = Alignment(horizontal="left", vertical="center", wrap_text=True)
            header_fill = PatternFill("solid", fgColor=dark)
            panel_fill = PatternFill("solid", fgColor=panel)
            title_font = Font(bold=True, size=15, color=white)
            label_font = Font(bold=True, color=muted_color, size=9)
            value_font = Font(bold=True, color=white, size=11)
            normal_font = Font(color=text_color, size=10)
            header_font = Font(bold=True, color=muted_color, size=9)

            stats = self._trade_stats(self.trades)
            symbol_label = self._selected_symbol() or "Semua Simbol"
            basis_label = self.basis.currentText() if hasattr(self, "basis") else "Tanggal entry"
            currency = (self.provider.account or {}).get("currency", "USD")

            ws.merge_cells("A1:D1")
            ws["A1"] = "ICT TERMINAL PRO · TRADE REPORT"
            ws["A1"].fill = PatternFill("solid", fgColor=green)
            ws["A1"].font = Font(bold=True, size=16, color="04110F")
            ws["A1"].alignment = left
            ws.row_dimensions[1].height = 30

            ws.merge_cells("A2:D2")
            ws["A2"] = f"Auto Trade MT5 multi-symbol · dibuat {datetime.now():%d %b %Y %H:%M:%S} waktu lokal"
            ws["A2"].font = Font(italic=True, color=muted_color, size=9)
            ws["A2"].alignment = left

            info_rows = [
                ("Simbol", symbol_label),
                ("Periode", f"{start_date:%d %b %Y} s/d {end_date:%d %b %Y}"),
                ("Filter tanggal", basis_label),
                ("Sumber", "History deals MT5 · magic Auto Trade"),
                ("Mata uang P/L", currency),
            ]
            row = 4
            for label, value in info_rows:
                ws.cell(row, 1, label).font = label_font
                ws.cell(row, 2, value).font = value_font
                ws.cell(row, 2).alignment = left
                ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
                row += 1

            row += 1
            ws.cell(row, 1, "METRIK").font = header_font
            ws.cell(row, 1).fill = header_fill
            ws.cell(row, 1).border = border
            ws.cell(row, 2, "NILAI").font = header_font
            ws.cell(row, 2).fill = header_fill
            ws.cell(row, 2).border = border
            ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
            row += 1
            metrics = [
                ("Orders closed", stats["orders"], "0"),
                ("Profit", stats["wins"], "0"),
                ("Loss", stats["losses"], "0"),
                ("Break-even", stats["be"], "0"),
                ("Win rate (profit/loss)", stats["win_rate"], "0.0%"),
                (f"Gross profit ({currency})", stats["gross_profit"], "#,##0.00"),
                (f"Gross loss ({currency})", stats["gross_loss"], "#,##0.00"),
                (f"Net P/L ({currency})", stats["net"], "+#,##0.00;-#,##0.00;0.00"),
                ("Average R", stats["avg_r"], "+0.00;-0.00;0.00"),
                ("Jumlah simbol", stats["symbols"], "0"),
            ]
            for label, value, number_format in metrics:
                ws.cell(row, 1, label).font = normal_font
                ws.cell(row, 1).fill = panel_fill
                ws.cell(row, 1).border = border
                cell = ws.cell(row, 2, value)
                cell.font = value_font
                cell.fill = panel_fill
                cell.border = border
                cell.number_format = number_format
                cell.alignment = Alignment(horizontal="left", vertical="center")
                if label.startswith("Net P/L"):
                    cell.font = Font(bold=True, size=11, color=green if value >= 0 else red)
                elif label.startswith("Profit"):
                    cell.font = Font(bold=True, size=11, color=green)
                elif label.startswith("Loss"):
                    cell.font = Font(bold=True, size=11, color=red)
                ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
                row += 1

            ws.column_dimensions["A"].width = 32
            for col in "BCD":
                ws.column_dimensions[col].width = 22
            ws.freeze_panes = "A4"

            # ---------------------------------------------------------- TRADES
            trade_ws = wb.create_sheet("TRADES")
            trade_headers = [
                "TICKET", "SIMBOL", "TF", "ARAH", "LOT", "ENTRY TIME", "EXIT TIME",
                "ENTRY", "EXIT", "STOP", "TP", "PROFIT", "R", "SOURCE",
            ]
            for c, name in enumerate(trade_headers, 1):
                cell = trade_ws.cell(1, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center
            for r, t in enumerate(self.trades, 2):
                local_entry = self._local(t.entry_time).to_pydatetime()
                local_exit = self._local(t.exit_time).to_pydatetime()
                values = [
                    int(t.ticket), t.symbol, t.tf, t.direction, float(t.volume),
                    local_entry, local_exit, float(t.entry), float(t.exit),
                    float(t.stop), float(t.target), float(t.profit), float(t.r), t.source,
                ]
                for c, value in enumerate(values, 1):
                    cell = trade_ws.cell(r, c, value)
                    cell.font = normal_font
                    cell.border = border
                    cell.alignment = center
                digits = self.provider.meta(t.symbol).digits
                price_format = f"0.{('0' * digits) if digits else '0'}"
                for c in (8, 9, 10, 11):
                    trade_ws.cell(r, c).number_format = price_format
                trade_ws.cell(r, 6).number_format = "dd mmm yyyy hh:mm:ss"
                trade_ws.cell(r, 7).number_format = "dd mmm yyyy hh:mm:ss"
                trade_ws.cell(r, 12).number_format = "+#,##0.00;-#,##0.00;0.00"
                trade_ws.cell(r, 13).number_format = "+0.00;-0.00;0.00"
                trade_ws.cell(r, 4).font = Font(
                    bold=True, color=green if t.direction == "BUY" else red, size=10
                )
                trade_ws.cell(r, 12).font = Font(
                    bold=True, color=green if t.profit >= 0 else red, size=10
                )
            if self.trades:
                trade_ws.auto_filter.ref = f"A1:N{len(self.trades) + 1}"
            else:
                trade_ws.merge_cells("A2:N2")
                trade_ws["A2"] = "Tidak ada trade closed pada filter ini."
                trade_ws["A2"].font = Font(italic=True, color=muted_color, size=10)
            trade_ws.freeze_panes = "A2"
            trade_ws.column_dimensions["A"].width = 13
            trade_ws.column_dimensions["B"].width = 13
            trade_ws.column_dimensions["C"].width = 8
            trade_ws.column_dimensions["D"].width = 9
            trade_ws.column_dimensions["E"].width = 9
            trade_ws.column_dimensions["F"].width = 21
            trade_ws.column_dimensions["G"].width = 21
            for c in range(8, 14):
                trade_ws.column_dimensions[get_column_letter(c)].width = 14
            trade_ws.column_dimensions["N"].width = 13

            # ----------------------------------------------------------- DAILY
            daily_ws = wb.create_sheet("DAILY")
            daily_headers = [
                "TANGGAL EXIT", "ORDERS", "WIN", "LOSS", "BE", "GROSS PROFIT",
                "GROSS LOSS", "NET P/L", "WIN RATE",
            ]
            for c, name in enumerate(daily_headers, 1):
                cell = daily_ws.cell(1, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center
            daily: dict[date, dict] = {}
            for t in self.trades:
                day = self._local(t.exit_time).date()
                item = daily.setdefault(day, {
                    "orders": 0, "wins": 0, "losses": 0, "be": 0,
                    "gross_profit": 0.0, "gross_loss": 0.0,
                })
                item["orders"] += 1
                if t.profit > 0:
                    item["wins"] += 1
                    item["gross_profit"] += t.profit
                elif t.profit < 0:
                    item["losses"] += 1
                    item["gross_loss"] += abs(t.profit)
                else:
                    item["be"] += 1
            for r, day in enumerate(sorted(daily), 2):
                item = daily[day]
                net = item["gross_profit"] - item["gross_loss"]
                win_rate = item["wins"] / (item["wins"] + item["losses"]) if (
                    item["wins"] + item["losses"]
                ) else 0.0
                values = [
                    day, item["orders"], item["wins"], item["losses"], item["be"],
                    item["gross_profit"], item["gross_loss"], net, win_rate,
                ]
                for c, value in enumerate(values, 1):
                    cell = daily_ws.cell(r, c, value)
                    cell.font = normal_font
                    cell.border = border
                    cell.alignment = center
                daily_ws.cell(r, 1).number_format = "dd mmm yyyy"
                daily_ws.cell(r, 6).number_format = "#,##0.00"
                daily_ws.cell(r, 7).number_format = "#,##0.00"
                daily_ws.cell(r, 8).number_format = "+#,##0.00;-#,##0.00;0.00"
                daily_ws.cell(r, 9).number_format = "0.0%"
                daily_ws.cell(r, 8).font = Font(
                    bold=True, color=green if net >= 0 else red, size=10
                )
            if daily:
                daily_ws.auto_filter.ref = f"A1:I{len(daily) + 1}"
            else:
                daily_ws.merge_cells("A2:I2")
                daily_ws["A2"] = "Tidak ada trade closed pada filter ini."
                daily_ws["A2"].font = Font(italic=True, color=muted_color, size=10)
            daily_ws.freeze_panes = "A2"
            daily_ws.column_dimensions["A"].width = 16
            for c in range(2, 10):
                daily_ws.column_dimensions[get_column_letter(c)].width = 15

            # ------------------------------------------------------ PER SYMBOL
            symbol_ws = wb.create_sheet("PER SYMBOL")
            symbol_headers = [
                "SIMBOL", "ORDERS", "WIN", "LOSS", "BE", "GROSS PROFIT",
                "GROSS LOSS", "NET P/L", "WIN RATE", "AVG R",
            ]
            for c, name in enumerate(symbol_headers, 1):
                cell = symbol_ws.cell(1, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center
            by_symbol: dict[str, list[HistoryTrade]] = {}
            for t in self.trades:
                by_symbol.setdefault(t.symbol, []).append(t)
            for r, sym in enumerate(sorted(by_symbol), 2):
                s = self._trade_stats(by_symbol[sym])
                values = [
                    sym, s["orders"], s["wins"], s["losses"], s["be"],
                    s["gross_profit"], s["gross_loss"], s["net"], s["win_rate"], s["avg_r"],
                ]
                for c, value in enumerate(values, 1):
                    cell = symbol_ws.cell(r, c, value)
                    cell.font = normal_font
                    cell.border = border
                    cell.alignment = center
                symbol_ws.cell(r, 6).number_format = "#,##0.00"
                symbol_ws.cell(r, 7).number_format = "#,##0.00"
                symbol_ws.cell(r, 8).number_format = "+#,##0.00;-#,##0.00;0.00"
                symbol_ws.cell(r, 9).number_format = "0.0%"
                symbol_ws.cell(r, 10).number_format = "+0.00;-0.00;0.00"
                symbol_ws.cell(r, 8).font = Font(
                    bold=True, color=green if s["net"] >= 0 else red, size=10
                )
            if by_symbol:
                symbol_ws.auto_filter.ref = f"A1:J{len(by_symbol) + 1}"
            else:
                symbol_ws.merge_cells("A2:J2")
                symbol_ws["A2"] = "Tidak ada trade closed pada filter ini."
                symbol_ws["A2"].font = Font(italic=True, color=muted_color, size=10)
            symbol_ws.freeze_panes = "A2"
            symbol_ws.column_dimensions["A"].width = 16
            for c in range(2, 11):
                symbol_ws.column_dimensions[get_column_letter(c)].width = 14

            # ---------------------------------------------- ANALISA KELAYAKAN
            viab_ws = wb.create_sheet("ANALISA KELAYAKAN")
            viab_headers = [
                "SIMBOL", "ORDERS", "WIN", "LOSS", "BE", "WIN RATE", "GROSS PROFIT",
                "GROSS LOSS", "NET P/L", "AVG R", "PROFIT FACTOR", "HARI TERBAIK",
                "HARI TERBURUK", "STATUS KELAYAKAN", "AUTO TRADE", "REKOMENDASI TINDAKAN",
            ]
            for c, name in enumerate(viab_headers, 1):
                cell = viab_ws.cell(1, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center

            by_exit_basis = getattr(self, "basis", None) is not None and self.basis.currentIndex() == 1
            row_idx = 2
            for sym in sorted(by_symbol):
                pva = PairViabilityAnalysis(sym, by_symbol[sym], by_exit=by_exit_basis)
                is_active = self.is_symbol_active(sym)
                values = [
                    sym, pva.total, pva.wins, pva.losses, pva.be,
                    (pva.win_rate / 100.0) if pva.total else 0.0,
                    pva.gross_profit, pva.gross_loss, pva.net,
                    pva.avg_r, pva.profit_factor,
                    pva.best_day_str, pva.worst_day_str,
                    pva.status,
                    "AKTIF" if is_active else "NONAKTIF",
                    pva.recommendation,
                ]
                for c, val in enumerate(values, 1):
                    cell = viab_ws.cell(row_idx, c, val)
                    cell.font = normal_font
                    cell.border = border
                    cell.alignment = center
                viab_ws.cell(row_idx, 6).number_format = "0.0%"
                viab_ws.cell(row_idx, 7).number_format = "#,##0.00"
                viab_ws.cell(row_idx, 8).number_format = "#,##0.00"
                viab_ws.cell(row_idx, 9).number_format = "+#,##0.00;-#,##0.00;0.00"
                viab_ws.cell(row_idx, 10).number_format = "+0.00;-0.00;0.00"
                viab_ws.cell(row_idx, 11).number_format = "0.00"
                viab_ws.cell(row_idx, 9).font = Font(
                    bold=True, color=green if pva.net >= 0 else red, size=10
                )
                stat_cell = viab_ws.cell(row_idx, 14)
                if "PROFIT" in pva.status:
                    stat_cell.font = Font(bold=True, color=green, size=10)
                elif "NONAKTIF" in pva.status:
                    stat_cell.font = Font(bold=True, color=red, size=10)
                else:
                    stat_cell.font = Font(bold=True, color=gold, size=10)
                viab_ws.cell(row_idx, 15).font = Font(
                    bold=True, color=green if is_active else red, size=10
                )
                viab_ws.cell(row_idx, 16).alignment = left
                row_idx += 1

            if not by_symbol:
                viab_ws.merge_cells("A2:P2")
                viab_ws["A2"] = "Tidak ada trade closed pada filter ini."
                viab_ws["A2"].font = Font(italic=True, color=muted_color, size=10)
            else:
                viab_ws.auto_filter.ref = f"A1:P{row_idx - 1}"

            row_idx += 2
            viab_ws.merge_cells(f"A{row_idx}:K{row_idx}")
            sec_cell = viab_ws.cell(row_idx, 1, "BREAKDOWN PERFORMA PER HARI DALAM SEMINGGU (SENIN - JUMAT)")
            sec_cell.font = Font(bold=True, color=gold, size=11)
            sec_cell.alignment = left
            row_idx += 1

            dow_headers = [
                "SIMBOL", "HARI", "ORDERS", "WIN", "LOSS", "WIN RATE", "GROSS PROFIT",
                "GROSS LOSS", "NET P/L", "STATUS HARI", "SARAN TINDAKAN",
            ]
            for c, name in enumerate(dow_headers, 1):
                cell = viab_ws.cell(row_idx, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center
            row_idx += 1

            dow_start_row = row_idx
            for sym in sorted(by_symbol):
                pva = PairViabilityAnalysis(sym, by_symbol[sym], by_exit=by_exit_basis)
                for dow_idx in range(5):
                    dstat = pva.dow_stats[dow_idx]
                    dstatus, dcolor, dadvice = pva.get_dow_recommendation(dow_idx)
                    dvalues = [
                        sym, pva.WEEKDAYS_ID[dow_idx], dstat["orders"], dstat["wins"], dstat["losses"],
                        (dstat["win_rate"] / 100.0) if dstat["orders"] else 0.0,
                        dstat["gross_profit"], dstat["gross_loss"], dstat["net"],
                        dstatus, dadvice,
                    ]
                    for c, val in enumerate(dvalues, 1):
                        cell = viab_ws.cell(row_idx, c, val)
                        cell.font = normal_font
                        cell.border = border
                        cell.alignment = center
                    viab_ws.cell(row_idx, 6).number_format = "0.0%"
                    viab_ws.cell(row_idx, 7).number_format = "#,##0.00"
                    viab_ws.cell(row_idx, 8).number_format = "#,##0.00"
                    viab_ws.cell(row_idx, 9).number_format = "+#,##0.00;-#,##0.00;0.00"
                    viab_ws.cell(row_idx, 9).font = Font(
                        bold=True, color=green if dstat["net"] >= 0 else red, size=10
                    )
                    viab_ws.cell(row_idx, 11).alignment = left
                    row_idx += 1

            if by_symbol and row_idx > dow_start_row:
                viab_ws.auto_filter.ref = f"A{dow_start_row - 1}:K{row_idx - 1}"

            viab_ws.freeze_panes = "A2"
            viab_ws.column_dimensions["A"].width = 14
            viab_ws.column_dimensions["B"].width = 10
            for c in range(3, 12):
                viab_ws.column_dimensions[get_column_letter(c)].width = 14
            viab_ws.column_dimensions["L"].width = 18
            viab_ws.column_dimensions["M"].width = 18
            viab_ws.column_dimensions["N"].width = 20
            viab_ws.column_dimensions["O"].width = 14
            viab_ws.column_dimensions["P"].width = 45

            # ---------------------------------------------------------- PER TF
            tf_ws = wb.create_sheet("PER TF")
            tf_headers = [
                "TF", "ORDERS", "WIN", "LOSS", "BE", "GROSS PROFIT",
                "GROSS LOSS", "NET P/L", "WIN RATE", "AVG R",
            ]
            for c, name in enumerate(tf_headers, 1):
                cell = tf_ws.cell(1, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.border = border
                cell.alignment = center
            by_tf: dict[str, list[HistoryTrade]] = {}
            for t in self.trades:
                by_tf.setdefault(t.tf, []).append(t)
            for r, tf in enumerate(sorted(by_tf), 2):
                s = self._trade_stats(by_tf[tf])
                values = [
                    tf, s["orders"], s["wins"], s["losses"], s["be"],
                    s["gross_profit"], s["gross_loss"], s["net"], s["win_rate"], s["avg_r"],
                ]
                for c, value in enumerate(values, 1):
                    cell = tf_ws.cell(r, c, value)
                    cell.font = normal_font
                    cell.border = border
                    cell.alignment = center
                tf_ws.cell(r, 6).number_format = "#,##0.00"
                tf_ws.cell(r, 7).number_format = "#,##0.00"
                tf_ws.cell(r, 8).number_format = "+#,##0.00;-#,##0.00;0.00"
                tf_ws.cell(r, 9).number_format = "0.0%"
                tf_ws.cell(r, 10).number_format = "+0.00;-0.00;0.00"
                tf_ws.cell(r, 8).font = Font(
                    bold=True, color=green if s["net"] >= 0 else red, size=10
                )
            if by_tf:
                tf_ws.auto_filter.ref = f"A1:J{len(by_tf) + 1}"
            tf_ws.freeze_panes = "A2"
            tf_ws.column_dimensions["A"].width = 12
            for c in range(2, 11):
                tf_ws.column_dimensions[get_column_letter(c)].width = 14

            # -------------------------------------------------------- CALENDAR
            cal_ws = wb.create_sheet("CALENDAR")
            cal_ws.sheet_view.showGridLines = False
            year, month = self.calendar._year, self.calendar._month
            month_name = self.calendar.MONTHS[month]
            cal_ws.merge_cells("A1:G1")
            cal_ws["A1"] = f"KALENDER P/L · {month_name} {year}"
            cal_ws["A1"].fill = PatternFill("solid", fgColor=gold)
            cal_ws["A1"].font = Font(bold=True, size=15, color="241A04")
            cal_ws["A1"].alignment = left
            cal_ws.merge_cells("A2:G2")
            cal_ws["A2"] = (
                f"{symbol_label} · realized P/L berdasarkan tanggal exit · "
                f"waktu lokal · net bulan {self.calendar._month_net:+,.2f} {currency}"
            )
            cal_ws["A2"].font = Font(italic=True, color=muted_color, size=9)
            cal_ws["A2"].alignment = left
            for c, name in enumerate(TradeCalendar.WEEKDAYS, 1):
                cell = cal_ws.cell(4, c, name)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center
                cell.border = border
            day_map = self.calendar._days
            for r, week in enumerate(calendar.monthcalendar(year, month)[:6], 5):
                cal_ws.row_dimensions[r].height = 45
                for c, day in enumerate(week, 1):
                    cell = cal_ws.cell(r, c)
                    cell.border = border
                    cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                    if not day:
                        continue
                    d = date(year, month, day)
                    info = day_map.get(d)
                    if not info or info["trades"] == 0:
                        cell.value = str(day)
                        cell.font = Font(color=muted_color, size=10)
                        cell.fill = PatternFill("solid", fgColor=panel)
                        continue
                    net = info["net"]
                    cell.value = f"{day}\n{net:+,.0f}\n{info['trades']} trade"
                    cell.font = Font(
                        bold=True, color=green if net >= 0 else red, size=10
                    )
                    cell.fill = PatternFill(
                        "solid", fgColor="E8F5E9" if net >= 0 else "FFEBEE"
                    )
            summary_row = 12
            cal_ws.merge_cells(start_row=summary_row, start_column=1, end_row=summary_row, end_column=7)
            cal_ws.cell(summary_row, 1,
                        f"Bulan ini: {self.calendar._month_trades} trade · "
                        f"net {self.calendar._month_net:+,.2f} {currency} · "
                        "hijau profit / merah loss").font = Font(
                bold=True, color=text_color, size=10
            )
            for c in range(1, 8):
                cal_ws.column_dimensions[get_column_letter(c)].width = 17

            wb.save(path)
        except Exception as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.export_btn.setEnabled(True)
            QtWidgets.QMessageBox.warning(
                self, "Export XLSX", f"Gagal membuat file Excel:\n{type(exc).__name__}: {exc}"
            )
            return None
        QtWidgets.QApplication.restoreOverrideCursor()
        self.export_btn.setEnabled(True)
        self.info.setToolTip(str(path))
        self.info.setText(f"XLSX disimpan: {path.name}")
        return path

    def set_symbol(self, symbol: str) -> None:
        """Keep the report filter independent; only make sure the symbol exists."""
        self.symbol = symbol.strip().upper() or self.symbol
        self._populate_symbol_filter()

    @staticmethod
    def _local(stamp: pd.Timestamp) -> pd.Timestamp:
        ts = pd.Timestamp(stamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert(datetime.now().astimezone().tzinfo).tz_localize(None)

    def load_data(self) -> None:
        start_date = self.date_from.date().toPyDate()
        end_date = self.date_to.date().toPyDate()
        if start_date > end_date:
            QtWidgets.QMessageBox.warning(self, "Trade Report", "Tanggal 'Dari' melebihi 'Sampai'.")
            return
        start = datetime.combine(start_date, time.min)
        end = datetime.combine(end_date, time.max)
        symbol = self._selected_symbol()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            trades = from_mt5_history(
                symbol, magic_base=app_settings.magic_base(),
                magic_bases=app_settings.magic_bases(),
                start=start, end=end,
                symbols=[symbol] if symbol else None,
            )
        except Exception as exc:
            QtWidgets.QApplication.restoreOverrideCursor()
            QtWidgets.QMessageBox.warning(self, "Trade Report", f"Gagal memuat history:\n{exc}")
            return
        QtWidgets.QApplication.restoreOverrideCursor()
        by_exit = self.basis.currentIndex() == 1
        selected = []
        for t in trades:
            stamp = self._local(t.exit_time if by_exit else t.entry_time)
            if start <= stamp.to_pydatetime() <= end:
                selected.append(t)
        self.trades = selected
        self._render()
        filter_label = symbol or "Semua Simbol"
        self.info.setText(
            f"{filter_label} · {start_date:%d %b %Y} s/d {end_date:%d %b %Y} · "
            f"filter {self.basis.currentText().lower()} · {len(selected)} order closed · waktu lokal"
        )
        # Keep the calendar in sync with the visible month.
        if (start_date.year, start_date.month) != (self.calendar._year, self.calendar._month):
            self.calendar.set_month(start_date.year, start_date.month)
        self.calendar.set_selected(start_date if start_date == end_date else None)
        self._load_month(start_date.year, start_date.month)

    def _render(self) -> None:
        self.table.setRowCount(len(self.trades))
        wins = losses = be = 0
        gross_profit = gross_loss = 0.0
        r_values = []
        for row, t in enumerate(reversed(self.trades)):
            local_entry = self._local(t.entry_time)
            local_exit = self._local(t.exit_time)
            digits = self.provider.meta(t.symbol).digits
            if t.profit > 0:
                wins += 1
                gross_profit += t.profit
            elif t.profit < 0:
                losses += 1
                gross_loss += abs(t.profit)
            else:
                be += 1
            if abs(t.r) > 1e-9:
                r_values.append(t.r)
            values = [
                str(t.ticket), t.symbol, t.tf, t.direction, f"{t.volume:.2f}",
                local_entry.strftime("%d %b %H:%M:%S"),
                local_exit.strftime("%d %b %H:%M:%S"),
                f"{t.entry:,.{digits}f}", f"{t.exit:,.{digits}f}",
                f"{t.profit:+,.2f}", f"{t.r:+.2f}" if abs(t.r) > 1e-9 else "—",
            ]
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if col == 3:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(
                        config.BULL if t.direction == "BUY" else config.BEAR
                    )))
                elif col == 9:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(
                        config.BULL if t.profit >= 0 else config.BEAR
                    )))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.MUTED)))
                self.table.setItem(row, col, item)

        total = len(self.trades)
        net = gross_profit - gross_loss
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) else 0.0
        self.card_orders.set(str(total))
        self.card_wins.set(str(wins), config.BULL)
        self.card_losses.set(str(losses), config.BEAR)
        self.card_winrate.set(f"{win_rate:.1f}%", config.BULL if win_rate >= 50 else config.GOLD)
        self.card_net.set(f"{net:+,.2f}", config.BULL if net >= 0 else config.BEAR)
        self.card_gross.set(f"+{gross_profit:,.2f} / -{gross_loss:,.2f}")
        avg_r = sum(r_values) / len(r_values) if r_values else 0.0
        self.card_avg.set(f"{avg_r:+.2f}R", config.BULL if avg_r >= 0 else config.BEAR)
        self.footer.setText(
            f"Total {total} order closed · {wins} profit · {losses} loss · {be} break-even · "
            f"net {net:+,.2f} · sumber: history deals MT5 (magic Auto Trade)"
        )
        self._render_pair_analysis()

    def _render_pair_analysis(self) -> None:
        if not hasattr(self, "pair_table"):
            return
        by_exit = getattr(self, "basis", None) is not None and self.basis.currentIndex() == 1
        by_symbol: dict[str, list[HistoryTrade]] = {}
        for t in self.trades:
            by_symbol.setdefault(t.symbol, []).append(t)

        self._pair_analyses = {}
        for sym, sym_trades in by_symbol.items():
            self._pair_analyses[sym] = PairViabilityAnalysis(sym, sym_trades, by_exit=by_exit)

        symbols = sorted(self._pair_analyses.keys())
        self.pair_table.setRowCount(len(symbols))
        for row, sym in enumerate(symbols):
            pva = self._pair_analyses[sym]
            is_active = self.is_symbol_active(sym)
            values = [
                sym,
                str(pva.total),
                f"{pva.wins} / {pva.losses}",
                f"{pva.win_rate:.1f}%",
                f"{pva.net:+,.2f}",
                f"{pva.avg_r:+.2f}R" if abs(pva.avg_r) > 1e-9 else "—",
                pva.best_day_str,
                pva.worst_day_str,
                pva.status,
                "AKTIF" if is_active else "NONAKTIF",
            ]
            for col, val in enumerate(values):
                item = QtWidgets.QTableWidgetItem(val)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if col == 0:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#ffffff")))
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                elif col == 4:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if pva.net >= 0 else config.BEAR)))
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                elif col == 8:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(pva.status_color)))
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                elif col == 9:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if is_active else config.BEAR)))
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.MUTED)))
                self.pair_table.setItem(row, col, item)

            btn = QtWidgets.QPushButton("Nonaktifkan" if is_active else "Aktifkan")
            btn.setFixedHeight(22)
            btn.setStyleSheet(
                f"QPushButton {{ background:{config.BEAR if is_active else config.BULL}; color:#ffffff; "
                f"font-weight:700; font-size:9px; border-radius:3px; padding:2px 6px; }}"
                f"QPushButton:hover {{ opacity:0.8; }}"
            )
            btn.clicked.connect(lambda _checked=False, s=sym: self._toggle_symbol_action(s))
            self.pair_table.setCellWidget(row, 10, btn)

        # Update combo
        current_selection = self._selected_pair
        self.pair_combo.blockSignals(True)
        self.pair_combo.clear()
        for sym in symbols:
            self.pair_combo.addItem(sym)
        self.pair_combo.blockSignals(False)

        if symbols:
            target = current_selection if current_selection in symbols else symbols[0]
            self._select_pair(target)
        else:
            self._select_pair(None)

    def _select_pair(self, sym: str | None) -> None:
        self._selected_pair = sym
        if not sym or sym not in self._pair_analyses:
            self.verdict_badge.setText("BELUM ADA DATA")
            self.verdict_badge.setStyleSheet(
                f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER}; "
                f"color:{config.MUTED}; border-radius:4px; padding:3px 10px; font-weight:800; font-size:11px;"
            )
            self.pair_auto_status.setText("Status Auto Trade: —")
            self.pair_toggle_btn.setEnabled(False)
            self.verdict_text.setText("Belum ada riwayat order tertutup pada filter tanggal yang dipilih.")
            self.dow_table.setRowCount(0)
            self.daily_table.setRowCount(0)
            return

        self.pair_combo.blockSignals(True)
        idx = self.pair_combo.findText(sym)
        if idx >= 0:
            self.pair_combo.setCurrentIndex(idx)
        self.pair_combo.blockSignals(False)

        pva = self._pair_analyses[sym]
        is_active = self.is_symbol_active(sym)

        self.verdict_badge.setText(pva.status)
        self.verdict_badge.setStyleSheet(
            f"background:{pva.status_color}22; border:1px solid {pva.status_color}; "
            f"color:{pva.status_color}; border-radius:4px; padding:3px 10px; font-weight:800; font-size:11px;"
        )
        self.pair_auto_status.setText(f"Status Auto Trade: {'AKTIF' if is_active else 'NONAKTIF'}")
        self.pair_auto_status.setStyleSheet(
            f"color:{config.BULL if is_active else config.BEAR}; font-size:10px; font-weight:700;"
        )
        self.pair_toggle_btn.setText("Nonaktifkan Pair Ini" if is_active else "Aktifkan Pair Ini")
        self.pair_toggle_btn.setStyleSheet(
            f"QPushButton {{ background:{config.BEAR if is_active else config.BULL}; color:#ffffff; "
            f"font-weight:700; border-radius:4px; padding:4px 12px; }}"
            f"QPushButton:hover {{ opacity:0.85; }}"
        )
        self.pair_toggle_btn.setEnabled(True)
        self.verdict_text.setText(pva.detailed_verdict)

        # DOW table
        show_weekend = pva.dow_stats[5]["orders"] > 0 or pva.dow_stats[6]["orders"] > 0
        dow_rows = 7 if show_weekend else 5
        self.dow_table.setRowCount(dow_rows)
        for row in range(dow_rows):
            dstat = pva.dow_stats[row]
            dstatus, dcolor, dadvice = pva.get_dow_recommendation(row)
            dvalues = [
                pva.WEEKDAYS_ID[row],
                str(dstat["orders"]),
                str(dstat["wins"]),
                str(dstat["losses"]),
                f"{dstat['win_rate']:.1f}%",
                f"{dstat['gross_profit']:+,.2f}" if dstat["orders"] else "0.00",
                f"-{dstat['gross_loss']:,.2f}" if dstat["orders"] else "0.00",
                f"{dstat['net']:+,.2f}" if dstat["orders"] else "0.00",
                dstatus,
                dadvice,
            ]
            for col, val in enumerate(dvalues):
                item = QtWidgets.QTableWidgetItem(val)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter if col < 9 else (QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter))
                if col == 0:
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#ffffff")))
                elif col == 7:
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if dstat["net"] >= 0 else config.BEAR)))
                elif col == 8:
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    item.setForeground(QtGui.QBrush(QtGui.QColor(dcolor)))
                elif col == 9:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.TEXT)))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.MUTED)))
                self.dow_table.setItem(row, col, item)

        # Daily date table
        sorted_dates = sorted(pva.daily_stats.keys(), reverse=True)
        self.daily_table.setRowCount(len(sorted_dates))
        for row, d in enumerate(sorted_dates):
            ds = pva.daily_stats[d]
            net = ds["net"]
            color_day = config.BULL if net > 0 else (config.BEAR if net < 0 else config.MUTED)
            dvalues = [
                d.strftime("%d %b %Y"),
                pva.WEEKDAYS_ID[d.weekday()],
                str(ds["orders"]),
                str(ds["wins"]),
                str(ds["losses"]),
                f"{ds['gross_profit']:+,.2f}",
                f"-{ds['gross_loss']:,.2f}",
                f"{net:+,.2f}",
            ]
            for col, val in enumerate(dvalues):
                item = QtWidgets.QTableWidgetItem(val)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if col == 7:
                    item.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.Weight.Bold))
                    item.setForeground(QtGui.QBrush(QtGui.QColor(color_day)))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(config.MUTED)))
                self.daily_table.setItem(row, col, item)

    def _refresh_pair_ui(self) -> None:
        if hasattr(self, "pair_table") and hasattr(self, "_pair_analyses"):
            symbols = sorted(self._pair_analyses.keys())
            for row, sym in enumerate(symbols):
                is_active = self.is_symbol_active(sym)
                act_item = self.pair_table.item(row, 9)
                if act_item:
                    act_item.setText("AKTIF" if is_active else "NONAKTIF")
                    act_item.setForeground(QtGui.QBrush(QtGui.QColor(config.BULL if is_active else config.BEAR)))
                btn = self.pair_table.cellWidget(row, 10)
                if isinstance(btn, QtWidgets.QPushButton):
                    btn.setText("Nonaktifkan" if is_active else "Aktifkan")
                    btn.setStyleSheet(
                        f"QPushButton {{ background:{config.BEAR if is_active else config.BULL}; color:#ffffff; "
                        f"font-weight:700; font-size:9px; border-radius:3px; padding:2px 6px; }}"
                        f"QPushButton:hover {{ opacity:0.8; }}"
                    )
        if self._selected_pair:
            is_active = self.is_symbol_active(self._selected_pair)
            self.pair_auto_status.setText(f"Status Auto Trade: {'AKTIF' if is_active else 'NONAKTIF'}")
            self.pair_auto_status.setStyleSheet(
                f"color:{config.BULL if is_active else config.BEAR}; font-size:10px; font-weight:700;"
            )
            self.pair_toggle_btn.setText("Nonaktifkan Pair Ini" if is_active else "Aktifkan Pair Ini")
            self.pair_toggle_btn.setStyleSheet(
                f"QPushButton {{ background:{config.BEAR if is_active else config.BULL}; color:#ffffff; "
                f"font-weight:700; border-radius:4px; padding:4px 12px; }}"
                f"QPushButton:hover {{ opacity:0.85; }}"
            )

    def _toggle_symbol_action(self, symbol: str) -> None:
        sym = symbol.strip().upper()
        current = self.is_symbol_active(sym)
        new_state = not current
        self.set_symbol_active(sym, new_state)
        self._refresh_pair_ui()

    def _toggle_selected_pair(self) -> None:
        if self._selected_pair:
            self._toggle_symbol_action(self._selected_pair)

    def _on_pair_table_selection(self) -> None:
        selected_items = self.pair_table.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            sym_item = self.pair_table.item(row, 0)
            if sym_item:
                self._select_pair(sym_item.text().strip().upper())

    def _on_pair_combo_changed(self, index: int) -> None:
        sym = self.pair_combo.currentText().strip().upper()
        if sym and sym != self._selected_pair:
            self._select_pair(sym)
            for row in range(self.pair_table.rowCount()):
                item = self.pair_table.item(row, 0)
                if item and item.text().strip().upper() == sym:
                    self.pair_table.blockSignals(True)
                    self.pair_table.selectRow(row)
                    self.pair_table.blockSignals(False)
                    break
