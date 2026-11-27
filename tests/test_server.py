"""End-to-end: real Socket.IO clients against a real server on localhost."""
import asyncio
import socket

import pytest
import socketio
import uvicorn

from server.app import GameServer
from server.store import Store




def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    def __init__(self, db, **options):
        self.db = db
        self.options = options
        self.port = free_port()

    async def __aenter__(self):
        self.game = GameServer(store=Store(self.db), **self.options)
        config = uvicorn.Config(self.game.app, host="127.0.0.1", port=self.port, log_level="warning", lifespan="on",
                                timeout_graceful_shutdown=1)
        self.server = uvicorn.Server(config)
        self.task = asyncio.ensure_future(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.02)
        return self

    async def __aexit__(self, *exc):
        self.server.should_exit = True
        await self.task

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


class Player:
    def __init__(self, name, token=None, transports=None):
        self.name, self.token = name, token
        self.transports = transports
        self.sio = socketio.AsyncClient(reconnection=False)
        self.state = None
        self.welcome = asyncio.Event()
        self.updated = asyncio.Event()
        self.events = []

        @self.sio.on("welcome")
        def on_welcome(data):
            self.id, self.token = data["player_id"], data["token"]
            self.welcome_data = data
            self.welcome.set()

        @self.sio.on("state")
        def on_state(data):
            if self.state is None or data["v"] >= self.state["v"]:
                self.state = data
            self.updated.set()

        @self.sio.on("*")
        def any_event(event, data):
            self.events.append(event)

    async def connect(self, url):
        await self.sio.connect(url, auth={"token": self.token, "name": self.name},
                               transports=self.transports or ["websocket"], wait_timeout=5)
        await asyncio.wait_for(self.welcome.wait(), 5)
        return self

    async def call(self, event, data=None):
        return await self.sio.call(event, data or {}, timeout=5)

    async def until(self, predicate, timeout=8):
        async def wait():
            while not (self.state and predicate(self.state)):
                self.updated.clear()
                await self.updated.wait()
        await asyncio.wait_for(wait(), timeout)
        return self.state

    async def close(self):
        if self.transports == ["polling"]:
            # The Python client waits out its pending long-poll before returning;
            # the server sees the disconnect immediately, so don't wait for it.
            self._closing = asyncio.ensure_future(self.sio.disconnect())
            await asyncio.sleep(0.1)
        else:
            await self.sio.disconnect()


async def test_full_flow_reconnect_and_restart(tmp_path):
    db = str(tmp_path / "game.db")
    async with Running(db) as srv:
        ada = await Player("Ada").connect(srv.url)
        # Long-polling must work too: some networks block WebSockets.
        bob = await Player("Bob", transports=["polling"]).connect(srv.url)

        created = await ada.call("create_room")
        assert created["ok"]
        room_id = created["room_id"]
        listed = await bob.call("rooms")
        assert [r["id"] for r in listed["rooms"]] == [room_id]
        joined = await bob.call("join_room", {"room_id": room_id})
        assert joined["ok"] and len(joined["state"]["players"]) == 2

        assert (await bob.call("set_max_hand", {"max_hand": 5}))["error"] == "not_host"
        assert (await ada.call("set_max_hand", {"max_hand": 99}))["error"] == "bad_max_hand"
        assert (await ada.call("set_max_hand", {"max_hand": 5}))["ok"]
        await bob.until(lambda s: s["room"]["hand_limit"]["choice"] == 5)
        assert (await ada.call("set_max_hand", {"max_hand": None}))["ok"]
        await bob.until(lambda s: s["room"]["hand_limit"]["choice"] is None)

        assert (await bob.call("start_game"))["error"] == "not_host"
        assert (await ada.call("start_game"))["ok"]
        state = await ada.until(lambda s: s["game"] and s["game"]["phase"] == "betting")
        assert state["room"]["max_hand"] == 6
        assert len(state["game"]["my_hand"]) == 1

        turn = state["game"]["turn_id"]
        first, second = (ada, bob) if turn == ada.id else (bob, ada)
        move = {"type": "bet", "bet": "pair_9", "turn_seq": state["game"]["turn_seq"], "move_id": "x1"}
        assert (await first.call("act", move)) == {"ok": True}
        # Retrying the identical move (lost ack on a bad network) is harmless.
        assert (await first.call("act", move)) == {"ok": True}
        state = await second.until(lambda s: s["game"]["last_bet"] == "pair_9")
        assert state["game"]["turn_id"] == second.id and len(state["game"]["bets"]) == 1

        # The second player drops off and comes back on a new socket with the same token.
        token = second.token
        await second.close()
        await first.until(lambda s: not next(p for p in s["players"] if p["id"] == state["game"]["turn_id"])["connected"])
        back = await Player(second.name, token=token).connect(srv.url)
        assert back.id == state["game"]["turn_id"]
        snap = await back.until(lambda s: s["game"] is not None)
        assert snap["game"]["last_bet"] == "pair_9" and len(snap["game"]["my_hand"]) == 1

        seq = snap["game"]["turn_seq"]
        assert (await back.call("act", {"type": "check", "turn_seq": seq - 1}))["error"] == "stale"
        assert (await back.call("act", {"type": "check", "turn_seq": seq}))["ok"]
        revealed = await first.until(lambda s: s["game"]["phase"] == "reveal")
        assert set(revealed["game"]["reveal"]["hands"]) == {ada.id, bob.id}

        await first.close()
        await back.close()

    # Server restarts: the game is still there and the player is recognised.
    async with Running(db) as srv:
        again = await Player("Ada", token=ada.token).connect(srv.url)
        snap = await again.until(lambda s: s["game"] is not None)
        # Nobody was connected to confirm the reveal, so it may already have moved on.
        assert snap["room"]["id"] == room_id and snap["game"]["phase"] in ("reveal", "betting")
        assert snap["game"]["deal_no"] >= 1
        sync = await again.call("sync")
        assert sync["ok"] and sync["state"]["room"]["id"] == room_id
        await again.close()


async def test_bad_input_never_crashes(tmp_path):
    async with Running(str(tmp_path / "g.db")) as srv:
        eve = await Player("Eve").connect(srv.url)
        for event, payload in [("act", "nonsense"), ("act", {"type": "bet"}), ("join_room", {"room_id": 5}),
                               ("kick", {"player_id": None}), ("start_game", None), ("sync", {}),
                               ("set_name", {"name": "\u0000" * 500}), ("set_max_hand", {"max_hand": "x"})]:
            result = await eve.call(event, payload)
            assert result["ok"] is False or event == "set_name"
        assert (await eve.call("ping", {"t": 1}))["ok"]
        await eve.close()


async def test_health_endpoint(tmp_path):
    import aiohttp
    async with Running(str(tmp_path / "g.db")) as srv:
        async with aiohttp.ClientSession() as http:
            async with http.get(srv.url + "/health") as response:
                assert response.status == 200
                assert (await response.json())["ok"] is True


async def test_bot_match_runs_and_problems_are_reported(tmp_path):
    from server.reporting import Reporter

    class Recorder(Reporter):
        def __init__(self):
            super().__init__("http://unused")
            self.reports = []

        def _send(self, payload):
            self.reports.append(payload)

    async with Running(str(tmp_path / "g.db")) as srv:
        recorder = Recorder()
        srv.game.reporter = recorder
        watcher = await Player("Watcher").connect(srv.url)
        reply = await watcher.call("watch_bots", {"bots": 3})
        assert reply["ok"] and reply["state"]["room"]["autoplay"] is True
        assert reply["state"]["me"]["role"] == "spectator"
        state = await watcher.until(lambda s: s["game"] and s["game"]["turn_seq"] >= 3)  # bots are moving
        assert all(p["is_bot"] for p in state["players"])

        # A broken game state is reported once, not on every tick.
        room = srv.game.lobby.rooms[reply["room_id"]]
        srv.game.lobby._problem(room, "invariant", "test problem")
        srv.game.lobby._problem(room, "invariant", "test problem")
        await srv.game.flush()
        await asyncio.sleep(0.2)
        mine = [r for r in recorder.reports if "test problem" in r["message"]]
        assert len(mine) == 1 and mine[0]["source"] == "liars-poker-server" and mine[0]["priority"] == "high"
        await watcher.close()


def test_reporter_dedupes_and_limits(monkeypatch):
    from server import reporting
    sent = []
    r = reporting.Reporter("http://unused")
    monkeypatch.setattr(r, "_send", sent.append)
    monkeypatch.setattr(reporting.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    assert r.report("x", "same") is True
    assert r.report("x", "same") is False
    for i in range(100):
        r.report("x", f"different {i}")
    assert len(sent) == reporting.MAX_PER_HOUR
    assert reporting.Reporter(None).report("x", "y") is False


async def test_welcome_carries_app_versions(tmp_path):
    async with Running(str(tmp_path / "a.db"), app_versions={"min": "1.3.0", "latest": "1.4.0"}) as srv:
        ada = await Player("Ada").connect(srv.url)
        assert ada.welcome_data["app_versions"] == {"min": "1.3.0", "latest": "1.4.0"}
        await ada.close()
    async with Running(str(tmp_path / "b.db"), app_versions={"min": "", "latest": ""}) as srv:
        bob = await Player("Bob").connect(srv.url)
        assert bob.welcome_data["app_versions"] == {}
        await bob.close()


async def test_stats_events_are_saved(tmp_path):
    import json
    import sqlite3
    db = str(tmp_path / "s.db")
    async with Running(db) as srv:
        ada = await Player("Ada").connect(srv.url)
        await ada.call("watch_bots", {"bots": 2})
        await asyncio.sleep(0.3)
        await ada.close()
        await asyncio.sleep(0.2)
    rows = sqlite3.connect(db).execute("SELECT type, player, data FROM events").fetchall()
    types = [r[0] for r in rows]
    for expected in ("session_start", "room_created", "game_start", "online", "session_end"):
        assert expected in types
    start = next(json.loads(d) for t, p, d in rows if t == "session_start")
    assert start["new"] is True
    created = next(json.loads(d) for t, p, d in rows if t == "room_created")
    assert created["bot_match"] is True


async def test_stats_mark_deploys_and_time_requests(tmp_path):
    import json
    import sqlite3
    db = str(tmp_path / "t.db")
    async with Running(db, version="1.2.3") as srv:
        ada = await Player("Ada").connect(srv.url)
        await ada.call("ping", {"t": 1})
        await ada.call("join_room", {"room_id": "NOPE"})
        srv.game.record_online(srv.game.clock())
        await ada.close()
    rows = sqlite3.connect(db).execute("SELECT type, data FROM events").fetchall()
    assert json.loads(next(d for t, d in rows if t == "server_start"))["version"] == "1.2.3"
    online = [json.loads(d) for t, d in rows if t == "online"][-1]
    assert online["requests"] == 2 and online["by_event"] == {"ping": 1, "join_room": 1}
    assert online["failed"] == {"room_not_found": 1} and online["ms_p95"] is not None


async def test_reports_are_saved(tmp_path):
    import sqlite3
    db = str(tmp_path / "r.db")
    async with Running(db) as srv:
        ada = await Player("Ada").connect(srv.url)
        bob = await Player("Bob").connect(srv.url)
        room = (await ada.call("create_room"))["room_id"]
        await bob.call("join_room", {"room_id": room})
        assert (await ada.call("report_player", {"player_id": bob.id, "reason": "offensive_name"}))["ok"]
        again = await ada.call("report_player", {"player_id": bob.id, "reason": "offensive_name"})
        assert again == {"ok": False, "error": "already_reported"}
        await ada.close()
        await bob.close()
    rows = sqlite3.connect(db).execute("SELECT reporter, target, name, reason, status FROM reports").fetchall()
    assert rows == [(ada.id, bob.id, "Bob", "offensive_name", "open")]
