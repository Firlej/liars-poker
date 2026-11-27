"""Socket.IO server: connects sockets to players and pushes snapshots.

Protocol, in one paragraph: the client connects with ``auth={token, name}``
and gets ``welcome`` with its ``player_id``, (possibly new) ``token`` and the
phone ``app_versions`` it supports.
Every request is an emit with an acknowledgement callback that answers
``{ok: true, ...}`` or ``{ok: false, error: <code>}``. Whenever a room changes,
every member's sockets receive ``state``: the full room snapshot from their
point of view, with a version number ``v``. Clients never patch state from
partial events, so a lost packet or a reconnect can never leave them out of
sync: the next snapshot (or a ``sync`` request) is always complete.

Run: ``uvicorn --factory server.app:create_app --host 0.0.0.0 --port 4000``
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import Counter, defaultdict
from typing import Callable, Dict, Optional, Set

import socketio

from .engine import GameError
from .reporting import DEFAULT_URL, Reporter
from .rooms import Lobby, Room
from .store import Store

log = logging.getLogger("liars_poker")

TICK_SECONDS = 0.25
PERSIST_SECONDS = 2.0
#: Requests per socket: sustained rate and burst.
RATE_PER_SECOND = 15
RATE_BURST = 40
#: How often the stats get a "who is online right now" row.
STATS_SAMPLE_SECONDS = 60.0


def short_text(value: object, limit: int = 20) -> Optional[str]:
    return value[:limit] if isinstance(value, str) and value else None


def percentile(values: list, share: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1)


class Bucket:
    def __init__(self, now: float):
        self.tokens, self.at = float(RATE_BURST), now

    def take(self, now: float) -> bool:
        self.tokens = min(RATE_BURST, self.tokens + (now - self.at) * RATE_PER_SECOND)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class GameServer:
    def __init__(self, store: Optional[Store] = None, clock: Callable[[], float] = time.time,
                 cors: object = "*", lobby: Optional[Lobby] = None, reporter: Optional[Reporter] = None,
                 app_versions: Optional[Dict[str, str]] = None, version: str = "dev"):
        self.clock = clock
        #: This server's version, saved with each start so the dashboard can mark deploys.
        self.version = version
        #: Phone app versions, sent in ``welcome``: ``min`` is the oldest the server
        #: still works with (older apps show "Please update"), ``latest`` is the
        #: newest in the stores (older apps show a dismissable "Update available").
        self.app_versions = {k: v for k, v in (app_versions or {}).items() if v}
        self.reporter = reporter or Reporter(None)
        self.store = store
        self.lobby = lobby or Lobby()
        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            cors_allowed_origins=cors,
            # Generous timeouts: a phone on a weak signal can go quiet for a while
            # without being treated as gone. The seat is kept far longer anyway.
            ping_interval=10,
            ping_timeout=30,
            max_http_buffer_size=32_000,
            compression_threshold=512,
            logger=False,
            engineio_logger=False,
        )
        self.app = socketio.ASGIApp(self.sio, other_asgi_app=self._http, socketio_path="socket.io",
                                    on_startup=self.start, on_shutdown=self.stop)
        self.sid_player: Dict[str, str] = {}
        self.player_sids: Dict[str, Set[str]] = defaultdict(set)
        self.buckets: Dict[str, Bucket] = {}
        self.sent_versions: Dict[tuple, int] = {}
        self.sent_list_version = -1
        self.saved_versions: Dict[str, int] = {}
        self.saved_profiles: Dict[str, tuple] = {}
        #: When each connected player's visit began, for the stats.
        self.session_started: Dict[str, float] = {}
        #: Requests since the last "online" row: how long each took, and what failed.
        self.request_ms: list = []
        self.request_counts: Counter = Counter()
        self.request_errors: Counter = Counter()
        self._tasks: list = []
        self._register()
        if store is not None:
            profiles, rooms = store.load()
            self.lobby.restore(profiles, rooms, clock())
            for room in self.lobby.rooms.values():
                self.saved_versions[room.id] = room.version
            log.info("restored %d rooms, %d players", len(self.lobby.rooms), len(self.lobby.profiles))

    # ----- plain HTTP ----------------------------------------------------

    async def _http(self, scope, receive, send):
        if scope["type"] != "http":
            return
        body = json.dumps({"ok": True, "rooms": len(self.lobby.rooms),
                           "online": len(self.player_sids)}).encode()
        status = 200 if scope.get("path") in ("/", "/health") else 404
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    # ----- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if not self._tasks:
            self.lobby.record("server_start", self.clock(), version=self.version,
                              rooms=len(self.lobby.rooms), players=len(self.lobby.profiles))
            self._tasks = [asyncio.ensure_future(self._ticker())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        now = self.clock()
        for pid, started in self.session_started.items():
            self.lobby.record("session_end", now, player=pid, seconds=round(now - started, 1), shutdown=True)
        self.session_started.clear()
        self.persist(force=True)

    async def _ticker(self) -> None:
        last_persist = last_sample = 0.0
        while True:
            try:
                now = self.clock()
                self.lobby.tick(now)
                await self.flush()
                if now - last_sample >= STATS_SAMPLE_SECONDS:
                    self.record_online(now)
                    last_sample = now
                if now - last_persist >= PERSIST_SECONDS:
                    self.persist()
                    last_persist = now
            except Exception as error:  # never let one bad room stop the clock for everyone
                log.exception("tick failed")
                self.reporter.report("server_tick_exception", repr(error), exc=error)
                self.lobby.record("error", self.clock(), kind="server_tick_exception", message=repr(error)[:200])
            await asyncio.sleep(TICK_SECONDS)

    def record_online(self, now: float) -> None:
        """A "right now" row: the dashboard's live numbers over time, and the record high."""
        rooms = self.lobby.rooms.values()
        in_room = {m.id for r in rooms for m in r.humans()}
        self.lobby.record("online", now, players=len(self.player_sids),
                          playing=sum(1 for r in rooms if r.status == "playing" and not r.autoplay),
                          waiting=sum(1 for r in rooms if r.status != "playing" and not r.autoplay),
                          bot_matches=sum(1 for r in rooms if r.autoplay),
                          in_menus=sum(1 for pid in self.player_sids if pid not in in_room),
                          watching=sum(1 for r in rooms if not r.autoplay
                                       for m in r.humans() if m.role == "spectator"),
                          requests=len(self.request_ms), by_event=dict(self.request_counts),
                          failed=dict(self.request_errors),
                          ms_p50=percentile(self.request_ms, 0.5), ms_p95=percentile(self.request_ms, 0.95),
                          ms_max=round(max(self.request_ms), 1) if self.request_ms else None)
        self.request_ms, self.request_counts, self.request_errors = [], Counter(), Counter()

    def persist(self, force: bool = False) -> None:
        if self.store is None:
            self.lobby.stats.clear()
            return
        now = self.clock()
        events, self.lobby.stats = self.lobby.stats, []
        try:
            self.store.add_events(events)
        except Exception:
            log.exception("saving stats failed")
            self.lobby.stats[:0] = events  # try again next time
        rooms = [self.lobby.room_to_dict(r, now) for r in self.lobby.rooms.values()
                 if force or self.saved_versions.get(r.id) != r.version]
        deleted = [item[1] for item in self.lobby.dirty if isinstance(item, tuple) and item[0] == "deleted"]
        profiles = []
        for p in self.lobby.profiles.values():
            key = (p.name, p.room_id)
            if force or self.saved_profiles.get(p.id) != key:
                profiles.append(self.lobby.profile_to_dict(p))
                self.saved_profiles[p.id] = key
        try:
            self.store.save(profiles, rooms, deleted, now)
        except Exception:
            log.exception("persist failed")
            return
        for r in self.lobby.rooms.values():
            self.saved_versions[r.id] = r.version
        for rid in deleted:
            self.saved_versions.pop(rid, None)
        self.lobby.dirty.clear()

    # ----- pushing state -------------------------------------------------

    async def push_room(self, room: Room, force: bool = False) -> None:
        now = self.clock()
        for pid in list(room.members):
            for sid in list(self.player_sids.get(pid, ())):
                key = (sid, room.id)
                if not force and self.sent_versions.get(key) == room.version:
                    continue
                self.sent_versions[key] = room.version
                await self.sio.emit("state", self.lobby.snapshot(room, pid, now), to=sid)

    async def flush(self) -> None:
        """Send whatever changed: room snapshots, notices, the public room list."""
        problems, self.lobby.problems = self.lobby.problems, []
        for problem in problems:
            log.error("game problem in %s: %s", problem["room_id"], problem["message"])
            self.reporter.report(problem["kind"], problem["message"],
                                 {"room_id": problem["room_id"], **problem["context"]})
            room = self.lobby.rooms.get(problem["room_id"])
            self.lobby.record("error", self.clock(), room=problem["room_id"], kind=problem["kind"],
                              message=problem["message"][:200],
                              players=[m.id for m in room.humans()] if room else [])
        notices, self.lobby.notices = self.lobby.notices, []
        for pid, event, payload in notices:
            for sid in list(self.player_sids.get(pid, ())):
                await self.sio.emit(event, payload, to=sid)
        for room in list(self.lobby.rooms.values()):
            await self.push_room(room)
        if self.lobby.list_version != self.sent_list_version:
            self.sent_list_version = self.lobby.list_version
            await self.sio.emit("rooms", {"rooms": self.lobby.room_list()}, room="lobby")
        # Forget versions for sockets/rooms that no longer exist.
        if len(self.sent_versions) > 4 * (len(self.sid_player) + 1):
            live = set(self.sid_player)
            self.sent_versions = {k: v for k, v in self.sent_versions.items()
                                  if k[0] in live and k[1] in self.lobby.rooms}

    # ----- handlers ------------------------------------------------------

    def _register(self) -> None:
        sio = self.sio

        @sio.event
        async def connect(sid, environ, auth=None):
            auth = auth if isinstance(auth, dict) else {}
            now = self.clock()
            token = auth.get("token")
            new_player = not (isinstance(token, str) and token in self.lobby.by_token)
            profile = self.lobby.hello(token, auth.get("name"), now)
            if not self.player_sids.get(profile.id):
                self.session_started[profile.id] = now
                self.lobby.record("session_start", now, player=profile.id, new=new_player,
                                  app_version=short_text(auth.get("app_version")),
                                  platform=short_text(auth.get("platform")))
            self.sid_player[sid] = profile.id
            self.player_sids[profile.id].add(sid)
            self.buckets[sid] = Bucket(now)
            self.lobby.set_connected(profile.id, True, now)
            await sio.emit("welcome", {"player_id": profile.id, "token": profile.token, "name": profile.name,
                                       "room_id": profile.room_id, "server_time": int(now * 1000),
                                       "app_versions": self.app_versions}, to=sid)
            room = self.lobby.rooms.get(profile.room_id or "")
            if room:
                await self.push_room(room, force=True)
            await self.flush()

        @sio.event
        async def disconnect(sid, *args):
            pid = self.sid_player.pop(sid, None)
            self.buckets.pop(sid, None)
            if pid is None:
                return
            sids = self.player_sids.get(pid, set())
            sids.discard(sid)
            if not sids:
                now = self.clock()
                self.player_sids.pop(pid, None)
                self.lobby.set_connected(pid, False, now)
                started = self.session_started.pop(pid, now)
                self.lobby.record("session_end", now, player=pid, seconds=round(now - started, 1))
            await self.flush()

        def handler(name: str, fn):
            async def wrapped(sid, data=None):
                pid = self.sid_player.get(sid)
                if pid is None:
                    return {"ok": False, "error": "not_connected"}
                now = self.clock()
                self.request_counts[name] += 1
                if not self.buckets[sid].take(now):
                    self.request_errors["rate_limited"] += 1
                    return {"ok": False, "error": "rate_limited"}
                started = time.perf_counter()
                data = data if isinstance(data, dict) else {}
                try:
                    result = fn(sid, pid, data, now)
                    if asyncio.iscoroutine(result):
                        result = await result
                except GameError as error:
                    result = {"ok": False, "error": error.code}
                except Exception as error:
                    log.exception("handler %s failed", name)
                    self.reporter.report("server_exception", f"{name}: {error!r}",
                                         {"event": name, "data": data}, exc=error)
                    self.lobby.record("error", now, player=pid, kind="server_exception", event=name,
                                      message=f"{name}: {error!r}"[:200])
                    result = {"ok": False, "error": "server_error"}
                self.request_ms.append((time.perf_counter() - started) * 1000)
                if isinstance(result, dict) and result.get("ok") is False:
                    self.request_errors[str(result.get("error"))[:40]] += 1
                await self.flush()
                return result
            sio.on(name, wrapped)

        def ok(**extra):
            return {"ok": True, **extra}

        async def rooms(sid, pid, data, now):
            await sio.enter_room(sid, "lobby")
            return ok(rooms=self.lobby.room_list())

        async def unwatch_rooms(sid, pid, data, now):
            await sio.leave_room(sid, "lobby")
            return ok()

        def set_name(sid, pid, data, now):
            profile = self.lobby.rename(pid, data.get("name"), now)
            return ok(name=profile.name)

        def create_room(sid, pid, data, now):
            room = self.lobby.create_room(pid, now)
            return ok(room_id=room.id, state=self.lobby.snapshot(room, pid, now))

        def join_room(sid, pid, data, now):
            room = self.lobby.join_room(pid, data.get("room_id"), now)
            return ok(room_id=room.id, state=self.lobby.snapshot(room, pid, now))

        def leave_room(sid, pid, data, now):
            self.lobby.leave(pid, now)
            return ok()

        def sync(sid, pid, data, now):
            profile = self.lobby.profiles[pid]
            room = self.lobby.rooms.get(profile.room_id or "")
            if room is None or (data.get("room_id") and data.get("room_id") != room.id):
                return {"ok": False, "error": "not_in_room"}
            self.sent_versions[(sid, room.id)] = room.version
            return ok(state=self.lobby.snapshot(room, pid, now))

        def act(sid, pid, data, now):
            return self.lobby.act(pid, data, now)

        def simple(method):
            def run(sid, pid, data, now):
                method(pid, now)
                return ok()
            return run

        def watch_bots(sid, pid, data, now):
            room = self.lobby.create_bot_match(pid, data.get("bots"), now)
            return ok(room_id=room.id, state=self.lobby.snapshot(room, pid, now))

        def kick(sid, pid, data, now):
            self.lobby.kick(pid, data.get("player_id"), now)
            return ok()

        def set_max_hand(sid, pid, data, now):
            self.lobby.set_max_hand(pid, data.get("max_hand"), now)
            return ok()

        def react(sid, pid, data, now):
            self.lobby.react(pid, data.get("reaction"), now)
            return ok()

        def ping(sid, pid, data, now):
            return ok(t=data.get("t"), server_time=int(now * 1000))

        for name, fn in {
            "rooms": rooms, "unwatch_rooms": unwatch_rooms, "set_name": set_name,
            "create_room": create_room, "join_room": join_room, "leave_room": leave_room,
            "sync": sync, "act": act, "kick": kick, "ping": ping, "watch_bots": watch_bots,
            "set_max_hand": set_max_hand, "react": react,
            "start_game": simple(self.lobby.start_game), "add_bot": simple(self.lobby.add_bot),
            "shuffle_seats": simple(self.lobby.shuffle_seats),
            "sit": simple(self.lobby.sit), "stand": simple(self.lobby.stand),
        }.items():
            handler(name, fn)


def create_app():
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cors = os.environ.get("CORS_ORIGINS", "*")
    cors = "*" if cors.strip() == "*" else [o.strip() for o in cors.split(",") if o.strip()]
    db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "liars_poker.db"))
    report_url = os.environ.get("ERROR_REPORT_URL", DEFAULT_URL).strip() or None
    server = GameServer(store=Store(db_path), cors=cors, version=os.environ.get("APP_VERSION", "server"),
                        reporter=Reporter(report_url, version=os.environ.get("APP_VERSION", "server")),
                        app_versions={"min": os.environ.get("MIN_APP_VERSION", "").strip(),
                                      "latest": os.environ.get("LATEST_APP_VERSION", "").strip()})
    return server.app
