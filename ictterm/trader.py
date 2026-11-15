"""Live multi-symbol auto-trading engine for the Python app (not an MQL5 EA).

The engine evaluates the same closed-bar signal as the backtester and sends
market orders through the MetaTrader5 Python API. It is deliberately guarded:
one position per timeframe/direction/symbol, global total-risk cap, max-drawdown
halt, spread/stop-level checks, and explicit UI confirmation before starting.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pyqtgraph.Qt import QtCore

from . import config, data, ict
from .backtest import SignalEvaluator
from .telegram import TelegramNotifier

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover
    mt5 = None


TF_MAGIC_OFFSET = {tf: i + 1 for i, tf in enumerate(config.TF_ORDER)}


@dataclass
class AutoTradeConfig:
    symbols: list[str] = field(default_factory=lambda: [config.DEFAULT_SYMBOL])
    timeframes: list[str] = field(default_factory=lambda: ["M15", "H1", "H4"])
    risk_pct: float = 0.5
    max_total_risk_pct: float = 2.0
    max_drawdown_pct: float = 4.0
    threshold: float = 7.0
    tp_mode: str = "RR"                 # "RR" or "STRUCTURE"
    rr: float = 1.5
    max_spread_points: int = 500
    max_bars: int = 45
    session_filter: bool = False
    history_bars: int = 3000
    magic_base: int = 770000
    slippage: int = 30
    execute: bool = True                # UI confirmation controls this
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""

    def normalized_symbols(self) -> list[str]:
        return list(dict.fromkeys(s.strip().upper() for s in self.symbols if s and s.strip()))

    @property
    def symbol(self) -> str:
        symbols = self.normalized_symbols()
        return symbols[0] if symbols else config.DEFAULT_SYMBOL

    def magic(self, tf: str, direction: str | None = None) -> int:
        """One magic per timeframe AND direction (same set for every symbol).

        MT5 position identity is (symbol, ticket), so the same magic on two
        different symbols cannot collide.  Keeping the magic TF/direction based
        also preserves compatibility with orders from the previous single-symbol
        version of this app.
        """
        offset = TF_MAGIC_OFFSET.get(tf, 0)
        if direction and direction.lower() in ("short", "sell"):
            return self.magic_base + 1100 + offset
        return self.magic_base + 1000 + offset

    def legacy_magic(self, tf: str) -> int:
        return self.magic_base + TF_MAGIC_OFFSET.get(tf, 0)


class AutoTrader(QtCore.QThread):
    log_message = QtCore.pyqtSignal(str)
    state_changed = QtCore.pyqtSignal(dict)
    positions_changed = QtCore.pyqtSignal(object)
    signal_changed = QtCore.pyqtSignal(str, str, object)  # symbol, tf, data
    trade_sent = QtCore.pyqtSignal(str, str)              # symbol, tf

    def __init__(self, provider: data.DataProvider, cfg: AutoTradeConfig, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.cfg = cfg
        self.symbols = cfg.normalized_symbols() or [config.DEFAULT_SYMBOL]
        try:
            base = int(cfg.magic_base)
        except Exception:
            base = 770000
        self._magic_bases: list[int] = [base]
        try:
            from .settings import magic_bases as configured_magic_bases

            for used_base in configured_magic_bases(base):
                if used_base not in self._magic_bases:
                    self._magic_bases.append(used_base)
        except Exception:
            pass
        self._stop = threading.Event()
        self._mt5_lock = threading.RLock()
        self._halted = False
        self._halt_reason = ""
        self._peak_equity = 0.0
        self._last_closed: dict[tuple[str, str], pd.Timestamp] = {}
        self._next_poll: dict[tuple[str, str], float] = {}
        self._poll_interval = 5.5
        self._was_open: dict[tuple[str, str, str], bool] = {
            (symbol, tf, side): False
            for symbol in self.symbols
            for tf in cfg.timeframes
            for side in ("long", "short")
        }
        self._cooldown_until: dict[str, float] = {
            f"{symbol}:{tf}:{side}": 0.0
            for symbol in self.symbols
            for tf in cfg.timeframes
            for side in ("long", "short")
        }
        self._last_order_time: dict[str, float] = {
            f"{symbol}:{tf}:{side}": 0.0
            for symbol in self.symbols
            for tf in cfg.timeframes
            for side in ("long", "short")
        }
        self._last_positions: list[dict] = []
        self._last_log: dict[str, float] = {}
        self.notifier: TelegramNotifier | None = None
        if cfg.telegram_enabled and cfg.telegram_token and cfg.telegram_chat_id:
            self.notifier = TelegramNotifier(cfg.telegram_token, cfg.telegram_chat_id)
            self.notifier.error.connect(self.log_message.emit)

    # ---------------------------------------------------------------- helpers
    def _log(self, text: str, key: str | None = None) -> None:
        if key:
            now = time.time()
            if now - self._last_log.get(key, 0) < 20:
                return
            self._last_log[key] = now
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_message.emit(f"[{stamp}] {text}")

    def _notify(self, text: str) -> None:
        if self.notifier is not None:
            self.notifier.send(text)

    def _emit_signal(self, symbol: str, tf: str, payload: dict) -> None:
        data = dict(payload)
        data["symbol"] = symbol
        self.signal_changed.emit(symbol, tf, data)

    def _account(self) -> Any:
        try:
            return mt5.account_info() if mt5 is not None else None
        except Exception:
            return None

    def _terminal_ok(self) -> bool:
        if mt5 is None or not self.provider.connected:
            return False
        try:
            term = mt5.terminal_info()
            acc = mt5.account_info()
            return bool(term and term.connected and term.trade_allowed and acc and acc.trade_allowed)
        except Exception:
            return False

    def _magics_for_tf(self, tf: str) -> set[int]:
        """Magic of one TF for the active base and every previously used base.

        The magic number is editable in Auto Trade settings.  Positions opened
        before a change must still be managed (SL/TP bookkeeping, STOP ALL), so
        the engine recognises the old bases too.
        """
        offset = TF_MAGIC_OFFSET.get(tf, 0)
        magics: set[int] = set()
        for base in self._magic_bases:
            magics.add(base + offset)               # legacy / BUY lama
            magics.add(base + 1000 + offset)        # BUY baru
            magics.add(base + 1100 + offset)        # SELL baru
        return magics

    def _all_magics(self) -> set[int]:
        magics: set[int] = set()
        for tf in config.TF_ORDER:
            magics |= self._magics_for_tf(tf)
        return magics

    def _our_positions(self, symbols: list[str] | None = None,
                       all_symbols: bool = False) -> list[Any]:
        if mt5 is None:
            return []
        try:
            positions = mt5.positions_get() or []
        except Exception:
            return []
        magics = self._all_magics()
        allowed = None if all_symbols else set(symbols or self.symbols)
        return [
            p for p in positions
            if p.magic in magics and (allowed is None or p.symbol in allowed)
        ]

    def _position_tf(self, pos: Any) -> str | None:
        for tf in config.TF_ORDER:
            if pos.magic in self._magics_for_tf(tf):
                return tf
        return None

    @staticmethod
    def _position_side(pos: Any) -> str:
        return "long" if mt5 is not None and pos.type == mt5.POSITION_TYPE_BUY else "short"

    def _positions_for(self, symbol: str, tf: str, direction: str | None = None) -> list[Any]:
        out = []
        for p in self._our_positions(symbols=[symbol]):
            if p.symbol != symbol or self._position_tf(p) != tf:
                continue
            if direction is None or self._position_side(p) == direction:
                out.append(p)
        return out

    @staticmethod
    def _side_key(symbol: str, tf: str, side: str) -> str:
        return f"{symbol}:{tf}:{side}"

    def _filling(self, info: Any) -> int:
        flags = int(getattr(info, "filling_mode", 1) or 1)
        if flags & 1:       # FOK
            return mt5.ORDER_FILLING_FOK
        if flags & 2:       # IOC
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def _normalize_lot(self, info: Any, raw: float) -> float:
        step = float(info.volume_step or 0.01)
        vmin = float(info.volume_min or step)
        vmax = float(info.volume_max or 100.0)
        lot = np.floor(raw / step) * step
        lot = round(lot, 8)
        if lot < vmin:
            return 0.0
        return min(lot, vmax)

    def _loss_per_lot(self, info: Any, risk_price: float) -> float:
        tick_size = float(info.trade_tick_size or info.point or 0.01)
        tick_value = float(info.trade_tick_value or 1.0)
        if tick_size <= 0 or tick_value <= 0:
            return 0.0
        return (risk_price / tick_size) * tick_value

    def _open_risk_amount(self) -> float:
        """Global open risk across every app position, including old symbols."""
        total = 0.0
        for p in self._our_positions(all_symbols=True):
            info = mt5.symbol_info(p.symbol)
            if info is None or p.sl <= 0:
                continue
            risk_price = abs(float(p.price_open) - float(p.sl))
            total += self._loss_per_lot(info, risk_price) * float(p.volume)
        return total

    def _check_new_bar(self, symbol: str, tf: str) -> tuple[pd.DataFrame | None, bool]:
        key = (symbol, tf)
        now = time.time()
        if now < self._next_poll.get(key, 0.0):
            return None, False
        # Stagger symbols/TFs so a 12-symbol scan does not hit MT5 all at once.
        jitter = (hash(key) % 40) / 10.0
        self._next_poll[key] = now + self._poll_interval + jitter
        df = self.provider.rates(symbol, tf, self.cfg.history_bars, ttl=0)
        if df is None or len(df) < 80:
            return None, False
        # The last bar is still forming; evaluate the last CLOSED bar.
        if len(df) < 3:
            return None, False
        closed = df.iloc[:-1].reset_index(drop=True)
        if len(closed) < 80:
            return closed, False
        closed_time = pd.Timestamp(closed["time"].iloc[-1])
        previous = self._last_closed.get(key)
        if previous is None:
            self._last_closed[key] = closed_time
            return closed, False
        if closed_time <= previous:
            return closed, False
        self._last_closed[key] = closed_time
        return closed, True

    # ----------------------------------------------------------------- events
    def run(self) -> None:  # noqa: D401
        self._log(
            f"Engine started · {len(self.symbols)} simbol: {', '.join(self.symbols)} "
            f"· TF {', '.join(self.cfg.timeframes)} · risk global"
        )
        for symbol in self.symbols:
            try:
                self.provider.select_symbol(symbol)
            except Exception:
                pass
        acc = self._account()
        self._peak_equity = float(acc.equity) if acc else 0.0
        self._emit_state()
        # Establish the current closed bar without trading on it.
        for symbol in self.symbols:
            for tf in self.cfg.timeframes:
                self._check_new_bar(symbol, tf)
        self._log("Menunggu penutupan candle baru pada TF/simbol yang dipilih untuk entry pertama.")
        while not self._stop.is_set():
            try:
                self._step()
            except Exception as exc:
                self._log(f"Engine error: {type(exc).__name__}: {exc}")
            self._emit_state()
            self._stop.wait(2.0)
        if self.notifier is not None:
            self.notifier.close()
        self._log("Engine stopped.")
        self._emit_state()

    def _step(self) -> None:
        if not self._terminal_ok():
            self._log("Auto trade menunggu: MT5 tidak terhubung / trade_allowed=false.", key="conn")
            self._emit_positions()
            return
        acc = self._account()
        if acc is None:
            return
        equity = float(acc.equity)
        self._peak_equity = max(self._peak_equity, equity)
        dd = (self._peak_equity - equity) / self._peak_equity * 100 if self._peak_equity > 0 else 0.0
        if dd >= self.cfg.max_drawdown_pct and not self._halted:
            self._halted = True
            self._halt_reason = f"Max DD {dd:.2f}% ≥ {self.cfg.max_drawdown_pct:.2f}% (global)"
            self._log(f"STOP ENTRY: {self._halt_reason}. Posisi lama tetap dikelola SL/TP.")
        if self._halted:
            self._manage_positions(acc)
            self._emit_positions()
            return

        self._manage_positions(acc)
        for symbol in self.symbols:
            for tf in self.cfg.timeframes:
                closed, is_new = self._check_new_bar(symbol, tf)
                if closed is None:
                    continue
                if not is_new:
                    continue
                self._evaluate_tf(symbol, tf, closed, acc, equity)

    def _evaluate_tf(self, symbol: str, tf: str, closed: pd.DataFrame,
                     acc: Any, equity: float) -> None:
        bar_label = pd.Timestamp(closed["time"].iloc[-1]).strftime("%d %b %H:%M")
        # Evaluate even when execute=False so the signal panel can be tested safely.
        evaluator = SignalEvaluator(
            closed, threshold=self.cfg.threshold,
            session_filter=self.cfg.session_filter,
            zone_limit=None, sweep_limit=None,
        )
        i = len(closed) - 1
        sig = evaluator.evaluate(i)
        if not sig:
            self._emit_signal(symbol, tf, {"signal": "WAIT", "reason": "tidak ada setup"})
            self._log(f"{symbol} · {tf} {bar_label} · WAIT — tidak ada setup")
            return
        side = sig["dir"]
        cooldown_key = self._side_key(symbol, tf, side)
        # One position per timeframe *per direction per symbol*: BUY and SELL may coexist.
        if self._positions_for(symbol, tf, side):
            self._emit_signal(symbol, tf, {
                "signal": "HOLD", "reason": f"posisi {side.upper()} TF masih terbuka",
            })
            self._log(
                f"{symbol} · {tf} {bar_label} · {side.upper()} skor {sig['score']:.1f} "
                f"· HOLD — posisi {side.upper()} TF masih terbuka"
            )
            return
        if time.time() < self._cooldown_until.get(cooldown_key, 0.0):
            self._emit_signal(symbol, tf, {
                "signal": "SKIP", "score": sig["score"],
                "reason": f"cooldown {side.upper()} setelah exit",
            })
            self._log(
                f"{symbol} · {tf} {bar_label} · {side.upper()} skor {sig['score']:.1f} "
                f"· SKIP — cooldown {side.upper()}"
            )
            return
        if time.time() - self._last_order_time.get(cooldown_key, 0.0) < 5.0:
            return

        info = mt5.symbol_info(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if info is None or tick is None:
            self._log(f"{symbol} · {tf} {bar_label} · SKIP — data tick/symbol tidak tersedia")
            return
        prefix = (
            f"{symbol} · {tf} {bar_label} · {sig['dir'].upper()} "
            f"skor {sig['score']:.1f} ({sig.get('setup', '-')})"
        )

        def skip(reason: str) -> None:
            self._emit_signal(symbol, tf, {
                "signal": "SKIP", "score": sig["score"], "reason": reason,
            })
            self._log(f"{prefix} · SKIP — {reason}")

        digits = int(info.digits)
        price_now = tick.ask if sig["dir"] == "long" else tick.bid
        self._notify(
            f"🔔 SINYAL ICT\n"
            f"{symbol} · {tf}\n"
            f"{sig['dir'].upper()} · skor {sig['score']:.1f}\n"
            f"Setup: {sig.get('setup', '-')}\n"
            f"Harga: {price_now:.{digits}f}"
        )
        spread_points = int(round((tick.ask - tick.bid) / info.point)) if info.point else 0
        if spread_points > self.cfg.max_spread_points:
            skip(f"spread {spread_points} > {self.cfg.max_spread_points}")
            return

        long = sig["dir"] == "long"
        entry = float(tick.ask if long else tick.bid)
        atr = float(evaluator.atr[i])
        zone = sig.get("zone")
        if long:
            base = float(zone.bottom) if zone is not None else float(np.min(evaluator.l[max(0, i - 2):i + 1]))
            stop = min(base, float(evaluator.l[i])) - atr * 0.25
            risk = entry - stop
            if risk < atr * 0.45:
                stop = entry - atr * 0.9
                risk = entry - stop
            elif risk > atr * 3.2:
                skip("SL terlalu jauh (>3.2 ATR)")
                return
            if self.cfg.tp_mode == "STRUCTURE":
                target = float(evaluator.ctx.get("liquidity_above", 0.0))
                if target <= entry + risk * 0.8:
                    skip("target struktur tidak valid / <0.8R")
                    return
            else:
                target = entry + risk * self.cfg.rr
        else:
            base = float(zone.top) if zone is not None else float(np.max(evaluator.h[max(0, i - 2):i + 1]))
            stop = max(base, float(evaluator.h[i])) + atr * 0.25
            risk = stop - entry
            if risk < atr * 0.45:
                stop = entry + atr * 0.9
                risk = stop - entry
            elif risk > atr * 3.2:
                skip("SL terlalu jauh (>3.2 ATR)")
                return
            if self.cfg.tp_mode == "STRUCTURE":
                target = float(evaluator.ctx.get("liquidity_below", 0.0))
                if target >= entry - risk * 0.8:
                    skip("target struktur tidak valid / <0.8R")
                    return
            else:
                target = entry - risk * self.cfg.rr

        if risk <= 0 or not np.isfinite(risk):
            skip("risiko tidak valid")
            return
        stops = float(info.trade_stops_level or 0) * float(info.point or 0)
        if stops > 0 and risk < stops * 1.05:
            skip(f"SL di bawah stop level broker ({stops:.3f})")
            return
        rr = abs(target - entry) / risk

        loss_lot = self._loss_per_lot(info, risk)
        if loss_lot <= 0:
            skip("nilai tick tidak valid")
            return
        raw_lot = (equity * self.cfg.risk_pct / 100.0) / loss_lot
        lot = self._normalize_lot(info, raw_lot)
        if lot <= 0:
            skip("lot di bawah volume_min")
            return
        new_risk = loss_lot * lot
        max_total = equity * self.cfg.max_total_risk_pct / 100.0
        if self._open_risk_amount() + new_risk > max_total + 1e-6:
            skip("max total risk global tercapai")
            return

        # Margin check.
        try:
            margin = mt5.order_calc_margin(
                mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL,
                symbol, lot, entry,
            )
            if margin is None or margin > float(acc.margin_free) * 0.9:
                skip("margin tidak cukup")
                return
        except Exception:
            pass

        self._emit_signal(symbol, tf, {
            "signal": sig["dir"].upper(), "score": sig["score"],
            "rr": rr, "entry": entry, "sl": stop, "tp": target,
            "lot": lot, "reason": sig["setup"],
        })
        self._log(f"{prefix} · VALID -> {'kirim order' if self.cfg.execute else 'signal only'}")
        if self.cfg.execute:
            self._send_order(symbol, tf, long, lot, entry, stop, target, info, sig)

    def _send_order(self, symbol: str, tf: str, long: bool, lot: float, price: float,
                    stop: float, target: float, info: Any, sig: dict) -> None:
        if mt5 is None:
            return
        digits = int(info.digits)
        side_key = self._side_key(symbol, tf, "long" if long else "short")
        sym_tag = "".join(ch for ch in symbol if ch.isalnum())[:10]
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY if long else mt5.ORDER_TYPE_SELL,
            "price": round(price, digits),
            "sl": round(stop, digits),
            "tp": round(target, digits),
            "deviation": int(self.cfg.slippage),
            "magic": int(self.cfg.magic(tf, "long" if long else "short")),
            "comment": f"ICT-{sym_tag}-{tf}-{'B' if long else 'S'}"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        }
        with self._mt5_lock:
            result = mt5.order_send(request)
        if result is None:
            self._log(f"{symbol} · {tf}: order_send None · {mt5.last_error()}")
            return
        if result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            self._log(
                f"ORDER {symbol} {tf} {'BUY' if long else 'SELL'} {lot:.2f} @ {price:.{digits}f} "
                f"SL {stop:.{digits}f} TP {target:.{digits}f} · ticket {result.order}"
            )
            self._notify(
                f"✅ ORDER OPENED\n"
                f"{symbol} · {tf}\n"
                f"{'BUY' if long else 'SELL'} {lot:.2f} lot\n"
                f"Entry: {price:.{digits}f}\n"
                f"SL: {stop:.{digits}f}\n"
                f"TP: {target:.{digits}f}\n"
                f"Ticket: {result.order}"
            )
            self._last_order_time[side_key] = time.time()
            self._cooldown_until[side_key] = 0.0
            self.trade_sent.emit(symbol, tf)
        else:
            self._log(
                f"ORDER GAGAL {symbol} {tf}: retcode {result.retcode} · {result.comment} "
                f"({sig.get('setup', '')})"
            )

    def _manage_positions(self, acc: Any) -> None:
        if mt5 is None:
            return
        now = time.time()
        for p in self._our_positions(all_symbols=True):
            tf = self._position_tf(p)
            if tf is None:
                continue
            limit = self.cfg.max_bars * config.TF_MINUTES.get(tf, 60) * 60
            if limit > 0 and now - float(p.time) > limit:
                self._close_position(p, f"timeout {self.cfg.max_bars} bar")
                continue
        # Cooldown after a position closes (2 bars) per symbol/TF/direction.
        current = {
            (p.symbol, self._position_tf(p), self._position_side(p))
            for p in self._our_positions(all_symbols=True)
        }
        for symbol in self.symbols:
            for tf in self.cfg.timeframes:
                for side in ("long", "short"):
                    key = (symbol, tf, side)
                    was = self._was_open.get(key, False)
                    now_open = key in current
                    if was and not now_open:
                        ckey = self._side_key(symbol, tf, side)
                        self._cooldown_until[ckey] = now + 2 * config.TF_MINUTES.get(tf, 60) * 60
                        self._log(f"{symbol} {tf}: posisi {side.upper()} tertutup, cooldown 2 bar")
                    self._was_open[key] = now_open
        self._emit_positions()

    def _close_position(self, p: Any, reason: str = "manual") -> bool:
        if mt5 is None:
            return False
        info = mt5.symbol_info(p.symbol)
        tick = mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None:
            return False
        closing_buy = p.type == mt5.POSITION_TYPE_SELL
        price = tick.ask if closing_buy else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": float(p.volume),
            "type": mt5.ORDER_TYPE_BUY if closing_buy else mt5.ORDER_TYPE_SELL,
            "position": int(p.ticket),
            "price": round(float(price), int(info.digits)),
            "deviation": int(self.cfg.slippage),
            "magic": int(p.magic),
            "comment": "ICT close"[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(info),
        }
        with self._mt5_lock:
            result = mt5.order_send(request)
        if result is not None and result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            self._log(f"CLOSE {p.symbol} ticket {p.ticket} · {reason}")
            return True
        detail = f"retcode {getattr(result, 'retcode', None)} · {getattr(result, 'comment', '')}"
        self._log(f"CLOSE GAGAL {p.symbol} ticket {p.ticket}: {detail}")
        return False

    # ------------------------------------------------------------- public API
    def request_stop(self) -> None:
        self._stop.set()

    def stop_all(self) -> int:
        if mt5 is None:
            return 0
        closed = 0
        for p in self._our_positions(all_symbols=True):
            if self._close_position(p, "STOP ALL"):
                closed += 1
        self._emit_positions()
        return closed

    def reset_halt(self) -> None:
        self._halted = False
        self._halt_reason = ""
        acc = self._account()
        self._peak_equity = float(acc.equity) if acc else 0.0
        self._log("Halt di-reset. Entry diizinkan kembali.")

    def _emit_positions(self) -> None:
        rows = []
        for p in self._our_positions(all_symbols=True):
            tf = self._position_tf(p) or "?"
            rows.append({
                "symbol": p.symbol,
                "tf": tf, "ticket": p.ticket,
                "dir": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                "volume": p.volume, "price": p.price_open,
                "sl": p.sl, "tp": p.tp, "profit": p.profit,
                "time": datetime.fromtimestamp(p.time).strftime("%d %b %H:%M"),
            })
        rows.sort(key=lambda r: (r["symbol"], r["time"]))
        self._last_positions = rows
        self.positions_changed.emit(rows)

    def _emit_state(self) -> None:
        acc = self._account()
        equity = float(acc.equity) if acc else 0.0
        dd = (self._peak_equity - equity) / self._peak_equity * 100 if self._peak_equity > 0 else 0.0
        risk_amount = self._open_risk_amount() if self._terminal_ok() else 0.0
        self.state_changed.emit({
            "running": not self._stop.is_set(),
            "connected": self.provider.connected,
            "trade_ok": self._terminal_ok(),
            "equity": equity,
            "balance": float(acc.balance) if acc else 0.0,
            "drawdown": dd,
            "halted": self._halted,
            "halt_reason": self._halt_reason,
            "open_risk": risk_amount,
            "open_risk_pct": (risk_amount / equity * 100) if equity > 0 else 0.0,
            "positions": len(self._last_positions),
            "symbols": list(self.symbols),
            "symbol_count": len(self.symbols),
            "server": getattr(acc, "server", "") if acc else "",
            "login": getattr(acc, "login", "") if acc else "",
            "mode": "DEMO" if acc and int(acc.trade_mode) == 0 else ("REAL" if acc else "OFFLINE"),
        })
