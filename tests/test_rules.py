import json
import random
import re
import subprocess
from pathlib import Path

import pytest

from server import rules
from server.rules import BETS, bet_holds, beats

ROOT = Path(__file__).resolve().parents[2]


def test_deck_and_limits():
    assert len(rules.DECK) == 24 and len(set(rules.DECK)) == 24
    assert rules.MAX_PLAYERS == 8
    assert len(BETS) == 83 and len(set(BETS)) == 83


def test_bet_order_matches_legacy_engine():
    """The ordering must be exactly what the old server used (and the client shows)."""
    import sys
    sys.path.insert(0, str(ROOT / "liars-poker"))
    try:
        from Deck import Deck  # legacy, still used by the solver notebooks
    except ImportError:
        pytest.skip("legacy deps not installed")
    assert list(Deck([]).combinations.keys()) == BETS


def test_bet_order_matches_client_list():
    data = ROOT / "liars-poker-app" / "utils" / "dataUtils.js"
    if not data.exists():
        pytest.skip("client not checked out")
    names = re.findall(r'"name":\s*"([^"]+)"', data.read_text())
    assert names == BETS


def test_beats():
    assert beats("high_card_9", None)
    assert beats("pair_9", "high_card_A")
    assert not beats("pair_9", "pair_9")
    assert not beats("high_card_A", "pair_9")
    assert rules.bets_above(rules.HIGHEST_BET) == []


@pytest.mark.parametrize("bet,cards,expected", [
    ("high_card_A", ["A♠"], True),
    ("high_card_A", ["K♠"], False),
    ("pair_T", ["T♠", "T♥", "9♣"], True),
    ("pair_T", ["T♠", "9♣"], False),
    ("two_pair_K_9", ["K♠", "K♥", "9♣", "9♦"], True),
    ("two_pair_K_9", ["K♠", "K♥", "9♣", "T♦"], False),
    ("small_straight", ["9♠", "T♥", "J♣", "Q♦", "K♠"], True),
    ("small_straight", ["T♥", "J♣", "Q♦", "K♠", "A♠"], False),
    ("big_straight", ["T♥", "J♣", "Q♦", "K♠", "A♠"], True),
    ("three_Q", ["Q♠", "Q♥", "Q♣"], True),
    ("three_Q", ["Q♠", "Q♥"], False),
    ("full_A_K", ["A♠", "A♥", "A♣", "K♠", "K♥"], True),
    ("full_A_K", ["A♠", "A♥", "K♣", "K♠", "K♥"], False),
    ("full_K_A", ["A♠", "A♥", "K♣", "K♠", "K♥"], True),
    ("quad_9", ["9♠", "9♥", "9♣", "9♦"], True),
    ("flush_♥", ["9♥", "T♥", "J♥", "Q♥", "A♥"], True),
    ("flush_♥", ["9♥", "T♥", "J♥", "Q♥", "A♠"], False),
    ("small_poker_♣", ["9♣", "T♣", "J♣", "Q♣", "K♣"], True),
    ("small_poker_♣", ["9♣", "T♣", "J♣", "Q♣", "K♦"], False),
    ("big_poker_♦", ["T♦", "J♦", "Q♦", "K♦", "A♦"], True),
    ("big_poker_♦", ["9♦", "T♦", "J♦", "Q♦", "K♦"], False),
])
def test_bet_holds(bet, cards, expected):
    assert bet_holds(bet, cards) is expected


def test_every_bet_evaluates_on_full_deck():
    assert all(bet_holds(bet, rules.DECK) for bet in BETS)
    assert not any(bet_holds(bet, []) for bet in BETS)


def test_deal_hands_are_disjoint():
    rng = random.Random(1)
    hands = rules.deal_hands([3] * 8, rng)
    flat = [c for h in hands for c in h]
    assert len(flat) == 24 and len(set(flat)) == 24
    with pytest.raises(ValueError):
        rules.deal_hands([4] * 7, rng)
