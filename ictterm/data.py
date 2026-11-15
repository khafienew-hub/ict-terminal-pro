"""Market-data access with cache, synthetic fallback and MT5 helpers."""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from . import config


OHLC_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


@dataclass
class SymbolMeta:
    symbol: str
    digits: int = 2
    point: float = 0.01
    tick_value: float = 1.0
    tick_size: float = 0.01
    contract_size: float = 100_000.0
    spread: int = 0
    description: str = ""
    currency: str = "USD"

    @property
    def pip(self) -> float:
        digits = self.digits
        return self.point * (10 if digits in (3, 5) else 1)


class DataProvider:
    """Single gateway to MetaTrader 5 with a short-lived candle cache."""

    def __init__(self) -> None:
        self.connected = False
        self.error = "belum terhubung"
        self.account: dict = {}
        self.terminal: dict = {}
        self._cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._meta_cache: dict[str, SymbolMeta] = {}
        self._lock = threading.RLock()
        self._symbols: list[str] = list(config.MAJOR_SYMBOLS)
        self._init_attempts = 0

    # ------------------------------------------------------------------ init
    def initialize(self) -> bool:
        if not config.MT5_AVAILABLE:
            self.connected = False
            self.error = "paket MetaTrader5 tidak terpasang"
            return False
        try:
            ok = config.mt5.initialize()
            if not ok:
                code, msg = config.mt5.last_error()
                self.error = f"initialize gagal ({code}): {msg}"
                self._init_attempts += 1
                return False
            acc = config.mt5.account_info()
            term = config.mt5.terminal_info()
            self.account = acc._asdict() if acc else {}
            self.terminal = term._asdict() if term else {}
            self.connected = acc is not None
            self.error = "" if self.connected else "terminal tidak mengembalikan akun"
            if self.connected:
                self.refresh_symbols()
            return self.connected
        except Exception as exc:  # pragma: no cover
            self.error = f"{type(exc).__name__}: {exc}"
            self._init_attempts += 1
            return False

    def reconnect(self) -> bool:
        try:
            if config.MT5_AVAILABLE:
                config.mt5.shutdown()
        except Exception:
            pass
        time.sleep(0.2)
        return self.initialize()

    def ensure_connected(self) -> bool:
        if self.connected:
            try:
                info = config.mt5.terminal_info() if config.MT5_AVAILABLE else None
                if info is not None and info.connected:
                    return True
            except Exception:
                pass
        if self._init_attempts < 3:
            return self.initialize()
        return False

    def shutdown(self) -> None:
        try:
            if config.MT5_AVAILABLE:
                config.mt5.shutdown()
        except Exception:
            pass

    # --------------------------------------------------------------- symbols
    def refresh_symbols(self) -> list[str]:
        if not self.connected or not config.MT5_AVAILABLE:
            return self._symbols
        try:
            syms = config.mt5.symbols_get()
        except Exception:
            syms = None
        if not syms:
            return self._symbols
        names = sorted({s.name for s in syms})
        majors = [s for s in config.MAJOR_SYMBOLS if s in names]
        rest = [s for s in names if s not in majors]
        self._symbols = majors + rest
        return self._symbols

    def symbols(self) -> list[str]:
        return list(self._symbols)

    def select_symbol(self, symbol: str) -> bool:
        if not self.connected or not config.MT5_AVAILABLE:
            return False
        try:
            info = config.mt5.symbol_info(symbol)
            if info is None:
                if not config.mt5.symbol_select(symbol, True):
                    return False
                info = config.mt5.symbol_info(symbol)
            elif not info.visible:
                config.mt5.symbol_select(symbol, True)
            return info is not None
        except Exception:
            return False

    def meta(self, symbol: str) -> SymbolMeta:
        with self._lock:
            if symbol in self._meta_cache:
                return self._meta_cache[symbol]
        meta = SymbolMeta(symbol=symbol)
        if self.connected and config.MT5_AVAILABLE:
            try:
                info = config.mt5.symbol_info(symbol)
                if info is not None:
                    meta = SymbolMeta(
                        symbol=symbol,
                        digits=info.digits,
                        point=info.point or 0.01,
                        tick_value=info.trade_tick_value or 1.0,
                        tick_size=info.trade_tick_size or info.point or 0.01,
                        contract_size=info.trade_contract_size or 100_000.0,
                        spread=info.spread,
                        description=info.description or "",
                        currency=info.currency_profit or "USD",
                    )
            except Exception:
                pass
        with self._lock:
            self._meta_cache[symbol] = meta
        return meta

    def tick(self, symbol: str) -> dict:
        if self.connected and config.MT5_AVAILABLE:
            try:
                t = config.mt5.symbol_info_tick(symbol)
                if t is not None:
                    return {
                        "bid": t.bid,
                        "ask": t.ask,
                        "last": t.last,
                        "volume": t.volume,
                        "time": pd.Timestamp(t.time, unit="s"),
                    }
            except Exception:
                pass
        return {}

    # ------------------------------------------------------------------ data
    def rates(self, symbol: str, tf_name: str, count: int | None = None, ttl: float = 1.5) -> pd.DataFrame:
        tf_name = tf_name.upper()
        count = int(count or config.TF_BARS.get(tf_name, 800))
        key = (symbol, tf_name, count)
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1].copy()
        df = self._fetch_rates(symbol, tf_name, count)
        if df is None or df.empty:
            df = self._synthetic_rates(symbol, tf_name, count)
        with self._lock:
            self._cache[key] = (now, df)
        return df.copy()

    def _fetch_rates(self, symbol: str, tf_name: str, count: int) -> pd.DataFrame | None:
        if not self.connected or not config.MT5_AVAILABLE:
            return None
        tf = config.TIMEFRAMES.get(tf_name)
        if tf is None:
            return None
        try:
            self.select_symbol(symbol)
            arr = config.mt5.copy_rates_from_pos(symbol, tf, 0, int(count))
            if arr is None or len(arr) == 0:
                return None
            df = pd.DataFrame(arr)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            for col in OHLC_COLUMNS:
                if col not in df.columns:
                    df[col] = 0
            return df[OHLC_COLUMNS].copy()
        except Exception:
            return None

    def rates_range(self, symbol: str, tf_name: str, start: datetime, end: datetime) -> pd.DataFrame | None:
        if not self.connected or not config.MT5_AVAILABLE:
            return None
        tf = config.TIMEFRAMES.get(tf_name)
        if tf is None:
            return None
        try:
            arr = config.mt5.copy_rates_range(symbol, tf, start, end)
            if arr is None or len(arr) == 0:
                return None
            df = pd.DataFrame(arr)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df[OHLC_COLUMNS].copy()
        except Exception:
            return None

    def invalidate(self, symbol: str | None = None) -> None:
        with self._lock:
            if symbol is None:
                self._cache.clear()
            else:
                for k in list(self._cache):
                    if k[0] == symbol:
                        del self._cache[k]

    # -------------------------------------------------------------- fallback
    def _synthetic_rates(self, symbol: str, tf_name: str, count: int) -> pd.DataFrame:
        """Deterministic demo candles so the UI remains usable without MT5."""
        seed = abs(hash((symbol, tf_name))) % (2**32)
        rng = np.random.default_rng(seed)
        random.seed(seed)
        bases = {
            "XAUUSD": 4000.0, "XAGUSD": 48.0, "EURUSD": 1.085, "GBPUSD": 1.27,
            "USDJPY": 155.0, "AUDUSD": 0.66, "USDCAD": 1.36, "USDCHF": 0.88,
            "NZDUSD": 0.60, "BTCUSD": 68000.0, "ETHUSD": 3200.0, "US30": 42000.0,
            "NAS100": 20000.0, "SPX500": 5800.0, "USOIL": 78.0,
        }
        base = bases.get(symbol, 100.0)
        minutes = config.TF_MINUTES.get(tf_name, 60)
        vol = base * (0.0009 * math.sqrt(minutes))
        steps = rng.normal(0, vol, count).cumsum()
        drift = np.linspace(0, base * 0.004, count)
        close = base + steps + drift
        open_ = np.concatenate([[close[0]], close[:-1]])
        wick = np.abs(rng.normal(0, vol * 0.7, count))
        high = np.maximum(open_, close) + wick
        low = np.minimum(open_, close) - wick
        end = pd.Timestamp.now().floor(f"{max(1, minutes)}min") if minutes < 60 else pd.Timestamp.now().floor("h")
        times = pd.date_range(end=end, periods=count, freq=f"{minutes}min")
        volume = rng.integers(120, 2200, count)
        spread = np.full(count, 20)
        return pd.DataFrame({
            "time": times, "open": open_, "high": high, "low": low,
            "close": close, "tick_volume": volume, "spread": spread,
            "real_volume": np.zeros(count, dtype=int),
        })


_provider: DataProvider | None = None


def provider() -> DataProvider:
    global _provider
    if _provider is None:
        _provider = DataProvider()
    return _provider
