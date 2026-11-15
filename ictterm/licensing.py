"""Offline licensing, 30-day trial and edition limits for ICT Terminal Pro.

Design
------
* **Offline** – the customer activates with a key that is bound to the
  machine (HWID).  No server, no internet connection required.
* **Trial** – 30 days full PRO on the first run of a new laptop.
* **Limits only** – the auto-trade engine logic is *not* modified.  The
  limits are clamped onto ``AutoTradeConfig`` right before the engine
  starts (see :func:`apply_autotrade_limits`) and onto the widgets of the
  Auto Trade tab (see ``AutoTradeTab.refresh_license_limits``).
* **Tamper resistant (casual)** – trial/activation records are mirrored in
  the registry, in ``%APPDATA%``, ``%LOCALAPPDATA%``, ``%PROGRAMDATA%`` and
  in the app folder, and each copy is protected with HMAC-SHA256.  Clock
  rollback is detected as well.

Key format (32 base32 characters, 20 bytes payload) — **legacy v2, no longer
issued**::

    ICT-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX

Current key format (v3, Ed25519-signed, 75 bytes = 120 base32 characters)::

    ICT3-XXXX-XXXX-... (30 groups of 4)

    byte  0      : version (3)
    byte  1..5   : HWID tag (5 bytes, sha256(hwid + secret))
    byte  6      : plan id
    byte  7..8   : duration in days, counted from activation (0 = lifetime)
    byte  9      : serial 0..255
    byte 10..73  : Ed25519 signature over ``b"ICTKEY3" + header``
    byte 74      : reserved (0)

Only the **public** key is embedded here.  Keys can be minted only with the
vendor private key (``tools/vendor/ed25519_private.key`` or the
``ICT_LICENSE_PRIVATE_KEY`` environment variable), so unpacking the shipped
exe can never produce a working key generator.  v2 (HMAC) keys are still
accepted for licences **already stored** on a machine, but new activations
require a v3 key; the vendor key generator can convert an old key and carry
the remaining days over (see ``tools/convert_keys.py``).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import platform
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
TRIAL_DAYS = 30            # total masa gratis
TRIAL_PRO_DAYS = 7         # hari pertama: fitur PRO penuh
TRIAL_LITE_DAYS = TRIAL_DAYS - TRIAL_PRO_DAYS   # 23 hari terbatas
KEY_PREFIX = "ICT"
EPOCH_DAY = date(2024, 1, 1)
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 32 chars, no 0/1/I/O

# ---- current keys (v3): Ed25519 signature over a 10-byte header ----------
_KEY_VERSION = 3
_KEY_HEADER_LEN = 10
_KEY_SIG_LEN = 64
_KEY_BODY_LEN = 75            # header + signature + 1 reserved byte
_KEY_CHARS = 120              # 75 bytes -> 120 base32 chars (30 groups of 4)
_SIGN_DOMAIN = b"ICTKEY3"

# Public half of the vendor signing key.  The private half is kept by the
# vendor only (tools/vendor/ed25519_private.key) and is never shipped.
PUBLIC_KEY_HEX = "6e1d052b66297cb65b67f10098de09d83c021e6f34fdfc665ed308cfea209159"

# ---- legacy keys (v2): 80-bit HMAC tag ----------------------------------
_V2_VERSION = 2
_V2_PAYLOAD_LEN = 20
_V2_MAC_LEN = 10
_V2_CHARS = 32

# Anti-reset: GUID "kosong" untuk menyimpan salinan catatan lisensi di
# registry, plus nama value yang dipakai di beberapa tempat.
_ANCHOR_GUID = "{2E9F4C1A-7B3D-4E52-9C11-6D8A4F0B7C21}"

PLAN_NAMES = {
    1: "PRO 1 Bulan",
    2: "PRO 3 Bulan",
    3: "PRO 6 Bulan",
    4: "PRO 1 Tahun",
    5: "PRO Lifetime",
    9: "PRO Custom",
}

# Change these two lines when you want to re-key the product.
_S1 = bytes.fromhex("eddade9addf80969eb99991641e567aba705e59d544dba85008126b331fb5eaf")
_M1 = bytes.fromhex("fa97ffdd1d309314cdca4b19d882b022c19087bdf841568b95d3d556a39d6b5a")
_SALT = bytes.fromhex("13a2145eb9973e6c63edf3144f52a447d91e955c2768a35b088f5297a313bd6b")


def _secret() -> bytes:
    """De-obfuscated HMAC secret (kept out of plain sight in the binary)."""
    return bytes(a ^ b for a, b in zip(_S1, _M1))


def _hmac(data: bytes) -> bytes:
    return hmac.new(_secret(), _SALT + data, hashlib.sha256).digest()


# ---------------------------------------------------------------------------
# edition limits
# ---------------------------------------------------------------------------
LIMITS_PRO = {
    "max_symbols": 12,
    "risk_pct": None,          # None -> user adjustable
    "risk_max": 5.0,
    "total_risk_max": 10.0,
    "dd_max": 50.0,
    "threshold": None,
    "rr": None,
    "tp_mode": None,
    "lock_symbols": False,
    "lock_settings": False,
    "lock_bot": False,
}

# Masa gratis terbatas (hari ke-8 .. hari ke-30)
LIMITS_FREE = {
    "max_symbols": 5,
    "risk_pct": 0.1,           # locked 0.1% per trade
    "risk_max": 0.1,
    "total_risk_max": 4.0,
    "dd_max": 4.0,
    "threshold": 10.0,         # locked minimum score
    "rr": 1.5,                 # locked RR
    "tp_mode": "RR",           # locked TP mode
    "lock_symbols": True,
    "lock_settings": True,     # all setting widgets disabled
    "lock_bot": False,
}

# Masa gratis habis: bot auto trade dimatikan total
LIMITS_LOCKED = dict(LIMITS_FREE, lock_bot=True)


def limits_for(tier: str) -> dict:
    """``tier``: ``pro`` (key / 7 hari pertama), ``lite`` (23 hari), ``locked``."""
    if tier == "pro":
        return dict(LIMITS_PRO)
    if tier == "locked":
        return dict(LIMITS_LOCKED)
    return dict(LIMITS_FREE)


# ---------------------------------------------------------------------------
# HWID
# ---------------------------------------------------------------------------
def _volume_serial() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        serial = ctypes.c_uint(0)
        root = os.environ.get("SystemDrive", "C:") + "\\"
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), None, 0,
            ctypes.byref(serial), None, None, None, 0,
        )
        return f"{serial.value:08X}" if ok else ""
    except Exception:
        return ""


def _machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except Exception:
        return ""


def machine_id() -> str:
    """Stable per-machine identifier, formatted as ``XXXX-XXXX-XXXX-XXXX``."""
    raw = "|".join((
        platform.node(),
        platform.machine(),
        platform.processor(),
        _volume_serial(),
        _machine_guid(),
        str(uuid.getnode()),
    ))
    value = int.from_bytes(_hmac(b"HWID" + raw.encode("utf-8", "ignore"))[:10], "big")
    text = "".join(ALPHABET[(value >> (5 * (15 - i))) & 31] for i in range(16))
    return "-".join(text[i:i + 4] for i in range(0, 16, 4))


def _hwid_tag(hwid: str) -> bytes:
    return _hmac(b"TAG" + hwid.upper().encode("ascii", "ignore"))[:5]


# ---------------------------------------------------------------------------
# key encoding / decoding
# ---------------------------------------------------------------------------
def _b32(payload: bytes, chars: int) -> str:
    """Base32 with the custom alphabet; ``chars`` must cover the payload."""
    value = int.from_bytes(payload, "big")
    return "".join(ALPHABET[(value >> (5 * (chars - 1 - i))) & 31] for i in range(chars))


def _unb32(text: str, size: int) -> bytes | None:
    chars = (size * 8 + 4) // 5
    if len(text) != chars:
        return None
    value = 0
    for ch in text:
        idx = ALPHABET.find(ch)
        if idx < 0:
            return None
        value = (value << 5) | idx
    try:
        return value.to_bytes(size, "big")
    except OverflowError:
        return None


def clean_key(text: str) -> str:
    """Normalise user input: strip prefix, spaces and dashes, upper-case."""
    raw = re.sub(r"[^0-9A-Za-z]", "", str(text or "")).upper()
    for prefix, size in (("ICT3", _KEY_CHARS), (KEY_PREFIX, _KEY_CHARS),
                         (KEY_PREFIX, _V2_CHARS)):
        if raw.startswith(prefix) and len(raw) == size + len(prefix):
            return raw[len(prefix):]
    return raw


def format_key(text: str) -> str:
    body = clean_key(text)
    prefix = "ICT3" if len(body) == _KEY_CHARS else KEY_PREFIX
    grouped = "-".join(body[i:i + 4] for i in range(0, len(body), 4))
    return f"{prefix}-{grouped}"


def _private_key_hex() -> str:
    """Locate the vendor private key (hex).  Never present in the app build."""
    env = os.environ.get("ICT_LICENSE_PRIVATE_KEY", "").strip()
    if env:
        return env
    root = Path(__file__).resolve().parent.parent
    candidates = [root / "tools" / "vendor" / "ed25519_private.key"]
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates += [base / "keys" / "ed25519_private.key",
                       base / "vendor" / "ed25519_private.key"]
    for path in candidates:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    raise RuntimeError(
        "Private key lisensi tidak ditemukan. Letakkan ed25519_private.key di "
        "tools\\vendor\\ (atau dist\\keys\\ untuk ICT-Keygen.exe) / set "
        "ICT_LICENSE_PRIVATE_KEY."
    )


def _sign_key(message: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    raw = bytes.fromhex(_private_key_hex())
    if len(raw) != 32:
        raise RuntimeError("Private key Ed25519 harus 32 byte (64 karakter hex).")
    return Ed25519PrivateKey.from_private_bytes(raw).sign(message)


def _verify_key(message: bytes, signature: bytes) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX)).verify(
            signature, message
        )
        return True
    except (InvalidSignature, ValueError):
        return False


def build_key(hwid: str, plan: int, days: int | None, serial: int = 1,
              start: date | None = None) -> str:
    """Create a v3 activation key (vendor key generator only).

    The key stores the **duration** in days, not an absolute date: the
    validity starts counting when the customer activates the key.
    ``days=None`` or ``0`` creates a lifetime key.  ``start`` is unused and
    kept only for backwards compatibility of old call sites.

    Requires the vendor private key; raises :class:`RuntimeError` without it.
    """
    return build_key_from_tag(_hwid_tag(hwid), plan, days, serial)


def build_key_from_tag(tag: bytes, plan: int, days: int | None,
                       serial: int = 1) -> str:
    """Build a v3 key from a 5-byte HWID tag.

    Used by :func:`build_key` and by the v2 -> v3 migration tool, which only
    has the tag stored inside the old key.
    """
    if days is None or int(days) <= 0:
        dur_days = 0                      # 0 -> lifetime
    else:
        dur_days = max(1, min(int(days), 0xFFFF))
    tag = bytes(tag)[:5].ljust(5, b"\x00")
    header = bytes([_KEY_VERSION]) + tag + bytes([int(plan) & 0xFF]) \
        + dur_days.to_bytes(2, "big") + bytes([int(serial) & 0xFF])
    signature = _sign_key(_SIGN_DOMAIN + header)
    payload = header + signature + b"\x00"
    return format_key(_b32(payload, _KEY_CHARS))


def parse_key(text: str) -> dict | None:
    """Validate a v3 key (Ed25519) and return its payload (or ``None``)."""
    body = clean_key(text)
    if len(body) != _KEY_CHARS:
        return None
    payload = _unb32(body, _KEY_BODY_LEN)
    if payload is None:
        return None
    header = payload[:_KEY_HEADER_LEN]
    signature = payload[_KEY_HEADER_LEN:_KEY_HEADER_LEN + _KEY_SIG_LEN]
    if header[0] != _KEY_VERSION:
        return None
    if not _verify_key(_SIGN_DOMAIN + header, signature):
        return None
    plan = header[6]
    dur_days = int.from_bytes(header[7:9], "big")
    return {
        "version": header[0],
        "tag": header[1:6],
        "plan": plan,
        "plan_name": PLAN_NAMES.get(plan, f"PRO #{plan}"),
        "days": dur_days,                 # 0 = lifetime
        "lifetime": dur_days == 0,
        "serial": header[9],
        "key": format_key(body),
    }


def parse_key_v2(text: str) -> dict | None:
    """Legacy v2 (HMAC) key parser.

    Used for licences already stored on a machine and by the vendor
    migration tool; :func:`activate` no longer accepts v2 keys.
    """
    body = clean_key(text)
    if len(body) != 32:
        return None
    payload = _unb32(body, _V2_PAYLOAD_LEN)
    if payload is None:
        return None
    header = payload[:_V2_PAYLOAD_LEN - _V2_MAC_LEN]
    mac = payload[_V2_PAYLOAD_LEN - _V2_MAC_LEN:]
    if payload[0] != _V2_VERSION:
        return None
    if not hmac.compare_digest(mac, _hmac(b"KEY" + header)[:_V2_MAC_LEN]):
        return None
    plan = payload[6]
    dur_days = int.from_bytes(payload[7:9], "big")
    return {
        "version": payload[0],
        "tag": payload[1:6],
        "plan": plan,
        "plan_name": PLAN_NAMES.get(plan, f"PRO #{plan}"),
        "days": dur_days,
        "lifetime": dur_days == 0,
        "serial": payload[9],
        "key": format_key(body),
    }


def key_matches_machine(info: dict, hwid: str | None = None) -> bool:
    return hmac.compare_digest(info.get("tag", b""), _hwid_tag(hwid or machine_id()))


# ---------------------------------------------------------------------------
# persistent store (registry + several files, HMAC protected)
# ---------------------------------------------------------------------------
def _app_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _store_paths() -> list[Path]:
    """Semua salinan catatan lisensi (terlihat + tersembunyi)."""
    paths: list[Path] = []
    for env in ("APPDATA", "LOCALAPPDATA", "PROGRAMDATA"):
        base = os.environ.get(env)
        if base:
            paths.append(Path(base) / "ICTTerminal" / "license.dat")
    paths.append(_app_base() / "cache" / "license.dat")
    paths.extend(_shadow_paths())
    return paths


def _shadow_paths() -> list[Path]:
    """Salinan tambahan yang tidak terlihat di folder aplikasi.

    Tujuannya menaikkan biaya "reset" lisensi: klien harus menemukan dan
    menghapus semua salinan ini juga, bukan hanya ``license.dat``.
    """
    out: list[Path] = []
    home = os.environ.get("USERPROFILE")
    if home:
        out.append(Path(home) / ".ictterm" / "s.dat")
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Microsoft" / "Windows" / "Themes" / "ictterm.dat")
    return out


def _reg_path() -> str:
    return r"Software\ICTTerminal\Pro"


def _anchor_paths() -> list[Path]:
    """Salinan "anchor": tanggal pertama pakai + tanggal aktivasi asli."""
    out: list[Path] = []
    home = os.environ.get("USERPROFILE")
    if home:
        out.append(Path(home) / ".ictterm" / "a.dat")
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Microsoft" / "Windows" / "Themes" / "ictterm2.dat")
    return out


def _anchor_regs() -> list[tuple[str, str]]:
    return [
        (_reg_path(), "anchor"),
        (rf"Software\Classes\CLSID\{_ANCHOR_GUID}", "a"),
    ]


def _record_regs() -> list[tuple[str, str]]:
    return [
        (_reg_path(), "state"),
        (rf"Software\Classes\CLSID\{_ANCHOR_GUID}", "d"),
    ]


def _hide(path: Path, on: bool = True) -> None:
    """Atur atribut hidden supaya tidak mencolok di Explorer."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02 if on else 0x80)
    except Exception:
        pass


def _record_mac(body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _hmac(b"REC" + canon).hex()[:32]


def _sign(record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "mac"}
    body["mac"] = _record_mac(body)
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _verify(text: str) -> dict | None:
    try:
        body = json.loads(text)
    except Exception:
        return None
    if not isinstance(body, dict) or "mac" not in body:
        return None
    mac = body.pop("mac")
    if not isinstance(mac, str) or not hmac.compare_digest(mac, _record_mac(body)):
        return None
    return body


def _read_raw() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in _store_paths():
        try:
            if path.exists():
                out.append(("file", path.read_text(encoding="utf-8")))
        except Exception:
            pass
    if os.name == "nt":
        import winreg

        for reg_path, name in _record_regs():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                    out.append(("reg", str(winreg.QueryValueEx(key, name)[0])))
            except Exception:
                pass
    return out


def _write_record(record: dict) -> None:
    text = _sign(record)
    for path in _store_paths():
        try:
            if path.exists():
                if path.read_text(encoding="utf-8") == text:
                    continue
                _hide(path, False)      # file hidden tidak bisa ditimpa
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            _hide(path)
        except Exception:
            pass
    if os.name == "nt":
        import winreg

        for reg_path, name in _record_regs():
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                    try:
                        if str(winreg.QueryValueEx(key, name)[0]) == text:
                            continue
                    except Exception:
                        pass
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, text)
            except Exception:
                pass
    _write_anchor(record)


# ---------------------------------------------------------------------------
# anchor: tanggal pertama pakai + tanggal aktivasi asli
# ---------------------------------------------------------------------------
def _anchor_mac(body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _hmac(b"ANC" + canon).hex()[:32]


def _sign_anchor(body: dict) -> str:
    data = {k: v for k, v in body.items() if k != "mac"}
    data["mac"] = _anchor_mac(data)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _verify_anchor(text: str) -> dict | None:
    try:
        body = json.loads(text)
    except Exception:
        return None
    if not isinstance(body, dict) or "mac" not in body:
        return None
    mac = body.pop("mac")
    if not isinstance(mac, str) or not hmac.compare_digest(mac, _anchor_mac(body)):
        return None
    return body


def _read_anchor() -> dict | None:
    """Anchor valid dengan tanggal ``first`` paling awal (atau ``None``)."""
    hwid = machine_id()
    found: list[dict] = []
    for path in _anchor_paths():
        try:
            if path.exists():
                body = _verify_anchor(path.read_text(encoding="utf-8"))
                if body and str(body.get("hwid")) == hwid:
                    found.append(body)
        except Exception:
            pass
    if os.name == "nt":
        import winreg

        for reg_path, name in _anchor_regs():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                    body = _verify_anchor(str(winreg.QueryValueEx(key, name)[0]))
                if body and str(body.get("hwid")) == hwid:
                    found.append(body)
            except Exception:
                pass
    if not found:
        return None
    found.sort(key=lambda b: str(b.get("first", "9999-99-99")))
    base = dict(found[0])
    acts = sorted(str(b.get("act") or "") for b in found if b.get("act"))
    if acts:
        base["act"] = acts[0]
    for body in sorted(found, key=lambda b: str(b.get("act") or ""), reverse=True):
        if body.get("key"):
            base["key"] = str(body["key"])
            base["exp_base"] = str(body.get("exp_base") or "")
            break
    return base


def _write_anchor(record: dict) -> None:
    """Simpan/segarkan anchor. Tanggal asli tidak pernah dimundurkan."""
    try:
        hwid = machine_id()
        first = str(record.get("first") or _today().isoformat())
        act = str(record.get("act_at") or "")
        key = str(record.get("key") or "")
        exp_base = str(record.get("exp_base") or "")
        old = _read_anchor()
        if old:
            first = min(first, str(old.get("first") or first))
            act = min([a for a in (act, str(old.get("act") or "")) if a] or [""])
            key = key or str(old.get("key") or "")
            exp_base = exp_base or str(old.get("exp_base") or "")
        body = {"v": 1, "hwid": hwid, "first": first, "act": act,
                "key": key, "exp_base": exp_base}
        text = _sign_anchor(body)
        for path in _anchor_paths():
            try:
                if path.exists():
                    if path.read_text(encoding="utf-8") == text:
                        continue
                    _hide(path, False)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
                _hide(path)
            except Exception:
                pass
        if os.name == "nt":
            import winreg

            for reg_path, name in _anchor_regs():
                try:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, text)
                except Exception:
                    pass
    except Exception:
        pass


def _recovered_record(anchor: dict) -> dict:
    """Bangun ulang catatan dari anchor setelah data lisensi dihapus."""
    try:
        first = date.fromisoformat(str(anchor.get("first")))
    except Exception:
        first = _today()
    act = str(anchor.get("act") or "")
    record = _new_record(first)
    record["key"] = str(anchor.get("key") or "")
    record["act_at"] = act
    record["exp_base"] = str(anchor.get("exp_base") or act)
    record["welcome_shown"] = 1
    record["recovered"] = 1
    return record


def _load_record() -> tuple[dict | None, bool]:
    """Return ``(record, tampered)``.

    The earliest ``first`` date wins so a deleted copy cannot extend a trial.
    """
    raws = _read_raw()
    if not raws:
        return None, False
    valid: list[dict] = []
    for _src, text in raws:
        body = _verify(text)
        if body:
            valid.append(body)
    if not valid:
        return None, True
    valid.sort(key=lambda r: str(r.get("first", "9999-99-99")))
    record = dict(valid[0])
    for other in valid[1:]:
        if not record.get("key") and other.get("key"):
            record["key"] = other["key"]
            record["act_at"] = other.get("act_at", "")
            record["exp_base"] = other.get("exp_base", "")
        elif (record.get("key") and record.get("key") == other.get("key")
              and not record.get("exp_base") and other.get("exp_base")):
            record["exp_base"] = other["exp_base"]
        if other.get("welcome_shown"):
            record["welcome_shown"] = 1
    return record, False


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------
@dataclass
class LicenseState:
    edition: str = "FREE"          # FREE | TRIAL | PRO
    plan: str = "FREE"
    tier: str = "locked"           # pro | lite | locked
    hwid: str = ""
    days_left: int = 0             # sisa masa gratis (dari 30 hari)
    pro_left: int = 0              # sisa fase PRO penuh (dari 7 hari)
    trial_day: int = 0             # hari ke-berapa sejak pertama dibuka
    expires: date | None = None
    lifetime: bool = False
    reason: str = ""
    trial_started: bool = False
    welcome: bool = False          # first run of a brand new trial
    tampered: bool = False
    limits: dict = field(default_factory=dict)
    key: str = ""
    activated_at: str = ""

    @property
    def is_pro(self) -> bool:
        """Fitur PRO penuh: key aktif, atau 7 hari pertama masa gratis."""
        return self.tier == "pro"

    @property
    def bot_locked(self) -> bool:
        """Bot auto trade dimatikan total (masa gratis habis, tanpa key)."""
        return self.tier == "locked"

    @property
    def phase(self) -> str:
        """Tahap saat ini, dipakai untuk notifikasi sekali per tahap."""
        if self.edition == "PRO":
            return "pro"
        if self.edition == "TRIAL":
            return "trial_pro" if self.tier == "pro" else "trial_lite"
        return "locked"

    @property
    def badge(self) -> str:
        if self.edition == "PRO":
            return "PRO" if self.lifetime else f"PRO · {self.days_left} hari"
        if self.edition == "TRIAL" and self.tier == "pro":
            return f"TRIAL PRO · {self.pro_left} hari"
        if self.edition == "TRIAL":
            return f"TRIAL · {self.days_left} hari"
        return "BOT TERKUNCI"

    @property
    def title(self) -> str:
        if self.edition == "PRO":
            return f"Lisensi PRO aktif ({self.plan})"
        if self.edition == "TRIAL" and self.tier == "pro":
            return (f"Masa gratis hari ke-{self.trial_day}: semua fitur PRO terbuka "
                    f"({self.pro_left} hari lagi)")
        if self.edition == "TRIAL":
            return (f"Masa gratis terbatas · sisa {self.days_left} hari · "
                    "bot aktif dengan batasan")
        return "Masa gratis habis · bot auto trade terkunci"


_CACHE: LicenseState | None = None


def _today() -> date:
    return datetime.now().date()


def _new_record(first: date) -> dict:
    return {
        "v": 1,
        "hwid": machine_id(),
        "first": first.isoformat(),
        "last": first.isoformat(),
        "runs": 0,
        "welcome_shown": 0,
        "key": "",
        "act_at": "",
        "exp_base": "",
    }


def _key_base(record: dict) -> date:
    """Tanggal mulai masa berlaku key (tersimpan saat aktivasi)."""
    for field in ("exp_base", "act_at", "first"):
        try:
            return date.fromisoformat(str(record.get(field)))
        except Exception:
            continue
    return _today()


def _evaluate(record: dict | None, tampered: bool) -> LicenseState:
    hwid = machine_id()
    state = LicenseState(hwid=hwid, tampered=tampered, tier="locked",
                         limits=limits_for("locked"))
    if record is None:
        state.reason = "Data lisensi tidak valid (terdeteksi perubahan)." if tampered else ""
        state.edition = "FREE"
        state.plan = "FREE"
        return state

    state.trial_started = True
    state.key = str(record.get("key") or "")
    state.activated_at = str(record.get("act_at") or "")
    state.welcome = not bool(record.get("welcome_shown"))

    # ---- activation key ------------------------------------------------
    info = (parse_key(state.key) or parse_key_v2(state.key)) if state.key else None
    if info and key_matches_machine(info, hwid):
        state.plan = info["plan_name"]
        state.lifetime = bool(info["lifetime"])
        if state.lifetime:
            state.edition = "PRO"
            state.tier = "pro"
            state.days_left = 9999
            state.limits = limits_for("pro")
            return state
        # masa berlaku dihitung dari tanggal aktivasi (exp_base)
        state.expires = _key_base(record) + timedelta(days=int(info.get("days") or 0))
        if state.expires >= _today():
            state.edition = "PRO"
            state.tier = "pro"
            state.days_left = (state.expires - _today()).days
            state.limits = limits_for("pro")
            return state
        state.reason = f"Lisensi PRO sudah kedaluwarsa sejak {state.expires:%d %b %Y}."

    # ---- masa gratis ---------------------------------------------------
    try:
        first = date.fromisoformat(str(record.get("first")))
    except Exception:
        first = _today()
    used = max(0, (_today() - first).days)
    state.trial_day = used + 1
    state.expires = first + timedelta(days=TRIAL_DAYS)
    state.days_left = max(0, TRIAL_DAYS - used)

    if used < TRIAL_PRO_DAYS:
        # 7 hari pertama: semua fitur PRO terbuka
        state.edition = "TRIAL"
        state.plan = "TRIAL PRO"
        state.tier = "pro"
        state.pro_left = TRIAL_PRO_DAYS - used
        state.limits = limits_for("pro")
        if not state.reason:
            state.reason = (f"Masa gratis hari ke-{used + 1}/{TRIAL_DAYS} · "
                            f"fitur PRO penuh {state.pro_left} hari lagi.")
    elif used < TRIAL_DAYS:
        # hari ke-8 s/d ke-30: bot aktif dengan batasan
        state.edition = "TRIAL"
        state.plan = "TRIAL"
        state.tier = "lite"
        state.limits = limits_for("lite")
        if not state.reason:
            state.reason = (f"Masa gratis terbatas · sisa {state.days_left} hari · "
                            "semua pengaturan auto trade dikunci.")
    else:
        # masa gratis habis: bot mati, chart & sinyal tetap bisa dilihat
        state.edition = "FREE"
        state.plan = "FREE"
        state.tier = "locked"
        state.limits = limits_for("locked")
        if not state.reason:
            state.reason = (f"Masa gratis {TRIAL_DAYS} hari sudah berakhir pada "
                            f"{first + timedelta(days=TRIAL_DAYS):%d %b %Y}. "
                            "Beli lisensi untuk mengaktifkan bot.")
    return state


def current_state(force: bool = False) -> LicenseState:
    """Read (and cache) the licence state of this machine."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    record, tampered = _load_record()
    if record is None and not tampered:
        anchor = _read_anchor()
        if anchor:
            # data lisensi dihapus, tapi anchor masih ada: pulihkan catatan
            # dengan tanggal asli supaya trial/aktivasi tidak bisa direset
            record = _recovered_record(anchor)
        else:
            record = _new_record(_today())
        _write_record(record)
    elif record is not None:
        # clock rollback / forward guard
        try:
            last = date.fromisoformat(str(record.get("last")))
            if _today() < last - timedelta(days=2):
                tampered = True
                record = None
        except Exception:
            pass
        if record is not None:
            record["last"] = _today().isoformat()
            record["runs"] = int(record.get("runs", 0)) + 1
            _write_record(record)
    state = _evaluate(record, tampered)
    if tampered:
        state.edition = "FREE"
        state.plan = "FREE"
        state.tier = "locked"
        state.limits = limits_for("locked")
        state.reason = ("Jam sistem dimundurkan / data lisensi diubah. "
                        "Bot auto trade dikunci sampai lisensi diaktivasi.")
    _CACHE = state
    return state


def mark_welcome_shown() -> None:
    """Remember that the first-run welcome notification has been displayed."""
    global _CACHE
    record, tampered = _load_record()
    if record is None or tampered or record.get("welcome_shown"):
        return
    record["welcome_shown"] = 1
    _write_record(record)
    if _CACHE is not None:
        _CACHE.welcome = False


def activate(text: str) -> tuple[bool, str]:
    """Activate this machine with ``text``. Returns ``(ok, message)``.

    The validity of the key starts **today** (activation day), not the day
    the vendor generated it.  Renewals continue after the current expiry.
    """
    global _CACHE
    hwid = machine_id()
    info = parse_key(text)
    if info is None:
        if parse_key_v2(text):
            return False, ("Key format lama (v2) sudah tidak berlaku.\n"
                           "Minta key baru ke penjual — sisa masa aktif akan diteruskan.")
        return False, "Format key tidak valid. Periksa kembali penulisannya."
    if not key_matches_machine(info, hwid):
        return False, ("Key ini bukan untuk laptop ini.\n"
                       f"HWID laptop kamu: {hwid}\n"
                       "Minta key baru ke penjual dengan HWID tersebut.")
    record, _tampered = _load_record()
    today = _today()
    anchor = _read_anchor()
    if record is None:
        record = _recovered_record(anchor) if anchor else _new_record(today)
    elif anchor:
        try:
            first = date.fromisoformat(str(anchor.get("first")))
            if first < date.fromisoformat(str(record.get("first"))):
                record["first"] = first.isoformat()
        except Exception:
            pass
    current = _evaluate(record, False)
    if current.edition == "PRO" and current.lifetime and not info["lifetime"]:
        return False, "Lisensi lifetime sudah aktif di laptop ini. Key baru tidak diperlukan."

    same_key = str(record.get("key") or "") == info["key"]
    if same_key and record.get("exp_base"):
        # aktivasi ulang key yang sama: tanggal mulai tidak direset
        base = _key_base(record)
    elif current.edition == "PRO" and not current.lifetime and current.expires:
        # perpanjangan: masa baru menyambung setelah masa aktif habis
        base = max(today, current.expires)
    elif anchor and anchor.get("act") and not record.get("exp_base"):
        # data lisensi pernah dihapus: masa aktif tetap dihitung dari
        # aktivasi asli (bukan hari ini) supaya tidak bisa direset
        try:
            base = date.fromisoformat(str(anchor["act"]))
        except Exception:
            base = today
        base = min(base, today)
    else:
        base = today

    record["key"] = info["key"]
    record["act_at"] = today.isoformat()
    record["exp_base"] = base.isoformat()
    record["last"] = today.isoformat()
    record["welcome_shown"] = 1
    _write_record(record)
    _CACHE = None
    state = current_state(force=True)
    if state.edition != "PRO":
        return False, state.reason or "Aktivasi gagal."
    if state.lifetime:
        return True, f"Aktivasi berhasil. Paket {state.plan} · lifetime."
    return True, (f"Aktivasi berhasil. Paket {state.plan} · {state.days_left} hari "
                  f"s/d {state.expires:%d %b %Y}.")


def deactivate() -> None:
    """Remove the activation key (keeps the trial record). Used for testing."""
    global _CACHE
    record, _tampered = _load_record()
    if record is None:
        return
    record["key"] = ""
    record["act_at"] = ""
    record["exp_base"] = ""
    _write_record(record)
    _CACHE = None


# ---------------------------------------------------------------------------
# enforcement helpers (auto trade)
# ---------------------------------------------------------------------------
def apply_autotrade_limits(cfg, state: LicenseState | None = None):
    """Clamp an ``AutoTradeConfig`` to the limits of the current edition.

    The engine logic itself is untouched: only the values that the engine
    receives are capped.  Returns ``(cfg, notes)`` where ``notes`` are
    human readable adjustments for the UI log.
    """
    state = state or current_state()
    lim = state.limits
    notes: list[str] = []

    try:
        symbols = cfg.normalized_symbols()
    except Exception:
        symbols = list(getattr(cfg, "symbols", []) or [])
    max_symbols = int(lim.get("max_symbols") or 0)
    if max_symbols and len(symbols) > max_symbols:
        cfg.symbols = symbols[:max_symbols]
        notes.append(
            f"Mode {state.edition}: maksimal {max_symbols} simbol. "
            f"{len(symbols) - max_symbols} simbol diabaikan."
        )

    fixed_risk = lim.get("risk_pct")
    if fixed_risk is not None and abs(float(cfg.risk_pct) - float(fixed_risk)) > 1e-9:
        notes.append(f"Risk/trade dikunci {fixed_risk:.2f}% pada mode {state.edition}.")
        cfg.risk_pct = float(fixed_risk)
    elif float(cfg.risk_pct) > float(lim.get("risk_max", cfg.risk_pct)):
        notes.append(f"Risk/trade dibatasi maksimal {lim['risk_max']:.2f}%.")
        cfg.risk_pct = float(lim["risk_max"])

    if float(cfg.max_total_risk_pct) > float(lim["total_risk_max"]):
        notes.append(f"Max total risk dibatasi {lim['total_risk_max']:.2f}% pada mode {state.edition}.")
        cfg.max_total_risk_pct = float(lim["total_risk_max"])

    if float(cfg.max_drawdown_pct) > float(lim["dd_max"]):
        notes.append(f"Max drawdown global dibatasi {lim['dd_max']:.2f}% pada mode {state.edition}.")
        cfg.max_drawdown_pct = float(lim["dd_max"])

    if lim.get("threshold") is not None and abs(float(cfg.threshold) - float(lim["threshold"])) > 1e-9:
        notes.append(f"Skor minimum dikunci {lim['threshold']:.1f} pada mode {state.edition}.")
        cfg.threshold = float(lim["threshold"])

    if lim.get("rr") is not None and abs(float(cfg.rr) - float(lim["rr"])) > 1e-9:
        notes.append(f"Target RR dikunci {lim['rr']:.2f}R pada mode {state.edition}.")
        cfg.rr = float(lim["rr"])

    if lim.get("tp_mode"):
        cfg.tp_mode = str(lim["tp_mode"])
        notes.append(f"Mode TP dikunci ke {lim['tp_mode']} pada mode {state.edition}.")

    if float(cfg.risk_pct) > float(cfg.max_total_risk_pct):
        cfg.risk_pct = float(cfg.max_total_risk_pct)
    return cfg, notes


def upgrade_hint(state: LicenseState | None = None) -> str:
    state = state or current_state()
    if state.bot_locked:
        return ("Masa gratis habis: bot auto trade terkunci. "
                "Beli lisensi untuk mengaktifkan bot.")
    if state.is_pro:
        return ""
    return ("Masa gratis terbatas: maks 5 simbol · risk 0.1%/trade · total risk 4% · "
            "max DD 4% · skor minimum 10.0 · RR 1.5 (semua dikunci).")


def license_text(state: LicenseState | None = None) -> str:
    """Plain-text summary used by dialogs and reports."""
    state = state or current_state()
    lines = [
        f"Edisi        : {state.edition}",
        f"Paket        : {state.plan}",
        f"HWID         : {state.hwid}",
    ]
    if state.edition == "PRO":
        lines.append("Berlaku      : " + ("lifetime" if state.lifetime
                                          else f"s/d {state.expires:%d %b %Y} ({state.days_left} hari)"))
    elif state.edition == "TRIAL":
        lines.append(f"Hari ke-     : {state.trial_day} dari {TRIAL_DAYS}")
        if state.tier == "pro":
            lines.append(f"Status       : PRO penuh, sisa {state.pro_left} hari")
        else:
            lines.append(f"Status       : terbatas, sisa {state.days_left} hari")
        lines.append(f"Berakhir     : {state.expires:%d %b %Y}")
    else:
        lines.append("Status       : bot auto trade terkunci (chart & sinyal tetap aktif)")
    if state.reason:
        lines.append(f"Catatan      : {state.reason}")
    return "\n".join(lines)


if __name__ == "__main__":  # quick manual check:  python -m ictterm.licensing
    print(license_text())
    print("Contoh key (lifetime):", build_key(machine_id(), 5, None))
