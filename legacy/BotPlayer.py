from typing import List, Optional
from Card import Card
from Solver import Solver
import random


class BotPlayer:
    """
    AI player that makes strategic decisions using probability calculations.
    """

    def __init__(self, player, game):
        """
        Initialize bot player.

        Args:
            player: The Player object this bot controls
            game: The Game instance the bot is playing in
        """
        self.player = player
        self.game = game

    def make_decision(self) -> str:
        """
        Decide whether to bet or check based on game state and probabilities.

        Returns:
            str: A bet string like 'pair_K' or 'check'
        """
        # If no bet yet, make an opening bet
        if self.game.last_bet is None:
            return self._make_opening_bet()

        # Calculate probability that current bet is valid
        bet_valid_probability = self._calculate_bet_probability(self.game.last_bet)

        # Decide whether to challenge (check) or raise
        if self._should_check(bet_valid_probability):
            return "check"
        else:
            return self._make_counter_bet()

    def _make_opening_bet(self) -> str:
        """
        Make the first bet of a round based on bot's hand.

        Returns:
            str: A bet string
        """
        # Get what combinations the bot actually has
        bot_combinations = self.player.hand.combinations

        # Strategy: Start with a bet just above what we have
        # This is conservative but believable

        # Get all valid bet options in order
        all_bets = list(self.game.cards.combinations.keys())

        # Find the best combination we actually have
        best_combo = None
        for bet in reversed(all_bets):  # Start from highest
            if bot_combinations.get(bet, False):
                best_combo = bet
                break

        if best_combo is None:
            # We have nothing, bet a high card
            best_combo = all_bets[0]  # Start with lowest bet

        # Find index of our best combo
        try:
            current_index = all_bets.index(best_combo)
        except ValueError:
            current_index = 0

        # Bet slightly higher than what we have (bluff a bit)
        # But be more conservative if we have more cards (closer to losing)
        risk_factor = 1 if self.player.hand_count == 1 else 0.5

        if random.random() < risk_factor and current_index < len(all_bets) - 1:
            # Bluff up by 1-3 positions
            bluff_amount = random.randint(1, min(3, len(all_bets) - current_index - 1))
            return all_bets[current_index + bluff_amount]
        else:
            # Bet what we have
            return best_combo

    def _calculate_bet_probability(self, bet: str) -> float:
        """
        Calculate probability that the current bet is valid across all players.

        Args:
            bet: The bet string to evaluate

        Returns:
            float: Probability between 0.0 and 1.0
        """
        if not bet or bet == "check":
            return 0.0

        # Parse the bet to determine what probability function to use
        solver = self.player.solver

        # High card bets
        if bet.startswith("high_card_"):
            rank = bet.split("_")[-1]
            return solver.probability_high_card(rank)

        # Pair bets
        elif bet.startswith("pair_"):
            rank = bet.split("_")[-1]
            return solver.probability_pair(rank)

        # Two pair bets
        elif bet.startswith("two_pair_"):
            parts = bet.split("_")
            rank_a, rank_b = parts[2], parts[3]
            return solver.probability_two_pair(rank_a, rank_b)

        # Three of a kind
        elif bet.startswith("three_"):
            rank = bet.split("_")[-1]
            return solver.probability_three(rank)

        # Quad bets
        elif bet.startswith("quad_"):
            rank = bet.split("_")[-1]
            return solver.probability_quad(rank)

        # Full house bets
        elif bet.startswith("full_"):
            parts = bet.split("_")
            rank_a, rank_b = parts[1], parts[2]
            return solver.probability_full(rank_a, rank_b)

        # Straight bets
        elif bet == "small_straight":
            return solver.probability_small_straight()
        elif bet == "big_straight":
            return solver.probability_big_straight()

        # Flush bets
        elif bet.startswith("flush_"):
            suit = bet.split("_")[-1]
            return solver.probability_flush(suit)

        # Straight flush bets
        elif bet.startswith("small_poker_"):
            suit = bet.split("_")[-1]
            return solver.probability_small_poker(suit)
        elif bet.startswith("big_poker_"):
            suit = bet.split("_")[-1]
            return solver.probability_big_poker(suit)

        # Unknown bet type, assume low probability
        return 0.1

    def _should_check(self, bet_valid_probability: float) -> bool:
        """
        Decide whether to challenge the current bet.

        Args:
            bet_valid_probability: Probability that current bet is valid

        Returns:
            bool: True if should check (challenge), False if should bet higher
        """
        # Adjust threshold based on hand count
        # More cards = more desperate = more likely to challenge
        base_threshold = 0.3
        hand_penalty = (self.player.hand_count - 1) * 0.1
        threshold = base_threshold + hand_penalty

        # If probability is low, it's likely a bluff - challenge it
        if bet_valid_probability < threshold:
            return True

        # If probability is high, we need a good counter-bet or should fold
        # Check if we can make a valid counter-bet
        next_bet = self._make_counter_bet()
        if next_bet == "check":
            # Can't make a valid higher bet, challenge instead
            # But only if probability isn't too high
            return bet_valid_probability < 0.7

        # Random factor to add unpredictability
        # Sometimes challenge even when probability is moderate
        if random.random() < 0.15:  # 15% chance to bluff-check
            return True

        return False

    def _make_counter_bet(self) -> str:
        """
        Make a bet that's higher than the current bet.

        Returns:
            str: A bet string, or 'check' if can't bet higher
        """
        all_bets = list(self.game.cards.combinations.keys())

        # Find current bet position
        try:
            current_index = all_bets.index(self.game.last_bet)
        except ValueError:
            return "check"

        # Get bets higher than current
        higher_bets = all_bets[current_index + 1:]

        if not higher_bets:
            return "check"  # No higher bets available

        # Check what we actually have
        bot_combinations = self.player.hand.combinations

        # Strategy: Find the lowest higher bet we can make believably
        # Consider:
        # 1. What we actually have
        # 2. Probability calculations
        # 3. Risk based on hand count

        # Find highest combination we actually have
        best_actual = None
        for bet in reversed(all_bets):
            if bot_combinations.get(bet, False):
                best_actual = bet
                break

        # Calculate risk tolerance
        risk_tolerance = 1.0 - (self.player.hand_count - 1) * 0.25
        risk_tolerance = max(0.2, risk_tolerance)  # Minimum 20% risk tolerance

        # Try to find a bet we can make
        for i, bet in enumerate(higher_bets):
            # Check if we actually have this combination
            if bot_combinations.get(bet, False):
                # We have it, definitely bet it
                return bet

            # Calculate probability we could have this
            prob = self._calculate_bet_probability(bet)

            # Bluff if:
            # 1. It's close to what we have
            # 2. Probability is reasonable
            # 3. We're not too desperate (low hand count)
            if prob > 0.1 and random.random() < risk_tolerance:
                # Only bluff up to a few positions higher
                if i < 4:  # Don't bluff too high
                    return bet

        # Can't find a good bet, check instead
        return "check"

    def get_username(self) -> str:
        """Get a display name for the bot."""
        return f"Bot ({self.player.username})"
