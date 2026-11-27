"""SQLite persistence so a restart or deploy does not end running games,
plus what the admin dashboard is built from: the ``events`` table, player
reports, refused names and the admin's own settings."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Iterable, List, Optional, Tuple

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
        self._add_column("reports", "handled_at", "REAL")
        # Names the filter refused, so the admin sees what a player tried.
        self.db.execute("CREATE TABLE IF NOT EXISTS refused_names (id INTEGER PRIMARY KEY, t REAL NOT NULL, "
                        "player TEXT NOT NULL, name TEXT NOT NULL)")
        self.db.execute("CREATE INDEX IF NOT EXISTS refused_player ON refused_names (player, t)")
        # The admin's own blocked words, on top of the built-in lists in names.py.
        self.db.execute("CREATE TABLE IF NOT EXISTS blocked_words (word TEXT PRIMARY KEY, whole INTEGER NOT NULL, "
                        "added REAL NOT NULL)")
        # Logged-in admin browsers: only a hash of each cookie is kept.
        self.db.execute("CREATE TABLE IF NOT EXISTS admin_sessions (token_hash TEXT PRIMARY KEY, "
                        "created REAL NOT NULL, expires REAL NOT NULL)")
        # What the admin did to whom, shown under "What was done".
        self.db.execute("CREATE TABLE IF NOT EXISTS admin_actions (id INTEGER PRIMARY KEY, t REAL NOT NULL, "
                        "player TEXT, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '')")
        self.db.execute("CREATE INDEX IF NOT EXISTS admin_actions_player ON admin_actions (player, t)")
        # Problems the admin marked: "watching" (muted until a time) or "resolved".
        self.db.execute("CREATE TABLE IF NOT EXISTS problem_state (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                        "since REAL NOT NULL, muted_until REAL)")

    def _add_column(self, table: str, column: str, kind: str) -> None:
        columns = [row[1] for row in self.db.execute(f"PRAGMA table_info({table})")]
        if column not in columns:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    def load(self) -> Tuple[List[dict], List[dict]]:
        cutoff = time.time() - PROFILE_TTL
        # Locked players are kept, so the lock survives a long break.
        self.db.execute("DELETE FROM profiles WHERE seen < ? AND json_extract(data, '$.room_id') IS NULL "
                        "AND COALESCE(json_extract(data, '$.locked'), 0) = 0", (cutoff,))
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

    def add_refused(self, refused: List[dict]) -> None:
        if refused:
            with self.db:
                self.db.execute("BEGIN")
                self.db.executemany("INSERT INTO refused_names (t, player, name) VALUES (?, ?, ?)",
                                    [(r["t"], r["player"], r["name"]) for r in refused])

    # ----- admin ---------------------------------------------------------

    def blocked_words(self) -> List[Tuple[str, bool, float]]:
        return [(w, bool(whole), added) for w, whole, added in
                self.db.execute("SELECT word, whole, added FROM blocked_words ORDER BY added DESC")]

    def add_blocked_word(self, word: str, whole: bool, now: float) -> None:
        self.db.execute("INSERT OR REPLACE INTO blocked_words (word, whole, added) VALUES (?, ?, ?)",
                        (word, int(whole), now))

    def remove_blocked_word(self, word: str) -> None:
        self.db.execute("DELETE FROM blocked_words WHERE word = ?", (word,))

    def add_session(self, token_hash: str, now: float, expires: float) -> None:
        self.db.execute("DELETE FROM admin_sessions WHERE expires < ?", (now,))
        self.db.execute("INSERT INTO admin_sessions (token_hash, created, expires) VALUES (?, ?, ?)",
                        (token_hash, now, expires))

    def session_valid(self, token_hash: str, now: float) -> bool:
        row = self.db.execute("SELECT expires FROM admin_sessions WHERE token_hash = ?", (token_hash,)).fetchone()
        return bool(row and row[0] > now)

    def end_session(self, token_hash: str) -> None:
        self.db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))

    def log_action(self, player: Optional[str], action: str, detail: str, now: float) -> None:
        self.db.execute("INSERT INTO admin_actions (t, player, action, detail) VALUES (?, ?, ?, ?)",
                        (now, player, action, detail))

    def set_reports_status(self, target: str, status: str, now: float, only_open: bool = True) -> None:
        where = " AND status = 'open'" if only_open else ""
        self.db.execute(f"UPDATE reports SET status = ?, handled_at = ? WHERE target = ?{where}",
                        (status, None if status == "open" else now, target))

    def set_problem(self, problem: str, status: Optional[str], now: float, muted_until: Optional[float] = None) -> None:
        if status is None:
            self.db.execute("DELETE FROM problem_state WHERE id = ?", (problem,))
        else:
            self.db.execute("INSERT OR REPLACE INTO problem_state (id, status, since, muted_until) VALUES (?, ?, ?, ?)",
                            (problem, status, now, muted_until))

    def close(self) -> None:
        self.db.close()
