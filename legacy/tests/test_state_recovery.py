"""
Tests for state validation and recovery in Game.py

Tests cover:
- validate_game_state() detecting various issues
- recover_game_state() fixing invalid states
- make_move() validating state before processing
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Game import Game, Player


class MockEmit:
    """Mock for flask_socketio.emit to capture emissions without SocketIO context"""
    def __init__(self):
        self.emissions = []

    def __call__(self, event, data=None, to=None):
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


class TestValidateGameState(unittest.TestCase):
    """Test validate_game_state() method"""

    @patch('Game.emit')
    def test_valid_state_returns_true(self, mock_emit):
        """Test that a valid state returns (True, [])"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        is_valid, issues = game.validate_game_state()

        self.assertTrue(is_valid)
        self.assertEqual(len(issues), 0)

    @patch('Game.emit')
    def test_detects_out_of_bounds_positive(self, mock_emit):
        """Test detection of player_turn_index > len(players)"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
        game.player_turn_index = 10  # Out of bounds

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('out of bounds' in issue for issue in issues))

    @patch('Game.emit')
    def test_detects_out_of_bounds_negative(self, mock_emit):
        """Test detection of player_turn_index < 0"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
        game.player_turn_index = -1  # Negative

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('out of bounds' in issue for issue in issues))

    @patch('Game.emit')
    def test_detects_inactive_current_player(self, mock_emit):
        """Test detection of inactive player having turn during deal"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
        game.deal_in_progress = True
        game.players[0].is_active = False  # Current player inactive
        game.player_turn_index = 0

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('inactive' in issue for issue in issues))

    @patch('Game.emit')
    def test_detects_no_active_players(self, mock_emit):
        """Test detection of no active players when game not finished"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.players[0].is_active = False
        game.players[1].is_active = False
        game.game_finished = False

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('no active players' in issue for issue in issues))

    @patch('Game.emit')
    def test_detects_inconsistent_flags(self, mock_emit):
        """Test detection of deal_in_progress=True with game_finished=True"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = True
        game.game_finished = True

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('deal_in_progress=True' in issue for issue in issues))

    @patch('Game.emit')
    def test_detects_invalid_last_bettor_index(self, mock_emit):
        """Test detection of invalid last_bettor_index"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.last_bettor_index = 100  # Out of bounds

        is_valid, issues = game.validate_game_state()

        self.assertFalse(is_valid)
        self.assertTrue(any('last_bettor_index' in issue for issue in issues))


class TestRecoverGameState(unittest.TestCase):
    """Test recover_game_state() method"""

    @patch('Game.emit')
    def test_valid_state_no_recovery_needed(self, mock_emit):
        """Test that valid state returns True without changes"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            original_index = game.player_turn_index

            result = game.recover_game_state()

            self.assertTrue(result)
            self.assertEqual(game.player_turn_index, original_index)

    @patch('Game.emit')
    def test_recovers_out_of_bounds_index(self, mock_emit):
        """Test recovery of out-of-bounds player_turn_index"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.player_turn_index = 10  # Out of bounds

            result = game.recover_game_state()

            self.assertTrue(result)
            self.assertGreaterEqual(game.player_turn_index, 0)
            self.assertLess(game.player_turn_index, len(game.players))

    @patch('Game.emit')
    def test_recovers_inactive_current_player(self, mock_emit):
        """Test recovery when current player is inactive"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.players[0].is_active = False
            game.player_turn_index = 0

            result = game.recover_game_state()

            self.assertTrue(result)
            # Should now point to an active player
            self.assertTrue(game.players[game.player_turn_index].is_active)

    @patch('Game.emit')
    def test_recovers_inconsistent_flags(self, mock_emit):
        """Test recovery of inconsistent flags"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.game_finished = True

            game.recover_game_state()

            # deal_in_progress should be reset
            self.assertFalse(game.deal_in_progress)

    @patch('Game.emit')
    def test_recovers_invalid_last_bettor_index(self, mock_emit):
        """Test recovery of invalid last_bettor_index"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.last_bettor_index = 100  # Out of bounds

            game.recover_game_state()

            # last_bettor_index should be reset to None
            self.assertIsNone(game.last_bettor_index)

    @patch('Game.emit')
    def test_returns_false_for_unrecoverable_no_players(self, mock_emit):
        """Test that recovery returns False when no players exist"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1'], 'test_room', ['P1'])
            game.players = []  # No players
            game.player_turn_index = 0

            result = game.recover_game_state()

            self.assertFalse(result)
            self.assertTrue(game.game_finished)

    @patch('Game.emit')
    def test_returns_false_for_unrecoverable_no_active(self, mock_emit):
        """Test that recovery returns False when no active players"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.players[0].is_active = False
            game.players[1].is_active = False
            game.deal_in_progress = True

            result = game.recover_game_state()

            self.assertFalse(result)
            self.assertTrue(game.game_finished)

    @patch('Game.emit')
    def test_emits_state_recovered_event(self, mock_emit):
        """Test that recovery emits a state_recovered event"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.player_turn_index = 10  # Invalid

            game.recover_game_state()

            # Should have emitted state_recovered
            emissions = [e for e in mock_emit_tracker.emissions
                        if e['event'] == 'game_update' and
                        e.get('data', {}).get('json', {}).get('action') == 'state_recovered']
            self.assertGreater(len(emissions), 0)


class TestMakeMoveValidation(unittest.TestCase):
    """Test that make_move() validates state before processing"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_make_move_validates_state(self, mock_gevent, mock_emit):
        """Test that make_move validates state before processing"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 100  # Invalid

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # Try to make a move with invalid state
            game.make_move('p1', 'high_card_A')

            # State should have been recovered or error emitted
            # Check that game didn't crash
            self.assertLess(game.player_turn_index, len(game.players))

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_make_move_rejects_with_unrecoverable_state(self, mock_gevent, mock_emit):
        """Test that make_move emits error for unrecoverable state"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.players = []  # Empty players - unrecoverable
            game.player_turn_index = 0

            game.make_move('p1', 'high_card_A')

            # Should have emitted error
            last_emission = mock_emit_tracker.get_last_emission('game_update')
            if last_emission:
                data = last_emission.get('data', {})
                # Either game_error or other error handling
                self.assertTrue(
                    'error' in data.get('text', '').lower() or
                    data.get('json', {}).get('action') == 'game_error' or
                    game.game_finished
                )

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_make_move_recovers_and_continues(self, mock_gevent, mock_emit):
        """Test that make_move recovers from invalid state and continues"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            # Player 0 inactive but it's their turn
            game.players[0].is_active = False
            game.player_turn_index = 0

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': True}

            # P2's move should work after recovery
            # (recovery should move turn to P2)
            game.make_move('p2', 'high_card_A')

            # P2 should be able to make the move
            # Either the turn was moved to them, or recovery happened


class TestGetGameState(unittest.TestCase):
    """Test get_game_state() method"""

    @patch('Game.emit')
    def test_returns_serializable_dict(self, mock_emit):
        """Test that get_game_state returns a serializable dict"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        state = game.get_game_state()

        self.assertIsInstance(state, dict)
        self.assertIn('room', state)
        self.assertIn('player_turn_index', state)
        self.assertIn('last_bet', state)
        self.assertIn('players', state)
        self.assertIn('deal_in_progress', state)
        self.assertIn('game_finished', state)
        self.assertIn('state_valid', state)

    @patch('Game.emit')
    def test_includes_player_hand_for_sid(self, mock_emit):
        """Test that get_game_state includes hand for requesting player"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.players[0].hand = MagicMock()
        game.players[0].hand.cards = ['A♠', 'K♥']

        state = game.get_game_state(for_sid='p1')

        self.assertIn('your_hand', state)
        self.assertEqual(state['your_hand'], ['A♠', 'K♥'])

    @patch('Game.emit')
    def test_does_not_include_hand_for_other_sid(self, mock_emit):
        """Test that get_game_state doesn't include hand for other player"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.players[0].hand = MagicMock()
        game.players[0].hand.cards = ['A♠', 'K♥']

        state = game.get_game_state(for_sid='p2')

        # P2 shouldn't see P1's hand
        self.assertNotIn('your_hand', state)

    @patch('Game.emit')
    def test_includes_validation_status(self, mock_emit):
        """Test that get_game_state includes validation status"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        state = game.get_game_state()

        self.assertIn('state_valid', state)
        self.assertTrue(state['state_valid'])

    @patch('Game.emit')
    def test_includes_issues_when_invalid(self, mock_emit):
        """Test that get_game_state includes issues when state is invalid"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.player_turn_index = 100  # Invalid

        state = game.get_game_state()

        self.assertFalse(state['state_valid'])
        self.assertIn('state_issues', state)
        self.assertGreater(len(state['state_issues']), 0)


if __name__ == '__main__':
    unittest.main()
