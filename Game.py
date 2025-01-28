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
        
    def __repr__(self) -> str:
        return f"Player(sid={self.sid}, hand_count={self.hand_count}, last_bet={self.last_bet}, hand={self.hand}, solver={self.solver})"
    

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
        
        self.deal_in_progess = False
        self.game_finished = False

        print("players", self.players)
        
        self.emit('game_start', {'sids': sids, 'usernames': usernames, 'room_name': self.room})
        
    def emit(self, event, data = {}, to = None):
        
        if to is None:
            to = self.room
        
        print(f"Emmiting {data} to {to}")
        
        emit(event, data, to = to)

    def deal(self):
        
        assert not self.deal_in_progess
    
        hands = Deck().get_hands([player.hand_count for player in self.players])
        
        self.cards = Deck.from_hands(hands)
        n = len(self.cards.cards)
        
        # print([n for n in self.cards.combinations.keys()])

        # Reset all players' last bets
        for player in self.players:
            player.last_bet = None
            
        player_hand_counts = { p.sid: p.hand_count for p in self.players}
        
        for player, hand in zip(self.players, hands):
            player.hand = hand
            player.solver = Solver(hand, n)
            
        for p in self.players:
        
            self.emit('game_update', {
                'text': f"New deal! your hand: {p.hand} | {player_hand_counts=}",
                'your_hand': p.hand,
                'player_hand_counts': player_hand_counts,
                'json': {
                    'action': 'new_deal',
                    'last_bet': None,
                    'player_turn_index': self.player_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet} for p in self.players],
                    'deal_in_progress': self.deal_in_progess,
                    'game_finished': self.game_finished
                }
            }, to = p.sid)
        
        self.last_bet = None
        
        self.deal_in_progess = True
        
        return

    def make_move(self, sid: str, bet: str):
                
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
                'text': f"Player {current_player.sid} checks!"
            })
                    
            loser_player_index = self.player_turn_index
            if not self.cards.combinations[self.last_bet]:
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
        self.player_turn_index = (self.player_turn_index + 1) % len(self.players)
        
        self.emit('game_update', {
            'text': f"Player {current_player.sid} bets {bet}",
            'json': {
                'action': 'bet',
                'current_player': current_player.sid,
                'last_bet': self.last_bet,
                'player_turn_index': self.player_turn_index,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet} for p in self.players],
                'deal_in_progress': self.deal_in_progess,
                'game_finished': self.game_finished
            }
        })
        
        return

    def finish_deal(self, loser_player_index = None):
        
        loser = self.players[loser_player_index]
        loser.hand_count += 1
        MAX_CARDS = 3
        
        self.emit('game_update', {
            'text': f"Player {loser.sid} lost the deal!"
        })
        
        player_cards = [[p.sid, p.hand] for p in self.players]
        
        if loser.hand_count > MAX_CARDS:
        
            self.emit('game_update', {
                'text': f"Player {loser.sid} is out!"
            })
            
            del self.players[loser_player_index]
            
        if len(self.players) <= 1:
            winner = self.players[0]
            self.emit('game_update', {
                'text': f"Player {winner.sid} won!"
            })
            self.game_finished = True
            return
            
        
        self.player_turn_index = loser_player_index % len(self.players)
        
        self.deal_in_progess = False
        
        return

    def end(self):
        pass
        
if __name__ == "__main__":
    player_ids = ["A", "B", "C"]
    game = Game(player_ids) # Initialize a game with 3 players
    game.deal()