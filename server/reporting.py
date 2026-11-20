"""Sends bugs seen on the server to the PocketBase "feedbacks" collection the
app already uses for bug reports, so they show up in one place.

Reports are deduplicated and rate-limited so a bug that repeats every tick
cannot flood the collection, and sending happens off the event loop.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import urllib.request
from typing import Optional

log = logging.getLogger("liars_poker.reporting")

DEFAULT_URL = "https://pb.adamtomczyk.com/api/collections/feedbacks/records"
#: The same problem is reported at most once in this window.
DEDUPE_SECONDS = 600
MAX_PER_HOUR = 30
MESSAGE_LIMIT = 6000


class Reporter:
    def __init__(self, url: Optional[str], version: str = "server"):
        self.url = url
        self.version = version
        self.seen: dict = {}
        self.sent: list = []
        self.lock = threading.Lock()

    def _allowed(self, key: str, now: float) -> bool:
        with self.lock:
            if now - self.seen.get(key, -1e9) < DEDUPE_SECONDS:
                return False
            self.sent = [t for t in self.sent if now - t < 3600]
            if len(self.sent) >= MAX_PER_HOUR:
                return False
            self.seen[key] = now
            self.sent.append(now)
            return True

    def report(self, kind: str, message: str, context: Optional[dict] = None,
               exc: Optional[BaseException] = None) -> bool:
        """Queue a report. Returns False when it was dropped (disabled, duplicate, over the limit)."""
        if not self.url:
            return False
        key = f"{kind}:{message[:200]}"
        if not self._allowed(key, time.time()):
            return False
        body = f"[{kind}] {message}"
        if exc is not None:
            body += "\n\n" + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        if context:
            body += "\n\ncontext: " + json.dumps(context, ensure_ascii=False, default=str)
        payload = {
            "message": body[:MESSAGE_LIMIT],
            "source": "liars-poker-server",
            "priority": "high",
            "place": kind,
            "version": self.version,
        }
        threading.Thread(target=self._send, args=(payload,), daemon=True).start()
        return True

    def _send(self, payload: dict) -> None:
        try:
            request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(request, timeout=10).read()
        except Exception as error:  # reporting must never take the server down
            log.warning("could not send error report: %s", error)
