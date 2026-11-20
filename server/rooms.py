"""Rooms, membership and everything time-driven around a game.

Like the engine, this layer does no I/O. The socket server calls into a
``Lobby`` with a player id and the current time, then sends each member the
snapshot returned by ``Room.snapshot``. ``Lobby.tick(now)`` runs timeouts,
bots, reveal advancement and dropping players who stayed away too long.

Identity is a ``player_id`` tied to a secret ``token`` the client keeps, so a
player stays the same person across reconnects, new sockets, app restarts
and server restarts. Socket ids never leave the server layer.
"""
from __future__ import annotations

import random
import secrets
import string
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import bots, rules
from .engine import BETTING, OVER, REVEAL, Game, GameError, Settings

#: Seconds a bot "thinks" before moving, so humans can follow.
BOT_DELAY = 1.4
#: Reveal shown for this long before the next deal when no connected human needs to confirm.
UNATTENDED_REVEAL = 4.0
#: A finished bot match starts again after this long.
AUTOPLAY_RESTART_AFTER = 8.0
MAX_BOTS_MATCH = 8
#: A seated player who is disconnected this long during a game leaves it.
FORFEIT_AFTER = 120.0
#: A disconnected member is dropped from a room without a running game after this long.
LOBBY_DROP_AFTER = 600.0
#: A room with no connected humans is deleted after this long.
ROOM_IDLE_AFTER = 1800.0
MAX_SPECTATORS = 50
LOG_LIMIT = 200
SNAPSHOT_LOG = 60
NAME_LIMIT = 20
MOVE_MEMORY = 32

ROOM_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def clean_name(raw: object) -> str:
    name = raw if isinstance(raw, str) else ""
    name = " ".join("".join(ch for ch in name if ch.isprintable()).split())
    return name[:NAME_LIMIT] or "Player"


@dataclass
class Profile:
    id: str
    token: str
    name: str
    room_id: Optional[str] = None
    connected: bool = False
    disconnected_at: Optional[float] = None


@dataclass
class Member:
    id: str
    name: str
    is_bot: bool = False
    role: str = "player"  # "player" | "spectator"


@dataclass
class Room:
    id: str
    name: str
    host_id: str
    created_at: float
    settings: Settings = field(default_factory=Settings)
    members: "OrderedDict[str, Member]" = field(default_factory=OrderedDict)
    #: Seating order for the next game (players only).
    seats: List[str] = field(default_factory=list)
    game: Optional[Game] = None
    #: Names of everyone who ever sat here, so history still reads after they leave.
    names: Dict[str, str] = field(default_factory=dict)
    bot_ids: set = field(default_factory=set)
    log: List[dict] = field(default_factory=list)
    log_seq: int = 0
    version: int = 0
    games_played: int = 0
    idle_since: Optional[float] = None
    #: Bot match: restarts by itself after each game.
    autoplay: bool = False
    finished_at: Optional[float] = None
    moves: Dict[str, "OrderedDict[str, dict]"] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.game is None:
            return "lobby"
        return "finished" if self.game.phase == OVER else "playing"

    def touch(self) -> None:
        self.version += 1

    def humans(self) -> List[Member]:
        return [m for m in self.members.values() if not m.is_bot]

    def players(self) -> List[Member]:
        return [self.members[pid] for pid in self.seats if pid in self.members]


class LobbyError(GameError):
    pass


class Lobby:
    def __init__(self, rng: Optional[random.Random] = None):
        self.rng = rng or random.Random()
        self.profiles: Dict[str, Profile] = {}
        self.by_token: Dict[str, str] = {}
        self.rooms: Dict[str, Room] = {}
        #: (player_id, event, payload) messages for the server to deliver.
        self.notices: List[Tuple[str, str, dict]] = []
        #: Bugs noticed while running (broken invariants, bots making illegal moves),
        #: for the server to report. Each item: {"kind", "message", "room_id", "context"}.
        self.problems: List[dict] = []
        #: Bumped whenever the public room list changes.
        self.list_version = 0
        self.dirty: set = set()

    # ----- identity ------------------------------------------------------

    def hello(self, token: object, name: object, now: float) -> Profile:
        """Find the player for ``token`` or register a new one."""
        pid = self.by_token.get(token) if isinstance(token, str) else None
        profile = self.profiles.get(pid) if pid else None
        if profile is None:
            pid = "p_" + secrets.token_hex(8)
            profile = Profile(id=pid, token=secrets.token_urlsafe(24), name=clean_name(name))
            self.profiles[pid] = profile
            self.by_token[profile.token] = pid
        elif isinstance(name, str) and name.strip():
            profile.name = clean_name(name)
        self.dirty.add("profiles")
        return profile

    def set_connected(self, pid: str, connected: bool, now: float) -> None:
        profile = self.profiles.get(pid)
        if profile is None or profile.connected == connected:
            return
        profile.connected = connected
        profile.disconnected_at = None if connected else now
        room = self.rooms.get(profile.room_id or "")
        if room and pid in room.members:
            self._log(room, now, "player_reconnected" if connected else "player_disconnected", pid)
            room.touch()

    def is_connected(self, pid: str) -> bool:
        profile = self.profiles.get(pid)
        return bool(profile and profile.connected)

    # ----- rooms ---------------------------------------------------------

    def _new_room_id(self) -> str:
        while True:
            code = "".join(self.rng.choice(ROOM_CODE_ALPHABET) for _ in range(5))
            if code not in self.rooms:
                return code

    def _room_of(self, pid: str) -> Room:
        profile = self._profile(pid)
        room = self.rooms.get(profile.room_id or "")
        if room is None or pid not in room.members:
            raise LobbyError("not_in_room")
        return room

    def _profile(self, pid: str) -> Profile:
        profile = self.profiles.get(pid)
        if profile is None:
            raise LobbyError("unknown_player")
        return profile

    def _require_host(self, room: Room, pid: str) -> None:
        if room.host_id != pid:
            raise LobbyError("not_host")

    def _require_not_playing(self, room: Room) -> None:
        if room.status == "playing":
            raise LobbyError("game_in_progress")

    def _unique_name(self, room: Room, name: str) -> str:
        taken = {m.name.lower() for m in room.members.values()}
        if name.lower() not in taken:
            return name
        n = 2
        while f"{name} {n}".lower() in taken:
            n += 1
        return f"{name[:NAME_LIMIT - 3]} {n}"

    def create_room(self, pid: str, now: float) -> Room:
        profile = self._profile(pid)
        self.leave(pid, now)
        room = Room(id=self._new_room_id(), name=f"{profile.name}'s table", host_id=pid, created_at=now)
        self.rooms[room.id] = room
        self._add_member(room, profile, now)
        self.list_version += 1
        return room

    def join_room(self, pid: str, room_id: object, now: float) -> Room:
        profile = self._profile(pid)
        room = self.rooms.get(room_id) if isinstance(room_id, str) else None
        if room is None:
            raise LobbyError("room_not_found")
        if pid in room.members:
            profile.room_id = room.id  # rejoin after reconnect: nothing changes
            return room
        would_watch = room.status == "playing" or len(room.seats) >= rules.MAX_PLAYERS
        watching = [m for m in room.members.values() if m.role == "spectator"]
        if would_watch and len(watching) >= MAX_SPECTATORS:
            raise LobbyError("room_full")
        self.leave(pid, now)
        self._add_member(room, profile, now)
        return room

    def _add_member(self, room: Room, profile: Profile, now: float) -> None:
        seated = room.status != "playing" and len(room.seats) < rules.MAX_PLAYERS
        member = Member(id=profile.id, name=self._unique_name(room, profile.name),
                        role="player" if seated else "spectator")
        room.members[member.id] = member
        room.names[member.id] = member.name
        if seated:
            room.seats.append(member.id)
        profile.room_id = room.id
        room.idle_since = None
        self._log(room, now, "player_joined", member.id, role=member.role)
        room.touch()
        self.list_version += 1

    def leave(self, pid: str, now: float, reason: str = "left") -> Optional[Room]:
        """Leave the current room, if any. Mid-game this forfeits the seat."""
        profile = self.profiles.get(pid)
        room = self.rooms.get(profile.room_id or "") if profile else None
        if profile:
            profile.room_id = None
        if room is None or pid not in room.members:
            return None
        self._remove_member(room, pid, now, reason)
        return room

    def _remove_member(self, room: Room, pid: str, now: float, reason: str) -> None:
        if room.game is not None and room.game.seat(pid) is not None:
            room.game.remove(pid, now, reason="kicked" if reason == "kicked" else "left")
            self._drain(room, now)
        room.members.pop(pid, None)
        room.moves.pop(pid, None)
        if pid in room.seats:
            room.seats.remove(pid)
        room.bot_ids.discard(pid)
        profile = self.profiles.get(pid)
        if profile and profile.room_id == room.id:
            profile.room_id = None
        self._log(room, now, "player_left", pid, reason=reason)
        if not room.humans():
            self._delete_room(room)
            return
        if room.host_id == pid:
            self._pick_host(room)
        room.touch()
        self.list_version += 1

    def _pick_host(self, room: Room) -> None:
        humans = room.humans()
        # Prefer someone connected and seated.
        humans.sort(key=lambda m: (not self.is_connected(m.id), m.role != "player"))
        room.host_id = humans[0].id
        self._log(room, None, "host_changed", room.host_id)

    def _delete_room(self, room: Room) -> None:
        for member in list(room.members.values()):
            profile = self.profiles.get(member.id)
            if profile and profile.room_id == room.id:
                profile.room_id = None
                self.notices.append((member.id, "room_closed", {"room_id": room.id}))
        self.rooms.pop(room.id, None)
        self.dirty.add(("deleted", room.id))
        self.list_version += 1

    def add_bot(self, pid: str, now: float) -> Member:
        room = self._room_of(pid)
        self._require_host(room, pid)
        self._require_not_playing(room)
        if len(room.seats) >= rules.MAX_PLAYERS:
            raise LobbyError("room_full")
        n = 1
        taken = {m.name for m in room.members.values()}
        while f"Bot {n}" in taken:
            n += 1
        bot = Member(id="b_" + secrets.token_hex(6), name=f"Bot {n}", is_bot=True)
        room.members[bot.id] = bot
        room.names[bot.id] = bot.name
        room.bot_ids.add(bot.id)
        room.seats.append(bot.id)
        self._log(room, now, "player_joined", bot.id, role="player")
        room.touch()
        self.list_version += 1
        return bot

    def kick(self, pid: str, target: object, now: float) -> None:
        room = self._room_of(pid)
        self._require_host(room, pid)
        if not isinstance(target, str) or target not in room.members or target == pid:
            raise LobbyError("player_not_found")
        member = room.members[target]
        if room.status == "playing" and room.game.seat(target) and not room.game.seat(target).out:
            # Mid-game the host may only remove someone who is gone.
            if not member.is_bot and self.is_connected(target):
                raise LobbyError("game_in_progress")
        self._remove_member(room, target, now, "kicked")
        if not member.is_bot:
            self.notices.append((target, "kicked", {"room_id": room.id}))

    def shuffle_seats(self, pid: str, now: float) -> None:
        room = self._room_of(pid)
        self._require_host(room, pid)
        self._require_not_playing(room)
        self.rng.shuffle(room.seats)
        room.touch()

    def sit(self, pid: str, now: float) -> None:
        room = self._room_of(pid)
        self._require_not_playing(room)
        member = room.members[pid]
        if member.role == "player":
            return
        if len(room.seats) >= rules.MAX_PLAYERS:
            raise LobbyError("room_full")
        member.role = "player"
        room.seats.append(pid)
        room.touch()
        self.list_version += 1

    def stand(self, pid: str, now: float) -> None:
        room = self._room_of(pid)
        self._require_not_playing(room)
        member = room.members[pid]
        if member.role == "spectator":
            return
        member.role = "spectator"
        room.seats.remove(pid)
        room.touch()
        self.list_version += 1

    def start_game(self, pid: str, now: float) -> None:
        room = self._room_of(pid)
        self._require_host(room, pid)
        self._require_not_playing(room)
        self._start(room, now)

    def _start(self, room: Room, now: float) -> None:
        seats = [m.id for m in room.players()]
        if len(seats) < 2:
            raise LobbyError("not_enough_players")
        room.finished_at = None
        room.game = Game(seats, now, rng=random.Random(self.rng.random()), settings=room.settings, start=False)
        room.games_played += 1
        room.moves = {}
        self._log(room, now, "game_start", None, players=list(seats))
        room.game._start_deal(now)
        self._drain(room, now)
        room.touch()
        self.list_version += 1

    def create_bot_match(self, pid: str, bots_count: object, now: float) -> Room:
        """A room where only bots play and the caller watches. It starts at once
        and starts again after every game, to see the game run (and catch bugs)."""
        n = bots_count if isinstance(bots_count, int) and not isinstance(bots_count, bool) else 4
        n = max(2, min(MAX_BOTS_MATCH, n))
        room = self.create_room(pid, now)
        room.name = "Bot match"
        room.autoplay = True
        self.stand(pid, now)
        for _ in range(n):
            self.add_bot(pid, now)
        self._start(room, now)
        return room

    # ----- moves ---------------------------------------------------------

    def act(self, pid: str, payload: object, now: float) -> dict:
        """Apply a player's move. Safe to retry: the same ``move_id`` returns the
        first answer without applying the move twice."""
        if not isinstance(payload, dict):
            raise LobbyError("bad_request")
        room = self._room_of(pid)
        move_id = payload.get("move_id")
        memory = room.moves.setdefault(pid, OrderedDict())
        if isinstance(move_id, str) and move_id in memory:
            return memory[move_id]
        result = self._apply(room, pid, payload, now)
        if isinstance(move_id, str) and len(move_id) <= 64:
            memory[move_id] = result
            while len(memory) > MOVE_MEMORY:
                memory.popitem(last=False)
        return result

    def _apply(self, room: Room, pid: str, payload: dict, now: float) -> dict:
        game = room.game
        kind = payload.get("type")
        try:
            if game is None:
                raise GameError("no_game")
            if kind in ("bet", "check"):
                if payload.get("turn_seq") != game.turn_seq:
                    raise GameError("stale")
                if kind == "bet":
                    game.bet(pid, payload.get("bet"), now)
                else:
                    game.check(pid, now)
            elif kind == "ready":
                game.mark_ready(pid)
            else:
                raise GameError("bad_request")
        except GameError as error:
            return {"ok": False, "error": error.code}
        self._drain(room, now)
        self._maybe_advance_reveal(room, now)
        room.touch()
        return {"ok": True}

    # ----- clock ---------------------------------------------------------

    def tick(self, now: float) -> List[Room]:
        """Advance every room by the clock. Returns rooms whose state changed."""
        changed = []
        for room in list(self.rooms.values()):
            before = room.version
            self._tick_room(room, now)
            if room.id in self.rooms and room.version != before:
                changed.append(room)
        return changed

    def _tick_room(self, room: Room, now: float) -> None:
        # Members who have been away too long.
        for member in list(room.humans()):
            profile = self.profiles.get(member.id)
            if profile is None or profile.connected or profile.disconnected_at is None:
                continue
            away = now - profile.disconnected_at
            game = room.game
            seated_alive = game is not None and game.phase != OVER and game.seat(member.id) and not game.seat(member.id).out
            if seated_alive and away >= FORFEIT_AFTER:
                game.remove(member.id, now, reason="left")
                self._log(room, now, "player_timed_out", member.id)
                self._drain(room, now)
                room.touch()
            elif not seated_alive and away >= LOBBY_DROP_AFTER:
                self._remove_member(room, member.id, now, "timed_out")
                if room.id not in self.rooms:
                    return

        # Empty rooms.
        if any(self.is_connected(m.id) for m in room.humans()):
            room.idle_since = None
        elif room.idle_since is None:
            room.idle_since = now
        elif now - room.idle_since >= ROOM_IDLE_AFTER:
            self._delete_room(room)
            return

        game = room.game
        if game is not None and game.phase == OVER and room.autoplay:
            if room.finished_at is None:
                room.finished_at = now
            elif now - room.finished_at >= AUTOPLAY_RESTART_AFTER:
                self._start(room, now)
            return
        if game is None or game.phase == OVER:
            return

        if game.phase == BETTING and game.current_id in room.bot_ids and now >= game.turn_started_at + BOT_DELAY:
            self._bot_move(room, game.current_id, now)
            return

        if game.phase == REVEAL and self._maybe_advance_reveal(room, now):
            room.touch()
            return

        if game.timeout(now):
            self._drain(room, now)
            room.touch()

    def _maybe_advance_reveal(self, room: Room, now: float) -> bool:
        game = room.game
        if game is None or game.phase != REVEAL:
            return False
        needed = [s.id for s in game.alive() if s.id not in room.bot_ids and self.is_connected(s.id)]
        if needed:
            if not all(pid in game.ready for pid in needed):
                return False
        elif now < game.turn_started_at + UNATTENDED_REVEAL:
            return False
        game.next_deal(now)
        self._drain(room, now)
        return True

    def _bot_move(self, room: Room, bot_id: str, now: float) -> None:
        game = room.game
        seat = game.seat(bot_id)
        kind, bet = bots.decide(seat.hand, len(game.cards_in_play()), game.last_bet, seat.cards,
                                game.settings.max_hand, self.rng)
        try:
            if kind == "check" and game.bets:
                game.check(bot_id, now)
            else:
                game.bet(bot_id, bet or rules.bets_above(game.last_bet)[0], now)
        except GameError as error:
            # A bot must never stall the table; but an illegal bot move is a bug.
            self._problem(room, "bot_illegal_move", f"bot chose {kind} {bet}: {error.code}")
            game.auto_play(now)
        self._drain(room, now)
        room.touch()

    # ----- log -----------------------------------------------------------

    def _log(self, room: Room, now: Optional[float], type_: str, pid: Optional[str], **data) -> None:
        room.log_seq += 1
        entry = {"id": room.log_seq, "type": type_, "ts": int((now or 0) * 1000)}
        if pid is not None:
            entry["player_id"] = pid
            entry["player_name"] = room.names.get(pid, "Someone")
        entry.update(data)
        room.log.append(entry)
        if len(room.log) > LOG_LIMIT:
            del room.log[: len(room.log) - LOG_LIMIT]

    def _problem(self, room: Room, kind: str, message: str) -> None:
        self.problems.append({
            "kind": kind, "message": message, "room_id": room.id,
            "context": {"status": room.status, "game": room.game.to_dict() if room.game else None,
                        "log": room.log[-15:]},
        })

    def _drain(self, room: Room, now: float) -> None:
        issues = room.game.problems()
        if issues:
            self._problem(room, "invariant", "; ".join(issues))
        for event in room.game.drain_events():
            event = dict(event)
            type_ = event.pop("type")
            pid = event.pop("player_id", None) or event.get("starter_id") or event.get("loser_id")
            if type_ == "game_won":
                self.list_version += 1
            self._log(room, now, type_, pid, **event)

    # ----- views ---------------------------------------------------------

    def room_list(self) -> List[dict]:
        out = []
        for room in self.rooms.values():
            if room.autoplay:
                continue  # bot matches are private to whoever started them
            host = room.members.get(room.host_id)
            out.append({
                "id": room.id, "name": room.name, "creator": host.name if host else "",
                "playerCount": len(room.seats), "maxPlayers": rules.MAX_PLAYERS,
                "status": "in_progress" if room.status == "playing" else "waiting",
                "spectatorCount": len([m for m in room.members.values() if m.role == "spectator"]),
            })
        return out

    def snapshot(self, room: Room, viewer: str, now: float) -> dict:
        game = room.game
        me = room.members.get(viewer)
        players = []
        order = [s.id for s in game.seats] if game and room.status == "playing" else list(room.seats)
        for pid in order:
            member = room.members.get(pid)
            seat = game.seat(pid) if game else None
            players.append({
                "id": pid,
                "name": room.names.get(pid, "Someone"),
                "is_bot": pid in room.bot_ids,
                "present": member is not None,
                "connected": pid in room.bot_ids or self.is_connected(pid),
                "cards": seat.cards if seat else 1,
                "out": bool(seat and seat.out) if room.status == "playing" else False,
                "out_reason": seat.out_reason if seat and room.status == "playing" else None,
                "last_bet": seat.last_bet if seat and room.status == "playing" else None,
                "ready": bool(game and pid in game.ready),
            })
        spectators = [{"id": m.id, "name": m.name, "connected": self.is_connected(m.id)}
                      for m in room.members.values() if m.role == "spectator"]
        snap = {
            "v": room.version,
            "server_time": int(now * 1000),
            "room": {"id": room.id, "name": room.name, "host_id": room.host_id, "status": room.status,
                     "max_players": rules.MAX_PLAYERS, "max_hand": room.settings.max_hand,
                     "games_played": room.games_played, "autoplay": room.autoplay},
            "me": {"id": viewer, "role": me.role if me else "spectator", "is_host": room.host_id == viewer},
            "players": players,
            "spectators": spectators,
            "game": None,
            "log": room.log[-SNAPSHOT_LOG:],
        }
        if game is not None:
            final_seats = {s.id: s for s in game.seats}
            if room.status == "finished":
                # Show the final table, not the lobby seating.
                snap["final"] = [{"id": s.id, "name": room.names.get(s.id, "Someone"), "cards": s.cards,
                                  "out": s.out, "out_reason": s.out_reason} for s in game.seats]
            my_seat = final_seats.get(viewer)
            snap["game"] = {
                "deal_no": game.deal_no,
                "turn_seq": game.turn_seq,
                "phase": game.phase,
                "turn_id": game.current_id,
                "deadline": int(game.deadline * 1000) if game.deadline else None,
                "phase_started": int(game.turn_started_at * 1000),
                "turn_seconds": game.settings.turn_seconds,
                "reveal_seconds": game.settings.reveal_seconds,
                "bets": list(game.bets),
                "last_bet": game.last_bet,
                "bettor_id": game.last_bettor,
                "cards_in_play": len(game.cards_in_play()) if game.phase != OVER else 0,
                "my_hand": list(my_seat.hand) if my_seat and not my_seat.out and game.phase != OVER else [],
                "reveal": game.reveal if game.phase in (REVEAL, OVER) else None,
                "winner_id": game.winner,
                "ready_ids": sorted(game.ready),
            }
        return snap

    # ----- persistence ---------------------------------------------------

    def room_to_dict(self, room: Room, now: float) -> dict:
        return {
            "saved_at": now,
            "id": room.id, "name": room.name, "host_id": room.host_id, "created_at": room.created_at,
            "settings": room.settings.to_dict(),
            "members": [vars(m) for m in room.members.values()],
            "seats": room.seats, "game": room.game.to_dict() if room.game else None,
            "names": room.names, "bot_ids": sorted(room.bot_ids), "log": room.log, "log_seq": room.log_seq,
            "version": room.version, "games_played": room.games_played, "autoplay": room.autoplay,
        }

    def room_from_dict(self, d: dict, now: float) -> Room:
        room = Room(id=d["id"], name=d["name"], host_id=d["host_id"], created_at=d["created_at"],
                    settings=Settings.from_dict(d.get("settings", {})))
        room.members = OrderedDict((m["id"], Member(**m)) for m in d["members"])
        room.seats = list(d["seats"])
        room.names = dict(d["names"])
        room.bot_ids = set(d["bot_ids"])
        room.log, room.log_seq = list(d["log"]), d["log_seq"]
        room.version, room.games_played = d["version"] + 1, d.get("games_played", 0)
        room.autoplay = d.get("autoplay", False)
        if d["game"]:
            room.game = Game.from_dict(d["game"], rng=random.Random(self.rng.random()))
            # Time spent while the server was down should not count against anyone.
            pause = max(0.0, now - d.get("saved_at", now))
            room.game.turn_started_at += pause
            if room.game.deadline is not None:
                room.game.deadline += pause
        return room

    def profile_to_dict(self, p: Profile) -> dict:
        return {"id": p.id, "token": p.token, "name": p.name, "room_id": p.room_id}

    def restore(self, profiles: List[dict], rooms: List[dict], now: float) -> None:
        for d in profiles:
            p = Profile(id=d["id"], token=d["token"], name=d["name"], room_id=d.get("room_id"),
                        connected=False, disconnected_at=now)
            self.profiles[p.id] = p
            self.by_token[p.token] = p.id
        for d in rooms:
            room = self.room_from_dict(d, now)
            self.rooms[room.id] = room
        for p in self.profiles.values():
            if p.room_id and (p.room_id not in self.rooms or p.id not in self.rooms[p.room_id].members):
                p.room_id = None
