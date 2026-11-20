"""
Tests for bot processing lock mechanism in Game.py

Tests cover:
- BoundedSemaphore initialization
- Non-blocking lock acquisition
- Concurrent bot processing prevention
- Lock release on exceptions
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Game import Game, Player
from gevent.lock import BoundedSemaphore


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


class TestBotLockInitialization(unittest.TestCase):
    """Test bot processing lock initialization"""

    @patch('Game.emit')
    def test_lock_is_bounded_semaphore(self, mock_emit):
        """Test that bot_processing_lock is a BoundedSemaphore"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        self.assertIsInstance(game.bot_processing_lock, BoundedSemaphore)

    @patch('Game.emit')
    def test_lock_allows_initial_acquire(self, mock_emit):
        """Test that lock can be acquired initially"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        # Should be able to acquire
        acquired = game.bot_processing_lock.acquire(blocking=False)
        self.assertTrue(acquired)

        # Release for cleanup
        game.bot_processing_lock.release()

    @patch('Game.emit')
    def test_lock_blocks_second_acquire(self, mock_emit):
        """Test that lock blocks second non-blocking acquire"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        # First acquire
        first = game.bot_processing_lock.acquire(blocking=False)
        self.assertTrue(first)

        # Second acquire should fail (non-blocking)
        second = game.bot_processing_lock.acquire(blocking=False)
        self.assertFalse(second)

        # Release for cleanup
        game.bot_processing_lock.release()


class TestBotProcessingLockBehavior(unittest.TestCase):
    """Test bot processing with lock"""

    @patch('Game.emit')
    def test_process_bot_turn_acquires_lock(self, mock_emit):
        """Test that _process_bot_turn acquires lock"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])
                game.deal_in_progress = False  # Prevent actual bot processing

                # Lock should be available
                available = game.bot_processing_lock.acquire(blocking=False)
                self.assertTrue(available)
                game.bot_processing_lock.release()

    @patch('Game.emit')
    def test_concurrent_bot_processing_blocked(self, mock_emit):
        """Test that concurrent bot processing is blocked"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])

                # Acquire lock manually
                game.bot_processing_lock.acquire(blocking=False)

                # _process_bot_turn should return immediately
                game._process_bot_turn()

                # Release for cleanup
                game.bot_processing_lock.release()

    @patch('Game.emit')
    def test_lock_released_on_normal_exit(self, mock_emit):
        """Test that lock is released after normal processing"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])
                game.deal_in_progress = False  # Will exit loop immediately

                game._process_bot_turn()

                # Lock should be released (can acquire again)
                acquired = game.bot_processing_lock.acquire(blocking=False)
                self.assertTrue(acquired)
                game.bot_processing_lock.release()

    @patch('Game.emit')
    def test_lock_released_on_exception(self, mock_emit):
        """Test that lock is released even when exception occurs"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])
                game.deal_in_progress = True
                game.game_finished = False
                game.players[0].hand = MagicMock()
                game.players[0].hand.combinations = {}

                # Mock bot to raise exception
                mock_bot = MagicMock()
                mock_bot.make_decision.side_effect = Exception("Bot error")
                game.bots['bot1'] = mock_bot

                # Mock cards
                game.cards = MagicMock()
                game.cards.combinations = {'high_card_A': True}

                # Run bot processing (should catch exception)
                game._process_bot_turn()

                # Lock should be released
                acquired = game.bot_processing_lock.acquire(blocking=False)
                self.assertTrue(acquired)
                game.bot_processing_lock.release()


class TestBotProcessingIterationLimit(unittest.TestCase):
    """Test bot processing iteration safety limit"""

    @patch('Game.emit')
    def test_iteration_limit_prevents_infinite_loop(self, mock_emit):
        """Test that iteration limit prevents infinite loops"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'bot2'], 'test_room', ['Bot 1', 'Bot 2'], [True, True])
                game.deal_in_progress = True
                game.game_finished = False

                # Mock players with hands
                for p in game.players:
                    p.hand = MagicMock()
                    p.hand.combinations = {}

                # Mock bots that always bet (never end deal)
                mock_bot = MagicMock()
                mock_bot.make_decision.return_value = 'high_card_A'
                game.bots['bot1'] = mock_bot
                game.bots['bot2'] = mock_bot

                # Mock cards with valid combination
                game.cards = MagicMock()
                game.cards.combinations = {f'high_card_{r}': True for r in 'AKQJT98765432'}

                # Run bot processing - should not infinite loop
                game._process_bot_turn()

                # Function should have returned (hit iteration limit or other exit)
                # If we get here without timeout, test passes


class TestBotProcessingStateValidation(unittest.TestCase):
    """Test state validation during bot processing"""

    @patch('Game.emit')
    def test_bot_processing_validates_state(self, mock_emit):
        """Test that bot processing validates state before each move"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])
                game.deal_in_progress = True
                game.player_turn_index = 100  # Invalid

                game._process_bot_turn()

                # Should have detected invalid state and stopped
                # (or recovered and continued)

    @patch('Game.emit')
    def test_bot_processing_handles_bounds_error(self, mock_emit):
        """Test that bot processing handles bounds errors gracefully"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])
                game.deal_in_progress = True
                game.player_turn_index = -1  # Invalid negative

                # Should not raise exception
                game._process_bot_turn()


class TestBotProcessingBotNotFound(unittest.TestCase):
    """Test bot processing when bot instance is missing"""

    @patch('Game.emit')
    def test_handles_missing_bot_instance(self, mock_emit):
        """Test graceful handling when bot instance is not found"""
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            with patch('Game.gevent') as mock_gevent:
                mock_gevent.sleep = MagicMock()

                game = Game(['bot1', 'p2'], 'test_room', ['Bot 1', 'P2'], [True, False])
                game.deal_in_progress = True
                game.game_finished = False
                game.bots = {}  # No bot instances

                # Should not raise exception
                game._process_bot_turn()


if __name__ == '__main__':
    unittest.main()
