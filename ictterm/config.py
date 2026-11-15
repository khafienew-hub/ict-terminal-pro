"""Application configuration and shared constants."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "ICT Terminal Pro"
APP_VERSION = "2.0.4"
APP_EDITION = "PRO"

# Kontak penjual yang tampil di dialog lisensi & pesan "bot terkunci".
SELLER_PHONE = "081225780898"
SELLER_PHONE_DISPLAY = "0812-2578-0898"
SELLER_CONTACT = (
    f"WhatsApp: {SELLER_PHONE_DISPLAY}\n"
    "Sertakan HWID laptop Anda saat menghubungi."
)


def app_dir() -> Path:
    """Directory that contains the exe (frozen) or the project root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = app_dir()
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
REPORT_DIR = BASE_DIR / "reports"
CACHE_DIR = BASE_DIR / "cache"
ASSET_DIR = RESOURCE_DIR / "assets"
for _d in (REPORT_DIR, CACHE_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

try:
    import MetaTrader5 as mt5

    MT5_AVAILABLE = True
except Exception:  # pragma: no cover - only happens without the package
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False


def _tf(name: str, fallback: int) -> int:
    return getattr(mt5, name, fallback) if mt5 is not None else fallback


# MetaTrader 5 timeframe constants (fallback values keep tests importable).
TIMEFRAMES: dict[str, int] = {
    "M1": _tf("TIMEFRAME_M1", 1),
    "M5": _tf("TIMEFRAME_M5", 5),
    "M15": _tf("TIMEFRAME_M15", 15),
    "M30": _tf("TIMEFRAME_M30", 30),
    "H1": _tf("TIMEFRAME_H1", 16385),
    "H4": _tf("TIMEFRAME_H4", 16388),
    "D1": _tf("TIMEFRAME_D1", 16408),
}
TF_ORDER = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
TF_WEIGHT = {"M1": 0.5, "M5": 1.0, "M15": 1.5, "M30": 2.0, "H1": 2.5, "H4": 3.0, "D1": 3.5}
TF_BARS = {"M1": 900, "M5": 900, "M15": 800, "M30": 800, "H1": 800, "H4": 800, "D1": 600}

DEFAULT_SYMBOL = "XAUUSD"
MAJOR_SYMBOLS = [
    "XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "US30",
    "NAS100", "SPX500", "GER40", "UK100", "USOIL", "UKOIL", "BTCUSD",
    "ETHUSD", "XRPUSD",
]

# ---- palette (TradingView dark inspired) -------------------------------
BG = "#0b0f14"
PANEL = "#111720"
PANEL_ALT = "#151d28"
BORDER = "#243040"
TEXT = "#d7e0ea"
MUTED = "#8291a5"
GRID = "#1c2634"
BULL = "#26a69a"
BEAR = "#ef5350"
BULL_SOFT = "#26a69a"
ACCENT = "#4f9cf9"
GOLD = "#f5c451"
VIOLET = "#b388ff"
LONG_ZONE = (38, 166, 154, 42)
SHORT_ZONE = (239, 83, 80, 42)
FVG_BULL = (79, 156, 249, 34)
FVG_BEAR = (255, 167, 38, 34)
LIQUIDITY = "#f5c451"
ORDER_LONG_FILL = (38, 166, 154, 55)
ORDER_SHORT_FILL = (239, 83, 80, 55)
ORDER_LONG_LINE = "#26a69a"
ORDER_SHORT_LINE = "#ef5350"

APP_QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
    font-size: 12px;
    color: {TEXT};
}}
QMainWindow, QWidget {{
    background: {BG};
}}
QFrame#Card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#Header {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
QLabel#Title {{
    font-size: 17px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.3px;
}}
QLabel#SubTitle {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#SectionTitle {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#BigBuy {{
    color: #07110f;
    background: {BULL};
    border-radius: 8px;
    font-size: 22px;
    font-weight: 800;
    padding: 10px;
}}
QLabel#BigSell {{
    color: #180707;
    background: {BEAR};
    border-radius: 8px;
    font-size: 22px;
    font-weight: 800;
    padding: 10px;
}}
QLabel#BigNeutral {{
    color: {TEXT};
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    font-size: 20px;
    font-weight: 700;
    padding: 10px;
}}
QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    background: #1b2634;
}}
QPushButton:pressed {{
    background: #0f1620;
}}
QPushButton:checked {{
    background: {ACCENT};
    color: #07111f;
    border-color: {ACCENT};
    font-weight: 700;
}}
QPushButton#BuyButton {{
    background: {BULL};
    border: none;
    color: #04110f;
    font-weight: 700;
    padding: 7px 14px;
}}
QPushButton#SellButton {{
    background: {BEAR};
    border: none;
    color: #160808;
    font-weight: 700;
    padding: 7px 14px;
}}
QPushButton#PrimaryButton {{
    background: {ACCENT};
    border: none;
    color: #06111f;
    font-weight: 700;
    padding: 7px 14px;
}}
QPushButton#PrimaryButton:hover {{
    background: #6aadfa;
}}
QPushButton#TfButton {{
    padding: 3px 2px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton#TfButton:checked {{
    background: {ACCENT};
    color: #07111f;
    border: 1px solid {ACCENT};
    font-weight: 700;
}}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
    border-color: #35506e;
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: #55657a;
    background: #0c1219;
    border-color: #1a2431;
}}
QComboBox QAbstractItemView {{
    background: {PANEL};
    border: 1px solid {BORDER};
    selection-background-color: #1f3247;
    outline: none;
}}
QCheckBox {{
    spacing: 7px;
    color: {TEXT};
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #3a4a5e;
    background: {PANEL_ALT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QTableWidget {{
    background: {PANEL};
    alternate-background-color: #131b26;
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: #1b2531;
    selection-background-color: #1d3047;
    selection-color: #ffffff;
}}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 5px;
    font-size: 10px;
    font-weight: 700;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG};
}}
QTabBar::tab {{
    background: {PANEL};
    border: 1px solid {BORDER};
    padding: 7px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    color: #ffffff;
    background: {PANEL_ALT};
    border-bottom-color: {PANEL_ALT};
}}
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #2c3a4d;
    min-height: 22px;
    border-radius: 5px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG};
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: #2c3a4d;
    min-width: 22px;
    border-radius: 5px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QStatusBar {{
    background: {PANEL};
    border-top: 1px solid {BORDER};
    color: {MUTED};
}}
QToolTip {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px;
}}
QSplitter::handle {{
    background: {BORDER};
}}
QProgressBar {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 5px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
"""


def price_decimals(point: float, default: int = 2) -> int:
    if not point or point <= 0:
        return default
    text = f"{point:.10f}".rstrip("0")
    return max(0, len(text.split(".")[1]) if "." in text else 0)


def fmt_price(value: float, digits: int = 2) -> str:
    try:
        return f"{value:,.{digits}f}"
    except (TypeError, ValueError):
        return "-"

