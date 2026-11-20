"""
Tests for connectivity improvements including:
- Turn timeout system
- Ready phase timeout
- Player reconnection
- Heartbeat system
- Game state resync
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import time

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

    def get_emissions_by_action(self, action):
        """Get all emissions with a specific action in json"""
        return [e for e in self.emissions
                if e.get('data', {}).get('json', {}).get('action') == action]


class TestTurnTimeout(unittest.TestCase):
    """Test turn timeout system"""

    @patch('Game.emit')
    def test_start_turn_timer_sets_time(self, mock_emit):
        """Test that start_turn_timer sets the turn_start_time"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        self.assertIsNone(game.turn_start_time)

        game.start_turn_timer()

        self.assertIsNotNone(game.turn_start_time)
        self.assertIsInstance(game.turn_start_time, float)

    @patch('Game.emit')
    def test_check_turn_timeout_returns_false_when_no_timer(self, mock_emit):
        """Test check_turn_timeout returns False when timer hasn't started"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = True

        result = game.check_turn_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_check_turn_timeout_returns_false_when_not_expired(self, mock_emit):
        """Test check_turn_timeout returns False when timeout hasn't expired"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = True
        game.start_turn_timer()

        result = game.check_turn_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_check_turn_timeout_returns_true_when_expired(self, mock_emit):
        """Test check_turn_timeout returns True when timeout has expired"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = True
        game.turn_start_time = time.time() - (Game.TURN_TIMEOUT_SECONDS + 5)

        result = game.check_turn_timeout()

        self.assertTrue(result)

    @patch('Game.emit')
    def test_check_turn_timeout_false_when_deal_not_in_progress(self, mock_emit):
        """Test check_turn_timeout returns False when deal not in progress"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = False
        game.turn_start_time = time.time() - (Game.TURN_TIMEOUT_SECONDS + 5)

        result = game.check_turn_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_check_turn_timeout_false_for_bots(self, mock_emit):
        """Test check_turn_timeout returns False when current player is a bot"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'], bot_flags=[True, False])
        game.deal_in_progress = True
        game.player_turn_index = 0  # Bot's turn
        game.turn_start_time = time.time() - (Game.TURN_TIMEOUT_SECONDS + 5)

        result = game.check_turn_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_handle_turn_timeout_marks_player_inactive(self, mock_emit):
        """Test that handle_turn_timeout marks the current player as inactive"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            result = game.handle_turn_timeout()

            self.assertTrue(result)
            self.assertFalse(game.players[0].is_active)

    @patch('Game.emit')
    def test_handle_turn_timeout_advances_turn(self, mock_emit):
        """Test that handle_turn_timeout advances to next active player"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            game.handle_turn_timeout()

            # Turn should now be on next active player (index 1 or 2)
            self.assertNotEqual(game.player_turn_index, 0)
            self.assertTrue(game.players[game.player_turn_index].is_active)

    @patch('Game.emit')
    def test_handle_turn_timeout_emits_event(self, mock_emit):
        """Test that handle_turn_timeout emits turn_timeout event"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            game.handle_turn_timeout()

            timeout_events = mock_emit_tracker.get_emissions_by_action('turn_timeout')
            self.assertGreater(len(timeout_events), 0)

    @patch('Game.emit')
    def test_handle_turn_timeout_ends_game_when_one_player_left(self, mock_emit):
        """Test that handle_turn_timeout ends game when only one active player remains"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = True
            game.player_turn_index = 0

            game.handle_turn_timeout()

            # P1 is now inactive, only P2 left
            self.assertTrue(game.game_finished)

    @patch('Game.emit')
    def test_handle_turn_timeout_returns_false_for_bot(self, mock_emit):
        """Test that handle_turn_timeout returns False for bot players"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'], bot_flags=[True, False])
        game.deal_in_progress = True
        game.player_turn_index = 0  # Bot's turn

        result = game.handle_turn_timeout()

        self.assertFalse(result)


class TestReadyPhaseTimeout(unittest.TestCase):
    """Test ready phase timeout system"""

    @patch('Game.emit')
    def test_start_ready_timer_sets_time(self, mock_emit):
        """Test that start_ready_timer sets the ready_phase_start_time"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        self.assertIsNone(game.ready_phase_start_time)

        game.start_ready_timer()

        self.assertIsNotNone(game.ready_phase_start_time)

    @patch('Game.emit')
    def test_check_ready_timeout_returns_false_when_no_timer(self, mock_emit):
        """Test check_ready_timeout returns False when timer hasn't started"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        result = game.check_ready_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_check_ready_timeout_returns_false_when_deal_in_progress(self, mock_emit):
        """Test check_ready_timeout returns False when deal is in progress"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = True
        game.ready_phase_start_time = time.time() - (Game.READY_TIMEOUT_SECONDS + 5)

        result = game.check_ready_timeout()

        self.assertFalse(result)

    @patch('Game.emit')
    def test_check_ready_timeout_returns_true_when_expired(self, mock_emit):
        """Test check_ready_timeout returns True when timeout has expired"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
        game.deal_in_progress = False
        game.ready_phase_start_time = time.time() - (Game.READY_TIMEOUT_SECONDS + 5)

        result = game.check_ready_timeout()

        self.assertTrue(result)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_handle_ready_timeout_auto_readies_players(self, mock_gevent, mock_emit):
        """Test that handle_ready_timeout calls deal even when players aren't ready"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = False
            game.players[0].ready_for_next_deal = False
            game.players[1].ready_for_next_deal = False
            game.ready_phase_start_time = time.time()

            # Mock deal to prevent actual dealing
            game.deal = MagicMock()

            result = game.handle_ready_timeout()

            self.assertTrue(result)
            # deal() should have been called (states are reset after deal is called)
            game.deal.assert_called_once()
            # Ready phase timer should be reset
            self.assertIsNone(game.ready_phase_start_time)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_handle_ready_timeout_starts_deal(self, mock_gevent, mock_emit):
        """Test that handle_ready_timeout starts the next deal"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = False
            game.ready_phase_start_time = time.time()

            # Mock deal to track call
            game.deal = MagicMock()

            game.handle_ready_timeout()

            game.deal.assert_called_once()

    @patch('Game.emit')
    def test_handle_ready_timeout_emits_event(self, mock_emit):
        """Test that handle_ready_timeout emits ready_timeout event"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
            game.deal_in_progress = False
            game.ready_phase_start_time = time.time()
            game.deal = MagicMock()

            game.handle_ready_timeout()

            timeout_events = mock_emit_tracker.get_emissions_by_action('ready_timeout')
            self.assertGreater(len(timeout_events), 0)


class TestPlayerReconnection(unittest.TestCase):
    """Test player reconnection system"""

    @patch('Game.emit')
    def test_get_player_by_username_finds_player(self, mock_emit):
        """Test that get_player_by_username finds a player"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])

        player = game.get_player_by_username('Alice')

        self.assertIsNotNone(player)
        self.assertEqual(player.username, 'Alice')
        self.assertEqual(player.sid, 'p1')

    @patch('Game.emit')
    def test_get_player_by_username_returns_none_for_unknown(self, mock_emit):
        """Test that get_player_by_username returns None for unknown username"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])

        player = game.get_player_by_username('Charlie')

        self.assertIsNone(player)

    @patch('Game.emit')
    def test_reconnect_player_updates_sid(self, mock_emit):
        """Test that reconnect_player updates the player's SID"""
        game = Game(['old_sid', 'p2'], 'test_room', ['Alice', 'Bob'])

        player = game.reconnect_player('Alice', 'new_sid')

        self.assertIsNotNone(player)
        self.assertEqual(player.sid, 'new_sid')
        self.assertEqual(player.username, 'Alice')

    @patch('Game.emit')
    def test_reconnect_player_updates_sids_list(self, mock_emit):
        """Test that reconnect_player updates the sids list"""
        game = Game(['old_sid', 'p2'], 'test_room', ['Alice', 'Bob'])

        game.reconnect_player('Alice', 'new_sid')

        self.assertIn('new_sid', game.sids)
        self.assertNotIn('old_sid', game.sids)

    @patch('Game.emit')
    def test_reconnect_player_marks_active(self, mock_emit):
        """Test that reconnect_player marks the player as active"""
        game = Game(['old_sid', 'p2'], 'test_room', ['Alice', 'Bob'])
        game.players[0].is_active = False

        player = game.reconnect_player('Alice', 'new_sid')

        self.assertTrue(player.is_active)

    @patch('Game.emit')
    def test_reconnect_player_returns_none_for_unknown(self, mock_emit):
        """Test that reconnect_player returns None for unknown username"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])

        player = game.reconnect_player('Charlie', 'new_sid')

        self.assertIsNone(player)


class TestGameStateForResync(unittest.TestCase):
    """Test get_game_state for state resync"""

    @patch('Game.emit')
    def test_get_game_state_includes_all_required_fields(self, mock_emit):
        """Test that get_game_state includes all fields needed for resync"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])

        state = game.get_game_state()

        self.assertIn('room', state)
        self.assertIn('player_turn_index', state)
        self.assertIn('last_bet', state)
        self.assertIn('last_bettor_index', state)
        self.assertIn('deal_in_progress', state)
        self.assertIn('game_finished', state)
        self.assertIn('players', state)
        self.assertIn('players_ready', state)
        self.assertIn('state_valid', state)

    @patch('Game.emit')
    def test_get_game_state_includes_hand_for_player(self, mock_emit):
        """Test that get_game_state includes the player's hand when requested"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])
        game.players[0].hand = MagicMock()
        game.players[0].hand.cards = ['A', 'K']

        state = game.get_game_state(for_sid='p1')

        self.assertIn('your_hand', state)
        self.assertEqual(state['your_hand'], ['A', 'K'])

    @patch('Game.emit')
    def test_get_game_state_players_include_bot_flag(self, mock_emit):
        """Test that player info includes is_bot flag"""
        game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bot1'], bot_flags=[False, True])

        state = game.get_game_state()

        self.assertIn('is_bot', state['players'][0])
        self.assertIn('is_bot', state['players'][1])
        self.assertFalse(state['players'][0]['is_bot'])
        self.assertTrue(state['players'][1]['is_bot'])


class TestDealStartsTurnTimer(unittest.TestCase):
    """Test that deal() starts turn timer for human players"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_deal_starts_turn_timer_for_human(self, mock_gevent, mock_emit):
        """Test that deal() starts turn timer when first player is human"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['Alice', 'Bob'])

            game.deal()

            # Timer should be started for human player
            self.assertIsNotNone(game.turn_start_time)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_deal_no_timer_for_bot_first(self, mock_gevent, mock_emit):
        """Test that deal() doesn't start timer when first player is bot"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2'], 'test_room', ['Bot1', 'Alice'], bot_flags=[True, False])

            # Mock bot processing to not actually run
            game._process_bot_turn = MagicMock()

            game.deal()

            # Timer should not be started for bot
            self.assertIsNone(game.turn_start_time)


class TestFinishDealStartsReadyTimer(unittest.TestCase):
    """Test that finish_deal() starts ready timer"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_finish_deal_starts_ready_timer(self, mock_gevent, mock_emit):
        """Test that finish_deal starts ready timer when humans present"""
        mock_emit_tracker = MockEmit()
        mock_gevent.sleep = MagicMock()

        with patch('Game.emit', mock_emit_tracker):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['Alice', 'Bob', 'Charlie'])
            game.deal_in_progress = True

            game.finish_deal(loser_player_index=0)

            # Ready timer should be started
            self.assertIsNotNone(game.ready_phase_start_time)


class TestTimeoutConstants(unittest.TestCase):
    """Test timeout constants are reasonable"""

    @patch('Game.emit')
    def test_turn_timeout_is_reasonable(self, mock_emit):
        """Test that turn timeout is at least 30 seconds"""
        self.assertGreaterEqual(Game.TURN_TIMEOUT_SECONDS, 30)
        self.assertLessEqual(Game.TURN_TIMEOUT_SECONDS, 300)

    @patch('Game.emit')
    def test_ready_timeout_is_reasonable(self, mock_emit):
        """Test that ready timeout is at least 30 seconds"""
        self.assertGreaterEqual(Game.READY_TIMEOUT_SECONDS, 30)
        self.assertLessEqual(Game.READY_TIMEOUT_SECONDS, 300)


if __name__ == '__main__':
    unittest.main()
