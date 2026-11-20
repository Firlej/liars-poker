import random

import pytest

from server import rooms as R
from server.engine import BETTING, OVER, REVEAL
from server.rooms import Lobby, LobbyError


@pytest.fixture
def lobby():
    return Lobby(rng=random.Random(5))


def join(lobby, name, now=0.0):
    p = lobby.hello(None, name, now)
    lobby.set_connected(p.id, True, now)
    return p.id


def table(lobby, *names, start=True):
    host = join(lobby, names[0])
    room = lobby.create_room(host, 0)
    others = [join(lobby, n) for n in names[1:]]
    for pid in others:
        lobby.join_room(pid, room.id, 0)
    if start:
        lobby.start_game(host, 0)
    return room, [host, *others]


def act(lobby, room, pid, type_, bet=None, move_id=None, now=1.0):
    payload = {"type": type_, "turn_seq": room.game.turn_seq, "bet": bet}
    if move_id:
        payload["move_id"] = move_id
    return lobby.act(pid, payload, now)


def test_hello_reuses_identity_by_token(lobby):
    a = lobby.hello(None, "Ada", 0)
    again = lobby.hello(a.token, "Ada L", 1)
    assert again.id == a.id and again.name == "Ada L"
    other = lobby.hello("forged", "Eve", 1)
    assert other.id != a.id


def test_names_are_cleaned_and_unique_per_room(lobby):
    assert R.clean_name("  a\x00b   c ") == "ab c"
    assert R.clean_name("") == "Player" and R.clean_name(None) == "Player"
    assert len(R.clean_name("x" * 50)) == 20
    room, (a, b) = table(lobby, "Ada", "ada", start=False)
    assert [m.name for m in room.members.values()] == ["Ada", "ada 2"]


def test_room_lifecycle_and_list(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob", start=False)
    [entry] = lobby.room_list()
    assert entry["playerCount"] == 2 and entry["status"] == "waiting" and entry["creator"] == "Ada"
    with pytest.raises(LobbyError, match="not_host"):
        lobby.start_game(b, 0)
    lobby.start_game(a, 0)
    assert lobby.room_list()[0]["status"] == "in_progress"


def test_need_two_players(lobby):
    a = join(lobby, "Ada")
    room = lobby.create_room(a, 0)
    with pytest.raises(LobbyError, match="not_enough_players"):
        lobby.start_game(a, 0)
    lobby.add_bot(a, 0)
    lobby.stand(a, 0)
    with pytest.raises(LobbyError, match="not_enough_players"):
        lobby.start_game(a, 0)
    lobby.add_bot(a, 0)
    lobby.start_game(a, 0)  # bots only, the host watches
    assert room.game.phase == BETTING


@pytest.mark.parametrize("count,expected", [(4, 4), (1, 2), (99, 8), ("x", 4), (True, 4)])
def test_bot_match_clamps_size(lobby, count, expected):
    a = join(lobby, "Ada")
    room = lobby.create_bot_match(a, count, 0)
    assert len(room.game.seats) == expected
    assert room.members[a].role == "spectator" and room.host_id == a
    assert lobby.room_list() == []


def test_bot_matches_run_many_games_without_problems():
    """Soak test: many bot games, every state checked against the engine invariants."""
    for seed in range(6):
        lobby = Lobby(rng=random.Random(seed))
        a = join(lobby, "Watcher")
        room = lobby.create_bot_match(a, 2 + seed, 0)
        now, games = 0.0, 0
        while games < 3 and now < 50_000:
            now += 0.5
            lobby.tick(now)
            if room.game.phase == OVER and room.finished_at is not None and now - room.finished_at < 0.5:
                games += 1
        assert games == 3, f"seed {seed}: only {games} games finished"
        assert room.games_played >= 3
        assert lobby.problems == [], lobby.problems[:1]
        snap = lobby.snapshot(room, a, now)
        assert snap["game"]["my_hand"] == []


def test_problems_are_recorded(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    room.game.seats[0].hand.append("A♠")  # corrupt the state
    room.game.seats[1].hand = list(room.game.seats[0].hand)
    act(lobby, room, room.game.current_id, "bet", "pair_9")
    assert lobby.problems and lobby.problems[0]["kind"] == "invariant"
    assert lobby.problems[0]["room_id"] == room.id


def test_room_capacity_and_late_joiners_spectate(lobby):
    room, ids = table(lobby, *[f"P{i}" for i in range(8)], start=False)
    late = join(lobby, "Late")
    lobby.join_room(late, room.id, 0)
    assert room.members[late].role == "spectator"
    with pytest.raises(LobbyError, match="room_full"):
        lobby.add_bot(ids[0], 0)
    lobby.start_game(ids[0], 0)
    later = join(lobby, "Later")
    lobby.join_room(later, room.id, 0)
    assert room.members[later].role == "spectator"
    assert room.game.seat(later) is None


def test_unknown_room(lobby):
    a = join(lobby, "Ada")
    with pytest.raises(LobbyError, match="room_not_found"):
        lobby.join_room(a, "NOPE", 0)
    with pytest.raises(LobbyError, match="room_not_found"):
        lobby.join_room(a, {"x": 1}, 0)


def test_rejoin_same_room_changes_nothing(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    version = room.version
    lobby.join_room(b, room.id, 1)
    assert room.version == version and room.game.seat(b) is not None


def test_room_codes_are_six_unambiguous_characters_and_join_forgives_typing(lobby):
    host = join(lobby, "Ada")
    room = lobby.create_room(host, 0)
    assert len(room.id) == 6 and set(room.id) <= set(R.ROOM_CODE_ALPHABET)
    assert not set("ILO01") & set(R.ROOM_CODE_ALPHABET)
    bob = join(lobby, "Bob")
    typed = f" {room.id[:3].lower()}-{room.id[3:]} "
    assert lobby.join_room(bob, typed, 0) is room
    with pytest.raises(LobbyError):
        lobby.join_room(join(lobby, "Cy"), "", 0)


def test_one_room_at_a_time(lobby):
    room1, (a, b) = table(lobby, "Ada", "Bob", start=False)
    room2 = lobby.create_room(b, 0)
    assert b not in room1.members and b in room2.members


def test_moves_validate_turn_seq_and_dedupe(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    first = room.game.current_id
    second = b if first == a else a
    stale = {"type": "bet", "bet": "pair_9", "turn_seq": room.game.turn_seq - 1, "move_id": "m0"}
    assert lobby.act(first, stale, 1) == {"ok": False, "error": "stale"}
    assert act(lobby, room, first, "bet", "pair_9", move_id="m1") == {"ok": True}
    seq = room.game.turn_seq
    # A resend (e.g. after a reconnect) returns the same answer and does not move again.
    assert lobby.act(first, {"type": "bet", "bet": "pair_9", "turn_seq": 1, "move_id": "m1"}, 2) == {"ok": True}
    assert room.game.turn_seq == seq
    assert act(lobby, room, first, "bet", "pair_T")["error"] == "not_your_turn"
    assert act(lobby, room, second, "bet", "pair_9")["error"] == "bet_too_low"
    assert act(lobby, room, second, "dance")["error"] == "bad_request"
    with pytest.raises(LobbyError):
        lobby.act(second, "garbage", 1)


def test_reveal_waits_for_connected_humans_then_deals(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    g = room.game
    p1 = g.current_id
    p2 = b if p1 == a else a
    act(lobby, room, p1, "bet", "quad_A")
    act(lobby, room, p2, "check")
    assert g.phase == REVEAL
    act(lobby, room, p1, "ready")
    assert g.phase == REVEAL
    act(lobby, room, p2, "ready")
    assert g.phase == BETTING and g.deal_no == 2


def test_reveal_does_not_wait_for_disconnected_player(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    g = room.game
    p1, p2 = g.current_id, (b if g.current_id == a else a)
    act(lobby, room, p1, "bet", "quad_A")
    act(lobby, room, p2, "check")
    lobby.set_connected(p2, False, 2)
    act(lobby, room, p1, "ready", now=2)
    assert g.phase == BETTING


def test_reveal_times_out(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    g = room.game
    p1, p2 = g.current_id, (b if g.current_id == a else a)
    act(lobby, room, p1, "bet", "quad_A")
    act(lobby, room, p2, "check")
    lobby.tick(1 + g.settings.reveal_seconds - 0.1)
    assert g.phase == REVEAL
    lobby.tick(1 + g.settings.reveal_seconds)
    assert g.phase == BETTING


def test_turn_timeout_auto_plays(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    g = room.game
    first = g.current_id
    lobby.tick(59)
    assert g.bets == []
    changed = lobby.tick(60)
    assert changed == [room]
    assert g.bets[0]["player_id"] == first
    assert any(e["type"] == "turn_timeout" for e in room.log)


def test_disconnected_player_keeps_seat_then_forfeits(lobby):
    room, (a, b, c) = table(lobby, "Ada", "Bob", "Cy")
    lobby.set_connected(c, False, 0)
    lobby.tick(R.FORFEIT_AFTER - 1)
    assert not room.game.seat(c).out
    lobby.set_connected(c, True, R.FORFEIT_AFTER - 1)  # back just in time
    lobby.tick(R.FORFEIT_AFTER + 10)
    assert not room.game.seat(c).out
    lobby.set_connected(c, False, 200)
    lobby.tick(200 + R.FORFEIT_AFTER)
    assert room.game.seat(c).out and room.game.seat(c).out_reason == "left"
    assert c in room.members  # can come back and watch


def test_leave_mid_game_forfeits_and_host_moves(lobby):
    room, (a, b, c) = table(lobby, "Ada", "Bob", "Cy")
    lobby.leave(a, 1)
    assert a not in room.members and room.host_id in (b, c)
    assert room.game.seat(a).out
    assert room.game.phase == BETTING
    snap = lobby.snapshot(room, b, 1)
    assert [p["name"] for p in snap["players"]][0] == "Ada"  # history keeps the name


def test_last_human_leaving_closes_room(lobby):
    a = join(lobby, "Ada")
    room = lobby.create_room(a, 0)
    lobby.add_bot(a, 0)
    lobby.start_game(a, 0)
    lobby.leave(a, 1)
    assert room.id not in lobby.rooms
    assert lobby.profiles[a].room_id is None


def test_game_over_then_rematch(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    room.settings.max_hand = 1
    g = room.game
    g.settings.max_hand = 1
    p1, p2 = g.current_id, (b if g.current_id == a else a)
    for s in g.seats:
        s.hand = ["9♠"] if s.id == p1 else ["T♠"]
    act(lobby, room, p1, "bet", "quad_A")
    act(lobby, room, p2, "check")
    assert g.phase == OVER and g.winner == p2
    assert room.status == "finished"
    snap = lobby.snapshot(room, a, 2)
    assert snap["game"]["winner_id"] == p2 and snap["final"]
    lobby.start_game(a, 3)
    assert room.game is not g and room.game.phase == BETTING and room.games_played == 2


def test_bots_play_a_whole_game(lobby):
    a = join(lobby, "Ada")
    room = lobby.create_room(a, 0)
    for _ in range(3):
        lobby.add_bot(a, 0)
    lobby.stand(a, 0)
    lobby.sit(a, 0)
    lobby.start_game(a, 0)
    lobby.leave  # noqa
    now = 0.0
    # Ada never moves: she is auto-played on timeouts until she is out, bots finish the game.
    for _ in range(20000):
        now += 0.5
        lobby.tick(now)
        if room.game.phase == REVEAL:
            act(lobby, room, a, "ready", now=now)
        if room.game.phase == OVER:
            break
    assert room.game.phase == OVER and room.game.winner is not None


def test_kick_rules(lobby):
    room, (a, b, c) = table(lobby, "Ada", "Bob", "Cy")
    with pytest.raises(LobbyError, match="game_in_progress"):
        lobby.kick(a, b, 1)
    lobby.set_connected(b, False, 1)
    lobby.kick(a, b, 2)
    assert b not in room.members and room.game.seat(b).out
    assert (b, "kicked", {"room_id": room.id}) in lobby.notices
    with pytest.raises(LobbyError, match="not_host"):
        lobby.kick(c, a, 2)


def test_snapshot_hides_other_hands_until_reveal(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    spectator = join(lobby, "Spec")
    lobby.join_room(spectator, room.id, 0)
    sa = lobby.snapshot(room, a, 1)
    ss = lobby.snapshot(room, spectator, 1)
    assert len(sa["game"]["my_hand"]) == 1
    assert ss["game"]["my_hand"] == [] and ss["me"]["role"] == "spectator"
    assert sa["game"]["reveal"] is None
    import json
    assert room.game.seat(b).hand[0] not in json.dumps(sa["players"])
    g = room.game
    p1, p2 = g.current_id, (b if g.current_id == a else a)
    act(lobby, room, p1, "bet", "pair_9")
    act(lobby, room, p2, "check")
    ss = lobby.snapshot(room, spectator, 2)
    assert set(ss["game"]["reveal"]["hands"]) == {a, b}


def test_persistence_round_trip_pauses_clock(lobby):
    room, (a, b) = table(lobby, "Ada", "Bob")
    act(lobby, room, room.game.current_id, "bet", "pair_9", now=10)
    saved = lobby.room_to_dict(room, now=20)
    profiles = [lobby.profile_to_dict(p) for p in lobby.profiles.values()]
    fresh = Lobby()
    fresh.restore(profiles, [saved], now=1000)
    restored = fresh.rooms[room.id]
    assert restored.game.to_dict()["bets"] == room.game.to_dict()["bets"]
    assert restored.game.deadline == pytest.approx(room.game.deadline + 980)
    assert not fresh.is_connected(a)
    assert fresh.hello(lobby.profiles[a].token, "Ada", 1000).id == a
    assert fresh.profiles[a].room_id == room.id
