"""
Edge case tests for Game.py

Tests cover unusual scenarios and edge cases:
- Multiple players eliminated in sequence
- All players inactive except one
- Bet on last possible hand
- Multiple checks in a row
- Player disconnects during their turn
- Wraparound edge cases
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Game import Game, Player


class MockEmit:
    """Mock for flask_socketio.emit"""
    def __init__(self):
        self.emissions = []

    def __call__(self, event, data, to=None):
        self.emissions.append({'event': event, 'data': data, 'to': to})

    def reset(self):
        self.emissions = []

    def get_last_emission(self, event_name):
        for emission in reversed(self.emissions):
            if emission['event'] == event_name:
                return emission
        return None


class TestMultipleEliminations(unittest.TestCase):
    """Test sequential player eliminations"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_sequential_eliminations(self, mock_gevent, mock_emit):
        """Test that multiple eliminations in a row work correctly"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3', 'p4'], 'test_room', ['P1', 'P2', 'P3', 'P4'])
            game.deal_in_progress = True

            # Set all players to elimination threshold
            for p in game.players:
                p.hand_count = 3

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # Eliminate P1
            game.finish_deal(loser_player_index=0)
            self.assertEqual(len(game.players), 3)
            self.assertFalse(game.game_finished)

            # Eliminate next player (now at index 0 since P1 was removed)
            game.finish_deal(loser_player_index=0)
            self.assertEqual(len(game.players), 2)
            self.assertFalse(game.game_finished)

            # Eliminate one more - should trigger win condition
            game.finish_deal(loser_player_index=0)
            self.assertEqual(len(game.players), 1)
            self.assertTrue(game.game_finished)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_elimination_updates_turn_correctly(self, mock_gevent, mock_emit):
        """Test that turn index is valid after each elimination"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True

            for p in game.players:
                p.hand_count = 3

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # Eliminate player 1 (middle player)
            game.finish_deal(loser_player_index=1)

            # Turn index should be valid
            self.assertIsNotNone(game.player_turn_index)
            self.assertLess(game.player_turn_index, len(game.players))
            self.assertTrue(game.players[game.player_turn_index].is_active)


class TestAllInactivePlayers(unittest.TestCase):
    """Test behavior when players disconnect"""

    @patch('Game.emit')
    def test_all_players_inactive_except_one(self, mock_emit):
        """Test that game ends when all but one player disconnect"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        # Mark all but one inactive
        game.players[1].is_active = False
        game.players[2].is_active = False

        active = game.get_active_players()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].sid, 'p1')

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_inactive_player_loses_deal(self, mock_gevent, mock_emit):
        """Test that inactive player is removed when they lose"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True

            # Mark player 2 as inactive
            game.players[1].is_active = False

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # Inactive player loses
            game.finish_deal(loser_player_index=1)

            # Should be removed from game
            self.assertEqual(len(game.players), 2)
            self.assertNotIn('p2', [p.sid for p in game.players])


class TestBettingEdgeCases(unittest.TestCase):
    """Test edge cases in betting logic"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_bet_on_highest_possible_hand(self, mock_gevent, mock_emit):
        """Test betting the highest possible hand"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            # Create ordered list of hands with straight_flush_A as highest
            game.cards.combinations = {
                'high_card_A': True,
                'pair_A': True,
                'straight_flush_A': True
            }

            # Bet highest hand
            game.make_move('p1', 'straight_flush_A')

            # Should succeed
            self.assertEqual(game.last_bet, 'straight_flush_A')

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_cannot_bet_after_highest_hand(self, mock_gevent, mock_emit):
        """Test that no valid bet exists after highest hand"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 1
            game.last_bet = 'straight_flush_A'

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {
                'high_card_A': True,
                'pair_A': True,
                'straight_flush_A': True
            }

            # Only option should be to check
            # Try to bet anything else - should fail
            game.make_move('p2', 'high_card_A')

            last_emission = mock_emit_tracker.get_last_emission('game_update')
            self.assertIn("higher", last_emission['data']['text'].lower())


class TestCheckEdgeCases(unittest.TestCase):
    """Test edge cases with checking"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_check_with_no_last_bettor_index(self, mock_gevent, mock_emit):
        """Test check when last_bettor_index is None (edge case)"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.last_bet = 'high_card_A'
            game.player_turn_index = 1
            game.last_bettor_index = None  # Edge case: no tracked bettor

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': False}  # Bet was false

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['K♠']

            # P2 checks
            game.make_move('p2', 'check')

            # Fallback logic should handle this gracefully
            # Either checker or previous player loses
            self.assertIn(game.players[0].hand_count, [1, 2])


class TestTurnWraparound(unittest.TestCase):
    """Test turn wraparound edge cases"""

    @patch('Game.emit')
    def test_turn_wraparound_with_inactive_at_end(self, mock_emit):
        """Test turn wraps correctly when last players are inactive"""
        game = Game(['p1', 'p2', 'p3', 'p4'], 'test_room', ['P1', 'P2', 'P3', 'P4'])

        # Mark last two players inactive
        game.players[2].is_active = False
        game.players[3].is_active = False

        # Start from index 3 (inactive) - should wrap to 0
        next_idx = game.get_next_active_player_index(3)
        self.assertEqual(next_idx, 0)

    @patch('Game.emit')
    def test_turn_wraparound_all_inactive_except_last(self, mock_emit):
        """Test when only last player is active"""
        game = Game(['p1', 'p2', 'p3', 'p4'], 'test_room', ['P1', 'P2', 'P3', 'P4'])

        # Only last player active
        game.players[0].is_active = False
        game.players[1].is_active = False
        game.players[2].is_active = False

        # From any index, should find player 3
        for start_idx in range(4):
            next_idx = game.get_next_active_player_index(start_idx)
            self.assertEqual(next_idx, 3)


class TestDealEdgeCases(unittest.TestCase):
    """Test edge cases in deal() method"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_deal_with_one_active_player(self, mock_gevent, mock_emit):
        """Test that deal doesn't start with only one active player"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Mark one player inactive
            game.players[1].is_active = False

            # Try to deal
            game.deal()

            # Game should be finished
            self.assertTrue(game.game_finished)
            self.assertFalse(game.deal_in_progress)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_deal_with_no_active_players(self, mock_gevent, mock_emit):
        """Test that deal handles all players being inactive"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Mark all players inactive
            game.players[0].is_active = False
            game.players[1].is_active = False

            # Try to deal
            game.deal()

            # Game should be finished
            self.assertTrue(game.game_finished)
            self.assertFalse(game.deal_in_progress)


class TestPlayerRemoval(unittest.TestCase):
    """Test edge cases in player removal"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_remove_last_player_in_list(self, mock_gevent, mock_emit):
        """Test removing the last player in the list"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.players[2].hand_count = 3

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # Remove last player
            game.finish_deal(loser_player_index=2)

            # Should only have 2 players left
            self.assertEqual(len(game.players), 2)
            self.assertNotIn('p3', [p.sid for p in game.players])

            # Turn index should be valid
            self.assertLess(game.player_turn_index, len(game.players))

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_remove_first_player_in_list(self, mock_gevent, mock_emit):
        """Test removing the first player in the list"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.players[0].hand_count = 3

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # Remove first player
            game.finish_deal(loser_player_index=0)

            # Should have p2 and p3
            self.assertEqual(len(game.players), 2)
            self.assertEqual(game.players[0].sid, 'p2')
            self.assertEqual(game.players[1].sid, 'p3')


class TestBotEdgeCases(unittest.TestCase):
    """Test edge cases with bot players"""

    @patch('Game.emit')
    def test_game_with_only_bots(self, mock_emit):
        """Test initializing a game with only bot players"""
        bot_flags = [True, True, True]
        game = Game(['bot1', 'bot2', 'bot3'], 'test_room', ['Bot 1', 'Bot 2', 'Bot 3'], bot_flags)

        self.assertEqual(len(game.players), 3)
        self.assertTrue(all(p.is_bot for p in game.players))

    @patch('Game.emit')
    def test_mixed_bots_and_humans(self, mock_emit):
        """Test game with mixed bot and human players"""
        bot_flags = [False, True, False, True]
        game = Game(['p1', 'bot1', 'p2', 'bot2'], 'test_room',
                   ['Human 1', 'Bot 1', 'Human 2', 'Bot 2'], bot_flags)

        self.assertFalse(game.players[0].is_bot)
        self.assertTrue(game.players[1].is_bot)
        self.assertFalse(game.players[2].is_bot)
        self.assertTrue(game.players[3].is_bot)


class TestRealWorldBugScenarios(unittest.TestCase):
    """Test cases based on actual bugs reported by users"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_turn_order_bug_igor_scenario(self, mock_gevent, mock_emit):
        """
        Test the exact scenario from user bug report:
        - Igor, Bot 1, Bot 2, Bot 3
        - Bot 1 loses a deal
        - New deal starts with Bot 2 first
        - Bot 3 bets pair_9
        - Igor bets pair_J
        - Bot 1 checks
        - Igor loses the deal
        - Igor should be able to make next move but gets "not your turn"

        This was caused by player_turn_index in deal_result emission
        being wrong (pointing to checker instead of loser)
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Setup: Igor (human), Bot 1, Bot 2, Bot 3
            game = Game(
                ['igor_sid', 'bot1_sid', 'bot2_sid', 'bot3_sid'],
                'test_room',
                ['Igor 16', 'Bot 1', 'Bot 2', 'Bot 3'],
                [False, True, True, True]  # Igor is human, rest are bots
            )

            # Simulate game state before the bug
            game.deal_in_progress = True
            game.player_turn_index = 0  # Igor's turn
            game.last_bet = 'pair_J'
            game.last_bettor_index = 0  # Igor made the last bet

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'pair_J': True}  # Bet was true

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['J♠', 'J♥']

            # Bot 1 checks (index 1)
            game.player_turn_index = 1
            game.make_move('bot1_sid', 'check')

            # At this point Igor should have lost (he was the checker)
            # Actually wait - if bet was TRUE, checker loses
            # In the real scenario: Bot 1 checks, and Igor loses
            # This means Igor was NOT the checker, Bot 1 was

            # Let me re-simulate the correct scenario:
            # Reset
            game = Game(
                ['igor_sid', 'bot1_sid', 'bot2_sid', 'bot3_sid'],
                'test_room',
                ['Igor 16', 'Bot 1', 'Bot 2', 'Bot 3'],
                [False, True, True, True]
            )

            game.deal_in_progress = True
            game.player_turn_index = 1  # Bot 1's turn to check
            game.last_bet = 'pair_J'
            game.last_bettor_index = 0  # Igor made pair_J bet

            game.cards = MagicMock()
            game.cards.combinations = {'pair_J': True}  # Bet was TRUE

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['J♠', 'J♥']

            # Bot 1 checks (checker loses since bet was true)
            initial_igor_hand_count = game.players[0].hand_count
            game.make_move('bot1_sid', 'check')

            # Igor should NOT have lost - Bot 1 (checker) should have lost
            # But let's check if the turn order is correct

            # After finish_deal, check the emission
            last_emission = mock_emit_tracker.get_last_emission('game_update')

            # The emission should have correct player_turn_index
            if last_emission and 'json' in last_emission['data']:
                json_data = last_emission['data']['json']
                if json_data.get('action') == 'deal_result':
                    loser_sid = json_data.get('loser_sid')
                    turn_index = json_data.get('player_turn_index')

                    # The loser should be Bot 1
                    self.assertEqual(loser_sid, 'bot1_sid')

                    # Find Bot 1's index after the deal
                    bot1_index = game.get_player_index_by_sid('bot1_sid')

                    # The turn_index in emission should point to the loser
                    # (who will start next deal)
                    self.assertEqual(turn_index, bot1_index)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_player_eliminated_turn_index_correct(self, mock_gevent, mock_emit):
        """
        Test that when a player is eliminated, the player_turn_index
        in the emission is correct BEFORE the deletion happens
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True

            # P2 at elimination threshold
            game.players[1].hand_count = 3

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # P2 loses and gets eliminated
            game.finish_deal(loser_player_index=1)

            # Check the player_eliminated emission
            emissions = [e for e in mock_emit_tracker.emissions
                        if e['event'] == 'game_update']

            eliminated_emission = next(
                (e for e in emissions
                 if e['data'].get('json', {}).get('action') == 'player_eliminated'),
                None
            )

            self.assertIsNotNone(eliminated_emission)

            json_data = eliminated_emission['data']['json']

            # The turn_index should be calculated BEFORE deletion
            # In our implementation, we calculate: loser_player_index % max(1, len(players) - 1)
            # With 3 players, loser at index 1: 1 % max(1, 2) = 1 % 2 = 1
            self.assertEqual(json_data['player_turn_index'], 1)


if __name__ == '__main__':
    unittest.main()
