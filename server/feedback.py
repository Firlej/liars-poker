"""Player feedback for the admin dashboard, read from PocketBase.

The app sends feedback and crash reports straight to PocketBase (the
``feedbacks`` collection, shared with other apps, so we filter on ``source``).
They stay there: PocketBase keeps working when this game server is down,
which is when crash reports matter most. This module only reads them, as a
read-only PocketBase user, and keeps a copy for a minute so the dashboard's
10-second refresh doesn't hit PocketBase every time.

Settings: ``FEEDBACK_PB_URL``, ``FEEDBACK_PB_EMAIL``, ``FEEDBACK_PB_PASSWORD``
(``FEEDBACK_SOURCE`` defaults to ``liars-poker-app``). Without them the
Feedback page says it isn't set up.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger("liars_poker.feedback")

LOGS_MARK = "=== DEBUG LOGS ==="
CACHE_SECONDS = 60.0
TOKEN_SECONDS = 6 * 3600.0
#: The detail view shows the end of a crash log; the start is mostly app setup.
LOG_TAIL = 30_000
TIMEOUT = 10


def _when(created: str) -> float:
    """PocketBase's "2026-11-27 15:58:12.123Z" as epoch seconds."""
    try:
        return datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def looks_like_test(message: str) -> bool:
    """Six random letters and nothing else ("vijomc", "kxtyqh"): what store reviewers and
    test taps sent, not feedback. Real one-word messages ("crash") have other lengths or a log."""
    return bool(re.fullmatch(r"[a-z]{6}", message.strip()))


def normalise(record: dict) -> dict:
    message = (record.get("message") or "").replace("\r\n", "\n")
    text, mark, logs = message.partition(LOGS_MARK)
    shots = record.get("screenshot") or []
    if isinstance(shots, str):
        shots = [shots] if shots else []
    return {
        "id": record.get("id", ""),
        "t": _when(record.get("created") or ""),
        "message": text.strip(),
        "has_logs": bool(mark),
        "logs": (mark + logs) if mark else "",
        "place": record.get("place") or "",
        "version": record.get("version") or "",
        "priority": record.get("priority") or "medium",
        "resolved": bool(record.get("resolved")),
        "screenshots": [s for s in shots if isinstance(s, str) and s],
        "audio": record.get("audio") or "",
        "notes": record.get("notes") or "",
        "sender": record.get("sender") or "",
        "test": not mark and looks_like_test(text),
    }


class FeedbackSource:
    def __init__(self, url: Optional[str], email: Optional[str], password: Optional[str],
                 source: str = "liars-poker-app"):
        self.url = (url or "").rstrip("/")
        self.email = email or ""
        self.password = password or ""
        self.source = source
        self._token = ""
        self._token_at = 0.0
        self._items: Optional[List[dict]] = None
        self._items_at = 0.0
        self.error: Optional[str] = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "FeedbackSource":
        return cls(os.environ.get("FEEDBACK_PB_URL"), os.environ.get("FEEDBACK_PB_EMAIL"),
                   os.environ.get("FEEDBACK_PB_PASSWORD"), os.environ.get("FEEDBACK_SOURCE", "liars-poker-app"))

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.email and self.password)

    def file_url(self, record_id: str, name: str, thumb: str = "") -> str:
        q = f"?thumb={thumb}" if thumb else ""
        return f"{self.url}/api/files/feedbacks/{urllib.parse.quote(record_id)}/{urllib.parse.quote(name)}{q}"

    def admin_url(self, record_id: str) -> str:
        return f"{self.url}/_/#/collections?collection=feedbacks&recordId={urllib.parse.quote(record_id)}"

    # ----- PocketBase calls (blocking; run them in a thread) ---------------

    def _call(self, method: str, path: str, body: Optional[dict] = None, auth: bool = True) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("content-type", "application/json")
        req.add_header("user-agent", "liars-poker-admin")
        if auth:
            req.add_header("authorization", self._auth())
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            # Crash logs can hold raw control characters, which strict JSON refuses.
            return json.loads(res.read().decode("utf-8", errors="replace"), strict=False)

    def _auth(self) -> str:
        if self._token and time.time() - self._token_at < TOKEN_SECONDS:
            return self._token
        res = self._call("POST", "/api/collections/users/auth-with-password",
                         {"identity": self.email, "password": self.password}, auth=False)
        self._token, self._token_at = res.get("token", ""), time.time()
        if not self._token:
            raise RuntimeError("PocketBase login gave no token")
        return self._token

    def items(self) -> List[dict]:
        """Every feedback for this app, newest first. Old copy if PocketBase can't be reached."""
        with self._lock:
            if self._items is not None and time.time() - self._items_at < CACHE_SECONDS:
                return self._items
            if not self.enabled:
                self.error = "not_set_up"
                return []
            query = urllib.parse.urlencode({"filter": f'source = "{self.source}"', "sort": "-created", "perPage": 500})
            try:
                try:
                    res = self._call("GET", f"/api/collections/feedbacks/records?{query}")
                except urllib.error.HTTPError as error:
                    if error.code not in (401, 403):
                        raise
                    self._token = ""  # expired: log in again once
                    res = self._call("GET", f"/api/collections/feedbacks/records?{query}")
                self._items = [normalise(r) for r in res.get("items", [])]
                self.error = None
            except Exception as error:  # keep showing what we had
                log.warning("feedback: could not read PocketBase: %r", error)
                self.error = "unreachable"
                if self._items is None:
                    return []
            self._items_at = time.time()
            return self._items


# ----- what the dashboard shows ----------------------------------------------

DAY = 86400.0


def _row(item: dict) -> dict:
    return {k: item[k] for k in ("id", "t", "message", "has_logs", "place", "version", "priority",
                                 "resolved", "test")} | {"shots": len(item["screenshots"]), "audio": bool(item["audio"])}


def page(source: FeedbackSource, tab: str, q: str, now: float) -> dict:
    items = source.items()
    real = [i for i in items if not i["test"]]
    open_ = [i for i in real if not i["resolved"]]
    week = [i for i in real if i["t"] > now - 7 * DAY]
    prev = [i for i in real if now - 14 * DAY < i["t"] <= now - 7 * DAY]
    start = now - 14 * DAY
    per_day = [0] * 14
    for i in real:
        if i["t"] > start:
            per_day[min(13, int((i["t"] - start) // DAY))] += 1
    rows = {"open": open_, "resolved": [i for i in real if i["resolved"]], "all": items}.get(tab, open_)
    if q:
        needle = q.lower()
        rows = [i for i in rows if needle in f"{i['message']} {i['place']} {i['version']}".lower()]
    places: dict = {}
    for i in open_:
        places[i["place"] or "Unknown"] = places.get(i["place"] or "Unknown", 0) + 1
    versions: dict = {}
    for i in real:
        versions[i["version"] or "?"] = versions.get(i["version"] or "?", 0) + 1
    return {
        "setup": source.enabled, "error": source.error,
        "kpis": {
            "open": len(open_), "open_high": sum(1 for i in open_ if i["priority"] == "high"),
            "week": len(week), "week_prev": len(prev), "per_day": per_day,
            "crashes": sum(1 for i in open_ if i["has_logs"]), "crashes_all": sum(1 for i in real if i["has_logs"]),
            "shots": sum(1 for i in real if i["screenshots"]),
            "resolved": sum(1 for i in real if i["resolved"]), "total": len(real), "tests": len(items) - len(real),
        },
        "counts": {"open": len(open_), "resolved": len(real) - len(open_), "all": len(items)},
        "places": sorted(places.items(), key=lambda kv: -kv[1]),
        "versions": sorted(versions.items(), key=lambda kv: kv[0], reverse=True),
        "rows": [_row(i) for i in rows],
    }


def detail(source: FeedbackSource, record_id: str) -> Optional[dict]:
    item = next((i for i in source.items() if i["id"] == record_id), None)
    if item is None:
        return None
    logs = item["logs"]
    return {
        **_row(item), "notes": item["notes"], "sender": item["sender"],
        "logs": logs[-LOG_TAIL:], "logs_cut": max(0, len(logs) - LOG_TAIL), "logs_size": len(logs),
        "screenshots": [{"full": source.file_url(item["id"], s), "thumb": source.file_url(item["id"], s, "600x0")}
                        for s in item["screenshots"]],
        "audio_url": source.file_url(item["id"], item["audio"]) if item["audio"] else "",
        "pocketbase": source.admin_url(item["id"]),
    }


def open_count(source: FeedbackSource) -> Optional[int]:
    """For the menu badge; only from the copy we already have, never a network call."""
    if source._items is None:
        return None
    return sum(1 for i in source._items if not i["test"] and not i["resolved"])
