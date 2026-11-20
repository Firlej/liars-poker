"""SQLite persistence so a restart or deploy does not end running games."""
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

    def close(self) -> None:
        self.db.close()
