"""The admin dashboard: login, its pages, and what its buttons change."""
import asyncio
import json
import sqlite3

import aiohttp
import pytest

from server import names
from server.admin import Throttle, bet_text, check_password, hash_password
from server.app import GameServer
from server.store import Store

from .test_server import Player, Running

PASSWORD = "correct horse battery"
HASH = hash_password(PASSWORD)


@pytest.fixture(autouse=True)
def no_custom_words():
    yield
    names.set_custom([])


def test_password_hash_and_throttle():
    assert check_password(PASSWORD, HASH) and not check_password("nope", HASH)
    assert not check_password(PASSWORD, "garbage")
    t = Throttle()
    assert t.wait("a", 0) == 0
    assert t.failed("a", 0) == 10 and t.wait("a", 5) == 5 and t.wait("b", 5) == 0
    for i in range(5):
        t.failed("a", 100 + i * 100)
    assert t.wait("a", 500) > 10  # longer after five misses
    t.succeeded("a")
    assert t.wait("a", 500) == 0


def test_bet_text():
    assert bet_text("two_pair_K_Q") == "two pair K & Q"
    assert bet_text("pair_A") == "pair of Aces" and bet_text("three_T") == "three 10s"
    assert bet_text("full_J_9") == "full house J over 9" and bet_text("flush_♥") == "flush ♥"
    assert bet_text("small_poker_♠") == "small poker ♠" and bet_text(None) is None


class Admin:
    def __init__(self, url):
        self.url = url
        self.http = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))

    async def login(self, password=PASSWORD):
        async with self.http.post(self.url + "/admin/api/login", json={"password": password},
                                  headers={"x-admin": "1"}) as r:
            return r.status, await r.json()

    async def get(self, path):
        async with self.http.get(self.url + "/admin/api/" + path) as r:
            return r.status, await r.json()

    async def post(self, path, body):
        async with self.http.post(self.url + "/admin/api/" + path, json=body, headers={"x-admin": "1"}) as r:
            return r.status, await r.json()


class AdminServer(Running):
    async def __aenter__(self):
        self.options.setdefault("admin_password_hash", HASH)
        self.options.setdefault("db_path", self.db)
        return await super().__aenter__()


async def test_admin_is_off_without_a_password(tmp_path):
    async with Running(str(tmp_path / "a.db")) as srv:
        async with aiohttp.ClientSession() as http:
            async with http.get(srv.url + "/admin") as r:
                assert r.status == 404


async def test_login_pages_and_actions(tmp_path):
    db = str(tmp_path / "g.db")
    async with AdminServer(db) as srv:
        admin = Admin(srv.url)
        try:
            async with admin.http.get(srv.url + "/admin") as r:
                assert r.status == 200 and "Liar's Poker Stats" in await r.text()
                assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
            assert (await admin.get("overview"))[0] == 401
            assert (await admin.login("wrong"))[1]["error"] == "wrong_password"
            assert (await admin.login())[1] == {"ok": False, "error": "wait", "wait": 10}  # locked for a moment
            srv.game.admin.throttle.succeeded("127.0.0.1")
            assert (await admin.login())[0] == 200
            # A POST without the custom header (what a form on another site would send) is refused.
            async with admin.http.post(srv.url + "/admin/api/words/add", json={"word": "kebab"}) as r:
                assert r.status == 403

            ada = await Player("Ada").connect(srv.url)
            bob = await Player("Bob").connect(srv.url)
            room = (await ada.call("create_room"))["room_id"]
            await bob.call("join_room", {"room_id": room})
            await ada.call("add_bot")
            await ada.call("start_game")
            await ada.call("report_player", {"player_id": bob.id, "reason": "offensive_name"})
            await bob.call("set_name", {"name": "shit"})
            srv.game.record_online(srv.game.clock())
            srv.game.persist()

            for page in ("overview", "players", "games", "problems", "moderation"):
                for rng in ("24h", "7d", "30d", "all"):
                    status, body = await admin.get(f"{page}?range={rng}")
                    assert status == 200 and body["ok"], (page, rng, body)
            # Product pages: feedback isn't connected in tests; the other two are hand-written files.
            status, body = await admin.get("feedback")
            assert status == 200 and body["data"]["setup"] is False and body["shell"]["feedback_open"] is None
            status, body = await admin.get("changelog")
            assert body["data"]["releases"][0]["items"]
            status, body = await admin.get("requests")
            done = [i for i in body["data"]["items"] if i["status"] == "done" and i.get("issue")]
            assert done[0]["url"].endswith(f"/issues/{done[0]['issue']}")
            assert all(f["message"] is None for i in body["data"]["items"] for f in i["feedback"])
            status, body = await admin.get("overview")
            assert body["data"]["live"]["online"] == 2 and body["shell"]["reports_open"] == 1
            status, body = await admin.get("games")
            assert body["data"]["live_tables"][0]["players"][0]["name"] in ("Ada", "Bob")
            status, body = await admin.get(f"players/{ada.id}")
            assert body["data"]["name"] == "Ada"

            status, body = await admin.get("moderation")
            [row] = body["data"]["rows"]
            assert row["id"] == bob.id and row["reason"] == "offensive_name"
            status, body = await admin.get(f"moderation/{bob.id}")
            assert body["data"]["refused"] == [{"name": "shit", "masked": "s**t"}]

            # Reset Bob's name, block the old one for everyone, and lock it.
            status, body = await admin.post(f"moderation/{bob.id}", {"action": "reset_name", "name": "Sly Otter",
                                                                      "block": True, "lock": True})
            assert status == 200, body
            assert srv.game.lobby.profiles[bob.id].name == "Sly Otter"
            assert srv.game.lobby.rooms[room].names[bob.id] == "Sly Otter"
            assert not names.is_allowed("Bob")  # blocked for everyone now
            assert (await bob.call("set_name", {"name": "Robert"}))["error"] == "name_locked"
            await admin.post(f"moderation/{bob.id}", {"action": "resolve"})
            status, body = await admin.get("moderation?tab=open")
            assert body["data"]["rows"] == [] and body["shell"]["reports_open"] == 0
            status, body = await admin.get(f"moderation/{bob.id}")
            assert [a["action"] for a in body["data"]["actions"]] == ["reset_name", "blocked_name", "locked", "resolved"]
            await admin.post(f"moderation/{bob.id}", {"action": "unlock"})
            assert not srv.game.lobby.profiles[bob.id].locked

            # Your own words.
            assert (await admin.post("words/add", {"word": "Kebab", "whole": False}))[1]["word"] == "kebab"
            assert not names.is_allowed("kebabking")
            assert (await admin.post("words/add", {"word": "x"}))[0] == 400
            await admin.post("words/remove", {"word": "kebab"})
            assert names.is_allowed("kebabking")

            # Problems: mute and resolve.
            srv.game.lobby.record("error", srv.game.clock(), kind="server_exception", message="boom")
            srv.game.persist()
            status, body = await admin.get("problems")
            assert body["data"]["rows"][0]["id"] == "error:server_exception"
            await admin.post("problems/error:server_exception", {"action": "mute"})
            status, body = await admin.get("problems?tab=watching")
            assert [p["id"] for p in body["data"]["rows"]] == ["error:server_exception"]

            assert (await admin.post("logout", {}))[0] == 200
            assert (await admin.get("overview"))[0] == 401
            await ada.close()
            await bob.close()
        finally:
            await admin.http.close()
