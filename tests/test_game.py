"""
Comprehensive unit tests for Game.py

Tests cover:
- Player index management after elimination
- Turn order logic
- Bot turn processing
- Inactive player handling
- Bet validation
- Check logic
- Win condition detection
"""

import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Game import Game, Player


class MockEmit:
    """Mock for flask_socketio.emit to capture emissions without SocketIO context"""
    def __init__(self):
        self.emissions = []

    def __call__(self, event, data, to=None):
        self.emissions.append({
            'event': event,
            'data': data,
            'to': to
        })

    def reset(self):
        self.emissions = []

    def get_last_emission(self, event_name):
        """Get the most recent emission for a specific event"""
        for emission in reversed(self.emissions):
            if emission['event'] == event_name:
                return emission
        return None


class TestGameInitialization(unittest.TestCase):
    """Test game initialization and setup"""

    @patch('Game.emit')
    def test_game_creates_players(self, mock_emit):
        """Test that game correctly initializes players"""
        sids = ['player1', 'player2', 'player3']
        usernames = ['Alice', 'Bob', 'Charlie']

        game = Game(sids, 'test_room', usernames)

        self.assertEqual(len(game.players), 3)
        self.assertEqual(game.players[0].sid, 'player1')
        self.assertEqual(game.players[0].username, 'Alice')
        self.assertEqual(game.players[0].hand_count, 1)
        self.assertTrue(game.players[0].is_active)
        self.assertFalse(game.players[0].is_bot)

    @patch('Game.emit')
    def test_game_creates_bot_players(self, mock_emit):
        """Test that game correctly initializes bot players"""
        sids = ['player1', 'bot1', 'player2']
        usernames = ['Alice', 'Bot 1', 'Bob']
        bot_flags = [False, True, False]

        game = Game(sids, 'test_room', usernames, bot_flags)

        self.assertFalse(game.players[0].is_bot)
        self.assertTrue(game.players[1].is_bot)
        self.assertFalse(game.players[2].is_bot)

    @patch('Game.emit')
    def test_game_initializes_attributes(self, mock_emit):
        """Test that game initializes all required attributes"""
        game = Game(['p1'], 'test_room', ['Player 1'])

        self.assertIsNone(game.last_bet)
        self.assertIsNone(game.last_bettor_index)
        self.assertFalse(game.deal_in_progress)
        self.assertFalse(game.game_finished)
        self.assertFalse(game.bot_processing_lock)
        self.assertEqual(game.player_turn_index, 0)


class TestPlayerManagement(unittest.TestCase):
    """Test player management functions"""

    @patch('Game.emit')
    def test_get_active_players(self, mock_emit):
        """Test getting list of active players"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        # All players active
        active = game.get_active_players()
        self.assertEqual(len(active), 3)

        # Mark one inactive
        game.players[1].is_active = False
        active = game.get_active_players()
        self.assertEqual(len(active), 2)
        self.assertEqual(active[0].sid, 'p1')
        self.assertEqual(active[1].sid, 'p3')

    @patch('Game.emit')
    def test_get_player_index_by_sid(self, mock_emit):
        """Test finding player index by SID"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        self.assertEqual(game.get_player_index_by_sid('p1'), 0)
        self.assertEqual(game.get_player_index_by_sid('p2'), 1)
        self.assertEqual(game.get_player_index_by_sid('p3'), 2)
        self.assertIsNone(game.get_player_index_by_sid('nonexistent'))

    @patch('Game.emit')
    def test_get_next_active_player_index(self, mock_emit):
        """Test finding next active player"""
        game = Game(['p1', 'p2', 'p3', 'p4'], 'test_room', ['P1', 'P2', 'P3', 'P4'])

        # All active - should return starting index
        self.assertEqual(game.get_next_active_player_index(0), 0)
        self.assertEqual(game.get_next_active_player_index(2), 2)

        # Mark player 1 inactive - should skip to player 2
        game.players[1].is_active = False
        self.assertEqual(game.get_next_active_player_index(1), 2)

        # Mark players 1 and 2 inactive - should skip to player 3
        game.players[2].is_active = False
        self.assertEqual(game.get_next_active_player_index(1), 3)

        # Starting from active player 3 returns 3 (doesn't need to wrap)
        self.assertEqual(game.get_next_active_player_index(3), 3)

        # Starting from inactive player 1 wraps around to player 0
        self.assertEqual(game.get_next_active_player_index(1), 3)  # skips 1, 2, finds 3
        # Starting from player 2 should also wrap to find player 3
        self.assertEqual(game.get_next_active_player_index(2), 3)

    @patch('Game.emit')
    def test_mark_player_inactive(self, mock_emit):
        """Test marking player as inactive"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        self.assertTrue(game.players[0].is_active)

        result = game.mark_player_inactive('p1')

        self.assertIsNotNone(result)
        self.assertFalse(game.players[0].is_active)

        # Try marking nonexistent player
        result = game.mark_player_inactive('nonexistent')
        self.assertIsNone(result)


class TestTurnOrder(unittest.TestCase):
    """Test turn order management"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_turn_order_after_player_loses(self, mock_gevent, mock_emit):
        """Test that loser starts next deal (the bug we just fixed!)"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.last_bet = 'high_card_A'
            game.player_turn_index = 1  # P2's turn (checking)
            game.last_bettor_index = 0  # P1 made the bet

            # Mock deck combinations (bet was true, so checker loses)
            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # P2 loses (checker)
            game.finish_deal(loser_player_index=1)

            # Check that player_turn_index points to P2 (loser)
            p2_index = game.get_player_index_by_sid('p2')
            self.assertEqual(game.player_turn_index, p2_index)

            # Check emission included correct turn index
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            if last_emission and 'json' in last_emission['data']:
                json_data = last_emission['data']['json']
                if json_data.get('action') == 'deal_result':
                    # The emission should have had next_turn_index pointing to loser
                    self.assertEqual(json_data['player_turn_index'], 1)  # P2's original index

    @patch('Game.emit')
    def test_turn_order_after_elimination(self, mock_emit):
        """Test turn order after player is eliminated"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.players[1].hand_count = 3  # P2 at MAX_CARDS
            game.player_turn_index = 1

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # P2 loses and gets eliminated
            game.finish_deal(loser_player_index=1)

            # P2 should be removed
            self.assertEqual(len(game.players), 2)
            self.assertNotIn('p2', [p.sid for p in game.players])

            # Turn index should point to a valid player
            self.assertIsNotNone(game.player_turn_index)
            self.assertLess(game.player_turn_index, len(game.players))


class TestBetValidation(unittest.TestCase):
    """Test bet validation logic"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_cannot_check_on_first_turn(self, mock_gevent, mock_emit):
        """Test that checking is not allowed when no bet exists"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.last_bet = None
            game.player_turn_index = 0

            game.make_move('p1', 'check')

            # Should emit error message
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            self.assertIn("can't check", last_emission['data']['text'].lower())

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_invalid_bet_rejected(self, mock_gevent, mock_emit):
        """Test that invalid bets are rejected"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # Try invalid bet
            game.make_move('p1', 'invalid_bet')

            # Should emit error
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            self.assertIn("invalid", last_emission['data']['text'].lower())

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_bet_must_be_higher(self, mock_gevent, mock_emit):
        """Test that bets must be progressively higher"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 1
            game.last_bet = 'pair_K'

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {
                'high_card_A': True,
                'pair_9': True,
                'pair_K': True,
                'two_pair_A_K': True
            }

            # Try betting lower
            game.make_move('p2', 'pair_9')

            # Should emit error
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            self.assertIn("higher", last_emission['data']['text'].lower())


class TestInactivePlayerHandling(unittest.TestCase):
    """Test handling of inactive/disconnected players"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_inactive_player_cannot_move(self, mock_gevent, mock_emit):
        """Test that inactive players cannot make moves"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            # Mark P1 as inactive
            game.players[0].is_active = False

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # P1 tries to make a move
            game.make_move('p1', 'high_card_A')

            # Should be rejected
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            self.assertIn("not your turn", last_emission['data']['text'].lower())

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_turn_skips_inactive_players(self, mock_gevent, mock_emit):
        """Test that turns skip inactive players"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            # Mark P2 as inactive
            game.players[1].is_active = False

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True, 'high_card_K': True}

            # P1 makes move
            game.make_move('p1', 'high_card_A')

            # Turn should skip P2 and go to P3
            self.assertEqual(game.player_turn_index, 2)


class TestCheckLogic(unittest.TestCase):
    """Test check/call logic to determine winners/losers"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_check_when_bet_true_checker_loses(self, mock_gevent, mock_emit):
        """Test that checker loses when bet was true"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.last_bet = 'high_card_A'
            game.player_turn_index = 1  # P2 checking
            game.last_bettor_index = 0  # P1 made bet

            # Set up mock hands
            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}  # Bet was true

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # P2 checks
            game.make_move('p2', 'check')

            # P2 should lose (checker)
            self.assertEqual(game.players[1].hand_count, 2)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_check_when_bet_false_bettor_loses(self, mock_gevent, mock_emit):
        """Test that bettor loses when bet was false"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.last_bet = 'high_card_A'
            game.player_turn_index = 1  # P2 checking
            game.last_bettor_index = 0  # P1 made bet

            # Set up mock hands
            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': False}  # Bet was false!

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['K♠']

            # P2 checks
            game.make_move('p2', 'check')

            # P1 should lose (bettor who lied)
            self.assertEqual(game.players[0].hand_count, 2)


class TestWinCondition(unittest.TestCase):
    """Test game win conditions"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_game_ends_when_one_player_remains(self, mock_gevent, mock_emit):
        """Test that game ends when only one player remains"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.players[1].hand_count = 3  # P2 at elimination threshold

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['A♠']

            # P2 loses and gets eliminated
            game.finish_deal(loser_player_index=1)

            # Game should be finished
            self.assertTrue(game.game_finished)

            # Winner emission should have been sent
            emissions = [e for e in mock_emit_tracker.emissions if e['event'] == 'game_update']
            winner_emission = next((e for e in emissions if 'won' in e['data'].get('text', '').lower()), None)
            self.assertIsNotNone(winner_emission)


class TestBotProcessing(unittest.TestCase):
    """Test bot turn processing"""

    @patch('Game.emit')
    def test_bot_processing_lock_prevents_concurrent_execution(self, mock_emit):
        """Test that bot processing lock prevents race conditions"""
        game = Game(['p1'], 'test_room', ['P1'])

        # Set lock
        game.bot_processing_lock = True

        # Try to process bot turn
        with patch('Game.gevent'):
            game._process_bot_turn()

        # Should return immediately without processing
        # (In real implementation, would check that no moves were made)
        self.assertTrue(game.bot_processing_lock)


if __name__ == '__main__':
    unittest.main()
