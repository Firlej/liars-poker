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
import re
import secrets
import string
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import bots, names, rules
from .engine import BETTING, OVER, REVEAL, Game, GameError, Settings

#: Seconds a bot "thinks" before moving, so humans can follow.
BOT_DELAY = 1.4
#: Reveal shown for this long before the next deal when no connected human needs to confirm.
UNATTENDED_REVEAL = 4.0
#: A finished bot match starts again after this long.
AUTOPLAY_RESTART_AFTER = 8.0
MAX_BOTS_MATCH = 8
#: Bot strength, weakest first. Every bot today plays the same way, so all are "easy".
BOT_LEVELS = ("easy", "medium", "hard")
BOT_LEVEL = "easy"
#: Per-player counts kept during a game for the stats (see ``_count``).
TALLY_KEYS = ("bets", "bluffs", "caught", "checks", "called_right", "called_wrong", "deals_lost", "timeouts")
#: Moves kept per game for the dashboard's "last rounds".
LAST_MOVES = 12
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

#: Room codes are typed by hand, so the alphabet leaves out look-alikes (I, L, O, 0, 1).
ROOM_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ROOM_CODE_LENGTH = 6
#: Bot names: fun, but still plainly robots, since the table shows no other bot mark.
BOT_NAMES = (
    "Bluffotron", "Robo Rex", "Beep Boop", "Ace-9000", "Tin Tony", "Sprocket",
    "Glitchy", "Wobblebot", "R2-Deal", "Clanky", "Pixel", "Chip", "Gizmo",
    "Bolt", "Nano", "Turbo", "Dr. Fibbs", "Bleep", "Rusty", "Byte", "Widget",
    "Zappy", "Sparky", "Botley", "Robo Rita", "Fibbot", "Circuit", "Gadget",
    "Dealbot", "Unit 7",
)
#: A new room is called "The <adjective> <character>", like an old pub.
ROOM_NAME_ADJECTIVES = (
    "Sneaky", "Shifty", "Crooked", "Sly", "Smug", "Fibbing", "Bluffing",
    "Two-Faced", "Sweaty", "Nervous", "Lucky", "Shady", "Cheeky", "Wily",
    "Slippery", "Stone-Faced", "Dodgy", "Grumpy", "Jolly", "Tipsy", "Sleepy",
    "Cunning", "Brazen", "Fishy", "Wobbly", "Innocent", "Honest", "Devious",
    "Suspicious", "Daring", "Mischievous", "Glum", "Fancy", "Rowdy",
)
ROOM_NAME_CHARACTERS = (
    "Badger", "Fox", "Weasel", "Raccoon", "Ferret", "Llama", "Walrus", "Goose",
    "Penguin", "Octopus", "Crow", "Magpie", "Possum", "Otter", "Toad", "Hyena",
    "Lobster", "Pelican", "Moose", "Flamingo", "Ace", "Joker", "Jack", "Queen",
    "King", "Card Shark", "Gambler", "Pirate", "Duchess", "Baron", "Cowboy",
    "Magician", "Detective", "Grandma",
)

#: Quick reactions anyone in a room can send: animated emoji and short phrases.
#: The app owns how each one looks; the server only checks the id.
REACTIONS = frozenset({
    "thumbs", "laugh", "cry", "angry", "shock", "think", "cool", "clap",
    "thanks", "good_game", "well_played", "hurry", "nice_bluff", "close",
    "liar", "oops", "sorry", "again",
    "lying", "poker_face", "smirk", "wink", "shush", "eyes", "sweat", "facepalm",
    "mind_blown", "skull", "clown", "devil", "fire", "party", "crown", "sleepy",
    "tongue", "loser",
})
#: Seconds between two reactions from the same player.
REACTION_COOLDOWN = 1.0
#: Why a player can be reported (App Store guideline 1.2).
REPORT_REASONS = frozenset({"offensive_name", "abusive_reactions", "cheating", "other"})
#: One report per reporter and player in this time, and at most this many per hour.
REPORT_AGAIN_AFTER = 600.0
REPORTS_PER_HOUR = 10
REPORT_NOTE_LIMIT = 300


DEFAULT_NAME = "Player"


def clean_name(raw: object) -> str:
    name = raw if isinstance(raw, str) else ""
    name = " ".join("".join(ch for ch in name if ch.isprintable()).split())
    return name[:NAME_LIMIT] or DEFAULT_NAME


@dataclass
class Profile:
    id: str
    token: str
    name: str
    room_id: Optional[str] = None
    connected: bool = False
    disconnected_at: Optional[float] = None
    #: Set by the admin: the player can't change their name.
    locked: bool = False
    locked_at: Optional[float] = None
    #: Names the admin took away from this player; the app may keep sending them.
    banned_names: List[str] = field(default_factory=list)


@dataclass
class Member:
    id: str
    name: str
    is_bot: bool = False
    role: str = "player"  # "player" | "spectator"
    #: Bots only: one of ``BOT_LEVELS``.
    level: Optional[str] = None


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
    #: When the current game started, for the stats.
    game_started_at: Optional[float] = None
    #: This game's counts per player, and the current deal's bets (for spotting bluffs).
    tally: Dict[str, Dict[str, int]] = field(default_factory=dict)
    deal_bets: List[dict] = field(default_factory=list)
    pending_check: Optional[dict] = None
    #: The current deal number, who went out in which deal, and the last few moves.
    deal_seen: int = 0
    out_order: List[dict] = field(default_factory=list)
    last_moves: List[dict] = field(default_factory=list)
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
        #: When each player last sent a reaction.
        self.reacted_at: Dict[str, float] = {}
        self.dirty: set = set()
        #: Stats events for the server to save (see ``record``).
        self.stats: List[dict] = []
        #: Names the filter refused, for the moderation page: {"t", "player", "name"}.
        self.refused: List[dict] = []
        #: New player reports for the server to save, and when each player last reported whom.
        self.reports: List[dict] = []
        self.reported_at: Dict[str, Dict[str, float]] = {}

    # ----- stats ---------------------------------------------------------

    def record(self, type_: str, now: float, player: Optional[str] = None,
               room: Optional[str] = None, **data) -> None:
        """Note something for the stats dashboard. Only counts and random ids:
        no names, no cards, no bets."""
        self.stats.append({"t": now, "type": type_, "player": player, "room": room, "data": data})

    def _game_key(self, room: Room) -> str:
        return f"{room.id}.{room.games_played}.{int(room.game_started_at or 0)}"

    def _record_game_end(self, room: Room, now: float, finished: bool) -> None:
        """One ``game_end`` for the game, and one ``player_game`` per real person in it."""
        game = room.game
        humans = [s for s in game.seats if s.id not in room.bot_ids]
        key = self._game_key(room)
        started = room.game_started_at if room.game_started_at is not None else now
        winner = game.winner if finished else None
        level = self._bot_level(room, [s.id for s in game.seats])
        self.record("game_end", now, room=room.id, game=key, finished=finished, table=room.name,
                    seconds=round(now - started, 1), deals=game.deal_no,
                    humans=len(humans), bots=len(game.seats) - len(humans), bot_match=room.autoplay,
                    bot_level=level, winner=winner, winner_is_bot=winner in room.bot_ids if winner else None,
                    left=sum(1 for s in humans if s.out_reason in ("left", "kicked")),
                    bluffs=sum(t.get("bluffs", 0) for t in room.tally.values()),
                    checks=sum(t.get("checks", 0) for t in room.tally.values()),
                    timeouts=sum(t.get("timeouts", 0) for t in room.tally.values()),
                    standing=self._standing(room, winner),
                    moves=[{**m, "id": None if m["id"] in room.bot_ids else m["id"]} for m in room.last_moves])
        for seat in humans:
            counts = room.tally.get(seat.id, {})
            self.record("player_game", now, player=seat.id, room=room.id, game=key, finished=finished,
                        won=seat.id == winner, out=seat.out_reason, seconds=round(now - started, 1),
                        players=len(game.seats), bots=len(game.seats) - len(humans), bot_level=level,
                        **{k: counts.get(k, 0) for k in TALLY_KEYS})

    def _remember_move(self, room: Room, move: dict) -> None:
        room.last_moves.append(move)
        del room.last_moves[:-LAST_MOVES]

    def _standing(self, room: Room, winner: Optional[str]) -> List[dict]:
        """Everyone in the game, best first: the winner, then who went out last."""
        game = room.game
        out = {o["id"]: o for o in room.out_order}
        order = [s.id for s in game.seats if s.id == winner]
        order += [s.id for s in game.seats if s.id != winner and s.id not in out]  # still in (abandoned)
        order += [o["id"] for o in reversed(room.out_order) if o["id"] in {s.id for s in game.seats}]
        rows = []
        for pid in dict.fromkeys(order):
            bot = pid in room.bot_ids
            rows.append({"id": None if bot else pid, "bot": bot, "out_deal": out.get(pid, {}).get("deal"),
                         "reason": out.get(pid, {}).get("reason"),
                         "bluffs": room.tally.get(pid, {}).get("bluffs", 0)})
        return rows

    def _bot_level(self, room: Room, seats: List[str]) -> Optional[str]:
        """The strongest bot at the table, or None without bots."""
        levels = [(room.members[pid].level if pid in room.members else None) or BOT_LEVEL
                  for pid in seats if pid in room.bot_ids]
        return max(levels, key=BOT_LEVELS.index) if levels else None

    def _tally(self, room: Room, pid: Optional[str], key: str) -> None:
        if pid:
            counts = room.tally.setdefault(pid, {})
            counts[key] = counts.get(key, 0) + 1

    def _count(self, room: Room, event: dict) -> None:
        """Turn a game event into per-player counts. A bluff is a bet that was not
        on the table when the deal was revealed; moves made by the timer don't count."""
        type_ = event["type"]
        if type_ == "new_deal":
            room.deal_seen = event.get("deal_no", room.deal_seen)
        if type_ == "player_eliminated":
            room.out_order.append({"id": event.get("player_id"), "deal": room.deal_seen,
                                   "reason": event.get("reason")})
        if type_ in ("new_deal", "deal_voided"):
            room.deal_bets, room.pending_check = [], None
        elif type_ == "bet":
            room.deal_bets.append({"player_id": event["player_id"], "bet": event["bet"],
                                   "auto": bool(event.get("auto"))})
            self._remember_move(room, {"deal": room.deal_seen, "id": event["player_id"], "bet": event["bet"],
                                       "auto": bool(event.get("auto"))})
            if not event.get("auto"):
                self._tally(room, event["player_id"], "bets")
        elif type_ == "turn_timeout":
            self._tally(room, event.get("player_id"), "timeouts")
        elif type_ == "check":
            room.pending_check = {"checker": event["player_id"], "bettor": event.get("bettor_id"),
                                  "auto": bool(event.get("auto"))}
            if not event.get("auto"):
                self._tally(room, event["player_id"], "checks")
        elif type_ == "deal_result":
            cards = [card for hand in (event.get("hands") or {}).values() for card in hand]
            for bet in room.deal_bets:
                if not bet["auto"] and not rules.bet_holds(bet["bet"], cards):
                    self._tally(room, bet["player_id"], "bluffs")
            check = room.pending_check or {}
            if check:
                self._remember_move(room, {"deal": room.deal_seen, "id": check["checker"], "check": True,
                                           "held": bool(event["held"]), "auto": check["auto"]})
            if not event["held"]:
                self._tally(room, check.get("bettor"), "caught")
            if check and not check["auto"]:
                self._tally(room, check["checker"], "called_wrong" if event["held"] else "called_right")
            self._tally(room, event.get("loser_id"), "deals_lost")
            room.deal_bets, room.pending_check = [], None

    # ----- identity ------------------------------------------------------

    def hello(self, token: object, name: object, now: float) -> Profile:
        """Find the player for ``token`` or register a new one."""
        pid = self.by_token.get(token) if isinstance(token, str) else None
        profile = self.profiles.get(pid) if pid else None
        wanted = clean_name(name)
        allowed = names.is_allowed(wanted)
        if profile is None:
            pid = "p_" + secrets.token_hex(8)
            profile = Profile(id=pid, token=secrets.token_urlsafe(24), name=wanted if allowed else DEFAULT_NAME)
            self.profiles[pid] = profile
            self.by_token[profile.token] = pid
        elif (isinstance(name, str) and name.strip() and allowed and not profile.locked
              and not self._banned(profile, wanted)):
            profile.name = wanted
        if not allowed:
            self._refuse(profile.id, wanted, now)
        self.dirty.add("profiles")
        return profile

    def _banned(self, profile: Profile, name: str) -> bool:
        return name.casefold() in (n.casefold() for n in profile.banned_names)

    def _refuse(self, pid: str, name: str, now: float) -> None:
        self.record("name_blocked", now, player=pid)
        self.refused.append({"t": now, "player": pid, "name": name})

    def rename(self, pid: str, name: object, now: float) -> Profile:
        """Change a player's name. An offensive name is refused and the old one kept."""
        profile = self._profile(pid)
        wanted = clean_name(name)
        if profile.locked:
            raise LobbyError("name_locked")
        if not names.is_allowed(wanted):
            self._refuse(pid, wanted, now)
            raise LobbyError("name_not_allowed")
        if self._banned(profile, wanted):
            raise LobbyError("name_not_allowed")
        profile.name = wanted
        self.dirty.add("profiles")
        return profile

    # ----- admin ---------------------------------------------------------

    def admin_rename(self, pid: str, name: str, now: float) -> str:
        """Give a player a new name (the admin's "Reset name"). Their old name is
        refused from them from now on. Returns the old name."""
        profile = self._profile(pid)
        old = profile.name
        if old != DEFAULT_NAME and not self._banned(profile, old):
            profile.banned_names.append(old)
        profile.name = clean_name(name)
        room = self.rooms.get(profile.room_id or "")
        if room and pid in room.members:
            member = room.members[pid]
            member.name = ""  # so the old name doesn't count as taken
            member.name = self._unique_name(room, profile.name)
            room.names[pid] = member.name
            room.touch()
            self.list_version += 1
        self.dirty.add("profiles")
        return old

    def set_locked(self, pid: str, locked: bool, now: float) -> None:
        profile = self._profile(pid)
        profile.locked = locked
        profile.locked_at = now if locked else None
        self.dirty.add("profiles")

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
            code = "".join(self.rng.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))
            if code not in self.rooms:
                return code

    def _new_room_name(self) -> str:
        taken = {room.name for room in self.rooms.values()}
        name = ""
        for _ in range(20):  # a few tries for a name no open room is using
            name = f"The {self.rng.choice(ROOM_NAME_ADJECTIVES)} {self.rng.choice(ROOM_NAME_CHARACTERS)}"
            if name not in taken:
                break
        return name

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

    def create_room(self, pid: str, now: float, bot_match: bool = False) -> Room:
        profile = self._profile(pid)
        self.leave(pid, now)
        room = Room(id=self._new_room_id(), name=self._new_room_name(), host_id=pid, created_at=now)
        self.rooms[room.id] = room
        self._add_member(room, profile, now)
        self.list_version += 1
        self.record("room_created", now, player=pid, room=room.id, bot_match=bot_match)
        return room

    def join_room(self, pid: str, room_id: object, now: float) -> Room:
        profile = self._profile(pid)
        # A typed code may carry spaces, dashes or lower case letters.
        code = re.sub(r"[^A-Za-z0-9]", "", room_id).upper() if isinstance(room_id, str) else None
        room = self.rooms.get(code) if code else None
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
            self._delete_room(room, now)
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

    def _delete_room(self, room: Room, now: float) -> None:
        if room.game is not None and room.game.phase != OVER:
            self._record_game_end(room, now, finished=False)
        self.record("room_closed", now, room=room.id, games=room.games_played, bot_match=room.autoplay)
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
        taken = {m.name for m in room.members.values()}
        free = [name for name in BOT_NAMES if name not in taken]
        if free:
            name = self.rng.choice(free)
        else:
            n = 1
            while f"Bot {n}" in taken:
                n += 1
            name = f"Bot {n}"
        bot = Member(id="b_" + secrets.token_hex(6), name=name, is_bot=True, level=BOT_LEVEL)
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

    def react(self, pid: str, reaction: object, now: float) -> None:
        """Show a quick reaction to everyone in the room. Not part of the room state."""
        room = self._room_of(pid)
        if reaction not in REACTIONS:
            raise LobbyError("bad_reaction")
        if now - self.reacted_at.get(pid, float("-inf")) < REACTION_COOLDOWN:
            raise LobbyError("rate_limited")
        self.reacted_at[pid] = now
        payload = {"room_id": room.id, "player_id": pid, "reaction": reaction, "ts": int(now * 1000)}
        for member in room.members.values():
            if not member.is_bot:
                self.notices.append((member.id, "reaction", payload))

    def report(self, pid: str, target: object, reason: object, note: object, now: float) -> dict:
        """Report someone in your room to the admin. Keeps the name they had at the
        time, since an offensive name is the most likely reason."""
        room = self._room_of(pid)
        if not isinstance(target, str) or target == pid or target not in room.names or target in room.bot_ids:
            raise LobbyError("player_not_found")
        if reason not in REPORT_REASONS:
            raise LobbyError("bad_request")
        mine = self.reported_at.setdefault(pid, {})
        for who, at in list(mine.items()):
            if now - at >= 3600:
                del mine[who]
        if now - mine.get(target, float("-inf")) < REPORT_AGAIN_AFTER:
            raise LobbyError("already_reported")
        if len(mine) >= REPORTS_PER_HOUR:
            raise LobbyError("rate_limited")
        mine[target] = now
        profile = self.profiles.get(target)
        report = {
            "t": now, "reporter": pid, "target": target, "room": room.id, "reason": reason,
            "name": profile.name if profile else room.names[target],
            "note": " ".join(note.split())[:REPORT_NOTE_LIMIT] if isinstance(note, str) else "",
        }
        self.reports.append(report)
        self.record("report", now, player=target, room=room.id, reason=reason)
        return report

    def shuffle_seats(self, pid: str, now: float) -> None:
        room = self._room_of(pid)
        self._require_host(room, pid)
        self._require_not_playing(room)
        self.rng.shuffle(room.seats)
        room.touch()

    def set_max_hand(self, pid: str, value: object, now: float) -> None:
        """Choose how many cards a player may hold before they are out, or None
        for auto. Kept as chosen; a game lowers it if its table cannot fit it."""
        room = self._room_of(pid)
        self._require_host(room, pid)
        self._require_not_playing(room)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool)
                                  or not 1 <= value <= rules.MAX_HAND_CHOICE):
            raise LobbyError("bad_max_hand")
        if room.settings.max_hand == value:
            return
        room.settings.max_hand = value
        self._log(room, now, "max_hand_changed", pid, max_hand=value,
                  effective=rules.hand_limit(len(room.seats), value))
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
        room.game_started_at = now
        room.moves = {}
        room.tally, room.deal_bets, room.pending_check = {}, [], None
        room.deal_seen, room.out_order, room.last_moves = 0, [], []
        bots_n = sum(1 for pid in seats if pid in room.bot_ids)
        self.record("game_start", now, room=room.id, game=self._game_key(room), table=room.name,
                    humans=len(seats) - bots_n, bots=bots_n, bot_match=room.autoplay,
                    bot_level=self._bot_level(room, seats), max_hand=room.game.settings.max_hand)
        self._log(room, now, "game_start", None, players=list(seats), max_hand=room.game.settings.max_hand)
        room.game._start_deal(now)
        self._drain(room, now)
        room.touch()
        self.list_version += 1

    def create_bot_match(self, pid: str, bots_count: object, now: float) -> Room:
        """A room where only bots play and the caller watches. It starts at once
        and starts again after every game, to see the game run (and catch bugs)."""
        n = bots_count if isinstance(bots_count, int) and not isinstance(bots_count, bool) else 4
        n = max(2, min(MAX_BOTS_MATCH, n))
        room = self.create_room(pid, now, bot_match=True)
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
            self._delete_room(room, now)
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
            self._count(room, event)
            event = dict(event)
            type_ = event.pop("type")
            pid = event.pop("player_id", None) or event.get("starter_id") or event.get("loser_id")
            self._log(room, now, type_, pid, **event)
            if type_ == "game_won":
                self.list_version += 1
                self._record_game_end(room, now, finished=True)

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
        seated = len(room.seats)
        next_limit = {
            "choice": room.settings.max_hand,  # None = auto
            "value": rules.hand_limit(seated, room.settings.max_hand),
            "auto": rules.auto_hand_limit(seated),
            "max": rules.deck_hand_limit(seated),
            "max_choice": rules.MAX_HAND_CHOICE,
        }
        snap = {
            "v": room.version,
            "server_time": int(now * 1000),
            "room": {"id": room.id, "name": room.name, "host_id": room.host_id, "status": room.status,
                     "max_players": rules.MAX_PLAYERS,
                     # The limit of the game on screen, or of the next one in the lobby.
                     "max_hand": game.settings.max_hand if game else next_limit["value"],
                     "hand_limit": next_limit,
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
            # Kept apart from "settings": rooms saved before hosts could choose hold 3 there.
            "max_hand_choice": room.settings.max_hand,
            "members": [vars(m) for m in room.members.values()],
            "seats": room.seats, "game": room.game.to_dict() if room.game else None,
            "names": room.names, "bot_ids": sorted(room.bot_ids), "log": room.log, "log_seq": room.log_seq,
            "version": room.version, "games_played": room.games_played, "autoplay": room.autoplay,
            "game_started_at": room.game_started_at, "tally": room.tally, "deal_bets": room.deal_bets,
            "pending_check": room.pending_check, "deal_seen": room.deal_seen, "out_order": room.out_order,
            "last_moves": room.last_moves,
        }

    def room_from_dict(self, d: dict, now: float) -> Room:
        room = Room(id=d["id"], name=d["name"], host_id=d["host_id"], created_at=d["created_at"],
                    settings=Settings.from_dict(d.get("settings", {})))
        room.settings.max_hand = d.get("max_hand_choice")
        room.members = OrderedDict((m["id"], Member(**m)) for m in d["members"])
        room.seats = list(d["seats"])
        room.names = {pid: n if names.is_allowed(n) else DEFAULT_NAME for pid, n in d["names"].items()}
        for member in room.members.values():
            member.name = room.names.get(member.id, member.name)
        room.bot_ids = set(d["bot_ids"])
        room.log, room.log_seq = list(d["log"]), d["log_seq"]
        room.version, room.games_played = d["version"] + 1, d.get("games_played", 0)
        room.autoplay = d.get("autoplay", False)
        room.game_started_at = d.get("game_started_at")
        room.tally = d.get("tally") or {}
        room.deal_bets = d.get("deal_bets") or []
        room.pending_check = d.get("pending_check")
        room.deal_seen = d.get("deal_seen", 0)
        room.out_order = d.get("out_order") or []
        room.last_moves = d.get("last_moves") or []
        if d["game"]:
            room.game = Game.from_dict(d["game"], rng=random.Random(self.rng.random()))
            # Time spent while the server was down should not count against anyone.
            pause = max(0.0, now - d.get("saved_at", now))
            room.game.turn_started_at += pause
            if room.game.deadline is not None:
                room.game.deadline += pause
        return room

    def profile_to_dict(self, p: Profile) -> dict:
        return {"id": p.id, "token": p.token, "name": p.name, "room_id": p.room_id,
                "locked": p.locked, "locked_at": p.locked_at, "banned_names": p.banned_names}

    def restore(self, profiles: List[dict], rooms: List[dict], now: float) -> None:
        for d in profiles:
            # Names saved before the filter existed are checked once more.
            name = d["name"] if names.is_allowed(d["name"]) else DEFAULT_NAME
            p = Profile(id=d["id"], token=d["token"], name=name, room_id=d.get("room_id"),
                        connected=False, disconnected_at=now, locked=bool(d.get("locked")),
                        locked_at=d.get("locked_at"), banned_names=list(d.get("banned_names") or []))
            self.profiles[p.id] = p
            self.by_token[p.token] = p.id
        for d in rooms:
            room = self.room_from_dict(d, now)
            self.rooms[room.id] = room
        for p in self.profiles.values():
            if p.room_id and (p.room_id not in self.rooms or p.id not in self.rooms[p.room_id].members):
                p.room_id = None
