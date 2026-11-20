"""Cards, bets and how bets are judged. Pure data and functions, no state.

Liar's poker is played with a 24-card deck (9 to ace in four suits). A bet
claims that a poker combination can be made from *all* cards in play, pooled
together. Bets are strictly ordered; every bet must be higher than the last.
"""
from __future__ import annotations

import itertools
import random
from collections import Counter
from typing import Iterable, List, Sequence

RANKS: List[str] = ["9", "T", "J", "Q", "K", "A"]
SUITS: List[str] = ["♠", "♣", "♦", "♥"]

SMALL_STRAIGHT = ["9", "T", "J", "Q", "K"]
BIG_STRAIGHT = ["T", "J", "Q", "K", "A"]

#: A card is a two-character string: rank then suit, e.g. "T♥" or "A♠".
Card = str

DECK: List[Card] = [rank + suit for rank in RANKS for suit in SUITS]

#: A player is eliminated when they would have to hold more than this.
MAX_HAND = 3

#: Every seated player can hold MAX_HAND cards without running out of deck.
MAX_PLAYERS = len(DECK) // MAX_HAND


def _rank_pairs_any() -> List[tuple]:
    return [(a, b) for a, b in itertools.product(RANKS, RANKS) if a != b]


def _rank_pairs_descending() -> List[tuple]:
    return [(a, b) for a, b in _rank_pairs_any() if RANKS.index(a) > RANKS.index(b)]


def _build_bets() -> List[str]:
    bets: List[str] = []
    bets += [f"high_card_{r}" for r in RANKS]
    bets += [f"pair_{r}" for r in RANKS]
    bets += [f"two_pair_{a}_{b}" for a, b in _rank_pairs_descending()]
    bets += ["small_straight", "big_straight"]
    bets += [f"three_{r}" for r in RANKS]
    bets += [f"full_{a}_{b}" for a, b in _rank_pairs_any()]
    bets += [f"quad_{r}" for r in RANKS]
    bets += [f"flush_{s}" for s in SUITS]
    bets += [f"small_poker_{s}" for s in SUITS]
    bets += [f"big_poker_{s}" for s in SUITS]
    return bets


#: Every legal bet, lowest first. The client keeps an identical list.
BETS: List[str] = _build_bets()
BET_INDEX = {bet: i for i, bet in enumerate(BETS)}

LOWEST_BET = BETS[0]
HIGHEST_BET = BETS[-1]


def is_bet(value: object) -> bool:
    return isinstance(value, str) and value in BET_INDEX


def bet_rank(bet: str) -> int:
    return BET_INDEX[bet]


def beats(bet: str, last: str | None) -> bool:
    """True if ``bet`` may follow ``last`` (None means no bet yet)."""
    return last is None or BET_INDEX[bet] > BET_INDEX[last]


def bets_above(last: str | None) -> List[str]:
    start = 0 if last is None else BET_INDEX[last] + 1
    return BETS[start:]


def rank_of(card: Card) -> str:
    return card[0]


def suit_of(card: Card) -> str:
    return card[1:]


def bet_holds(bet: str, cards: Iterable[Card]) -> bool:
    """Whether ``bet`` can be made from ``cards`` (the pooled cards in play)."""
    cards = set(cards)
    return holds_counted(bet, Counter(rank_of(c) for c in cards), Counter(suit_of(c) for c in cards), cards)


def holds_counted(bet: str, ranks: Counter, suits: Counter, held: set) -> bool:
    """``bet_holds`` with the rank/suit counts precomputed, for evaluating many bets
    against one set of cards."""
    parts = bet.split("_")

    if bet.startswith("high_card_"):
        return ranks[parts[2]] >= 1
    if bet.startswith("pair_"):
        return ranks[parts[1]] >= 2
    if bet.startswith("two_pair_"):
        return ranks[parts[2]] >= 2 and ranks[parts[3]] >= 2
    if bet == "small_straight":
        return all(ranks[r] >= 1 for r in SMALL_STRAIGHT)
    if bet == "big_straight":
        return all(ranks[r] >= 1 for r in BIG_STRAIGHT)
    if bet.startswith("three_"):
        return ranks[parts[1]] >= 3
    if bet.startswith("full_"):
        return ranks[parts[1]] >= 3 and ranks[parts[2]] >= 2
    if bet.startswith("quad_"):
        return ranks[parts[1]] >= 4
    if bet.startswith("flush_"):
        return suits[parts[1]] >= 5
    if bet.startswith("small_poker_"):
        return all(r + parts[2] in held for r in SMALL_STRAIGHT)
    if bet.startswith("big_poker_"):
        return all(r + parts[2] in held for r in BIG_STRAIGHT)
    raise ValueError(f"unknown bet {bet!r}")


def deal_hands(sizes: Sequence[int], rng: random.Random) -> List[List[Card]]:
    """Shuffle a fresh deck and deal one hand per entry in ``sizes``."""
    if sum(sizes) > len(DECK):
        raise ValueError("not enough cards in the deck")
    deck = DECK[:]
    rng.shuffle(deck)
    hands, at = [], 0
    for size in sizes:
        hands.append(deck[at:at + size])
        at += size
    return hands
