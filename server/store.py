"""SQLite persistence so a restart or deploy does not end running games,
plus the ``events`` table the stats dashboard is built from."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import List, Tuple

#: Players not seen for this long (and not in a room) are forgotten.
PROFILE_TTL = 60 * 24 * 3600


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, data TEXT NOT NULL, seen REAL NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        # One row per thing that happened, kept for good: who (a random player id,
        # never a name), when, and a few numbers. See ``Lobby.record``.
        self.db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, t REAL NOT NULL, "
                        "type TEXT NOT NULL, player TEXT, room TEXT, data TEXT NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS events_type_t ON events (type, t)")
        self.db.execute("CREATE INDEX IF NOT EXISTS events_player ON events (player, t)")
        # Player reports for the admin to act on: "open" until handled.
        self.db.execute("CREATE TABLE IF NOT EXISTS reports (id INTEGER PRIMARY KEY, t REAL NOT NULL, "
                        "reporter TEXT NOT NULL, target TEXT NOT NULL, name TEXT NOT NULL, room TEXT, "
                        "reason TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open')")
        self.db.execute("CREATE INDEX IF NOT EXISTS reports_status ON reports (status, t)")

    def load(self) -> Tuple[List[dict], List[dict]]:
        cutoff = time.time() - PROFILE_TTL
        self.db.execute("DELETE FROM profiles WHERE seen < ? AND json_extract(data, '$.room_id') IS NULL", (cutoff,))
        profiles = [json.loads(row[0]) for row in self.db.execute("SELECT data FROM profiles")]
        rooms = []
        for (data,) in self.db.execute("SELECT data FROM rooms"):
            try:
                rooms.append(json.loads(data))
            except ValueError:
                continue
        return profiles, rooms

    def save(self, profiles: List[dict], rooms: List[dict], deleted: List[str], now: float) -> None:
        if not (profiles or rooms or deleted):
            return
        with self.db:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT OR REPLACE INTO profiles (id, data, seen) VALUES (?, ?, ?)",
                                [(p["id"], json.dumps(p), now) for p in profiles])
            self.db.executemany("INSERT OR REPLACE INTO rooms (id, data) VALUES (?, ?)",
                                [(r["id"], json.dumps(r, ensure_ascii=False)) for r in rooms])
            self.db.executemany("DELETE FROM rooms WHERE id = ?", [(rid,) for rid in deleted])

    def add_events(self, events: List[dict]) -> None:
        if not events:
            return
        with self.db:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT INTO events (t, type, player, room, data) VALUES (?, ?, ?, ?, ?)",
                                [(e["t"], e["type"], e.get("player"), e.get("room"), json.dumps(e.get("data") or {}))
                                 for e in events])

    def add_reports(self, reports: List[dict]) -> None:
        if not reports:
            return
        with self.db:
            self.db.execute("BEGIN")
            self.db.executemany("INSERT INTO reports (t, reporter, target, name, room, reason, note) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                [(r["t"], r["reporter"], r["target"], r["name"], r["room"], r["reason"], r["note"])
                                 for r in reports])

    def close(self) -> None:
        self.db.close()
