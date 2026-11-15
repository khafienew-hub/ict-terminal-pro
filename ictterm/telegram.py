"""Telegram notifier for auto-trade signals and orders (stdlib only)."""
from __future__ import annotations

import json
import queue
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pyqtgraph.Qt import QtCore


class TelegramNotifier(QtCore.QObject):
    error = QtCore.pyqtSignal(str)

    def __init__(self, token: str, chat_id: str, parent=None):
        super().__init__(parent)
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if self.token and self.chat_id:
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

    def send(self, text: str) -> None:
        if not self.token or not self.chat_id or self._stop.is_set():
            return
        self._queue.put(text)

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def _worker(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            ok, message = self.send_now(self.token, self.chat_id, item)
            if not ok:
                self.error.emit(f"Telegram gagal: {message}")

    @staticmethod
    def send_now(token: str, chat_id: str, text: str, timeout: int = 10) -> tuple[bool, str]:
        token = (token or "").strip()
        chat_id = (chat_id or "").strip()
        if not token or not chat_id:
            return False, "Bot token / chat ID kosong"
        try:
            payload = urlencode({
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }).encode("utf-8")
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            request = Request(url, data=payload, method="POST")
            with urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if data.get("ok"):
                return True, "OK"
            return False, data.get("description", "unknown Telegram error")
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
