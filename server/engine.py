"""The game itself: a deterministic state machine with no I/O.

Time is always passed in (``now``, seconds) and randomness comes from an
injected ``random.Random``, so every transition can be unit-tested and
replayed. The server layer owns sockets, timers and bots; this module only
answers "given this state and this action, what is the next state?".

Phases:
    betting  players take turns raising or checking
    reveal   someone checked; all hands are shown until the next deal
    over     one player is left; ``winner`` is set
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from . import rules

BETTING, REVEAL, OVER = "betting", "reveal", "over"


class GameError(Exception):
    """A rejected action. ``code`` is a stable string the client can map to text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Settings:
    turn_seconds: float = 60.0
    reveal_seconds: float = 10.0
    #: Most cards a player may hold; one more puts them out. None means "auto"
    #: (see rules.hand_limit). A running game always holds a resolved number.
    max_hand: Optional[int] = None

    def to_dict(self) -> dict:
        return {"turn_seconds": self.turn_seconds, "reveal_seconds": self.reveal_seconds, "max_hand": self.max_hand}

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        return cls(**{k: d[k] for k in ("turn_seconds", "reveal_seconds", "max_hand") if k in d})


@dataclass
class Seat:
    id: str
    cards: int = 1
    out: bool = False
    #: "cards" (lost too many deals), "left" (quit or timed out while away), "kicked"
    out_reason: Optional[str] = None
    hand: List[str] = field(default_factory=list)
    last_bet: Optional[str] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "cards": self.cards, "out": self.out, "out_reason": self.out_reason,
                "hand": list(self.hand), "last_bet": self.last_bet}

    @classmethod
    def from_dict(cls, d: dict) -> "Seat":
        return cls(id=d["id"], cards=d["cards"], out=d["out"], out_reason=d.get("out_reason"),
                   hand=list(d.get("hand", [])), last_bet=d.get("last_bet"))


class Game:
    def __init__(self, player_ids: List[str], now: float, rng: Optional[random.Random] = None,
                 settings: Optional[Settings] = None, start: bool = True):
        if len(player_ids) < 2:
            raise GameError("not_enough_players")
        if len(player_ids) > rules.MAX_PLAYERS:
            raise GameError("too_many_players")
        if len(set(player_ids)) != len(player_ids):
            raise GameError("duplicate_players")
        self.rng = rng or random.Random()
        # A copy, so the room's choice ("auto") is kept for the next game.
        base = settings or Settings()
        self.settings = replace(base, max_hand=rules.hand_limit(len(player_ids), base.max_hand))
        self.seats: List[Seat] = [Seat(pid) for pid in player_ids]
        self.phase = BETTING
        self.deal_no = 0
        #: Bumped on every accepted move or deal. Clients send it back so a move
        #: made against an old state (e.g. resent after a reconnect) is rejected.
        self.turn_seq = 0
        self.turn = 0
        self.starter = 0
        self.bets: List[dict] = []
        self.deadline: Optional[float] = None
        self.turn_started_at: float = now
        self.reveal: Optional[dict] = None
        self.winner: Optional[str] = None
        self.ready: set = set()
        #: Events produced since the caller last drained them.
        self.events: List[dict] = []
        if start:
            self._start_deal(now)

    # ----- queries -------------------------------------------------------

    def seat(self, pid: str) -> Optional[Seat]:
        return next((s for s in self.seats if s.id == pid), None)

    def alive(self) -> List[Seat]:
        return [s for s in self.seats if not s.out]

    def alive_ids(self) -> List[str]:
        return [s.id for s in self.alive()]

    @property
    def current_id(self) -> Optional[str]:
        return self.seats[self.turn].id if self.phase == BETTING else None

    @property
    def last_bet(self) -> Optional[str]:
        return self.bets[-1]["bet"] if self.bets else None

    @property
    def last_bettor(self) -> Optional[str]:
        return self.bets[-1]["player_id"] if self.bets else None

    def cards_in_play(self) -> List[str]:
        return [card for s in self.alive() for card in s.hand]

    def _next_alive(self, index: int, include_self: bool = False) -> int:
        n = len(self.seats)
        for step in range(0 if include_self else 1, n + 1):
            i = (index + step) % n
            if not self.seats[i].out:
                return i
        raise GameError("no_players_left")

    def _index(self, pid: str) -> int:
        for i, s in enumerate(self.seats):
            if s.id == pid:
                return i
        raise GameError("not_in_game")

    def _emit(self, type_: str, **data) -> None:
        self.events.append({"type": type_, **data})

    def drain_events(self) -> List[dict]:
        events, self.events = self.events, []
        return events

    # ----- transitions ---------------------------------------------------

    def _start_deal(self, now: float) -> None:
        alive = self.alive()
        hands = rules.deal_hands([s.cards for s in alive], self.rng)
        for s in self.seats:
            s.hand, s.last_bet = [], None
        for s, hand in zip(alive, hands):
            s.hand = hand
        self.phase = BETTING
        self.deal_no += 1
        self.turn_seq += 1
        self.bets = []
        self.reveal = None
        self.ready = set()
        self.turn = self._next_alive(self.starter, include_self=True)
        self.turn_started_at = now
        self.deadline = now + self.settings.turn_seconds
        self._emit("new_deal", deal_no=self.deal_no, starter_id=self.seats[self.turn].id,
                   cards={s.id: s.cards for s in alive})

    def _require_turn(self, pid: str) -> Seat:
        if self.phase != BETTING:
            raise GameError("wrong_phase")
        seat = self.seat(pid)
        if seat is None:
            raise GameError("not_in_game")
        if seat.out:
            raise GameError("you_are_out")
        if self.seats[self.turn].id != pid:
            raise GameError("not_your_turn")
        return seat

    def bet(self, pid: str, bet: str, now: float, auto: bool = False) -> None:
        seat = self._require_turn(pid)
        if not rules.is_bet(bet):
            raise GameError("invalid_bet")
        if not rules.beats(bet, self.last_bet):
            raise GameError("bet_too_low")
        self.bets.append({"player_id": pid, "bet": bet})
        seat.last_bet = bet
        self.turn = self._next_alive(self.turn)
        self.turn_seq += 1
        self.turn_started_at = now
        self.deadline = now + self.settings.turn_seconds
        self._emit("bet", player_id=pid, bet=bet, auto=auto)

    def check(self, pid: str, now: float, auto: bool = False) -> None:
        self._require_turn(pid)
        if not self.bets:
            raise GameError("nothing_to_check")
        bet, bettor = self.last_bet, self.last_bettor
        held = rules.bet_holds(bet, self.cards_in_play())
        loser_id = pid if held else bettor
        hands = {s.id: list(s.hand) for s in self.alive()}
        self._emit("check", player_id=pid, bet=bet, bettor_id=bettor, auto=auto)

        loser = self.seat(loser_id)
        loser.cards += 1
        eliminated = loser.cards > self.settings.max_hand
        loser_index = self._index(loser_id)
        if eliminated:
            loser.out, loser.out_reason = True, "cards"

        self.reveal = {"checker_id": pid, "bettor_id": bettor, "bet": bet, "held": held,
                       "loser_id": loser_id, "eliminated": eliminated, "hands": hands}
        self._emit("deal_result", loser_id=loser_id, held=held, bet=bet, eliminated=eliminated,
                   hands=hands)
        if eliminated:
            self._emit("player_eliminated", player_id=loser_id, reason="cards")

        self.turn_seq += 1
        # The loser opens the next deal; if they are out, the next player does.
        if self._finish_if_won(now):
            return
        self.starter = self._next_alive(loser_index, include_self=True)
        self.phase = REVEAL
        self.ready = set()
        self.turn_started_at = now
        self.deadline = now + self.settings.reveal_seconds

    def mark_ready(self, pid: str) -> None:
        if self.phase != REVEAL:
            raise GameError("wrong_phase")
        seat = self.seat(pid)
        if seat is None:
            raise GameError("not_in_game")
        self.ready.add(pid)

    def next_deal(self, now: float) -> None:
        if self.phase != REVEAL:
            raise GameError("wrong_phase")
        self._start_deal(now)

    def timeout(self, now: float) -> bool:
        """Apply whatever the clock demands. Returns True if the state changed."""
        if self.deadline is None or now < self.deadline:
            return False
        if self.phase == BETTING:
            self.auto_play(now)
            return True
        if self.phase == REVEAL:
            self.next_deal(now)
            return True
        return False

    def auto_play(self, now: float) -> None:
        """Move for the current player when their time runs out.

        Opening the deal is forced to the lowest bet; otherwise the player checks,
        which ends the deal quickly instead of stalling everyone.
        """
        pid = self.seats[self.turn].id
        self._emit("turn_timeout", player_id=pid)
        if self.bets:
            self.check(pid, now, auto=True)
        else:
            self.bet(pid, rules.LOWEST_BET, now, auto=True)

    def remove(self, pid: str, now: float, reason: str = "left") -> None:
        """A player quits (or is dropped). Mid-deal the deal is voided and redealt,
        because their cards were part of the pool every bet was made against."""
        seat = self.seat(pid)
        if seat is None or seat.out or self.phase == OVER:
            return
        index = self._index(pid)
        seat.out, seat.out_reason = True, reason
        self.ready.discard(pid)
        self._emit("player_eliminated", player_id=pid, reason=reason)
        self.turn_seq += 1
        if self._finish_if_won(now):
            return
        if self.phase == BETTING:
            # Whoever was about to act opens the redeal.
            self.starter = self._next_alive(self.turn, include_self=index != self.turn)
            self._emit("deal_voided", player_id=pid)
            self._start_deal(now)
        elif self.phase == REVEAL and self.starter == index:
            self.starter = self._next_alive(index)

    def _finish_if_won(self, now: float) -> bool:
        alive = self.alive()
        if len(alive) > 1:
            return False
        self.phase = OVER
        self.deadline = None
        self.winner = alive[0].id if alive else None
        self._emit("game_won", player_id=self.winner)
        return True

    # ----- self-checks ---------------------------------------------------

    def problems(self) -> List[str]:
        """Invariants that must always hold. Anything returned here is a bug."""
        found = []
        alive = self.alive()
        if self.phase != OVER and len(alive) < 2:
            found.append(f"{len(alive)} players alive but phase is {self.phase}")
        if self.phase == OVER and len(alive) > 1:
            found.append("game over with more than one player alive")
        if self.phase == OVER and self.winner not in [s.id for s in alive] + ([None] if not alive else []):
            found.append(f"winner {self.winner} is not the last player alive")
        if self.phase == BETTING:
            if not (0 <= self.turn < len(self.seats)) or self.seats[self.turn].out:
                found.append(f"turn {self.turn} points at a missing or eliminated player")
            if self.deadline is None:
                found.append("betting without a deadline")
            for s in alive:
                if len(s.hand) != s.cards:
                    found.append(f"{s.id} holds {len(s.hand)} cards but should hold {s.cards}")
            cards = self.cards_in_play()
            if len(cards) != len(set(cards)):
                found.append("duplicate cards in play")
            if any(c not in rules.DECK for c in cards):
                found.append("unknown card in play")
        for s in self.seats:
            if s.out and s.hand and self.phase == BETTING:
                found.append(f"eliminated {s.id} still holds cards")
            if not s.out and s.cards > self.settings.max_hand:
                found.append(f"{s.id} has {s.cards} cards and is still in")
        ranks = [rules.bet_rank(b["bet"]) for b in self.bets if rules.is_bet(b["bet"])]
        if len(ranks) != len(self.bets) or ranks != sorted(set(ranks)):
            found.append("bets are not strictly increasing")
        return found

    # ----- persistence ---------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "seats": [s.to_dict() for s in self.seats], "phase": self.phase, "deal_no": self.deal_no,
            "turn_seq": self.turn_seq, "turn": self.turn, "starter": self.starter, "bets": list(self.bets),
            "deadline": self.deadline, "turn_started_at": self.turn_started_at, "reveal": self.reveal,
            "winner": self.winner, "ready": sorted(self.ready), "settings": self.settings.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict, rng: Optional[random.Random] = None) -> "Game":
        game = cls.__new__(cls)
        game.rng = rng or random.Random()
        game.settings = Settings.from_dict(d.get("settings", {}))
        game.seats = [Seat.from_dict(s) for s in d["seats"]]
        if game.settings.max_hand is None:
            game.settings.max_hand = rules.hand_limit(len(game.seats))
        game.phase, game.deal_no, game.turn_seq = d["phase"], d["deal_no"], d["turn_seq"]
        game.turn, game.starter, game.bets = d["turn"], d["starter"], list(d["bets"])
        game.deadline, game.turn_started_at = d["deadline"], d["turn_started_at"]
        game.reveal, game.winner, game.ready = d["reveal"], d["winner"], set(d["ready"])
        game.events = []
        return game
