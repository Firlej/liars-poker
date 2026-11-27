"""The numbers behind the admin dashboard, read from the SQLite file.

Every function here runs in a worker thread with its own read-only
connection (see ``admin.py``), so a slow query never holds up the games.
What only the running server knows (who is online, live tables, names) is
passed in as a ``Live`` snapshot taken on the event loop.

Times are bucketed in the dashboard's time zone (``STATS_TZ``).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from statistics import mean
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import names

DAY = 86400.0
HOUR = 3600.0
RANGES = {"24h": DAY, "7d": 7 * DAY, "30d": 30 * DAY}
PAGE = 12
#: Players with no game for this long count as "inactive"; this long and less than 30 days as "churned".
INACTIVE_AFTER = 14 * DAY
#: A player on 3+ different days in the last 7 is a regular.
REGULAR_DAYS = 3
SLOW_MS = 100.0

ERROR_KINDS = {
    "server_exception": ("Server error", "Move failed", "high",
                         "A player's request threw an exception and was answered with an error; the table kept running."),
    "server_tick_exception": ("Server loop crash", "Server loop crash", "high",
                              "The game clock hit an exception. One tick was skipped; the next one ran as usual."),
    "invariant": ("Game check failed", "Game check failed", "medium",
                  "A table's state broke one of the game's rules (for example a hand of the wrong size)."),
    "bot_illegal_move": ("Bot illegal move", "Bot illegal move", "medium",
                         "A bot chose a move the rules don't allow; the server played a legal move for it."),
}
REJECTED = {"stale": "Out of date move", "not_your_turn": "Not your turn", "rate_limited": "Too many requests"}
REASONS = ("offensive_name", "abusive_reactions", "cheating", "other")


@dataclass
class Live:
    """What only the running server knows, taken on the event loop."""
    now: float
    names: Dict[str, str] = field(default_factory=dict)
    online: Set[str] = field(default_factory=set)
    playing: Set[str] = field(default_factory=set)
    locked: Dict[str, Optional[float]] = field(default_factory=dict)
    rooms: Dict[str, str] = field(default_factory=dict)  # room id -> name, for open rooms
    tables: List[dict] = field(default_factory=list)  # live tables for the Games page
    game_keys: Set[str] = field(default_factory=set)  # games being played right now
    counts: Dict[str, int] = field(default_factory=dict)  # playing, waiting, bot_matches, in_menus
    latest_app: str = ""
    min_app: str = ""


class Reader:
    def __init__(self, db: sqlite3.Connection, live: Live, tz: tzinfo):
        self.db, self.live, self.tz, self.now = db, live, tz, live.now
        self._cache: Dict[tuple, list] = {}

    # ----- plumbing ------------------------------------------------------

    def events(self, type_: str, start: float = 0.0, end: Optional[float] = None) -> List[tuple]:
        """(id, t, player, room, data) rows of one type, oldest first."""
        key = (type_, start, end)
        if key not in self._cache:
            rows = self.db.execute("SELECT id, t, player, room, data FROM events WHERE type = ? AND t >= ? AND t < ? "
                                   "ORDER BY t", (type_, start, end if end is not None else self.now + 1)).fetchall()
            self._cache[key] = [(i, t, p, r, json.loads(d)) for i, t, p, r, d in rows]
        return self._cache[key]

    def first_event(self) -> float:
        row = self.db.execute("SELECT MIN(t) FROM events").fetchone()
        return row[0] if row and row[0] else self.now

    def local(self, t: float) -> datetime:
        return datetime.fromtimestamp(t, self.tz)

    def midnight(self, t: float) -> float:
        d = self.local(t)
        return datetime(d.year, d.month, d.day, tzinfo=self.tz).timestamp()

    def days(self, start: float, end: float) -> List[float]:
        """Local midnights from the day of ``start`` up to the day of ``end``."""
        out, d = [], self.local(start).date()
        last = self.local(end).date()
        while d <= last:
            out.append(datetime(d.year, d.month, d.day, tzinfo=self.tz).timestamp())
            d += timedelta(days=1)
        return out

    def window(self, rng: str) -> Tuple[float, float]:
        """(start, previous start) of the chosen range; the previous one is as long."""
        if rng == "all":
            start = min(self.first_event(), self.now - DAY)
            return start, start - (self.now - start)
        length = RANGES.get(rng, RANGES["7d"])
        return self.now - length, self.now - 2 * length

    def player(self, pid: Optional[str]) -> dict:
        if not pid:
            return {"id": None, "sid": "bot", "name": "Bot", "auto": False, "bot": True}
        name = self.live.names.get(pid)
        auto = not name or name == "Player"
        return {"id": pid, "sid": names.short_id(pid), "name": names.fun_name(pid) if auto else name,
                "auto": auto, "masked": None if auto else names.mask(name)}

    def status(self, pid: str) -> str:
        if pid in self.live.playing:
            return "playing"
        return "online" if pid in self.live.online else "offline"

    def table_names(self) -> Dict[str, str]:
        """Room id -> table name, from games ever played and rooms open now."""
        out = {}
        for _, _, _, room, data in self.events("game_start"):
            if room and data.get("table"):
                out[room] = data["table"]
        out.update(self.live.rooms)
        return out

    # ----- shared numbers ------------------------------------------------

    def games(self, start: float, end: Optional[float] = None, bot_matches: bool = False) -> List[dict]:
        """Finished or abandoned games that ended in the window."""
        out = []
        for i, t, _, room, d in self.events("game_end", start, end):
            if d.get("bot_match") and not bot_matches:
                continue
            out.append({**d, "end": t, "room": room, "event": i})
        return out

    def active_days(self, start: float, end: Optional[float] = None) -> Dict[str, Set[float]]:
        """Player -> local days they opened the app on."""
        out: Dict[str, Set[float]] = defaultdict(set)
        for _, t, pid, _, _ in self.events("session_start", start, end):
            if pid:
                out[pid].add(self.midnight(t))
        return out

    def first_seen(self) -> Dict[str, float]:
        return {p: t for p, t in self.db.execute(
            "SELECT player, MIN(t) FROM events WHERE type = 'session_start' AND player IS NOT NULL GROUP BY player")}

    def last_seen(self) -> Dict[str, float]:
        out = {p: t for p, t in self.db.execute(
            "SELECT player, MAX(t) FROM events WHERE type IN ('session_start', 'session_end') "
            "AND player IS NOT NULL GROUP BY player")}
        for pid in self.live.online:
            out[pid] = self.now
        return out

    def retention(self, start: float, end: float, gap_days: int) -> Optional[float]:
        """Share of players active on a day in the window who came back ``gap_days`` later
        (exactly one day later for 1; any day at least that much later otherwise)."""
        active = self.active_days(start - gap_days * DAY - DAY, self.now)
        today = self.midnight(self.now)
        eligible = came = 0
        for days in active.values():
            for d in days:
                if not (start <= d + gap_days * DAY < end) or d + gap_days * DAY > today:
                    continue
                eligible += 1
                later = [x for x in days if x > d]
                if (gap_days == 1 and any(abs(x - d - DAY) < 2 * HOUR for x in later)) or \
                        (gap_days > 1 and any(x - d >= gap_days * DAY - 2 * HOUR for x in later)):
                    came += 1
        return came / eligible if eligible else None

    def regulars(self, end: float) -> Set[str]:
        days = self.active_days(end - 7 * DAY, end)
        return {p for p, d in days.items() if len(d) >= REGULAR_DAYS}

    def sparkline(self, values_for_day, count: int = 14) -> List[float]:
        today = self.midnight(self.now)
        return [values_for_day(today - (count - 1 - i) * DAY) for i in range(count)]

    def per_day(self, events: Iterable[tuple], count: int = 14, unique: bool = False) -> List[float]:
        today = self.midnight(self.now)
        buckets: Dict[int, set] = defaultdict(set)
        counts: Counter = Counter()
        for row in events:
            t, pid = row[1], row[2]
            i = round((self.midnight(t) - today) / DAY) + count - 1
            if 0 <= i < count:
                if unique:
                    buckets[i].add(pid)
                else:
                    counts[i] += 1
        return [len(buckets[i]) if unique else counts[i] for i in range(count)]

    def month(self) -> dict:
        d = self.local(self.now)
        start = datetime(d.year, d.month, 1, tzinfo=self.tz)
        prev = datetime(d.year - 1, 12, 1, tzinfo=self.tz) if d.month == 1 else datetime(d.year, d.month - 1, 1, tzinfo=self.tz)
        nxt = datetime(d.year + 1, 1, 1, tzinfo=self.tz) if d.month == 12 else datetime(d.year, d.month + 1, 1, tzinfo=self.tz)
        this = len(self.active_days(start.timestamp()))
        last = len(self.active_days(prev.timestamp(), start.timestamp()))
        return {"this": this, "last": last, "day": d.day, "days": (nxt - start).days,
                "start": start.timestamp(), "change": (this - last) / last if last else None}

    def shell(self) -> dict:
        """The sidebar: badges and the "players this month" card."""
        return {"reports_open": self.db.execute(
                    "SELECT COUNT(DISTINCT target) FROM reports WHERE status = 'open'").fetchone()[0],
                "problems_open": sum(1 for p in self.problem_list() if p["status"] == "open"),
                "month": self.month(), "now": self.now}

    # ----- overview ------------------------------------------------------

    def overview(self, rng: str) -> dict:
        start, prev = self.window(rng)
        games, before = self.games(start), self.games(prev, start)
        active, active_before = self.active_days(start), self.active_days(prev, start)
        finished = [g["seconds"] for g in games if g.get("finished")]
        finished_before = [g["seconds"] for g in before if g.get("finished")]
        next_day = self.retention(start, self.now, 1)
        next_day_before = self.retention(prev, start, 1)
        return {
            "range": rng,
            "kpis": {
                "games": len(games), "games_prev": len(before),
                "players": len(active), "players_prev": len(active_before),
                "avg_game": mean(finished) if finished else None,
                "avg_game_prev": mean(finished_before) if finished_before else None,
                "next_day": next_day, "next_day_prev": next_day_before,
            },
            "chart": self.games_chart(rng, start, games),
            "live": self.live_now(),
            "attention": [p for p in self.problem_list() if p["status"] == "open"][:3],
            "players": self.top_players(start),
            "heatmap": self.heatmap(max(start, self.now - 7 * DAY) if rng == "24h" else start),
            "coming_back": {
                "next_day": next_day, "next_day_prev": next_day_before,
                "after_7": self.retention(start, self.now, 7), "after_7_prev": self.retention(prev, start, 7),
                "regulars": len(self.regulars(self.now)),
            },
        }

    def games_chart(self, rng: str, start: float, games: List[dict]) -> dict:
        """Stacked bars: real players, with bots, abandoned. Hours for 24h, 4-hour
        blocks for 7d, days otherwise (weeks for long "all" ranges)."""
        if rng == "24h":
            step, first = HOUR, self.now - self.now % HOUR - 23 * HOUR
            count = 24
        elif rng == "7d":
            step = 4 * HOUR
            first = self.midnight(self.now) - 6 * DAY
            count = 42
        else:
            first = self.midnight(start)
            span_days = int((self.now - first) // DAY) + 1
            step = DAY if span_days <= 92 else 7 * DAY
            count = int((self.now - first) // step) + 1
        bars = [{"t": first + i * step, "real": 0, "bots": 0, "abandoned": 0} for i in range(count)]
        for g in games:
            i = int((g["end"] - first) // step)
            if 0 <= i < count:
                key = "abandoned" if not g.get("finished") else "bots" if g.get("bots") else "real"
                bars[i][key] += 1
        return {"step": step, "bars": bars}

    def live_now(self) -> dict:
        record = self.db.execute("SELECT MAX(json_extract(data, '$.players')) FROM events WHERE type = 'online'").fetchone()[0]
        online = len(self.live.online)
        return {"online": online, "record": max(record or 0, online), **self.live.counts}

    def top_players(self, start: float, limit: int = 6) -> List[dict]:
        stats = self.player_stats(start)
        last = self.last_seen()
        week = self.events("player_game", self.midnight(self.now) - 6 * DAY)
        per_day: Dict[str, Counter] = defaultdict(Counter)
        today = self.midnight(self.now)
        for _, t, pid, _, _ in week:
            per_day[pid][round((self.midnight(t) - today) / DAY) + 6] += 1
        order = {"playing": 0, "online": 1, "offline": 2}
        pids = set(stats) | self.live.online
        rows = sorted(pids, key=lambda p: (order[self.status(p)], -stats.get(p, {}).get("games", 0)))[:limit]
        return [{**self.player(p), "status": self.status(p), "games": stats.get(p, {}).get("games", 0),
                 "week": [per_day[p][i] for i in range(7)], "win_rate": stats.get(p, {}).get("win_rate"),
                 "avg_game": stats.get(p, {}).get("avg_game"), "last_seen": last.get(p)} for p in rows]

    def player_stats(self, start: float, end: Optional[float] = None) -> Dict[str, dict]:
        rows = self.db.execute(
            "SELECT player, COUNT(*), SUM(json_extract(data, '$.won')), AVG(json_extract(data, '$.seconds')), "
            "SUM(json_extract(data, '$.bluffs')), SUM(json_extract(data, '$.bets')) FROM events "
            "WHERE type = 'player_game' AND t >= ? AND t < ? GROUP BY player",
            (start, end if end is not None else self.now + 1)).fetchall()
        return {p: {"games": n, "wins": w or 0, "win_rate": (w or 0) / n if n else None, "avg_game": avg,
                    "bluff_rate": (b or 0) / bets if bets else None} for p, n, w, avg, b, bets in rows}

    def heatmap(self, start: float) -> List[List[int]]:
        grid = [[0] * 24 for _ in range(7)]
        for _, t, _, _, d in self.events("game_start", start):
            if not d.get("bot_match"):
                local = self.local(t)
                grid[local.weekday()][local.hour] += 1
        return grid

    # ----- players -------------------------------------------------------

    def players(self, rng: str, tab: str, sort: str, q: str, page: int) -> dict:
        start, _ = self.window(rng)
        first, last = self.first_seen(), self.last_seen()
        stats = self.player_stats(start)
        regulars = self.regulars(self.now)
        pids = set(first) | set(self.live.online)
        week_ago = self.now - 7 * DAY
        if tab == "new":
            pids = {p for p in pids if first.get(p, self.now) >= week_ago}
        elif tab == "regulars":
            pids &= regulars
        elif tab == "inactive":
            pids = {p for p in pids if self.now - last.get(p, 0) >= INACTIVE_AFTER}
        rows = []
        for p in pids:
            info = self.player(p)
            if q and q.lower().lstrip("#") not in (info["name"].lower() + " " + info["sid"].lower()):
                continue
            s = stats.get(p, {})
            rows.append({**info, "status": self.status(p), "joined": first.get(p), "last_seen": last.get(p),
                         "new": first.get(p, 0) >= week_ago, "games": s.get("games", 0),
                         "win_rate": s.get("win_rate"), "bluff_rate": s.get("bluff_rate")})
        order = {"playing": 0, "online": 1, "offline": 2}
        keys = {
            "games": lambda r: -r["games"],
            "win_rate": lambda r: -(r["win_rate"] or -1),
            "joined": lambda r: -(r["joined"] or 0),
            "name": lambda r: r["name"].lower(),
        }
        rows.sort(key=keys.get(sort, lambda r: (order[r["status"]], -(r["last_seen"] or 0))))
        month = self.month()
        all_first = sorted(first.values())
        churned = {p for p, t in last.items() if INACTIVE_AFTER <= self.now - t < 30 * DAY}
        churned_before = {p for p, t in last.items() if INACTIVE_AFTER <= self.now - DAY - t < 30 * DAY}
        online_samples = self.events("online", self.midnight(self.now) - 13 * DAY)
        peak: Dict[int, int] = defaultdict(int)
        today = self.midnight(self.now)
        for _, t, _, _, d in online_samples:
            i = round((self.midnight(t) - today) / DAY) + 13
            peak[i] = max(peak[i], d.get("players", 0))
        return {
            "kpis": {
                "total": len(first), "total_prev": len([t for t in all_first if t < month["start"]]),
                "total_spark": [len([t for t in all_first if t < d + DAY]) for d in self.sparkline(lambda d: d)],
                "new_week": len([t for t in all_first if t >= week_ago]),
                "new_week_prev": len([t for t in all_first if week_ago - 7 * DAY <= t < week_ago]),
                "new_spark": self.per_day([(0, t, p) for p, t in first.items()]),
                "online": len(self.live.online), "record": self.live_now()["record"],
                "online_spark": [peak[i] for i in range(14)],
                "regulars": len(regulars), "regulars_prev": len(self.regulars(self.now - 7 * DAY)),
                "regulars_spark": self.sparkline(lambda d: len(self.regulars(d + DAY))),
                "churned": len(churned), "churned_change": len(churned) - len(churned_before),
                "churned_spark": self.sparkline(
                    lambda d: len([p for p, t in last.items() if INACTIVE_AFTER <= d + DAY - t < 30 * DAY])),
            },
            "counts": {"all": len(set(first) | self.live.online)},
            "total": len(rows), "page": page, "page_size": PAGE,
            "rows": rows[page * PAGE:(page + 1) * PAGE],
        }

    def player_detail(self, pid: str) -> dict:
        info = self.player(pid)
        games = self.events("player_game")
        mine = [(t, room, d) for _, t, p, room, d in games if p == pid]
        sessions = [d for _, _, p, _, d in self.events("session_start") if p == pid]
        first = self.db.execute("SELECT MIN(t) FROM events WHERE player = ?", (pid,)).fetchone()[0]
        won = [d for _, _, d in mine if d.get("won")]
        totals = Counter()
        for _, _, d in mine:
            for k in ("bets", "bluffs", "caught", "checks", "called_right", "timeouts"):
                totals[k] += d.get(k, 0)
        vs_bots = [d for _, _, d in mine if d.get("bots")]
        vs_people = [d for _, _, d in mine if not d.get("bots")]
        days = sorted({self.midnight(t) for t, _, _ in mine}, reverse=True)
        streak, expect = 0, self.midnight(self.now)
        if days and days[0] < expect:
            expect -= DAY  # a streak still counts if today has no game yet
        for d in days:
            if abs(d - expect) < 2 * HOUR:
                streak += 1
                expect -= DAY
            elif d < expect:
                break
        last20 = [{"won": bool(d.get("won")), "quit": d.get("out") in ("left", "kicked")} for _, _, d in mine[-20:]]
        today = self.midnight(self.now)
        month = Counter(round((self.midnight(t) - today) / DAY) + 29 for t, _, _ in mine if t >= today - 29 * DAY)
        slots = Counter((self.local(t).weekday(), self.local(t).hour // 2) for t, _, _ in mine)
        tables = self.table_names()
        rooms = Counter(tables.get(room, "") for _, room, _ in mine if room)
        sizes = Counter(d.get("players") for _, _, d in mine if d.get("players"))
        refused = self.db.execute("SELECT COUNT(*) FROM refused_names WHERE player = ?", (pid,)).fetchone()[0]
        reports = self.db.execute("SELECT COUNT(*) FROM reports WHERE target = ?", (pid,)).fetchone()[0]
        return {
            **info, "status": self.status(pid), "first_seen": first,
            "platform": sessions[-1].get("platform") if sessions else None,
            "app_version": sessions[-1].get("app_version") if sessions else None,
            "games": len(mine), "win_rate": len(won) / len(mine) if mine else None,
            "avg_game": mean(d.get("seconds", 0) for _, _, d in mine) if mine else None,
            "streak": streak, "last20": last20,
            "bluffing": {
                "bluffs": totals["bluffs"], "bets": totals["bets"], "caught": totals["caught"],
                "checks": totals["checks"], "called_right": totals["called_right"], "timeouts": totals["timeouts"],
            },
            "vs_bots": sum(1 for d in vs_bots if d.get("won")) / len(vs_bots) if vs_bots else None,
            "vs_people": sum(1 for d in vs_people if d.get("won")) / len(vs_people) if vs_people else None,
            "month": [month[i] for i in range(30)],
            "plays_most": list(slots.most_common(1)[0][0]) if slots else None,
            "favorite_room": rooms.most_common(1)[0][0] if rooms and rooms.most_common(1)[0][0] else None,
            "usual_table": sizes.most_common(1)[0][0] if sizes else None,
            "reports": reports, "refused": refused, "locked": pid in self.live.locked,
        }

    # ----- games ---------------------------------------------------------

    def game_numbers(self) -> Dict[str, Tuple[int, float, dict]]:
        """Game key -> (number, start time, game_start data)."""
        starts = [(t, d) for _, t, _, _, d in self.events("game_start") if d.get("game")]
        return {d["game"]: (n, t, d) for n, (t, d) in enumerate(starts, 1)}

    def games_page(self, rng: str, tab: str, q: str, page: int) -> dict:
        start, prev = self.window(rng)
        games, before = self.games(start), self.games(prev, start)
        numbers = self.game_numbers()
        people: Dict[str, List[str]] = defaultdict(list)
        for _, _, pid, _, d in self.events("player_game", start - DAY):
            people[d.get("game")].append(pid)
        ends = {g["game"]: g for g in self.games(start, None, bot_matches=True)}
        rows = []
        for key, (number, t, d) in numbers.items():
            if t < start or (key not in ends and key not in self.live.game_keys):
                continue  # older, or a game the server lost track of
            rows.append(self.game_row(number, t, d, ends.get(key), people.get(key, [])))
        if tab == "finished":
            rows = [r for r in rows if r["result"] == "finished"]
        elif tab == "abandoned":
            rows = [r for r in rows if r["result"] == "abandoned"]
        elif tab == "bots":
            rows = [r for r in rows if r["bots"]]
        if q:
            needle = q.lower().lstrip("#")
            rows = [r for r in rows if needle in str(r["number"]) or needle in r["table"].lower()
                    or any(needle in (p["name"].lower() + " " + p["sid"].lower()) for p in r["players"])]
        rows.sort(key=lambda r: -r["start"])
        lengths = [g["seconds"] for g in games if g.get("finished")]
        lengths_before = [g["seconds"] for g in before if g.get("finished")]
        seats = [g.get("humans", 0) + g.get("bots", 0) for g in games]
        seats_before = [g.get("humans", 0) + g.get("bots", 0) for g in before]

        def share(items, pred):
            return sum(1 for g in items if pred(g)) / len(items) if items else None

        recent = self.games(self.midnight(self.now) - 13 * DAY)
        by_day: Dict[int, List[dict]] = defaultdict(list)
        today = self.midnight(self.now)
        for g in recent:
            by_day[round((self.midnight(g["end"]) - today) / DAY) + 13].append(g)
        sizes = Counter(g.get("humans", 0) + g.get("bots", 0) for g in games)
        return {
            "kpis": {
                "games": len(games), "games_prev": len(before),
                "games_spark": [len(by_day[i]) for i in range(14)],
                "avg_game": mean(lengths) if lengths else None,
                "avg_game_prev": mean(lengths_before) if lengths_before else None,
                "avg_spark": [mean([g["seconds"] for g in by_day[i] if g.get("finished")] or [0]) for i in range(14)],
                "seats": mean(seats) if seats else None, "seats_prev": mean(seats_before) if seats_before else None,
                "seats_spark": [mean([g.get("humans", 0) + g.get("bots", 0) for g in by_day[i]] or [0]) for i in range(14)],
                "with_bots": share(games, lambda g: g.get("bots")),
                "with_bots_prev": share(before, lambda g: g.get("bots")),
                "bots_spark": [share(by_day[i], lambda g: g.get("bots")) or 0 for i in range(14)],
                "abandoned": share(games, lambda g: not g.get("finished")),
                "abandoned_prev": share(before, lambda g: not g.get("finished")),
                "abandoned_spark": [share(by_day[i], lambda g: not g.get("finished")) or 0 for i in range(14)],
            },
            "by_hour": self.games_by_hour(),
            "sizes": [[n, sizes.get(n, 0)] for n in range(2, 9)],
            "vs_bots": self.win_vs_bots(start),
            "total": len(rows), "page": page, "page_size": PAGE, "rows": rows[page * PAGE:(page + 1) * PAGE],
            "live_tables": self.live.tables,
        }

    def game_row(self, number: int, t: float, start: dict, end: Optional[dict], pids: List[str]) -> dict:
        winner = None
        if end and end.get("finished"):
            if end.get("winner_is_bot"):
                winner = {"bot": True, "level": end.get("bot_level") or "easy"}
            elif end.get("winner"):
                winner = self.player(end["winner"])
        result = "playing" if end is None else "finished" if end.get("finished") else "abandoned"
        return {
            "key": start.get("game"), "number": number, "start": t, "table": start.get("table") or "",
            "bot_match": bool(start.get("bot_match")), "players": [self.player(p) for p in pids],
            "bots": start.get("bots", 0), "rounds": end.get("deals") if end else None,
            "bluffs": end.get("bluffs") if end else None, "seconds": end.get("seconds") if end else None,
            "winner": winner, "result": result, "quits": end.get("left", 0) if end else 0,
        }

    def games_by_hour(self) -> dict:
        today = self.midnight(self.now)
        now_hour = self.local(self.now).hour
        todays = [0] * 24
        abandoned = [0] * 24
        usual = [0.0] * 24
        for g in self.games(today):
            h = self.local(g["end"]).hour
            todays[h] += 1
            abandoned[h] += 0 if g.get("finished") else 1
        before = self.games(today - 7 * DAY, today)
        for g in before:
            usual[self.local(g["end"]).hour] += 1 / 7
        return {"today": todays, "abandoned": abandoned, "usual": [round(u, 2) for u in usual], "hour": now_hour}

    def win_vs_bots(self, start: float) -> dict:
        out = {}
        for level in ("easy", "medium", "hard"):
            rows = [d for _, _, _, _, d in self.events("player_game", start) if d.get("bot_level") == level]
            out[level] = sum(1 for d in rows if d.get("won")) / len(rows) if rows else None
        return out

    def game_detail(self, key: str) -> Optional[dict]:
        numbers = self.game_numbers()
        if key not in numbers:
            return None
        number, t, start = numbers[key]
        end = next((g for g in self.games(t - 1, None, True) if g["game"] == key), None)
        pids = [p for _, _, p, _, d in self.events("player_game", t - 1) if d.get("game") == key]
        row = self.game_row(number, t, start, end, pids)
        standing = []
        for s in (end or {}).get("standing", []):
            who = {"bot": True, "level": end.get("bot_level") or "easy"} if s.get("bot") else self.player(s.get("id"))
            standing.append({**who, "out_deal": s.get("out_deal"), "reason": s.get("reason"),
                             "bluffs": s.get("bluffs", 0)})
        moves = []
        for m in reversed((end or {}).get("moves", [])):
            who = self.player(m["id"]) if m.get("id") else {"bot": True, "name": "Bot", "sid": "bot"}
            moves.append({**m, "who": who})
        return {**row, "end": end["end"] if end else None, "checks": (end or {}).get("checks"),
                "humans": start.get("humans"), "standing": standing, "moves": moves}

    # ----- problems ------------------------------------------------------

    def problem_states(self) -> Dict[str, Tuple[str, float, Optional[float]]]:
        return {i: (s, since, muted) for i, s, since, muted in
                self.db.execute("SELECT id, status, since, muted_until FROM problem_state")}

    def problem_list(self) -> List[dict]:
        if ("problems",) in self._cache:
            return self._cache[("problems",)]
        week = self.now - 7 * DAY
        today = self.midnight(self.now)
        found: List[dict] = []
        errors = self.events("error", week)
        by_kind: Dict[str, List[tuple]] = defaultdict(list)
        for row in errors:
            by_kind[row[4].get("kind", "error")].append(row)
        for kind, rows in by_kind.items():
            title, short, severity, _ = ERROR_KINDS.get(kind, (kind.replace("_", " ").capitalize(), kind, "medium", ""))
            first = self.db.execute("SELECT MIN(t) FROM events WHERE type = 'error' AND json_extract(data, '$.kind') = ?",
                                    (kind,)).fetchone()[0]
            players = {p for r in rows for p in ([r[2]] if r[2] else []) + list(r[4].get("players") or [])}
            found.append({"id": f"error:{kind}", "kind": "error", "title": title,
                          "subtitle": f"{short} · {kind}", "severity": severity, "first_seen": first,
                          "last_seen": rows[-1][1], "count": len(rows), "players": len(players),
                          "last_hour": sum(1 for r in rows if r[1] >= self.now - HOUR),
                          "strip": self.error_strip(rows), "active_since": rows[-1][1]})
        todays = self.games(today)
        usual = self.games(today - 7 * DAY, today)
        share_today = sum(1 for g in todays if not g.get("finished")) / len(todays) if todays else 0
        share_usual = sum(1 for g in usual if not g.get("finished")) / len(usual) if usual else 0
        if len(todays) >= 5 and share_today >= 0.1 and share_today >= 2 * max(share_usual, 0.01):
            quits = [g for g in todays if not g.get("finished") or g.get("left")]
            found.append({"id": "abandoned", "kind": "abandoned", "title": "Abandoned games up",
                          "subtitle": f"{share_today:.0%} of games quit early today vs {share_usual:.0%} usual",
                          "severity": "medium", "first_seen": today, "last_seen": todays[-1]["end"],
                          "count": len(quits), "players": sum(g.get("humans", 0) for g in quits),
                          "today": share_today, "usual": share_usual, "times": share_today / max(share_usual, 0.01),
                          "strip": self.abandoned_strip(), "active_since": today})
        old = self.old_versions(week)
        if old["outdated"]:
            found.append({"id": "old_app", "kind": "old_app", "title": "Old app version",
                          "subtitle": f"{old['outdated']} players on {old['oldest']} · update needed",
                          "severity": "low", "first_seen": old["since"], "last_seen": self.now,
                          "count": old["outdated"], "players": old["outdated"], "versions": old["versions"],
                          "active_since": self.now})
        timeouts_today = [g.get("timeouts", 0) for g in todays]
        timeouts_usual = [g.get("timeouts", 0) for g in usual]
        if len(todays) >= 5 and timeouts_usual and mean(timeouts_today) >= 3 * max(mean(timeouts_usual), 0.2):
            found.append({"id": "timeouts", "kind": "timeouts", "title": "Many timeouts",
                          "subtitle": f"Players let the timer run {mean(timeouts_today) / max(mean(timeouts_usual), 0.2):.0f}x more than usual",
                          "severity": "medium", "first_seen": today, "last_seen": self.now,
                          "count": sum(timeouts_today), "players": None, "active_since": today})
        slow = [(t, d) for _, t, _, _, d in self.events("online", self.now - DAY) if (d.get("ms_p95") or 0) > SLOW_MS]
        if slow:
            found.append({"id": "slow", "kind": "slow", "title": "Slow replies",
                          "subtitle": f"p95 over {SLOW_MS:.0f} ms in {len(slow)} minutes today",
                          "severity": "low", "first_seen": slow[0][0], "last_seen": slow[-1][0],
                          "count": len(slow), "players": None, "active_since": slow[-1][0]})
        states = self.problem_states()
        for p in found:
            status, since, muted = states.get(p["id"], ("open", 0, None))
            if status == "resolved" and p["active_since"] > since and p["kind"] == "error":
                status = "open"  # it came back
            if status == "watching" and muted is not None and muted < self.now:
                status = "open"
            p["status"], p["status_since"], p["muted_until"] = status, since, muted
        # Resolved problems that no longer happen still show under "Resolved".
        for pid, (status, since, muted) in states.items():
            if status == "resolved" and not any(p["id"] == pid for p in found) and since >= self.now - 30 * DAY:
                kind = pid.split(":", 1)[-1]
                title = ERROR_KINDS.get(kind, (kind.replace("_", " ").capitalize(),))[0]
                found.append({"id": pid, "kind": "gone", "title": title, "subtitle": "No longer happening",
                              "severity": "low", "first_seen": since, "last_seen": since, "count": 0,
                              "players": None, "status": "resolved", "status_since": since, "muted_until": None})
        rank = {"high": 0, "medium": 1, "low": 2}
        found.sort(key=lambda p: ({"open": 0, "watching": 1, "resolved": 2}[p["status"]], rank[p["severity"]],
                                  -(p["last_seen"] or 0)))
        self._cache[("problems",)] = found
        return found

    def error_strip(self, rows: List[tuple]) -> List[int]:
        """Errors per 5 minutes over the last two hours."""
        start = self.now - 2 * HOUR
        out = [0] * 24
        for r in rows:
            if r[1] >= start:
                out[min(23, int((r[1] - start) // 300))] += 1
        return out

    def abandoned_strip(self) -> List[float]:
        """Share of games quit early per hour today, next to the usual share."""
        today = self.midnight(self.now)
        out = []
        for h in range(self.local(self.now).hour + 1):
            games = [g for g in self.games(today + h * HOUR, today + (h + 1) * HOUR)]
            out.append(sum(1 for g in games if not g.get("finished")) / len(games) if games else 0)
        return out

    def old_versions(self, start: float) -> dict:
        latest: Dict[str, Tuple[float, str]] = {}
        for _, t, pid, _, d in self.events("session_start", start):
            if pid and d.get("app_version") and d.get("platform") in ("ios", "android"):
                latest[pid] = (t, d["app_version"])
        versions = Counter(v for _, v in latest.values())
        target = self.live.min_app or self.live.latest_app
        outdated = {p: v for p, (_, v) in latest.items() if target and _version(v) < _version(target)}
        since = min((latest[p][0] for p in outdated), default=self.now)
        return {"versions": versions.most_common(), "outdated": len(outdated),
                "oldest": min(outdated.values(), key=_version) if outdated else None, "since": since}

    def problems(self, rng: str, tab: str) -> dict:
        found = self.problem_list()
        day_ago = self.now - DAY
        errors = self.events("error", day_ago - DAY)
        last, prev = [e for e in errors if e[1] >= day_ago], [e for e in errors if e[1] < day_ago]
        online = self.events("online", day_ago - DAY)
        hours: List[dict] = [{"t": self.now - self.now % HOUR - (23 - i) * HOUR, "errors": 0, "requests": 0}
                             for i in range(24)]
        first_hour = hours[0]["t"]
        for _, t, *_ in last:
            i = int((t - first_hour) // HOUR)
            if 0 <= i < 24:
                hours[i]["errors"] += 1
        rejected: Counter = Counter()
        p95_now, p95_before = [], []
        for _, t, _, _, d in online:
            i = int((t - first_hour) // HOUR)
            if 0 <= i < 24 and t >= day_ago:
                hours[i]["requests"] += d.get("requests", 0)
                rejected.update(d.get("failed") or {})
            if d.get("ms_p95") is not None:
                if t >= self.now - HOUR:
                    p95_now.append(d["ms_p95"])
                elif t >= self.now - 2 * HOUR:
                    p95_before.append(d["ms_p95"])
        deploys = [{"t": t, "version": d.get("version")} for _, t, _, _, d in self.events("server_start", day_ago)]
        for dep in deploys:
            after = [e[1] for e in last if e[1] >= dep["t"]]
            dep["errors_after"] = (after[0] - dep["t"]) if after else None
        sessions = self.events("session_start", self.now - 7 * DAY)
        week_errors = self.events("error", self.now - 7 * DAY)
        hit = {e[2] for e in week_errors if e[2]} | {p for e in week_errors for p in e[4].get("players") or []}
        players = {s[2] for s in sessions if s[2]}
        today_errors = [e for e in errors if e[1] >= self.midnight(self.now)]
        affected = {e[2] for e in today_errors if e[2]} | {p for e in today_errors for p in e[4].get("players") or []}
        kinds = Counter(e[4].get("kind", "error") for e in self.events("error", self.window(rng)[0]))
        states = Counter(p["status"] for p in found)
        opened_today = [p for p in found if p["status"] == "open" and (p["first_seen"] or 0) >= day_ago]
        listed = [p for p in found if tab == "all" or p["status"] == tab]
        return {
            "kpis": {
                "open": states["open"], "open_new": len(opened_today),
                "errors": len(last), "errors_prev": len(prev),
                "errors_spark": [h["errors"] for h in hours[-14:]],
                "clean_sessions": 1 - len(hit & players) / len(players) if players else None,
                "p95": max(p95_now) if p95_now else None, "p95_prev": max(p95_before) if p95_before else None,
                "affected": len(affected),
            },
            "hours": hours, "deploys": deploys,
            "by_type": [{"kind": k, "label": ERROR_KINDS.get(k, (k,))[0], "count": n} for k, n in kinds.most_common()],
            "rejected": [{"code": c, "label": REJECTED.get(c, c.replace("_", " ").capitalize()), "count": n}
                         for c, n in rejected.most_common(3)],
            "counts": {"open": states["open"], "watching": states["watching"], "resolved": states["resolved"]},
            "rows": listed,
        }

    def problem_detail(self, problem: str) -> Optional[dict]:
        p = next((x for x in self.problem_list() if x["id"] == problem), None)
        if p is None:
            return None
        events = []
        if problem.startswith("error:"):
            kind = problem.split(":", 1)[1]
            p["description"] = ERROR_KINDS.get(kind, ("", "", "", "An error the server reported."))[3]
            tables = self.table_names()
            rows = self.db.execute("SELECT t, player, room, data FROM events WHERE type = 'error' AND "
                                   "json_extract(data, '$.kind') = ? ORDER BY t DESC LIMIT 30", (kind,)).fetchall()
            for t, pid, room, data in rows:
                d = json.loads(data)
                who = pid or (d.get("players") or [None])[0]
                events.append({"t": t, "label": ERROR_KINDS.get(kind, (kind, kind))[1].lower(),
                               "table": tables.get(room or "", ""), "player": names.short_id(who) if who else "bot",
                               "message": d.get("message", "")})
        else:
            p["description"] = {
                "abandoned": "More games than usual ended with everyone leaving, or someone quitting mid-game.",
                "old_app": "Players on an app version older than the one the server asks for.",
                "timeouts": "Players let their turn timer run out more often than usual today.",
                "slow": "The server took longer than usual to answer requests.",
            }.get(p["kind"], "")
        return {**p, "events": events}

    # ----- moderation ----------------------------------------------------

    def moderation(self, tab: str, show: bool) -> dict:
        reports = self.db.execute("SELECT id, t, reporter, target, name, room, reason, note, status, handled_at "
                                  "FROM reports ORDER BY t").fetchall()
        tables = self.table_names()
        grouped: Dict[str, dict] = {}
        for rid, t, reporter, target, name, room, reason, note, status, handled in reports:
            g = grouped.setdefault(target, {"reasons": Counter(), "reporters": set(), "count": 0, "open": 0})
            g["reasons"][reason] += 1
            g["reporters"].add(reporter)
            g["count"] += 1
            g["open"] += status == "open"
            g.update({"name": name, "room": room, "last": t, "status": status})
        rows = []
        for target, g in grouped.items():
            now_name = self.player(target)
            status = "open" if g["open"] else g["status"]
            rows.append({"id": target, "sid": names.short_id(target), "name": g["name"],
                         "masked": names.mask(g["name"]),
                         "now": now_name["name"] if now_name["name"] != g["name"] else None,
                         "now_auto": now_name["auto"],
                         "reason": g["reasons"].most_common(1)[0][0], "more": len(g["reasons"]) - 1,
                         "count": g["count"], "by": len(g["reporters"]), "table": tables.get(g["room"] or "", ""),
                         "last": g["last"], "status": status})
        rows.sort(key=lambda r: (r["status"] != "open", -r["last"]))
        counts = Counter("open" if r["status"] == "open" else "resolved" for r in rows)
        listed = [r for r in rows if tab == "all" or (r["status"] == "open") == (tab == "open")]
        week = self.now - 7 * DAY
        week_reports = [r for r in reports if r[1] >= week]
        refused = self.db.execute("SELECT t, player, name FROM refused_names").fetchall()
        words = self.db.execute("SELECT word, whole, added FROM blocked_words ORDER BY added DESC").fetchall()
        your_words = [{"word": w, "masked": names.mask_word(w), "whole": bool(whole), "added": added,
                       "stopped": sum(1 for _, _, n in refused if names.word_matches(w, bool(whole), n))}
                      for w, whole, added in words]
        builtin = {"English": [names.mask_word(w) for w in names.ANYWHERE_EN + names.WHOLE_EN],
                   "Polish": [names.mask_word(w) for w in names.ANYWHERE_PL + names.WHOLE_PL]}
        locked = [{**self.player(p), "locked_at": at} for p, at in self.live.locked.items()]
        locked.sort(key=lambda r: -(r["locked_at"] or 0))
        day_ago = self.now - DAY
        refused_week = [r for r in refused if r[0] >= week]
        today = self.midnight(self.now)
        return {
            "kpis": {
                "open": counts["open"],
                "open_new": len({r[3] for r in reports if r[1] >= day_ago and r[8] == "open"}),
                "open_spark": self.per_day([(0, r[1], r[3]) for r in reports if r[8] == "open"]),
                "week": len(week_reports), "week_from": len({r[3] for r in week_reports}),
                "week_spark": self.per_day([(0, r[1], r[3]) for r in reports]),
                "refused": len(refused_week), "refused_spark": self.per_day([(0, r[0], r[1]) for r in refused]),
                "words": len(words), "builtin": len(names.ANYWHERE) + len(names.WHOLE_WORDS),
                "words_spark": [len([w for w in words if w[2] < today - (13 - i) * DAY + DAY]) for i in range(14)],
                "locked": len(locked),
                "locked_spark": [len([r for r in locked if (r["locked_at"] or 0) < today - (13 - i) * DAY + DAY])
                                 for i in range(14)],
            },
            "counts": {"open": counts["open"], "resolved": counts["resolved"], "all": len(rows)},
            "rows": listed, "words": your_words, "builtin": builtin, "locked": locked,
        }

    def moderation_detail(self, pid: str) -> dict:
        tables = self.table_names()
        reports = self.db.execute("SELECT t, reporter, name, room, reason, note, status, handled_at FROM reports "
                                  "WHERE target = ? ORDER BY t DESC", (pid,)).fetchall()
        refused = self.db.execute("SELECT name FROM refused_names WHERE player = ? ORDER BY t DESC", (pid,)).fetchall()
        actions = self.db.execute("SELECT t, action, detail FROM admin_actions WHERE player = ? ORDER BY t",
                                  (pid,)).fetchall()
        sessions = [d for _, _, p, _, d in self.events("session_start") if p == pid]
        first = self.db.execute("SELECT MIN(t) FROM events WHERE player = ?", (pid,)).fetchone()[0]
        games = self.db.execute("SELECT COUNT(*) FROM events WHERE type = 'player_game' AND player = ?",
                                (pid,)).fetchone()[0]
        reported_as = reports[0][2] if reports else self.player(pid)["name"]
        status = "open" if any(r[6] == "open" for r in reports) else (reports[0][6] if reports else "none")
        handled = max((r[7] or 0 for r in reports), default=0) or None
        current = self.player(pid)
        return {
            "id": pid, "sid": names.short_id(pid), "name": reported_as, "masked": names.mask(reported_as),
            "now": current["name"] if current["name"] != reported_as else None, "now_auto": current["auto"],
            "first_seen": first, "platform": sessions[-1].get("platform") if sessions else None,
            "status": status, "handled_at": handled, "games": games,
            "reports": [{"t": t, "by": names.short_id(r), "reason": reason, "note": note,
                         "table": tables.get(room or "", "")} for t, r, _, room, reason, note, _, _ in reports],
            "reporters": len({r[1] for r in reports}),
            "refused": [{"name": n, "masked": names.mask(n)} for (n,) in refused],
            "actions": [{"t": t, "action": a, "detail": d} for t, a, d in actions],
            "locked": pid in self.live.locked, "suggestions": names.fun_names(6),
        }


def _version(v: Optional[str]) -> Tuple[int, ...]:
    parts = []
    for piece in (v or "0").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
