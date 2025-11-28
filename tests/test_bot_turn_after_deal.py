"""
Test case for the bot turn after deal bug.

Bug report from user debug logs:
After a bot loses a deal, if the next player is also a bot, the game hangs
because finish_deal() sets deal_in_progress=False but doesn't call deal().

The bug only triggers when:
1. A deal ends (someone loses)
2. The next player to start the deal is a bot
3. The game hangs because bots don't trigger deal() via the bet handler

This was discovered through user debug logs showing:
- Bot 2 loses at [144.555s]
- No new deal event follows
- Game hangs with deal_in_progress=False
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

    def get_last_emission(self, event_name):
        emissions = self.get_emissions_by_event(event_name)
        return emissions[-1] if emissions else None


class TestBotTurnAfterDeal(unittest.TestCase):
    """Test that game continues when bot's turn follows a deal end"""

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_bot_turn_after_human_loses_deal(self, mock_gevent, mock_emit):
        """
        Test the exact scenario from user bug report:
        - Igor (human), Bot 2, Bot 3
        - Bot 2 loses a deal
        - New deal should start with Bot 2's turn
        - Bot 2 should automatically bet
        - Game should NOT hang
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Setup: Igor (human), Bot 2, Bot 3
            game = Game(
                ['igor_sid', 'bot2_sid', 'bot3_sid'],
                'test_room',
                ['Igor', 'Bot 2', 'Bot 3'],
                [False, True, True]  # Igor is human, rest are bots
            )

            # Simulate state before Bot 2 loses
            game.deal_in_progress = True
            game.player_turn_index = 2  # Bot 3's turn to check
            game.last_bet = 'pair_9'
            game.last_bettor_index = 1  # Bot 2 made the bet

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {}  # Bet was FALSE, so bettor loses

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['Q♣', 'K♥']

            # Set Bot 2 at 2 cards (will go to 3 after losing)
            game.players[1].hand_count = 2

            # Bot 3 checks -> Bot 2 loses
            game.make_move('bot3_sid', 'check')

            # Verify:
            # 1. Bot 2 lost the deal
            deal_result_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'deal_result'
            ]
            self.assertEqual(len(deal_result_emissions), 1)
            self.assertEqual(deal_result_emissions[0]['data']['json']['loser_sid'], 'bot2_sid')

            # 2. A new deal was started (this was the bug - no new deal!)
            new_deal_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'new_deal'
            ]
            self.assertGreater(len(new_deal_emissions), 0, "New deal should have started after finish_deal!")

            # 3. The new deal started with Bot 2's turn
            last_new_deal = new_deal_emissions[-1]
            self.assertEqual(last_new_deal['data']['json']['player_turn_index'], 1)  # Bot 2 index

            # 4. Bot 2 made a bet (game continued automatically)
            bot2_bet_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('text', '').startswith('Bot 2 bets')
            ]
            self.assertGreater(len(bot2_bet_emissions), 0, "Bot 2 should have bet after new deal started!")

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_bot_turn_after_bot_loses_to_human_check(self, mock_gevent, mock_emit):
        """
        Test when a bot loses to human's check, next deal starts with that bot's turn
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # Setup: Bot 1, Bot 2, Igor (human)
            game = Game(
                ['bot1_sid', 'bot2_sid', 'igor_sid'],
                'test_room',
                ['Bot 1', 'Bot 2', 'Igor'],
                [True, True, False]
            )

            game.deal_in_progress = True
            game.player_turn_index = 2  # Igor's turn
            game.last_bet = 'high_card_A'
            game.last_bettor_index = 1  # Bot 2 made the bet

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {}  # Bet FALSE -> bettor loses

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['K♣']

            # Bot 2 at 1 card
            game.players[1].hand_count = 1

            # Igor checks -> Bot 2 loses
            game.make_move('igor_sid', 'check')

            # Verify new deal started and Bot 2 moved
            new_deal_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                e['data'].get('json', {}).get('action') == 'new_deal'
            ]
            self.assertGreater(len(new_deal_emissions), 0)

            bot2_bet_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                'Bot 2 bets' in e['data'].get('text', '')
            ]
            self.assertGreater(len(bot2_bet_emissions), 0)

    @patch('Game.emit')
    @patch('Game.gevent')
    def test_all_bots_continue_after_deal(self, mock_gevent, mock_emit):
        """
        Test game with only bots - should continue automatically after every deal
        """
        mock_emit_tracker = MockEmit()

        with patch('Game.emit', mock_emit_tracker):
            # All bots
            game = Game(
                ['bot1_sid', 'bot2_sid', 'bot3_sid'],
                'test_room',
                ['Bot 1', 'Bot 2', 'Bot 3'],
                [True, True, True]
            )

            game.deal_in_progress = True
            game.player_turn_index = 2
            game.last_bet = 'pair_K'
            game.last_bettor_index = 1

            from unittest.mock import MagicMock
            game.cards = MagicMock()
            game.cards.combinations = {}

            for p in game.players:
                p.hand = MagicMock()
                p.hand.cards = ['9♣']

            game.players[1].hand_count = 1

            # Bot 3 checks -> Bot 2 loses
            game.make_move('bot3_sid', 'check')

            # Count how many bets were made (should continue automatically)
            bet_emissions = [
                e for e in mock_emit_tracker.emissions
                if e['event'] == 'game_update' and
                'bets' in e['data'].get('text', '')
            ]

            # At least Bot 2 should have bet after losing
            self.assertGreater(len(bet_emissions), 0,
                "Bots should continue playing after deal ends")


if __name__ == '__main__':
    unittest.main()
