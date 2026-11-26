"""Write the answer keys the app's Training mode is tested against.

Training runs a copy of the game rules on the phone (liars-poker-app/training).
This script plays many seeded games with the real server engine and saves every
step, so the app's copy can replay them and must end up in exactly the same
state. Rerun it whenever server/rules.py or server/engine.py changes:

    .venv/bin/python scripts/export_training_fixtures.py [OUT_DIR]

OUT_DIR defaults to ../liars-poker-app/training/fixtures. The output depends only
on the code, never on the clock, so tests/test_training_fixtures.py can check
that the saved copy is still current.
"""
from __future__ import annotations

import json
import os
import random
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from server import bots, rules  # noqa: E402
from server.engine import BETTING, OVER, REVEAL, Game, GameError, Settings  # noqa: E402

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "liars-poker-app", "training", "fixtures")

HOLDS_SAMPLES = 4000
GAMES = 72
MAX_STEPS = 400


# ----- rules ---------------------------------------------------------------

def rules_fixture() -> dict:
    rng = random.Random(20261126)
    holds = []
    for i in range(HOLDS_SAMPLES):
        # Every pool size, weighted towards the sizes real tables have.
        size = (i % len(rules.DECK)) + 1 if i < 240 else rng.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16])
        cards = rng.sample(rules.DECK, size)
        result = "".join("1" if rules.bet_holds(bet, cards) else "0" for bet in rules.BETS)
        holds.append({"cards": cards, "result": result})
    limits = {}
    for players in range(2, rules.MAX_PLAYERS + 1):
        limits[str(players)] = {
            "auto": rules.auto_hand_limit(players),
            "deck": rules.deck_hand_limit(players),
            "chosen": [rules.hand_limit(players, chosen) for chosen in range(1, rules.MAX_HAND_CHOICE + 1)],
        }
    return {
        "ranks": rules.RANKS, "suits": rules.SUITS, "deck": rules.DECK, "bets": rules.BETS,
        "max_hand": rules.MAX_HAND, "auto_pool": rules.AUTO_POOL, "max_players": rules.MAX_PLAYERS,
        "max_hand_choice": rules.MAX_HAND_CHOICE, "hand_limits": limits, "holds": holds,
    }


# ----- games ---------------------------------------------------------------

class Recorder:
    """Captures every hand the engine deals, so a replay can deal the same cards."""

    def __init__(self):
        self.deals: List[List[List[str]]] = []
        self._real = rules.deal_hands

    def __enter__(self):
        def recording(sizes, rng):
            hands = self._real(sizes, rng)
            self.deals.append([list(h) for h in hands])
            return hands
        rules.deal_hands = recording
        return self

    def __exit__(self, *exc):
        rules.deal_hands = self._real


def _try(game: Game, action: dict) -> Optional[str]:
    kind, pid, now = action["type"], action.get("player_id"), action["now"]
    try:
        if kind == "bet":
            game.bet(pid, action["bet"], now)
        elif kind == "check":
            game.check(pid, now)
        elif kind == "ready":
            game.mark_ready(pid)
        elif kind == "next_deal":
            game.next_deal(now)
        elif kind == "timeout":
            game.timeout(now)
        elif kind == "remove":
            game.remove(pid, now, action.get("reason", "left"))
        else:
            raise ValueError(kind)
    except GameError as error:
        return error.code
    return None


def _choose(game: Game, rng: random.Random, now: float) -> dict:
    ids = [s.id for s in game.seats]
    roll = rng.random()
    if roll < 0.03:
        return {"type": "remove", "player_id": rng.choice(ids), "now": now,
                "reason": rng.choice(["left", "kicked"])}
    if roll < 0.06:
        # Moves that must be refused (wrong player, wrong phase, bad bet).
        return rng.choice([
            {"type": "bet", "player_id": rng.choice(ids), "bet": rng.choice(rules.BETS), "now": now},
            {"type": "bet", "player_id": rng.choice(ids), "bet": "pair_X", "now": now},
            {"type": "check", "player_id": rng.choice(ids), "now": now},
            {"type": "next_deal", "now": now},
            {"type": "ready", "player_id": rng.choice(ids + ["nobody"]), "now": now},
            {"type": "bet", "player_id": "nobody", "bet": rules.LOWEST_BET, "now": now},
        ])
    if game.phase == BETTING:
        pid = game.current_id
        if roll < 0.08:
            # The player whose turn it is, with a bet that must be refused.
            if game.bets and rng.random() < 0.6:
                return {"type": "bet", "player_id": pid, "bet": rng.choice(rules.BETS[:rules.bet_rank(game.last_bet) + 1]),
                        "now": now}
            return {"type": "bet", "player_id": pid, "bet": rng.choice(["pair_X", "", "flush", "PAIR_A"]), "now": now}
        if roll < 0.10:
            return {"type": "timeout", "now": game.deadline + rng.choice([0.0, 0.5])}
        if roll < 0.12:
            return {"type": "timeout", "now": now}  # too early: nothing happens
        if roll < 0.75:
            seat = game.seat(pid)
            kind, bet = bots.decide(seat.hand, len(game.cards_in_play()), game.last_bet, seat.cards,
                                    game.settings.max_hand, rng)
            if kind == "check" and game.bets:
                return {"type": "check", "player_id": pid, "now": now}
            return {"type": "bet", "player_id": pid, "bet": bet or rules.bets_above(game.last_bet)[0], "now": now}
        above = rules.bets_above(game.last_bet)
        if game.bets and (not above or rng.random() < 0.35):
            return {"type": "check", "player_id": pid, "now": now}
        return {"type": "bet", "player_id": pid, "bet": rng.choice(above[:8]), "now": now}
    if game.phase == REVEAL:
        if roll < 0.15:
            return {"type": "timeout", "now": game.deadline}
        if roll < 0.55:
            return {"type": "ready", "player_id": rng.choice(ids), "now": now}
        return {"type": "next_deal", "now": now}
    return {"type": "bet", "player_id": rng.choice(ids), "bet": rules.LOWEST_BET, "now": now}


def play_game(index: int) -> dict:
    rng = random.Random(1000 + index)
    players = rng.choice([2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 6, 7, 8])
    ids = [f"p{i}" for i in range(players)]
    chosen = None if rng.random() < 0.6 else rng.randint(1, rules.MAX_HAND_CHOICE)
    settings = Settings(turn_seconds=60.0, reveal_seconds=10.0, max_hand=chosen)
    now = 100.0
    mini = index % 3 == 2  # every third game starts in the middle, like a Training mini game
    with Recorder() as recorder:
        game = Game(ids, now, rng=random.Random(rng.random()), settings=settings, start=False)
        setup = None
        if mini:
            limit = game.settings.max_hand
            alive = rng.randint(2, players)
            out = set(rng.sample(range(players), players - alive))
            cards = []
            for i, seat in enumerate(game.seats):
                if i in out:
                    seat.cards, seat.out, seat.out_reason = limit + 1, True, "cards"
                else:
                    seat.cards = rng.randint(1, limit)
                cards.append(seat.cards)
            game.deal_no = rng.randint(2, 12)
            game.starter = rng.choice([i for i in range(players) if i not in out])
            setup = {"cards": cards, "out": sorted(out), "deal_no": game.deal_no, "starter": game.starter}
        game._start_deal(now)
        steps = [{"action": {"type": "start", "now": now}, "error": None,
                  "events": game.drain_events(), "state": game.to_dict()}]
        for _ in range(MAX_STEPS):
            if game.phase == OVER:
                break
            now += rng.choice([0.5, 1.0, 1.5, 2.0])
            action = _choose(game, rng, now)
            now = max(now, action["now"])
            error = _try(game, action)
            problems = game.problems()
            if problems:
                raise AssertionError(f"game {index}: {problems}")
            steps.append({"action": action, "error": error, "events": game.drain_events(), "state": game.to_dict()})
        if game.phase == OVER:
            # A move after the end must still be refused the same way.
            action = {"type": "bet", "player_id": ids[0], "bet": rules.LOWEST_BET, "now": now + 1}
            steps.append({"action": action, "error": _try(game, action), "events": game.drain_events(),
                          "state": game.to_dict()})
    return {"players": ids, "settings": settings.to_dict(), "setup": setup, "deals": recorder.deals, "steps": steps}


def games_fixture() -> dict:
    return {"games": [play_game(i) for i in range(GAMES)]}


def build() -> Dict[str, str]:
    """File name -> exact file contents."""
    return {
        "rules.json": json.dumps(rules_fixture(), ensure_ascii=False, separators=(",", ":")) + "\n",
        "games.json": json.dumps(games_fixture(), ensure_ascii=False, separators=(",", ":")) + "\n",
    }


def main() -> None:
    out_dir = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    os.makedirs(out_dir, exist_ok=True)
    for name, text in build().items():
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {path} ({len(text.encode()) // 1024} KB)")


if __name__ == "__main__":
    main()
