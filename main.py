"""Entry point for ICT Terminal Pro (GUI, selftest and report generation)."""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# A windowed PyInstaller build has no stdout/stderr. Keep print() calls safe.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = sys.stdout

# Make stdout robust on Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ictterm import config, data  # noqa: E402


def _set_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ICTTerminal.Pro.1")
    except Exception:
        pass


def _log_error(exc_text: str) -> Path:
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORT_DIR / "app_error.log"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{exc_text}\n")
    return path


def generate_reports(symbol: str, bars: int = 5000, threshold: float = 10.0,
                     rr: float = 2.0, risk: float = 1.0) -> list[Path]:
    from ictterm import backtest, reporting, signals

    provider = data.provider()
    if not provider.initialize():
        print(f"MT5 tidak terhubung ({provider.error}); laporan memakai data demo sintetis.")
    meta = provider.meta(symbol)
    results = {}
    for tf in config.TF_ORDER:
        df = provider.rates(symbol, tf, bars, ttl=0)
        if df is None or len(df) < 150:
            print(f"  {tf}: data tidak cukup, dilewati")
            continue
        result = backtest.run_backtest(
            symbol, tf, df, digits=meta.digits, point=meta.point,
            spread_points=meta.spread, rr=rr, threshold=threshold, risk_pct=risk,
        )
        results[tf] = result
        s = result.stats
        print(f"  {tf:>3}: {s['trades']:>3} trades · win {s['win_rate']:5.1f}% · "
              f"PF {s['profit_factor']:5.2f} · net {s['net_r']:+6.1f}R · DD {s['max_dd']:4.1f}%")
    if not results:
        raise RuntimeError("Tidak ada hasil backtest")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    paths: list[Path] = []
    print("Membuat gambar backtest…")
    for tf, result in results.items():
        out = config.REPORT_DIR / f"ict_backtest_{symbol}_{tf}_{stamp}.png"
        paths.append(reporting.render_backtest(result, out))
        print(f"  {out.name}")
    summary = config.REPORT_DIR / f"ict_summary_{symbol}_{stamp}.png"
    paths.append(reporting.render_summary(results, symbol, summary))
    print(f"  {summary.name}")

    sigs = signals.analyze_symbol(symbol, provider, meta.digits)
    best = sigs.get("H4") or sigs.get("H1") or (next(iter(sigs.values())) if sigs else None)
    if best is not None:
        forecast = config.REPORT_DIR / f"ict_forecast_{symbol}_{stamp}.png"
        paths.append(reporting.render_forecast(best, forecast))
        print(f"  {forecast.name}")
    if sigs:
        dash = config.REPORT_DIR / f"ict_dashboard_{symbol}_{stamp}.png"
        paths.append(reporting.render_dashboard(symbol, sigs, dash))
        print(f"  {dash.name}")
    provider.shutdown()
    print(f"\nSelesai: {len(paths)} gambar di {config.REPORT_DIR}")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ICT Terminal Pro")
    parser.add_argument("--selftest", action="store_true", help="buka UI sebentar lalu simpan screenshot")
    parser.add_argument("--reports", action="store_true", help="generate semua gambar backtest ICT")
    parser.add_argument("--symbol", default=config.DEFAULT_SYMBOL, help="simbol untuk --reports")
    parser.add_argument("--bars", type=int, default=5000, help="jumlah candle untuk --reports")
    parser.add_argument("--rr", type=float, default=2.0, help="target risk-reward backtest")
    parser.add_argument("--threshold", type=float, default=10.0, help="skor minimum backtest")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{config.APP_NAME} {config.APP_VERSION}")
        return 0

    _set_windows_app_id()

    if args.reports:
        try:
            generate_reports(args.symbol.upper(), bars=args.bars, threshold=args.threshold, rr=args.rr)
            return 0
        except Exception:
            text = traceback.format_exc()
            path = _log_error(text)
            print(text)
            print(f"Log: {path}")
            return 1

    from ictterm.app import run_app

    provider = data.provider()
    try:
        ok = provider.initialize()
        if ok:
            acc = provider.account or {}
            print(f"MT5 terhubung: {acc.get('server')} · akun {acc.get('login')} · "
                  f"balance {acc.get('balance'):,.2f} {acc.get('currency')}")
        else:
            print(f"MT5 tidak terhubung: {provider.error} · UI berjalan dengan demo data")
    except Exception:
        print(traceback.format_exc())

    try:
        return run_app(provider, selftest=args.selftest)
    except Exception:
        text = traceback.format_exc()
        path = _log_error(text)
        print(text)
        try:
            from pyqtgraph.Qt import QtWidgets
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
            QtWidgets.QMessageBox.critical(None, config.APP_NAME, f"Terjadi error:\n\n{text[-1500:]}\n\nLog: {path}")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
