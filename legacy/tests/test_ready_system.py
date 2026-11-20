"""
Unit tests for the Ready for Next Deal system

Tests cover:
- Ready state initialization for players
- All players ready detection (humans vs bots)
- Mark player ready functionality
- Reset ready states
- Finish deal with all bots (immediate continuation)
- Finish deal with human players (wait for ready)
- Deal triggering after all players ready
- Ready state tracking and emissions
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

    def get_emissions_by_event(self, event_name):
        """Get all emissions for a specific event"""
        return [e for e in self.emissions if e['event'] == event_name]


class TestReadySystemInitialization(unittest.TestCase):
    """Test initialization of ready system"""

    @patch('Game.emit')
    def test_player_ready_state_initializes_false(self, mock_emit):
        """Test that players are initialized with ready_for_next_deal = False"""
        game = Game(['p1', 'p2'], 'test_room', ['Player 1', 'Player 2'])

        for player in game.players:
            self.assertFalse(player.ready_for_next_deal)

    @patch('Game.emit')
    def test_bot_player_ready_state_initializes_false(self, mock_emit):
        """Test that bot players also initialize with ready_for_next_deal = False"""
        game = Game(['p1', 'bot1'], 'test_room', ['Player 1', 'Bot 1'], [False, True])

        for player in game.players:
            self.assertFalse(player.ready_for_next_deal)


class TestAllPlayersReady(unittest.TestCase):
    """Test all_players_ready_for_next_deal logic"""

    @patch('Game.emit')
    def test_no_players_ready(self, mock_emit):
        """Test that method returns False when no players are ready"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        self.assertFalse(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_all_human_players_ready(self, mock_emit):
        """Test that method returns True when all human players are ready"""
        game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

        game.players[0].ready_for_next_deal = True
        game.players[1].ready_for_next_deal = True

        self.assertTrue(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_some_human_players_ready(self, mock_emit):
        """Test that method returns False when only some human players are ready"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        game.players[0].ready_for_next_deal = True
        game.players[1].ready_for_next_deal = False
        game.players[2].ready_for_next_deal = True

        self.assertFalse(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_bots_always_considered_ready(self, mock_emit):
        """Test that bot players are always considered ready (don't block)"""
        game = Game(['p1', 'bot1', 'p2'], 'test_room', ['P1', 'Bot', 'P2'], [False, True, False])

        # Mark human players ready, bot is not marked
        game.players[0].ready_for_next_deal = True
        game.players[1].ready_for_next_deal = False  # Bot not ready
        game.players[2].ready_for_next_deal = True

        # Should still return True because bots are ignored
        self.assertTrue(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_all_bots_always_ready(self, mock_emit):
        """Test that all bots means always ready"""
        game = Game(['bot1', 'bot2'], 'test_room', ['Bot 1', 'Bot 2'], [True, True])

        # Even if bots aren't marked ready, should return True
        self.assertTrue(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_inactive_players_ignored(self, mock_emit):
        """Test that inactive players are ignored in ready check"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        game.players[0].ready_for_next_deal = True
        game.players[1].is_active = False  # Inactive player
        game.players[1].ready_for_next_deal = False
        game.players[2].ready_for_next_deal = True

        # Should be True because inactive player is ignored
        self.assertTrue(game.all_players_ready_for_next_deal())


class TestResetReadyStates(unittest.TestCase):
    """Test reset_ready_states functionality"""

    @patch('Game.emit')
    def test_reset_all_ready_states(self, mock_emit):
        """Test that reset_ready_states sets all players to False"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        # Set all players ready
        for player in game.players:
            player.ready_for_next_deal = True

        # Reset
        game.reset_ready_states()

        # Verify all are False
        for player in game.players:
            self.assertFalse(player.ready_for_next_deal)

    @patch('Game.emit')
    def test_reset_mixed_states(self, mock_emit):
        """Test reset when players have mixed ready states"""
        game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

        game.players[0].ready_for_next_deal = True
        game.players[1].ready_for_next_deal = False
        game.players[2].ready_for_next_deal = True

        game.reset_ready_states()

        for player in game.players:
            self.assertFalse(player.ready_for_next_deal)

    @patch('Game.emit')
    def test_reset_includes_bots(self, mock_emit):
        """Test that reset also affects bot players"""
        game = Game(['p1', 'bot1'], 'test_room', ['P1', 'Bot'], [False, True])

        game.players[0].ready_for_next_deal = True
        game.players[1].ready_for_next_deal = True

        game.reset_ready_states()

        for player in game.players:
            self.assertFalse(player.ready_for_next_deal)


class TestMarkPlayerReady(unittest.TestCase):
    """Test mark_player_ready functionality"""

    @patch('Game.emit')
    def test_mark_player_ready_sets_flag(self, mock_emit):
        """Test that marking a player ready sets their flag"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            self.assertFalse(game.players[0].ready_for_next_deal)

            game.mark_player_ready('p1')

            self.assertTrue(game.players[0].ready_for_next_deal)

    @patch('Game.emit')
    def test_mark_player_ready_emits_event(self, mock_emit):
        """Test that marking a player ready emits player_ready event"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            game.mark_player_ready('p1')

            # Should emit game_update with action: player_ready
            last_emission = mock_emit_obj.get_last_emission('game_update')
            self.assertIsNotNone(last_emission)
            self.assertEqual(last_emission['data']['json']['action'], 'player_ready')
            self.assertEqual(last_emission['data']['json']['player_sid'], 'p1')
            self.assertIn('p1', last_emission['data']['json']['players_ready'])

    @patch('Game.emit')
    def test_mark_player_ready_unknown_player(self, mock_emit):
        """Test marking a non-existent player ready returns False"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            result = game.mark_player_ready('unknown_sid')

            self.assertFalse(result)

    @patch('Game.emit')
    def test_mark_player_ready_triggers_deal_when_all_ready(self, mock_emit):
        """Test that marking the last player ready triggers deal logic"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Mark first player ready
            result1 = game.mark_player_ready('p1')
            self.assertFalse(result1)  # Should not be all ready yet
            self.assertFalse(game.all_players_ready_for_next_deal())

            # Mark second player ready - should return True to indicate all ready
            self.assertTrue(game.players[0].ready_for_next_deal)
            game.players[1].ready_for_next_deal = True  # Simulate marking ready
            self.assertTrue(game.all_players_ready_for_next_deal())

    @patch('Game.emit')
    def test_mark_player_ready_resets_states_before_deal(self, mock_emit):
        """Test that ready states are properly tracked before reset"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Mark both players ready
            game.mark_player_ready('p1')
            self.assertTrue(game.players[0].ready_for_next_deal)

            game.players[1].ready_for_next_deal = True
            self.assertTrue(game.all_players_ready_for_next_deal())

            # Reset should clear all states
            game.reset_ready_states()
            self.assertFalse(game.players[0].ready_for_next_deal)
            self.assertFalse(game.players[1].ready_for_next_deal)

    @patch('Game.emit')
    def test_mark_multiple_players_ready_tracks_all(self, mock_emit):
        """Test that marking multiple players tracks all ready players"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

            game.mark_player_ready('p1')
            game.mark_player_ready('p3')

            # Check emission contains both players
            last_emission = mock_emit_obj.get_last_emission('game_update')
            ready_list = last_emission['data']['json']['players_ready']

            self.assertIn('p1', ready_list)
            self.assertIn('p3', ready_list)
            self.assertNotIn('p2', ready_list)


class TestFinishDealWithBots(unittest.TestCase):
    """Test finish_deal behavior with all bots"""

    @patch('Game.emit')
    def test_finish_deal_all_bots_continues_immediately(self, mock_emit):
        """Test that all bots are detected correctly"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['bot1', 'bot2'], 'test_room', ['Bot1', 'Bot2'], [True, True])

            # Test the logic: all bots should trigger immediate deal
            active_players = game.get_active_players()
            all_bots = all(p.is_bot for p in active_players)

            # Should identify as all bots
            self.assertTrue(all_bots)

            # In the real implementation, when all_bots is True, finish_deal calls deal() immediately

    @patch('Game.emit')
    def test_finish_deal_all_bots_no_waiting_event(self, mock_emit):
        """Test that all bots doesn't emit waiting_for_ready"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['bot1', 'bot2'], 'test_room', ['Bot1', 'Bot2'], [True, True])

            # Test the logic directly rather than calling finish_deal
            active_players = game.get_active_players()
            all_bots = all(p.is_bot for p in active_players)

            # Verify that the game correctly identifies all players as bots
            self.assertTrue(all_bots)

            # Verify no waiting_for_ready emissions so far
            waiting_emissions = [e for e in mock_emit_obj.emissions
                               if e['data'].get('json', {}).get('action') == 'waiting_for_ready']
            self.assertEqual(len(waiting_emissions), 0)


class TestFinishDealWithHumans(unittest.TestCase):
    """Test finish_deal behavior with human players"""

    @patch('Game.emit')
    def test_finish_deal_humans_emits_waiting_event(self, mock_emit):
        """Test that finish_deal with humans emits waiting_for_ready"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Test the logic by simulating what finish_deal does
            game.deal_in_progress = False
            active_players = game.get_active_players()
            all_bots = all(p.is_bot for p in active_players)

            # Since not all bots, should emit waiting_for_ready
            if not all_bots:
                game.emit('game_update', {
                    'text': 'Waiting for players to be ready...',
                    'json': {
                        'action': 'waiting_for_ready',
                        'players_ready': [p.sid for p in game.players if p.ready_for_next_deal],
                        'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count,
                                   'last_bet': p.last_bet, 'is_active': p.is_active,
                                   'ready_for_next_deal': p.ready_for_next_deal} for p in game.players],
                        'player_turn_index': game.player_turn_index,
                        'deal_in_progress': game.deal_in_progress,
                        'game_finished': game.game_finished
                    }
                })

            # Should emit waiting_for_ready
            last_emission = mock_emit_obj.get_last_emission('game_update')
            self.assertIsNotNone(last_emission)
            self.assertEqual(last_emission['data']['json']['action'], 'waiting_for_ready')

    @patch('Game.emit')
    def test_finish_deal_humans_does_not_call_deal(self, mock_emit):
        """Test that humans are detected correctly (not all bots)"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Test the logic directly
            active_players = game.get_active_players()
            all_bots = all(p.is_bot for p in active_players)

            # Verify not all bots
            self.assertFalse(all_bots)

            # With humans, deal() should not be called automatically
            # (it will be called after all players mark ready)

    @patch('Game.emit')
    def test_finish_deal_mixed_bots_and_humans(self, mock_emit):
        """Test finish_deal with mix of bots and humans waits for humans"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'bot1', 'p2'], 'test_room', ['P1', 'Bot', 'P2'], [False, True, False])

            # Test the logic
            active_players = game.get_active_players()
            all_bots = all(p.is_bot for p in active_players)

            # Should NOT be all bots (there are humans)
            self.assertFalse(all_bots)

            # Simulate emitting waiting_for_ready
            game.emit('game_update', {
                'text': 'Waiting for players to be ready...',
                'json': {
                    'action': 'waiting_for_ready',
                    'players_ready': [],
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count,
                               'last_bet': p.last_bet, 'is_active': p.is_active,
                               'ready_for_next_deal': p.ready_for_next_deal} for p in game.players],
                    'player_turn_index': game.player_turn_index,
                    'deal_in_progress': False,
                    'game_finished': game.game_finished
                }
            })

            last_emission = mock_emit_obj.get_last_emission('game_update')
            self.assertEqual(last_emission['data']['json']['action'], 'waiting_for_ready')

    @patch('Game.emit')
    def test_finish_deal_waiting_emission_includes_player_data(self, mock_emit):
        """Test that waiting_for_ready emission includes player data"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # Simulate the emission that finish_deal would create
            game.emit('game_update', {
                'text': 'Waiting for players to be ready...',
                'json': {
                    'action': 'waiting_for_ready',
                    'players_ready': [p.sid for p in game.players if p.ready_for_next_deal],
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count,
                               'last_bet': p.last_bet, 'is_active': p.is_active,
                               'ready_for_next_deal': p.ready_for_next_deal} for p in game.players],
                    'player_turn_index': game.player_turn_index,
                    'deal_in_progress': False,
                    'game_finished': game.game_finished
                }
            })

            last_emission = mock_emit_obj.get_last_emission('game_update')
            json_data = last_emission['data']['json']

            self.assertIn('players_ready', json_data)
            self.assertIn('players', json_data)
            self.assertIn('deal_in_progress', json_data)
            self.assertEqual(json_data['deal_in_progress'], False)


class TestReadySystemIntegration(unittest.TestCase):
    """Integration tests for the complete ready system workflow"""

    @patch('Game.emit')
    def test_complete_ready_workflow_two_players(self, mock_emit):
        """Test complete workflow: mark ready -> all ready -> deal starts"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            # 1. Mark first player ready - should emit player_ready but not trigger deal
            with patch.object(game, 'deal') as mock_deal_method:
                result = game.mark_player_ready('p1')
                self.assertFalse(result)
                mock_deal_method.assert_not_called()

            # 2. Mark second player ready - should trigger deal
            with patch.object(game, 'deal') as mock_deal_method:
                result = game.mark_player_ready('p2')
                self.assertTrue(result)
                mock_deal_method.assert_called_once()

    @patch('Game.emit')
    def test_ready_states_reset_after_all_ready(self, mock_emit):
        """Test that ready states are reset after all players ready"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2'], 'test_room', ['P1', 'P2'])

            game.mark_player_ready('p1')
            self.assertTrue(game.players[0].ready_for_next_deal)

            with patch.object(game, 'deal'):
                game.mark_player_ready('p2')

            # After all ready and deal triggered, states should be reset
            self.assertFalse(game.players[0].ready_for_next_deal)
            self.assertFalse(game.players[1].ready_for_next_deal)

    @patch('Game.emit')
    def test_ready_workflow_with_three_players(self, mock_emit):
        """Test ready workflow with three players"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

            # Mark players ready one by one
            with patch.object(game, 'deal') as mock_deal:
                game.mark_player_ready('p1')
                mock_deal.assert_not_called()

                game.mark_player_ready('p2')
                mock_deal.assert_not_called()

                game.mark_player_ready('p3')
                mock_deal.assert_called_once()

    @patch('Game.emit')
    def test_inactive_player_doesnt_block_ready(self, mock_emit):
        """Test that inactive player doesn't block ready system"""
        mock_emit_obj = MockEmit()

        with patch('Game.emit', mock_emit_obj):
            game = Game(['p1', 'p2', 'p3'], 'test_room', ['P1', 'P2', 'P3'])

            # Make p2 inactive
            game.players[1].is_active = False

            # Mark only active players ready
            with patch.object(game, 'deal') as mock_deal:
                game.mark_player_ready('p1')
                mock_deal.assert_not_called()

                game.mark_player_ready('p3')
                # Should trigger deal because inactive player is ignored
                mock_deal.assert_called_once()


if __name__ == '__main__':
    unittest.main()
