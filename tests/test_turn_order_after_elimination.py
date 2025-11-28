"""
Test case for turn order after player elimination bug fix.

Bug: When a player is eliminated, turn index was incorrectly reset to 0
instead of continuing to the next player in sequence.

This test ensures the fix works correctly by validating that:
1. When player at index N is eliminated
2. The next turn goes to the player who was at index N+1
3. Not to player at index 0
"""

import unittest
from unittest.mock import patch, MagicMock
from Game import Game


class MockEmit:
    """Track all emit calls for verification"""
    def __init__(self):
        self.emissions = []

    def __call__(self, event, data, **kwargs):
        self.emissions.append({
            'event': event,
            'data': data,
            'kwargs': kwargs
        })

    def get_emissions_by_event(self, event_name):
        return [e for e in self.emissions if e['event'] == event_name]


class TestTurnOrderAfterElimination(unittest.TestCase):
    """Test that turn order continues correctly after player elimination"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_middle_player_elimination_continues_to_next(self, mock_gevent, mock_emit):
        """
        When player at index N is eliminated, turn should go to player
        who was at index N+1 (now at index N), NOT reset to index 0
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Setup: 5 players [P0, P1, P2, P3, P4]
            game = Game(
                ['p0', 'p1', 'p2', 'p3', 'p4'],
                'test_room',
                ['Player 0', 'Player 1', 'Player 2', 'Player 3', 'Player 4']
            )

            # Player 2 at index 2 will be eliminated
            game.deal_in_progress = True
            game.player_turn_index = 1  # P1's turn to check
            game.last_bet = 'high_card_A'
            game.last_bettor_index = 2  # P2 made the bet

            # Setup mock cards - bet is FALSE, so bettor loses
            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'high_card_A': False}  # Bet exists but is False -> bettor loses

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['K♣']

            # P2 is at MAX_CARDS (will be eliminated)
            game.players[2].hand_count = 3

            # Store player SIDs before elimination
            p0_sid = game.players[0].sid
            p1_sid = game.players[1].sid
            p2_sid = game.players[2].sid  # Will be eliminated
            p3_sid = game.players[3].sid  # Should get turn next
            p4_sid = game.players[4].sid

            # P1 checks -> P2 loses and gets eliminated
            game.make_move('p1', 'check')

            # Verify P2 was eliminated
            self.assertEqual(len(game.players), 4)
            remaining_sids = [p.sid for p in game.players]
            self.assertNotIn(p2_sid, remaining_sids)
            self.assertIn(p0_sid, remaining_sids)
            self.assertIn(p1_sid, remaining_sids)
            self.assertIn(p3_sid, remaining_sids)
            self.assertIn(p4_sid, remaining_sids)

            # After elimination, players list is: [P0, P1, P3, P4]
            # P3 is now at index 2 (was index 3)
            # Turn should be index 2 (P3), NOT index 0 (P0)

            # Get new deal emission to check turn index
            new_deal_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'new_deal'
            ]

            self.assertGreater(len(new_deal_emissions), 0, "New deal should have started")
            last_new_deal = new_deal_emissions[-1]

            # CRITICAL ASSERTION: Turn should be P3 (now at index 2), NOT P0 (index 0)
            turn_index = last_new_deal['data']['json']['player_turn_index']
            self.assertEqual(turn_index, 2, "Turn should be index 2 (Player 3, next after eliminated player)")

            # Verify it's actually P3
            current_turn_sid = game.players[turn_index].sid
            self.assertEqual(current_turn_sid, p3_sid, "Turn should belong to Player 3 (was next in line)")

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_last_player_elimination_wraps_to_first(self, mock_gevent, mock_emit):
        """
        When the LAST player is eliminated, turn should wrap to index 0
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Setup: 3 players [P0, P1, P2]
            game = Game(['p0', 'p1', 'p2'], 'test_room', ['P0', 'P1', 'P2'])

            game.deal_in_progress = True
            game.player_turn_index = 1  # P1's turn to check
            game.last_bet = 'pair_K'
            game.last_bettor_index = 2  # P2 (last player) made the bet

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'pair_K': False}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['Q♠']

            # P2 at MAX_CARDS
            game.players[2].hand_count = 3

            p0_sid = game.players[0].sid
            p2_sid = game.players[2].sid

            # P1 checks -> P2 loses and gets eliminated
            game.make_move('p1', 'check')

            # Verify P2 eliminated
            self.assertEqual(len(game.players), 2)
            self.assertNotIn(p2_sid, [p.sid for p in game.players])

            # Get new deal emission
            new_deal_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'new_deal'
            ]

            last_new_deal = new_deal_emissions[-1]
            turn_index = last_new_deal['data']['json']['player_turn_index']

            # When last player eliminated, should wrap to 0
            self.assertEqual(turn_index, 0, "When last player eliminated, turn should wrap to index 0")
            self.assertEqual(game.players[turn_index].sid, p0_sid, "Turn should belong to P0")

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_scenario_from_user_bug_report(self, mock_gevent, mock_emit):
        """
        Test exact scenario from user's debug logs:
        - Bot 4 at index 4 gets eliminated
        - Turn should go to Bot 5 (now at index 4), NOT Igor 16 (index 0)
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Recreate scenario: [Igor, Bot1, Bot2, Bot3, Bot4, Bot5, Bot6, ...]
            game = Game(
                ['igor_sid', 'bot1', 'bot2', 'bot3', 'bot4', 'bot5', 'bot6'],
                'test_room',
                ['Igor 16', 'Bot 1', 'Bot 2', 'Bot 3', 'Bot 4', 'Bot 5', 'Bot 6'],
                [False, True, True, True, True, True, True]  # Igor human, rest bots
            )

            game.deal_in_progress = True
            game.player_turn_index = 3  # Bot 3's turn to check
            game.last_bet = 'full_J_9'
            game.last_bettor_index = 4  # Bot 4 made the bet

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {'full_J_9': False}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['T♣', 'J♠', 'K♦']

            # Bot 4 at MAX_CARDS (will be eliminated)
            game.players[4].hand_count = 3

            igor_sid = game.players[0].sid
            bot4_sid = game.players[4].sid
            bot5_sid = game.players[5].sid  # Should get turn

            # Bot 3 checks -> Bot 4 loses and gets eliminated
            game.make_move('bot3', 'check')

            # Verify Bot 4 eliminated
            self.assertEqual(len(game.players), 6)
            self.assertNotIn(bot4_sid, [p.sid for p in game.players])

            # After elimination: [Igor(0), Bot1(1), Bot2(2), Bot3(3), Bot5(4), Bot6(5)]
            # Bot5 moved from index 5 to index 4

            # Get new deal emission
            new_deal_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'new_deal'
            ]

            self.assertGreater(len(new_deal_emissions), 0)
            last_new_deal = new_deal_emissions[-1]
            turn_index = last_new_deal['data']['json']['player_turn_index']

            # CRITICAL: Should be index 4 (Bot 5), NOT index 0 (Igor)
            self.assertEqual(turn_index, 4, "Turn should be index 4 (Bot 5), not 0 (Igor)")

            current_turn_sid = game.players[turn_index].sid
            self.assertEqual(current_turn_sid, bot5_sid, "Turn should belong to Bot 5")
            self.assertNotEqual(current_turn_sid, igor_sid, "Turn should NOT be Igor's")

            # Verify Bot 5 made a move (since it's a bot and game should continue)
            bot5_bet_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                'Bot 5 bets' in e['data'].get('text', '')
            ]
            self.assertGreater(len(bot5_bet_emissions), 0, "Bot 5 should have made a bet")


if __name__ == '__main__':
    unittest.main()
