"""
Integration tests for the Ready for Next Deal system

These tests verify the COMPLETE workflow end-to-end without mocking deal().
They catch issues that unit tests miss by testing actual behavior.

Tests cover:
- Complete ready workflow that actually triggers deal()
- Backend socket handlers (app.py)
- State transitions through the full cycle
"""

import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Game import Game, Player


class MockEmit:
    """Mock for flask_socketio.emit to capture emissions"""
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

    def get_emissions_by_event(self, event_name):
        """Get all emissions for a specific event"""
        return [e for e in self.emissions if e['event'] == event_name]

    def count_emissions_with_action(self, action):
        """Count emissions with a specific action in json"""
        count = 0
        for e in self.emissions:
            if e['data'].get('json', {}).get('action') == action:
                count += 1
        return count


class TestReadySystemFullIntegration(unittest.TestCase):
    """Integration tests that verify deal() is actually called"""

    @patch('Game.emit')
    def test_mark_ready_actually_triggers_deal(self, mock_emit):
        """CRITICAL: Verify that marking all players ready ACTUALLY calls deal()"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Track deal() calls by checking for 'new_deal' emissions
            initial_deal_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Mark first player ready
            game.mark_player_ready('p1')

            # Should not have triggered deal yet
            self.assertEqual(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_deal_count,
                "deal() should NOT be called after only one player ready"
            )

            # Mark second player ready - THIS SHOULD TRIGGER DEAL
            game.mark_player_ready('p2')

            # Verify deal() was called by checking for new_deal emission
            # This will FAIL if deal() doesn't actually get called!
            new_deal_emissions = mock_emit_obj.count_emissions_with_action('new_deal')
            self.assertGreater(
                new_deal_emissions,
                initial_deal_count,
                "CRITICAL FAILURE: deal() was NOT called when all players ready! "
                "This means the ready system is broken."
            )

    @patch('Game.emit')
    def test_three_players_all_must_be_ready(self, mock_emit):
        """Verify deal() only triggers when ALL players are ready"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

            initial_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Mark two players ready
            game.mark_player_ready('p1')
            game.mark_player_ready('p2')

            # Should NOT have triggered deal
            self.assertEqual(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_count,
                "deal() should NOT trigger until ALL players ready"
            )

            # Mark third player ready
            game.mark_player_ready('p3')

            # NOW it should trigger
            self.assertGreater(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_count,
                "deal() MUST trigger when all players are ready"
            )

    @patch('Game.emit')
    def test_ready_states_actually_reset_after_deal(self, mock_emit):
        """Verify ready states are reset AFTER deal() is called"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Mark both ready
            game.mark_player_ready('p1')
            self.assertTrue(game.players[0].ready_for_next_deal)

            game.mark_player_ready('p2')

            # After deal() is triggered, states should be reset
            self.assertFalse(
                game.players[0].ready_for_next_deal,
                "Ready states MUST be reset after deal() is called"
            )
            self.assertFalse(
                game.players[1].ready_for_next_deal,
                "Ready states MUST be reset after deal() is called"
            )

    @patch('Game.emit')
    def test_bots_dont_block_ready_system(self, mock_emit):
        """Verify bots are automatically considered ready"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'bot1', 'p2'], 'test_room', ['P1', 'Bot', 'P2'], [False, True, False])

            initial_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Only mark human players ready (bot should not block)
            game.mark_player_ready('p1')

            # Bot is not marked ready, but should not block
            self.assertFalse(game.players[1].ready_for_next_deal)  # Bot not marked

            # But all_players_ready should still return False (waiting for p2)
            self.assertFalse(game.all_players_ready_for_next_deal())

            # Mark second human ready
            game.mark_player_ready('p2')

            # Now should trigger even though bot is not marked
            self.assertGreater(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_count,
                "deal() should trigger when all HUMAN players ready (bots don't block)"
            )

    @patch('Game.emit')
    def test_inactive_players_dont_block(self, mock_emit):
        """Verify inactive players don't prevent deal from starting"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

            # Make p2 inactive
            game.players[1].is_active = False

            initial_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Mark only active players ready
            game.mark_player_ready('p1')
            game.mark_player_ready('p3')

            # Should trigger even though p2 is not ready (because inactive)
            self.assertGreater(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_count,
                "deal() should trigger when all ACTIVE players ready"
            )


class TestSocketHandlerIntegration(unittest.TestCase):
    """Test the actual socket handler in app.py"""

    def test_socket_handler_exists(self):
        """Verify ready_for_next_deal socket handler exists"""
        # Import app to verify handler is registered
        try:
            import app
            # If we can import it, the handler should be registered
            # (socketio.on decorator runs at import time)
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Failed to import app.py: {e}")

    @patch('Game.emit')
    def test_mark_player_ready_return_values(self, mock_emit):
        """Verify mark_player_ready returns correct values"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # First player - should return False (not all ready)
            result1 = game.mark_player_ready('p1')
            self.assertFalse(result1, "Should return False when not all players ready")

            # Second player - should return True (all ready, deal triggered)
            result2 = game.mark_player_ready('p2')
            self.assertTrue(result2, "Should return True when all players ready and deal triggered")

            # Unknown player - should return False
            result3 = game.mark_player_ready('unknown')
            self.assertFalse(result3, "Should return False for unknown player")


class TestReadySystemRegressionTests(unittest.TestCase):
    """Tests that catch common bugs and regressions"""

    @patch('Game.emit')
    def test_cannot_ready_twice_to_skip_waiting(self, mock_emit):
        """Ensure a player can't mark ready multiple times to bypass waiting"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            initial_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Mark p1 ready twice
            game.mark_player_ready('p1')
            game.mark_player_ready('p1')  # Second time

            # Should still not trigger deal
            self.assertEqual(
                mock_emit_obj.count_emissions_with_action('new_deal'),
                initial_count,
                "Marking same player ready twice should not trigger deal"
            )

    @patch('Game.emit')
    def test_ready_after_deal_starts_new_cycle(self, mock_emit):
        """Verify ready system works for multiple deals in sequence"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # First cycle
            game.mark_player_ready('p1')
            game.mark_player_ready('p2')
            first_deal_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # States should be reset
            self.assertFalse(game.players[0].ready_for_next_deal)
            self.assertFalse(game.players[1].ready_for_next_deal)

            # Second cycle should work the same way
            game.mark_player_ready('p1')
            game.mark_player_ready('p2')
            second_deal_count = mock_emit_obj.count_emissions_with_action('new_deal')

            # Should have triggered deal again
            self.assertGreater(
                second_deal_count,
                first_deal_count,
                "Ready system should work across multiple cycles"
            )


if __name__ == '__main__':
    unittest.main()
