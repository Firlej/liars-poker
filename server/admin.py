"""The admin dashboard at ``/admin``: login, its data and its few actions.

Login is one password, kept on the server only as a scrypt hash in the
``ADMIN_PASSWORD_HASH`` setting (make one with ``python -m server.admin``).
A good password gets a random session cookie (HttpOnly, SameSite=Strict,
30 days); the database keeps only a hash of it. Each wrong password locks
that address for 10 s, longer after five, and many failures from anywhere
lock the login for everyone for a few minutes.

Without ``ADMIN_PASSWORD_HASH`` the dashboard is off and ``/admin`` is a 404.
"""
from __future__ import annotations

import asyncio
import getpass
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import secrets
import sqlite3
import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote

from . import names, rules
from .dashboard import Live, Reader
from .rooms import LobbyError

if TYPE_CHECKING:
    from .app import GameServer

log = logging.getLogger("liars_poker.admin")

STATIC = Path(__file__).with_name("admin_static")
COOKIE = "lp_admin"
SESSION_DAYS = 30
MAX_BODY = 16_000
#: Wrong passwords: this lock after each, doubling after FREE_TRIES, up to MAX_LOCK.
LOCK_SECONDS = 10.0
FREE_TRIES = 5
MAX_LOCK = 900.0
#: This many wrong passwords in an hour, from anywhere, locks the login for GLOBAL_LOCK.
GLOBAL_FAILS = 30
GLOBAL_LOCK = 300.0
MUTE_SECONDS = 3600.0

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"), (b"cache-control", b"no-store"),
]


# ----- password --------------------------------------------------------------

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        kind, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)
    except ValueError:
        return False


class Throttle:
    """Slows down password guessing: per address, and for everyone at once."""

    def __init__(self):
        self.by_ip: Dict[str, Tuple[int, float]] = {}
        self.recent: deque = deque()
        self.global_until = 0.0

    def wait(self, ip: str, now: float) -> float:
        _, until = self.by_ip.get(ip, (0, 0.0))
        return max(0.0, until - now, self.global_until - now)

    def failed(self, ip: str, now: float) -> float:
        count, _ = self.by_ip.get(ip, (0, 0.0))
        count += 1
        lock = LOCK_SECONDS if count <= FREE_TRIES else min(MAX_LOCK, LOCK_SECONDS * 2 ** (count - FREE_TRIES))
        self.by_ip[ip] = (count, now + lock)
        self.recent.append(now)
        while self.recent and self.recent[0] < now - 3600:
            self.recent.popleft()
        if len(self.recent) >= GLOBAL_FAILS:
            self.global_until = now + GLOBAL_LOCK
        if len(self.by_ip) > 10_000:  # never grow without bound
            self.by_ip = {k: v for k, v in self.by_ip.items() if v[1] > now}
        return self.wait(ip, now)

    def succeeded(self, ip: str) -> None:
        self.by_ip.pop(ip, None)


# ----- bets in words, for live tables ------------------------------------------

RANK_WORDS = {"9": ("9", "9s"), "T": ("10", "10s"), "J": ("J", "Jacks"), "Q": ("Q", "Queens"),
              "K": ("K", "Kings"), "A": ("A", "Aces")}


def bet_text(bet: Optional[str]) -> Optional[str]:
    """"two_pair_K_Q" -> "two pair K & Q"."""
    if not bet:
        return None
    parts = bet.split("_")
    short = lambda r: RANK_WORDS.get(r, (r, r))[0]
    plural = lambda r: RANK_WORDS.get(r, (r, r))[1]
    if bet.startswith("high_card_"):
        return f"high card {plural(parts[-1])[:-1] if parts[-1] in 'JQKA' else short(parts[-1])}"
    if bet.startswith("pair_"):
        return f"pair of {plural(parts[1])}"
    if bet.startswith("two_pair_"):
        return f"two pair {short(parts[2])} & {short(parts[3])}"
    if bet in ("small_straight", "big_straight"):
        return bet.replace("_", " ")
    if bet.startswith("three_"):
        return f"three {plural(parts[1])}"
    if bet.startswith("full_"):
        return f"full house {short(parts[1])} over {short(parts[2])}"
    if bet.startswith("quad_"):
        return f"four {plural(parts[1])}"
    if bet.startswith("flush_"):
        return f"flush {parts[1]}"
    if bet.startswith("small_poker_") or bet.startswith("big_poker_"):
        return f"{parts[0]} poker {parts[-1]}"
    return bet.replace("_", " ")


# ----- the dashboard ---------------------------------------------------------------

class Admin:
    def __init__(self, server: "GameServer", password_hash: Optional[str], db_path: Optional[str],
                 tz_name: str = "Europe/Warsaw"):
        self.server = server
        self.password_hash = (password_hash or "").strip() or None
        self.db_path = db_path
        self.throttle = Throttle()
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(tz_name)
        except Exception:  # no tz database: fall back to UTC
            from datetime import timezone
            self.tz = timezone.utc
        #: Page files, read again when they change on disk: name -> (mtime, body, type).
        self.static: Dict[str, Tuple[float, bytes, str]] = {}
        if server.store is not None:
            names.set_custom((w, whole) for w, whole, _ in server.store.blocked_words())

    @property
    def enabled(self) -> bool:
        return bool(self.password_hash and self.server.store is not None and self.db_path)

    # ----- HTTP plumbing -------------------------------------------------

    async def handle(self, scope, receive, send) -> None:
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope.get("headers", [])}
        if not self.enabled:
            return await self._send(send, 404, {"ok": False, "error": "not_found"})
        if path in ("/admin", "/admin/"):
            body, _ = self._file("index.html") or (b"", "")
            return await self._raw(send, 200, body, "text/html; charset=utf-8", [(b"content-security-policy", CSP.encode())])
        if path.startswith("/admin/static/"):
            item = self._file(path.rsplit("/", 1)[-1])
            if item is None:
                return await self._send(send, 404, {"ok": False, "error": "not_found"})
            return await self._raw(send, 200, item[0], item[1])
        if not path.startswith("/admin/api/"):
            return await self._send(send, 404, {"ok": False, "error": "not_found"})
        route = [unquote(p) for p in path[len("/admin/api/"):].split("/") if p]
        query = {k: v[0] for k, v in parse_qs(scope.get("query_string", b"").decode()).items()}
        body: dict = {}
        if method == "POST":
            # A custom header and JSON only: a form on another site can't send either.
            if headers.get("x-admin") != "1" or "application/json" not in headers.get("content-type", ""):
                return await self._send(send, 403, {"ok": False, "error": "forbidden"})
            raw = await self._read_body(receive)
            if raw is None:
                return await self._send(send, 413, {"ok": False, "error": "too_large"})
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return await self._send(send, 400, {"ok": False, "error": "bad_request"})
            if not isinstance(body, dict):
                return await self._send(send, 400, {"ok": False, "error": "bad_request"})
        ip = headers.get("cf-connecting-ip") or (scope.get("client") or ("?",))[0]
        if route == ["login"] and method == "POST":
            return await self._login(send, ip, body, headers)
        token = self._cookie(headers)
        if not token or not self.server.store.session_valid(_token_hash(token), time.time()):
            return await self._send(send, 401, {"ok": False, "error": "login"})
        try:
            status, payload = await self._route(method, route, query, body, token)
        except LobbyError as error:
            status, payload = 400, {"ok": False, "error": error.code}
        except Exception as error:
            log.exception("admin %s %s failed", method, path)
            self.server.reporter.report("admin_exception", f"{method} {path}: {error!r}", exc=error)
            status, payload = 500, {"ok": False, "error": "server_error"}
        headers_out = []
        if route == ["logout"]:
            headers_out.append((b"set-cookie", self._cookie_header("", headers, 0).encode()))
        await self._send(send, status, payload, headers_out)

    def _file(self, name: str) -> Optional[Tuple[bytes, str]]:
        path = STATIC / name
        if "/" in name or name.startswith(".") or not path.is_file():
            return None
        mtime = path.stat().st_mtime
        cached = self.static.get(name)
        if not cached or cached[0] != mtime:
            cached = (mtime, path.read_bytes(), mimetypes.guess_type(name)[0] or "application/octet-stream")
            self.static[name] = cached
        return cached[1], cached[2]

    async def _read_body(self, receive) -> Optional[bytes]:
        chunks, size = [], 0
        while True:
            message = await receive()
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_BODY:
                return None
            chunks.append(chunk)
            if not message.get("more_body"):
                return b"".join(chunks)

    async def _send(self, send, status: int, payload: dict, extra=()) -> None:
        await self._raw(send, status, json.dumps(payload, separators=(",", ":")).encode(),
                        "application/json", list(extra))

    async def _raw(self, send, status: int, body: bytes, kind: str, extra=()) -> None:
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", kind.encode()), *SECURITY_HEADERS, *extra]})
        await send({"type": "http.response.body", "body": body})

    def _cookie(self, headers: Dict[str, str]) -> Optional[str]:
        for part in headers.get("cookie", "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == COOKIE and value:
                return value
        return None

    def _cookie_header(self, value: str, headers: Dict[str, str], max_age: int) -> str:
        host = headers.get("host", "").split(":")[0]
        local = host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.", "172."))
        return (f"{COOKIE}={value}; Path=/admin; Max-Age={max_age}; HttpOnly; SameSite=Strict"
                + ("" if local else "; Secure"))

    # ----- login ---------------------------------------------------------

    async def _login(self, send, ip: str, body: dict, headers: Dict[str, str]) -> None:
        now = time.time()
        wait = self.throttle.wait(ip, now)
        if wait > 0:
            return await self._send(send, 429, {"ok": False, "error": "wait", "wait": round(wait + 0.5)})
        password = body.get("password")
        good = isinstance(password, str) and len(password) <= 200 and \
            await asyncio.to_thread(check_password, password, self.password_hash)
        if not good:
            wait = self.throttle.failed(ip, now)
            log.warning("admin login failed from %s", ip)
            return await self._send(send, 401, {"ok": False, "error": "wrong_password", "wait": round(wait + 0.5)})
        self.throttle.succeeded(ip)
        token = secrets.token_urlsafe(32)
        self.server.store.add_session(_token_hash(token), now, now + SESSION_DAYS * 86400)
        cookie = self._cookie_header(token, headers, SESSION_DAYS * 86400)
        await self._send(send, 200, {"ok": True}, [(b"set-cookie", cookie.encode())])

    # ----- routes --------------------------------------------------------

    async def _route(self, method: str, route: list, query: dict, body: dict, token: str) -> Tuple[int, dict]:
        rng = query.get("range", "7d") if query.get("range") in ("24h", "7d", "30d", "all") else "7d"
        tab = query.get("tab", "")
        page = max(0, int(query.get("page", "0"))) if query.get("page", "0").isdigit() else 0
        q = (query.get("q") or "")[:40]
        head, rest = (route[0] if route else ""), route[1:]
        if method == "GET":
            if head == "me":
                return 200, {"ok": True}
            if head == "overview":
                return await self._read(lambda r: r.overview(rng))
            if head == "players" and not rest:
                return await self._read(lambda r: r.players(rng, tab or "all", query.get("sort", "last_seen"), q, page))
            if head == "players":
                return await self._read(lambda r: r.player_detail(rest[0]))
            if head == "games" and not rest:
                return await self._read(lambda r: r.games_page(rng, tab or "all", q, page))
            if head == "games":
                return await self._read(lambda r: r.game_detail(rest[0]))
            if head == "problems" and not rest:
                return await self._read(lambda r: r.problems(rng, tab or "open"))
            if head == "problems":
                return await self._read(lambda r: r.problem_detail(rest[0]))
            if head == "moderation" and not rest:
                return await self._read(lambda r: r.moderation(tab or "open", False))
            if head == "moderation":
                return await self._read(lambda r: r.moderation_detail(rest[0]))
        if method == "POST":
            if head == "logout":
                self.server.store.end_session(_token_hash(token))
                return 200, {"ok": True}
            if head == "moderation" and rest:
                return self._moderate(rest[0], body)
            if head == "words":
                return self._words(rest[0] if rest else "add", body)
            if head == "problems" and rest:
                return self._problem(rest[0], body)
        return 404, {"ok": False, "error": "not_found"}

    def live(self) -> Live:
        """What the running server knows right now. Runs on the event loop."""
        server, lobby = self.server, self.server.lobby
        live = Live(now=time.time(), latest_app=server.app_versions.get("latest", ""),
                    min_app=server.app_versions.get("min", ""))
        live.names = {pid: p.name for pid, p in lobby.profiles.items()}
        live.online = set(server.player_sids)
        live.locked = {pid: p.locked_at for pid, p in lobby.profiles.items() if p.locked}
        in_room = set()
        counts = {"playing": 0, "waiting": 0, "bot_matches": 0, "in_menus": 0}
        for room in lobby.rooms.values():
            live.rooms[room.id] = room.name
            humans = [m.id for m in room.humans()]
            in_room.update(humans)
            counts["bot_matches" if room.autoplay else "playing" if room.status == "playing" else "waiting"] += 1
            if room.status != "playing":
                continue
            game = room.game
            live.game_keys.add(lobby._game_key(room))
            seated = [s for s in game.seats]
            live.playing.update(s.id for s in seated if s.id not in room.bot_ids and not s.out)
            live.tables.append({
                "key": lobby._game_key(room), "table": room.name, "bot_match": room.autoplay,
                "players": [s.id for s in seated if s.id not in room.bot_ids],
                "bots": sum(1 for s in seated if s.id in room.bot_ids),
                "seconds": live.now - (room.game_started_at or live.now), "round": game.deal_no,
                "left": len(game.alive()), "seats": len(seated), "cards": len(game.cards_in_play()),
                "bid": bet_text(game.last_bet),
            })
        counts["in_menus"] = sum(1 for pid in live.online if pid not in in_room)
        live.counts = counts
        live.tables.sort(key=lambda t: (t["bot_match"], -t["seconds"]))
        return live

    async def _read(self, fn: Callable[[Reader], Optional[dict]]) -> Tuple[int, dict]:
        live = self.live()

        def run():
            db = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            try:
                reader = Reader(db, live, self.tz)
                data = fn(reader)
                if data is None:
                    return None
                if "live_tables" in data:
                    data["live_tables"] = [{**t, "players": [reader.player(p) for p in t["players"]]}
                                           for t in data["live_tables"]]
                return {"ok": True, "data": data, "shell": reader.shell()}
            finally:
                db.close()

        result = await asyncio.to_thread(run)
        return (200, result) if result else (404, {"ok": False, "error": "not_found"})

    # ----- actions -------------------------------------------------------

    def _moderate(self, pid: str, body: dict) -> Tuple[int, dict]:
        store, lobby, now = self.server.store, self.server.lobby, time.time()
        action = body.get("action")
        if action == "reset_name":
            name = body.get("name")
            if not isinstance(name, str) or not name.strip() or len(name) > 20 or not names.is_allowed(name):
                return 400, {"ok": False, "error": "bad_name"}
            old = lobby.admin_rename(pid, name.strip(), now)
            store.log_action(pid, "reset_name", f"{old} → {name.strip()}", now)
            word = names.clean_word(old)
            if body.get("block") and old != "Player" and len(word) >= 2:
                store.add_blocked_word(word, True, now)
                names.set_custom((w, whole) for w, whole, _ in store.blocked_words())
                store.log_action(pid, "blocked_name", word, now)
            if body.get("lock"):
                lobby.set_locked(pid, True, now)
                store.log_action(pid, "locked", "", now)
        elif action in ("lock", "unlock"):
            lobby.set_locked(pid, action == "lock", now)
            store.log_action(pid, "locked" if action == "lock" else "unlocked", "", now)
        elif action in ("resolve", "dismiss"):
            store.set_reports_status(pid, "resolved" if action == "resolve" else "dismissed", now)
            store.log_action(pid, "resolved" if action == "resolve" else "dismissed", "", now)
        elif action == "reopen":
            store.set_reports_status(pid, "open", now, only_open=False)
            store.log_action(pid, "reopened", "", now)
        else:
            return 400, {"ok": False, "error": "bad_request"}
        self.server.persist()
        return 200, {"ok": True}

    def _words(self, what: str, body: dict) -> Tuple[int, dict]:
        store, now = self.server.store, time.time()
        word = names.clean_word(body.get("word") or "") if isinstance(body.get("word"), str) else ""
        if not 2 <= len(word) <= 30:
            return 400, {"ok": False, "error": "bad_word"}
        if what == "add":
            store.add_blocked_word(word, bool(body.get("whole")), now)
            store.log_action(None, "word_added", word, now)
        elif what == "remove":
            store.remove_blocked_word(word)
            store.log_action(None, "word_removed", word, now)
        else:
            return 404, {"ok": False, "error": "not_found"}
        names.set_custom((w, whole) for w, whole, _ in store.blocked_words())
        return 200, {"ok": True, "word": word}

    def _problem(self, problem: str, body: dict) -> Tuple[int, dict]:
        store, now = self.server.store, time.time()
        action = body.get("action")
        if action == "resolve":
            store.set_problem(problem, "resolved", now)
        elif action == "mute":
            store.set_problem(problem, "watching", now, now + MUTE_SECONDS)
        elif action == "watch":
            store.set_problem(problem, "watching", now)
        elif action == "reopen":
            store.set_problem(problem, None, now)
        else:
            return 400, {"ok": False, "error": "bad_request"}
        return 200, {"ok": True}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def main() -> None:
    """``python -m server.admin``: print the ADMIN_PASSWORD_HASH for a new password."""
    password = getpass.getpass("New admin password: ")
    if len(password) < 12:
        sys.exit("Use at least 12 characters.")
    if getpass.getpass("Again: ") != password:
        sys.exit("The two passwords differ.")
    print(hash_password(password))


if __name__ == "__main__":
    main()
