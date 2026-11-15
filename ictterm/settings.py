"""Runtime settings shared by the UI, the trade engine and the report readers.

The only value kept here for now is the Auto Trade **magic number base**.  It is
stored in QSettings so a buyer can change it from the Auto Trade page without
editing code, and so every reader (history, trade report) uses the same value.
"""
from __future__ import annotations

MAGIC_BASE_DEFAULT = 770000
MAGIC_BASE_MIN = 100000
MAGIC_BASE_MAX = 999999
MAGIC_BASE_KEY = "auto_magic_base"
MAGIC_BASES_USED_KEY = "auto_magic_bases_used"
MAX_USED_BASES = 12


def _qsettings():
    from pyqtgraph.Qt import QtCore

    return QtCore.QSettings("ICT Terminal", "ICT Terminal Pro")


def normalize_magic_base(value) -> int:
    """Return a valid magic base, falling back to the default on bad input."""
    try:
        base = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return MAGIC_BASE_DEFAULT
    if base < MAGIC_BASE_MIN or base > MAGIC_BASE_MAX:
        return MAGIC_BASE_DEFAULT
    return base


def _parse_bases(raw) -> list[int]:
    if isinstance(raw, (list, tuple)):
        parts = raw
    else:
        parts = str(raw or "").replace(";", ",").split(",")
    out: list[int] = []
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        try:
            base = int(float(text))
        except ValueError:
            continue
        if MAGIC_BASE_MIN <= base <= MAGIC_BASE_MAX and base not in out:
            out.append(base)
    return out


def magic_base() -> int:
    """Currently configured magic base (default 770000)."""
    try:
        return normalize_magic_base(_qsettings().value(MAGIC_BASE_KEY, MAGIC_BASE_DEFAULT))
    except Exception:
        return MAGIC_BASE_DEFAULT


def set_magic_base(value, remember: bool = False) -> int:
    """Persist a new magic base.

    ``remember=True`` also records the base as "used" so history readers keep
    seeing trades opened with it.  Call it when the engine actually starts, not
    on every spin-box change, to avoid storing values the user only scrolled
    through.
    """
    base = normalize_magic_base(value)
    try:
        settings = _qsettings()
        settings.setValue(MAGIC_BASE_KEY, base)
        if remember:
            used = _parse_bases(settings.value(MAGIC_BASES_USED_KEY, ""))
            if base not in used:
                used.append(base)
            if len(used) > MAX_USED_BASES:
                used = used[-MAX_USED_BASES:]
            settings.setValue(MAGIC_BASES_USED_KEY, ",".join(str(b) for b in used))
    except Exception:
        pass
    return base


def magic_bases(current: int | None = None) -> list[int]:
    """Every base that may own orders: current, default and previously used.

    Reports must still see trades that were opened before the buyer changed the
    magic number, so the readers build their magic map from this list.
    """
    bases = [normalize_magic_base(current)] if current is not None else [magic_base()]
    bases.append(MAGIC_BASE_DEFAULT)
    try:
        bases.extend(_parse_bases(_qsettings().value(MAGIC_BASES_USED_KEY, "")))
    except Exception:
        pass
    return list(dict.fromkeys(bases))
