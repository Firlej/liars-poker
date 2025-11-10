from typing import List
from Deck import Deck
from collections import namedtuple
from flask_socketio import emit
import random

from Solver import Solver, combinations# Player = namedtuple("Player", ["name", "hand", "solver"])

class Player:
    def __init__(self, sid, hand_count, username, hand=None, solver=None):
        self.sid = sid
        self.hand_count = hand_count
        self.hand = hand
        self.solver = solver
        self.last_bet = None
        self.username = username
        self.is_active = True  # Track if player is still connected/active

    def __repr__(self) -> str:
        return f"Player(sid={self.sid}, hand_count={self.hand_count}, last_bet={self.last_bet}, is_active={self.is_active}, hand={self.hand}, solver={self.solver})"
    

class Game:
    
    def __init__(self, sids: List[str], room: str, usernames: List[str]):
        
        print("usernames", usernames)
        self.room = room
        self.sids = sids
        self.usernames = usernames
            
        self.players: List[Player] = [
            Player(
                sid = sid,
                hand_count = 1,
                hand = None,
                solver = None,
                username = usernames[i]
            )
            for i, sid in enumerate(sids)
        ]
        
        self.player_turn_index = 0
        self.last_bettor_index = None  # Track who made the last bet

        self.deal_in_progess = False
        self.game_finished = False

        print("players", self.players)

        self.emit('game_start', {'sids': sids, 'usernames': usernames, 'room_name': self.room})

    def get_active_players(self):
        """Returns a list of players who are still active (connected)."""
        return [p for p in self.players if p.is_active]

    def get_next_active_player_index(self, start_index):
        """Find the next active player starting from start_index."""
        if not self.get_active_players():
            return None

        checked = 0
        current_index = start_index % len(self.players)

        while checked < len(self.players):
            if self.players[current_index].is_active:
                return current_index
            current_index = (current_index + 1) % len(self.players)
            checked += 1

        return None

    def mark_player_inactive(self, sid: str):
        """Mark a player as inactive (disconnected) but keep them in the game."""
        player = next((p for p in self.players if p.sid == sid), None)
        if player:
            player.is_active = False
            return player
        return None
        
    def emit(self, event, data = {}, to = None):
        
        if to is None:
            to = self.room
        
        print(f"Emmiting {data} to {to}")
        
        emit(event, data, to = to)

    def deal(self):

        assert not self.deal_in_progess

        active_players = self.get_active_players()

        # Check if we have enough active players to continue
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                self.emit('game_update', {
                    'text': f"{winner.username} won! All other players have left."
                })
            else:
                self.emit('game_update', {
                    'text': "Game ended - no active players remaining."
                })
            self.game_finished = True
            return

        hands = Deck().get_hands([player.hand_count for player in active_players])

        self.cards = Deck.from_hands(hands)
        n = len(self.cards.cards)

        # print([n for n in self.cards.combinations.keys()])

        # Reset all players' last bets
        for player in self.players:
            player.last_bet = None

        player_hand_counts = { p.sid: p.hand_count for p in self.players}

        for player, hand in zip(active_players, hands):
            player.hand = hand
            player.solver = Solver(hand, n)

        # Ensure player_turn_index points to an active player
        self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
        if self.player_turn_index is None:
            self.game_finished = True
            return

        for p in self.players:
            if not p.is_active:
                continue

            self.emit('game_update', {
                'text': f"New deal! Your hand: {p.hand}",
                'your_hand': p.hand,
                'player_hand_counts': player_hand_counts,
                'json': {
                    'action': 'new_deal',
                    'last_bet': None,
                    'player_turn_index': self.player_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                    'deal_in_progress': self.deal_in_progess,
                    'game_finished': self.game_finished,
                    'your_hand': p.hand
                }
            }, to = p.sid)

        self.last_bet = None
        self.last_bettor_index = None  # Reset last bettor for new deal

        self.deal_in_progess = True

        return

    def make_move(self, sid: str, bet: str):

        current_player = self.players[self.player_turn_index]

        # Check if current player is still active
        if not current_player.is_active:
            # Skip to next active player
            self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
            if self.player_turn_index is None:
                self.game_finished = True
                return
            current_player = self.players[self.player_turn_index]

        if current_player.sid != sid:

            self.emit('game_update', {
                'text': "Not your turn!"
            }, to = sid)

            return
        
        if bet == "check":
            if self.last_bet is None:
        
                self.emit('game_update', {
                    'text': "You can't check on first turn. Place a bet."
                }, to = sid)
                
                return
        
            self.emit('game_update', {
                'text': f"{current_player.username} checks!",
                'json': {
                    'action': 'check',
                    'current_player': current_player.sid,
                    'last_bet': self.last_bet,
                    'player_turn_index': self.player_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                    'deal_in_progress': self.deal_in_progess,
                    'game_finished': self.game_finished
                }
            })

            # Determine loser: checker or last bettor
            loser_player_index = self.player_turn_index
            if not self.cards.combinations[self.last_bet]:
                # Bet was false, so the last bettor loses
                # Use last_bettor_index if available, otherwise try to find previous player
                if self.last_bettor_index is not None:
                    loser_player_index = self.last_bettor_index
                else:
                    # Fallback: find previous active player (this shouldn't happen with proper tracking)
                    loser_player_index = (self.player_turn_index - 1) % len(self.players)

            self.finish_deal(loser_player_index)
            return
        
        if bet not in self.cards.combinations:
        
            self.emit('game_update', {
                'text': "Invalid bet. Try again."
            }, to = sid)
            
            return
        
        def is_bet_higher(bet: str) -> bool:
            def bet_index(bet: str):
                return list(self.cards.combinations.keys()).index(bet)
            if self.last_bet is not None and bet_index(self.last_bet) >= bet_index(bet):
                return False
            return True
        
        if not is_bet_higher(bet):
        
            self.emit('game_update', {
                'text': "Your bet must be higher than the last one. Try again."
            }, to = sid)
            
            return
        
        self.last_bet = bet
        current_player.last_bet = bet
        self.last_bettor_index = self.player_turn_index  # Track who made this bet

        # Move to next active player
        next_index = self.get_next_active_player_index(self.player_turn_index + 1)
        if next_index is None:
            self.game_finished = True
            return
        self.player_turn_index = next_index

        self.emit('game_update', {
            'text': f"{current_player.username} bets {bet}",
            'json': {
                'action': 'bet',
                'current_player': current_player.sid,
                'last_bet': self.last_bet,
                'player_turn_index': self.player_turn_index,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                'deal_in_progress': self.deal_in_progess,
                'game_finished': self.game_finished
            }
        })
        
        return

    def finish_deal(self, loser_player_index = None):

        loser = self.players[loser_player_index]

        # If loser is inactive (disconnected), they're effectively already out
        if not loser.is_active:
            self.emit('game_update', {
                'text': f"{loser.username} lost the deal (but already disconnected)!"
            })
            # Remove the inactive player from the game
            del self.players[loser_player_index]
        else:
            loser.hand_count += 1
            MAX_CARDS = 3

            self.emit('game_update', {
                'text': f"{loser.username} lost the deal!"
            })

            player_cards = [[p.sid, p.hand] for p in self.players]

            if loser.hand_count > MAX_CARDS:

                self.emit('game_update', {
                    'text': f"{loser.username} is out!"
                })

                del self.players[loser_player_index]

        # Check if only one active player remains (win condition)
        active_players = self.get_active_players()
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                self.emit('game_update', {
                    'text': f"{winner.username} won!"
                })
            else:
                self.emit('game_update', {
                    'text': "Game ended - no active players remaining."
                })
            self.game_finished = True
            return


        # Set next turn to the loser (or next active player if loser was eliminated)
        if loser_player_index < len(self.players):
            self.player_turn_index = loser_player_index % len(self.players)
        else:
            self.player_turn_index = 0

        # Ensure we're pointing to an active player
        self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
        if self.player_turn_index is None:
            self.game_finished = True
            return

        self.deal_in_progess = False

        return

    def end(self):
        pass
        
if __name__ == "__main__":
    player_ids = ["A", "B", "C"]
    game = Game(player_ids) # Initialize a game with 3 players
    game.deal()