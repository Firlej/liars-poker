import random

import pytest

from server import rules
from server.engine import BETTING, OVER, REVEAL, Game, GameError, Settings


def make(n=3, seed=0, **settings):
    return Game([f"p{i}" for i in range(n)], now=0.0, rng=random.Random(seed), settings=Settings(**settings))


def rig(game, hands):
    """Give each seat (in order) a fixed hand for this deal."""
    for seat, hand in zip(game.alive(), hands):
        seat.hand = list(hand)


def ids(game):
    return [s.id for s in game.seats]


def test_new_game_deals_one_card_each_and_first_seat_opens():
    g = make(4)
    assert g.phase == BETTING and g.deal_no == 1
    assert all(len(s.hand) == 1 for s in g.seats)
    assert len(set(g.cards_in_play())) == 4
    assert g.current_id == "p0"
    assert g.deadline == 60.0


@pytest.mark.parametrize("players", [[], ["a"], ["a", "a"], [str(i) for i in range(9)]])
def test_rejects_bad_player_lists(players):
    with pytest.raises(GameError):
        Game(players, now=0)


def test_bets_must_rise_and_follow_turn_order():
    g = make(3)
    with pytest.raises(GameError, match="not_your_turn"):
        g.bet("p1", "pair_9", 1)
    with pytest.raises(GameError, match="invalid_bet"):
        g.bet("p0", "pair_X", 1)
    with pytest.raises(GameError, match="invalid_bet"):
        g.bet("p0", None, 1)
    g.bet("p0", "pair_9", 1)
    assert g.current_id == "p1" and g.last_bet == "pair_9"
    with pytest.raises(GameError, match="bet_too_low"):
        g.bet("p1", "pair_9", 2)
    with pytest.raises(GameError, match="bet_too_low"):
        g.bet("p1", "high_card_A", 2)
    g.bet("p1", "pair_T", 2)
    g.bet("p2", "pair_J", 3)
    assert g.current_id == "p0"  # wraps around


def test_cannot_check_opening():
    g = make(2)
    with pytest.raises(GameError, match="nothing_to_check"):
        g.check("p0", 1)


def test_check_on_false_bet_costs_the_bettor_a_card():
    g = make(3)
    rig(g, [["9♠"], ["T♠"], ["J♠"]])
    g.bet("p0", "pair_A", 1)
    g.check("p1", 2)
    assert g.phase == REVEAL
    assert g.reveal["held"] is False and g.reveal["loser_id"] == "p0"
    assert g.seat("p0").cards == 2 and g.seat("p1").cards == 1
    assert g.reveal["hands"] == {"p0": ["9♠"], "p1": ["T♠"], "p2": ["J♠"]}
    g.next_deal(3)
    assert g.current_id == "p0"  # loser opens
    assert len(g.seat("p0").hand) == 2


def test_check_on_true_bet_costs_the_checker_a_card():
    g = make(3)
    rig(g, [["9♠"], ["9♥"], ["J♠"]])
    g.bet("p0", "pair_9", 1)
    g.check("p1", 2)
    assert g.reveal["held"] is True and g.reveal["loser_id"] == "p1"
    g.next_deal(3)
    assert g.current_id == "p1"


def test_cards_pool_across_all_hands():
    g = make(5)
    rig(g, [["9♠"], ["T♥"], ["J♣"], ["Q♦"], ["K♠"]])
    g.bet("p0", "small_straight", 1)
    g.check("p1", 2)
    assert g.reveal["held"] is True


def test_elimination_and_next_starter_skips_eliminated_player():
    g = make(3, max_hand=1)  # one loss eliminates
    rig(g, [["9♠"], ["T♠"], ["J♠"]])
    g.bet("p0", "quad_A", 1)
    g.check("p1", 2)
    assert g.seat("p0").out and g.seat("p0").out_reason == "cards"
    assert g.phase == REVEAL
    g.next_deal(3)
    assert g.current_id == "p1"
    assert g.seat("p0").hand == []
    assert len(g.cards_in_play()) == 2


def test_last_player_standing_wins():
    g = make(2, max_hand=1)
    rig(g, [["9♠"], ["T♠"]])
    g.bet("p0", "quad_A", 1)
    g.check("p1", 2)
    assert g.phase == OVER and g.winner == "p1" and g.deadline is None
    with pytest.raises(GameError):
        g.bet("p1", "pair_9", 3)
    assert g.timeout(10_000) is False


def test_full_game_to_completion_with_max_hand_3():
    g = make(3, seed=7)
    rng = random.Random(3)
    now = 0.0
    for _ in range(500):
        if g.phase == OVER:
            break
        now += 1
        if g.phase == REVEAL:
            g.next_deal(now)
            continue
        pid = g.current_id
        if g.bets and rng.random() < 0.4:
            g.check(pid, now)
        else:
            options = rules.bets_above(g.last_bet)
            if not options:
                g.check(pid, now)
            else:
                g.bet(pid, options[0], now)
        assert sum(len(s.hand) for s in g.alive()) <= 24
    assert g.phase == OVER and g.winner in ids(g)
    assert sum(not s.out for s in g.seats) == 1


def test_eight_players_at_max_cards_fit_the_deck():
    g = make(8)
    for s in g.seats:
        s.cards = 3
    g.bet("p0", "pair_9", 1)
    g.check("p1", 2)
    g.next_deal(3)  # someone may be out; no deck overflow either way
    assert len(set(g.cards_in_play())) == len(g.cards_in_play())


def test_highest_bet_leaves_only_check():
    g = make(2)
    g.bet("p0", rules.HIGHEST_BET, 1)
    with pytest.raises(GameError, match="bet_too_low"):
        g.bet("p1", rules.HIGHEST_BET, 2)
    g.check("p1", 2)
    assert g.reveal["held"] is False


def test_timeout_opening_bets_lowest_then_checks():
    g = make(2)
    assert g.timeout(59) is False
    assert g.timeout(60) is True
    assert g.bets == [{"player_id": "p0", "bet": rules.LOWEST_BET}]
    assert g.current_id == "p1" and g.deadline == 120
    assert g.timeout(120) is True
    assert g.phase == REVEAL
    assert g.timeout(120 + 19) is False
    assert g.timeout(120 + 20) is True
    assert g.phase == BETTING and g.deal_no == 2


def test_turn_seq_increments_on_every_move():
    g = make(2)
    seqs = [g.turn_seq]
    g.bet("p0", "pair_9", 1); seqs.append(g.turn_seq)
    g.check("p1", 2); seqs.append(g.turn_seq)
    g.next_deal(3); seqs.append(g.turn_seq)
    assert seqs == sorted(set(seqs))


def test_leaving_mid_deal_voids_and_redeals():
    g = make(3)
    g.bet("p0", "pair_9", 1)  # p1 to act
    deal = g.deal_no
    g.remove("p2", 2)
    assert g.seat("p2").out and g.seat("p2").out_reason == "left"
    assert g.deal_no == deal + 1 and g.bets == []
    assert g.current_id == "p1"  # whoever was about to act opens
    assert {s.id for s in g.alive()} == {"p0", "p1"}
    assert g.seat("p2").hand == []


def test_current_player_leaving_passes_opening_to_next():
    g = make(3)
    g.bet("p0", "pair_9", 1)  # p1 to act
    g.remove("p1", 2)
    assert g.current_id == "p2"


def test_leaving_two_player_game_hands_win_to_other():
    g = make(2)
    g.remove("p0", 1)
    assert g.phase == OVER and g.winner == "p1"


def test_leaving_during_reveal_moves_starter():
    g = make(3)
    rig(g, [["9♠"], ["T♠"], ["J♠"]])
    g.bet("p0", "pair_A", 1)
    g.check("p1", 2)  # p0 loses and would open
    g.remove("p0", 3)
    assert g.phase == REVEAL
    g.next_deal(4)
    assert g.current_id == "p1"


def test_remove_is_idempotent_and_ignores_unknown():
    g = make(3)
    g.remove("p2", 1)
    seq = g.turn_seq
    g.remove("p2", 2)
    g.remove("nobody", 2)
    assert g.turn_seq == seq


def test_ready_only_in_reveal():
    g = make(2)
    with pytest.raises(GameError, match="wrong_phase"):
        g.mark_ready("p0")
    g.bet("p0", "pair_9", 1)
    g.check("p1", 2)
    g.mark_ready("p0")
    assert g.ready == {"p0"}
    with pytest.raises(GameError, match="not_in_game"):
        g.mark_ready("ghost")


def test_out_player_cannot_act():
    g = make(3, max_hand=1)
    rig(g, [["9♠"], ["T♠"], ["J♠"]])
    g.bet("p0", "quad_A", 1)
    g.check("p1", 2)
    g.next_deal(3)
    with pytest.raises(GameError, match="you_are_out"):
        g.bet("p0", "pair_9", 4)


def test_round_trips_through_dict():
    g = make(3)
    g.bet("p0", "pair_9", 1)
    copy = Game.from_dict(g.to_dict())
    assert copy.to_dict() == g.to_dict()
    copy.bet("p1", "pair_T", 2)
    assert copy.current_id == "p2"


def test_events_describe_the_deal():
    g = make(2)
    rig(g, [["9♠"], ["T♠"]])
    g.drain_events()
    g.bet("p0", "pair_A", 1)
    g.check("p1", 2)
    types = [e["type"] for e in g.drain_events()]
    assert types == ["bet", "check", "deal_result"]
    assert g.drain_events() == []
