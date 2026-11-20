"""Bot players.

A bot only sees what a human in its seat would see: its own hand, how many
cards are in play and the bets so far. It estimates how likely each bet is by
sampling the unseen cards (Monte Carlo), which works the same for every bet
type and costs a few milliseconds.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Dict, List, Optional, Tuple

from . import rules

SAMPLES = 300
#: How many bets above the current one a bot considers.
LOOKAHEAD = 30


def estimate(hand: List[str], total_cards: int, bets: List[str], rng: random.Random,
             samples: int = SAMPLES) -> Dict[str, float]:
    """Probability, for each bet in ``bets``, that it holds over all cards in play."""
    unseen = [c for c in rules.DECK if c not in set(hand)]
    hidden = max(0, min(total_cards - len(hand), len(unseen)))
    hits = Counter()
    for _ in range(samples):
        cards = set(hand)
        cards.update(rng.sample(unseen, hidden))
        ranks = Counter(rules.rank_of(c) for c in cards)
        suits = Counter(rules.suit_of(c) for c in cards)
        for bet in bets:
            if rules.holds_counted(bet, ranks, suits, cards):
                hits[bet] += 1
    return {bet: hits[bet] / samples for bet in bets}


def decide(hand: List[str], total_cards: int, last_bet: Optional[str], my_cards: int,
           max_hand: int, rng: random.Random) -> Tuple[str, Optional[str]]:
    """Return ("bet", bet) or ("check", None)."""
    candidates = rules.bets_above(last_bet)[:LOOKAHEAD]
    to_score = candidates + ([last_bet] if last_bet else [])
    odds = estimate(hand, total_cards, to_score, rng)

    # The closer to elimination, the less the bot is willing to bluff.
    danger = (my_cards - 1) / max(1, max_hand - 1)          # 0.0 fresh .. 1.0 one loss from out
    confidence = 0.55 + 0.15 * danger + rng.uniform(-0.1, 0.1)

    if last_bet is not None:
        believable = odds[last_bet]
        if believable < 0.35 + rng.uniform(-0.1, 0.1):
            return "check", None

    # Lowest bet the bot is confident in; raising minimally keeps it safest.
    for bet in candidates:
        if odds[bet] >= confidence:
            # Occasionally bluff a step or two higher to stay unpredictable.
            if rng.random() < 0.2 * (1 - danger):
                index = candidates.index(bet)
                return "bet", candidates[min(index + rng.randint(1, 2), len(candidates) - 1)]
            return "bet", bet

    if last_bet is None:
        # Must open; take the likeliest bet.
        return "bet", max(candidates, key=lambda b: odds[b])

    if not candidates:
        return "check", None
    # Checking loses if the last bet holds; raising (roughly) loses if ours does not.
    best = max(candidates, key=lambda b: odds[b])
    if odds[last_bet] < 1 - odds[best]:
        return "check", None
    return "bet", best
