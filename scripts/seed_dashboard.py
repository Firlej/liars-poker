"""Fill a separate SQLite file with 30 days of made-up activity, to look at
the admin dashboard before real players arrive. Never point it at the real
database.

    .venv/bin/python scripts/seed_dashboard.py data/dashboard-demo.db
    ADMIN_PASSWORD_HASH=... DB_PATH=data/dashboard-demo.db .venv/bin/uvicorn --factory server.app:create_app --port 4000
"""
from __future__ import annotations

import json
import os
import random
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import names, rules  # noqa: E402
from server.store import Store  # noqa: E402

NICKS = ["bluffking", "Kasia_77", "AceHunter", "queen_of_lies", "nine_lives", "pokerface_pl", "ZoZo", "tenhigh",
         "Marek", "Ola", "kuba", "Gosia", "liar_liar", "two_pair", "Antek", "Wera", "BigBluff", "Ninja", "Tosia",
         "Pablo", "maja", "Bartek", "DonCheck", "Hania", "lucky7", "Szymon", "Iga", "Franek", "Zuza", "Olek"]
TABLES = ["The Sneaky Badger", "The Smug Walrus", "The Shady Pirate", "The Grumpy Heron", "The Lazy Fox",
          "The Bold Mole", "The Sly Raccoon", "The Fancy Goose", "The Wily Crow", "The Lucky Otter"]
BETS = [b for b in rules.BETS if not b.startswith("high_card")]


def main(path: str) -> None:
    if os.path.exists(path):
        sys.exit(f"{path} exists; pick a new file (this never overwrites a database).")
    rng = random.Random(7)
    store = Store(path)
    now = time.time()
    start = now - 30 * 86400
    events, reports, refused = [], [], []

    def ev(t, type_, player=None, room=None, **data):
        events.append((t, type_, player, room, json.dumps(data)))

    players = []
    for i in range(140):
        pid = "p_" + secrets.token_hex(8)
        name = NICKS[i] if i < len(NICKS) else ("Player" if rng.random() < 0.5 else f"{rng.choice(NICKS)}{rng.randint(2, 99)}")
        joined = start + rng.random() * 29 * 86400
        players.append({"id": pid, "name": name, "joined": joined, "keen": rng.random() ** 2})
    profiles = [{"id": p["id"], "token": secrets.token_urlsafe(24), "name": p["name"], "room_id": None,
                 "locked": False, "locked_at": None, "banned_names": []} for p in players]

    ev(start, "server_start", version="server-1a2b3c4")
    ev(now - 5 * 3600, "server_start", version="server-9f8e7d6")
    game_no = 0
    day = start
    while day < now:
        for p in players:
            if p["joined"] > day + 86400 or rng.random() > 0.15 + p["keen"] * 0.8:
                continue
            hour = rng.choice([8, 12, 13, 17, 18, 19, 20, 20, 21, 21, 22, 23])
            t0 = day + hour * 3600 + rng.random() * 3600
            if t0 > now:
                continue
            ev(t0, "session_start", p["id"], new=abs(t0 - p["joined"]) < 86400 and rng.random() < 0.3,
               app_version=rng.choice(["1.2.0"] * 8 + ["1.1.4", "1.0.3"]), platform=rng.choice(["ios", "ios", "android", "web"]))
            ev(t0 + rng.randint(300, 3600), "session_end", p["id"], seconds=600)
        day += 86400

    # Games: groups of players sitting together, sometimes with bots.
    t = start
    while t < now - 600:
        t += rng.expovariate(1 / 900) * (0.4 if 17 <= time.localtime(t).tm_hour <= 23 else 2.5)
        live = [p for p in players if p["joined"] < t]
        if len(live) < 3:
            continue
        humans = rng.sample(live, min(len(live), rng.choice([1, 2, 2, 3, 3, 3, 4, 4, 5, 6])))
        bots = rng.choice([0, 0, 0, 1, 2]) if len(humans) > 1 else rng.choice([1, 2, 3])
        game_no += 1
        room = "R" + secrets.token_hex(3).upper()
        table = rng.choice(TABLES)
        key = f"{room}.1.{int(t)}"
        seconds = rng.randint(90, 720)
        finished = rng.random() > 0.07
        deals = max(2, seconds // 35)
        level = "easy" if bots else None
        ev(t, "game_start", room=room, game=key, table=table, humans=len(humans), bots=bots, bot_match=False,
           bot_level=level, max_hand=3)
        seats = [p["id"] for p in humans] + [None] * bots
        rng.shuffle(seats)
        winner = rng.choice(seats) if finished else None
        standing, moves = [], []
        tallies = {}
        for i, pid in enumerate(seats):
            bets = rng.randint(3, 16)
            bluffs = rng.randint(0, bets // 2)
            tallies[i] = {"bets": bets, "bluffs": bluffs, "caught": rng.randint(0, bluffs), "checks": rng.randint(1, 8),
                          "called_right": 0, "called_wrong": 0, "deals_lost": rng.randint(0, 4),
                          "timeouts": rng.choice([0, 0, 0, 0, 1, 2])}
            tallies[i]["called_right"] = rng.randint(0, tallies[i]["checks"])
            tallies[i]["called_wrong"] = tallies[i]["checks"] - tallies[i]["called_right"]
        order = sorted(range(len(seats)), key=lambda i: (seats[i] != winner, rng.random()))
        for rank, i in enumerate(order):
            quit_ = rank > 0 and rng.random() < 0.06
            standing.append({"id": seats[i], "bot": seats[i] is None, "out_deal": None if rank == 0 else max(1, deals - rank * 2),
                             "reason": None if rank == 0 else "left" if quit_ else "cards", "bluffs": tallies[i]["bluffs"]})
        for d in range(max(1, deals - 3), deals + 1):
            bet = rng.choice(BETS)
            a, b = rng.sample(range(len(seats)), 2)
            moves += [{"deal": d, "id": seats[a], "bet": bet, "auto": False},
                      {"deal": d, "id": seats[b], "check": True, "held": rng.random() < 0.4, "auto": False}]
        left = sum(1 for s in standing if s["reason"] == "left" and not s["bot"])
        end = t + seconds
        if end < now:
            ev(end, "game_end", room=room, game=key, finished=finished, table=table, seconds=seconds, deals=deals,
               humans=len(humans), bots=bots, bot_match=False, bot_level=level, winner=winner,
               winner_is_bot=(winner is None) if finished else None, left=left,
               bluffs=sum(x["bluffs"] for x in tallies.values()), checks=sum(x["checks"] for x in tallies.values()),
               timeouts=sum(x["timeouts"] for x in tallies.values()), standing=standing, moves=moves[-12:])
            for i, pid in enumerate(seats):
                if pid:
                    s = next(x for x in standing if x["id"] == pid)
                    ev(end, "player_game", pid, room, game=key, finished=finished, won=pid == winner, out=s["reason"],
                       seconds=seconds, players=len(seats), bots=bots, bot_level=level, **tallies[i])
    for m in range(0, 30 * 1440, 5):
        tm = start + m * 60
        hour = time.localtime(tm).tm_hour
        busy = 1 + 6 * (17 <= hour <= 23) + 2 * (12 <= hour <= 14)
        ev(tm, "online", players=rng.randint(0, 6) * busy, playing=rng.randint(0, 3) * busy // 2,
           waiting=rng.randint(0, 2), bot_matches=rng.randint(0, 1), in_menus=rng.randint(0, 4),
           requests=rng.randint(20, 200) * busy, by_event={"act": 50}, failed={"stale": rng.randint(0, 3)},
           ms_p50=round(rng.uniform(1, 3), 1), ms_p95=round(rng.uniform(4, 12) if rng.random() > 0.004 else 160, 1), ms_max=20)
    for _ in range(40):
        p = rng.choice(players)
        tm = now - rng.random() * 26 * 3600
        ev(tm, "error", p["id"], rng.choice(TABLES), kind="server_exception", event="act", message="act: KeyError('bet')")
    for _ in range(6):
        ev(now - rng.random() * 6 * 86400, "error", None, None, kind="bot_illegal_move", message="bot chose bet pair_9: bet_too_low", players=[])

    rude = players[40]
    rude["name"] = "bitchboy"
    profiles[40]["name"] = "bitchboy"
    for who in rng.sample(players[:30], 3):
        reports.append({"t": now - rng.random() * 3600, "reporter": who["id"], "target": rude["id"], "name": "bitchboy",
                        "room": "RSNEAK", "reason": "offensive_name", "note": ""})
    for target, reason in ((players[3], "cheating"), (players[7], "abusive_reactions"), (players[9], "other")):
        reports.append({"t": now - rng.random() * 86400, "reporter": players[0]["id"], "target": target["id"],
                        "name": target["name"], "room": "RSNEAK", "reason": reason, "note": ""})
    for n in ("b1tchboy", "b.i.t.c.h", "bitchking", "fuuuck", "kurwa_mac"):
        refused.append({"t": now - rng.random() * 5 * 86400, "player": rude["id"], "name": n})
    for i, (word, whole) in enumerate((("kebab", False), ("lol", True))):
        store.add_blocked_word(word, whole, now - (i + 2) * 86400)
    profiles[12].update(locked=True, locked_at=now - 3 * 86400, name="Brave Llama")

    store.db.executemany("INSERT INTO events (t, type, player, room, data) VALUES (?, ?, ?, ?, ?)", events)
    store.add_reports(reports)
    store.add_refused(refused)
    store.save(profiles, [], [], now)
    print(f"wrote {len(events)} events, {game_no} games, {len(players)} players to {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/dashboard-demo.db")
