"""Licence activation dialog (activation key, HWID, trial status)."""
from __future__ import annotations

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config, licensing


SELLER_CONTACT = config.SELLER_CONTACT


class LicenseDialog(QtWidgets.QDialog):
    """Shows the current edition and accepts an activation key."""

    activated = QtCore.pyqtSignal()

    def __init__(self, parent=None, welcome: bool = False):
        super().__init__(parent)
        self._welcome = welcome
        self.setWindowTitle(f"Lisensi · {config.APP_NAME}")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.title = QtWidgets.QLabel("LISENSI APLIKASI")
        self.title.setObjectName("Title")
        root.addWidget(self.title)

        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"background:{config.PANEL}; border:1px solid {config.BORDER};"
            "border-radius:8px; padding:10px; font-size:12px;"
        )
        root.addWidget(self.status)

        # ---- HWID -------------------------------------------------------
        hwid_row = QtWidgets.QHBoxLayout()
        hwid_row.setSpacing(6)
        hwid_label = QtWidgets.QLabel("HWID laptop ini")
        hwid_label.setFixedWidth(120)
        hwid_label.setStyleSheet(f"color:{config.MUTED};")
        self.hwid_edit = QtWidgets.QLineEdit(licensing.machine_id())
        self.hwid_edit.setReadOnly(True)
        self.hwid_edit.setStyleSheet(
            f"font-family:Consolas,monospace; font-size:13px; letter-spacing:1px; color:{config.GOLD};"
        )
        copy_btn = QtWidgets.QPushButton("Salin")
        copy_btn.setFixedWidth(64)
        copy_btn.clicked.connect(self._copy_hwid)
        hwid_row.addWidget(hwid_label)
        hwid_row.addWidget(self.hwid_edit, 1)
        hwid_row.addWidget(copy_btn)
        root.addLayout(hwid_row)

        hwid_note = QtWidgets.QLabel(
            "Kirim HWID di atas ke penjual untuk mendapatkan key. "
            "Key hanya berlaku di laptop ini. Key baru (v3) lebih panjang — "
            "tempel apa adanya (Ctrl+V), spasi dan tanda hubung dirapikan otomatis."
        )
        hwid_note.setWordWrap(True)
        hwid_note.setStyleSheet(f"color:{config.MUTED}; font-size:9px;")
        root.addWidget(hwid_note)

        # ---- key input --------------------------------------------------
        key_row = QtWidgets.QHBoxLayout()
        key_row.setSpacing(6)
        key_label = QtWidgets.QLabel("Key aktivasi")
        key_label.setFixedWidth(120)
        key_label.setStyleSheet(f"color:{config.MUTED};")
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setPlaceholderText("ICT3-XXXX-XXXX-XXXX-… (30 grup, tempel dengan Ctrl+V)")
        self.key_edit.setStyleSheet("font-family:Consolas,monospace; font-size:12px;")
        self.key_edit.returnPressed.connect(self.activate)
        self.activate_btn = QtWidgets.QPushButton("AKTIFKAN")
        self.activate_btn.setObjectName("PrimaryButton")
        self.activate_btn.setFixedWidth(110)
        self.activate_btn.clicked.connect(self.activate)
        key_row.addWidget(key_label)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.activate_btn)
        root.addLayout(key_row)

        self.message = QtWidgets.QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet(f"color:{config.MUTED}; font-size:10px;")
        root.addWidget(self.message)

        # ---- limits table ----------------------------------------------
        table_title = QtWidgets.QLabel("BATAS FITUR AUTO TRADE")
        table_title.setObjectName("SectionTitle")
        root.addWidget(table_title)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(4)
        headers = ["Fitur", "Masa gratis terbatas", "PRO (dengan key)"]
        for col, text in enumerate(headers):
            lbl = QtWidgets.QLabel(text)
            lbl.setStyleSheet(f"color:{config.MUTED}; font-size:10px; font-weight:700;")
            grid.addWidget(lbl, 0, col)
        rows = [
            ("Jumlah pair / simbol", "maks 5", "maks 12"),
            ("Risk per trade", "0.1% (dikunci)", "0.1% – 5%"),
            ("Max total risk", "4%", "s/d 10%"),
            ("Max drawdown global", "4%", "s/d 50%"),
            ("Skor minimum sinyal", "10.0 (dikunci)", "3.0 – 10.0"),
            ("Target RR", "1.5R (dikunci)", "0.5R – 5R"),
            ("Mode TP", "RR saja", "RR / struktur liquidity"),
            ("Masa berlaku", f"{licensing.TRIAL_DAYS} hari sejak pertama dibuka",
             "1 / 3 / 6 / 12 bulan sejak aktivasi"),
        ]
        for r, (name, free, pro) in enumerate(rows, start=1):
            grid.addWidget(self._cell(name), r, 0)
            grid.addWidget(self._cell(free, config.GOLD), r, 1)
            grid.addWidget(self._cell(pro, config.BULL), r, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 2)
        root.addLayout(grid)

        # ---- contact + close -------------------------------------------
        contact = QtWidgets.QLabel(
            f"Beli / perpanjang lisensi:\n{SELLER_CONTACT}"
        )
        contact.setWordWrap(True)
        contact.setStyleSheet(
            f"background:{config.PANEL_ALT}; border:1px solid {config.BORDER};"
            "border-radius:6px; padding:8px; font-size:10px;"
        )
        root.addWidget(contact)

        bottom = QtWidgets.QHBoxLayout()
        self.copy_key_btn = QtWidgets.QPushButton("Salin key")
        self.copy_key_btn.clicked.connect(self._copy_key)
        self.copy_key_btn.setVisible(False)
        close_btn = QtWidgets.QPushButton("Tutup")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.copy_key_btn)
        bottom.addStretch(1)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

    @staticmethod
    def _cell(text: str, color: str = None) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet(f"color:{color or config.TEXT}; font-size:10px;")
        return lbl

    # -------------------------------------------------------------- actions
    def _copy_hwid(self) -> None:
        QtWidgets.QApplication.clipboard().setText(licensing.machine_id())
        self.message.setText("HWID disalin ke clipboard.")
        self.message.setStyleSheet(f"color:{config.BULL}; font-size:10px;")

    def _copy_key(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.key_edit.text().strip())
        self.message.setText("Key disalin ke clipboard.")
        self.message.setStyleSheet(f"color:{config.BULL}; font-size:10px;")

    def activate(self) -> None:
        text = self.key_edit.text().strip()
        if not text:
            self.message.setText("Masukkan key aktivasi terlebih dahulu.")
            self.message.setStyleSheet(f"color:{config.GOLD}; font-size:10px;")
            return
        ok, message = licensing.activate(text)
        if not ok:
            self.message.setText(message)
            self.message.setStyleSheet(f"color:{config.BEAR}; font-size:10px;")
            return
        self.key_edit.setText(licensing.format_key(text))
        self.copy_key_btn.setVisible(True)
        self.message.setText(message)
        self.message.setStyleSheet(f"color:{config.BULL}; font-size:10px; font-weight:700;")
        self.refresh()
        self.activated.emit()

    # -------------------------------------------------------------- display
    def refresh(self) -> None:
        state = licensing.current_state(force=True)
        if state.edition == "PRO":
            color = config.BULL
        elif state.bot_locked:
            color = config.BEAR
        elif state.tier == "pro":
            color = config.ACCENT
        else:
            color = config.GOLD
        badge = state.badge
        if state.edition == "PRO":
            validity = "Lifetime" if state.lifetime else f"Berlaku sampai {state.expires:%d %b %Y}"
        elif state.edition == "TRIAL":
            validity = (f"Hari ke-{state.trial_day} dari {licensing.TRIAL_DAYS} · "
                        f"berakhir {state.expires:%d %b %Y}")
            validity += (f" · PRO penuh sisa {state.pro_left} hari"
                         if state.tier == "pro" else "")
        else:
            validity = "Chart, sinyal, dan backtest tetap bisa dipakai"
        self.status.setText(
            f"<div style='font-size:20px; font-weight:800; color:{color};'>{badge}</div>"
            f"<div style='color:{config.TEXT}; margin-top:2px;'>{state.title}</div>"
            f"<div style='color:{config.MUTED}; font-size:10px;'>{validity}</div>"
            + (f"<div style='color:{config.GOLD}; font-size:10px;'>{state.reason}</div>"
               if state.reason else "")
        )
        if self._welcome and state.edition == "TRIAL":
            self.title.setText("SELAMAT DATANG · MASA GRATIS DIMULAI")
        elif state.edition == "PRO":
            self.title.setText("LISENSI AKTIF")
        elif state.bot_locked:
            self.title.setText("BOT TERKUNCI · BELI LISENSI")
        else:
            self.title.setText("LISENSI APLIKASI")
        if state.key:
            self.key_edit.setText(state.key)
            self.copy_key_btn.setVisible(True)
        self.activate_btn.setEnabled(state.edition != "PRO")


def show_license_dialog(parent=None, welcome: bool = False) -> bool:
    """Open the dialog; returns ``True`` when a key was activated."""
    dlg = LicenseDialog(parent, welcome=welcome)
    activated = {"value": False}
    dlg.activated.connect(lambda: activated.__setitem__("value", True))
    dlg.exec()
    return activated["value"]
