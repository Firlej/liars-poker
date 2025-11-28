from typing import List
from Deck import Deck
from collections import namedtuple
from flask_socketio import emit
import random
import time
import gevent

from Solver import Solver, combinations# Player = namedtuple("Player", ["name", "hand", "solver"])

class Player:
    def __init__(self, sid, hand_count, username, hand=None, solver=None, is_bot=False, was_human=False):
        self.sid = sid
        self.hand_count = hand_count
        self.hand = hand
        self.solver = solver
        self.last_bet = None
        self.username = username
        self.is_active = True  # Track if player is still connected/active
        self.is_bot = is_bot  # Track if player is a bot
        self.was_human = was_human  # Track if converted from human to bot

    def __repr__(self) -> str:
        return f"Player(sid={self.sid}, hand_count={self.hand_count}, last_bet={self.last_bet}, is_active={self.is_active}, is_bot={self.is_bot}, hand={self.hand}, solver={self.solver})"
    

class Game:

    def __init__(self, sids: List[str], room: str, usernames: List[str], bot_flags: List[bool] = None, bet_timer_duration: int = 30, socketio=None):

        print("usernames", usernames)
        self.room = room
        self.sids = sids
        self.usernames = usernames
        self.socketio = socketio  # Store socketio instance for background tasks

        # Timer configuration and state
        self.bet_timer_duration = bet_timer_duration  # seconds, 0 = disabled
        self.active_timer_greenlet = None  # Reference to running timer greenlet
        self.timer_target_player_sid = None  # Which player the timer is for

        # Handle bot flags - default to all human players if not specified
        if bot_flags is None:
            bot_flags = [False] * len(sids)

        self.players: List[Player] = [
            Player(
                sid = sid,
                hand_count = 1,
                hand = None,
                solver = None,
                username = usernames[i],
                is_bot = bot_flags[i]
            )
            for i, sid in enumerate(sids)
        ]

        # Store bot instances
        self.bots = {}  # Will be populated in deal() when bots have hands

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
        """Mark a player as inactive (disconnected) and convert to permanent bot."""
        player = next((p for p in self.players if p.sid == sid), None)
        if player:
            player.is_active = False

            # Convert to permanent bot if they were human and game is in progress
            if not player.is_bot and self.deal_in_progess:
                self._convert_player_to_bot(sid, temporary=False)

                # Notify all players about bot takeover
                self.emit('game_update', {
                    'text': f"{player.username} disconnected. Bot taking over.",
                    'json': {
                        'action': 'player_converted_to_bot',
                        'player_sid': sid,
                        'player_username': player.username,
                        'permanent': True
                    }
                })

            return player
        return None
        
    def emit(self, event, data = {}, to = None):

        if to is None:
            to = self.room

        print(f"Emmiting {data} to {to}")

        # Use socketio.emit() if available (works in all contexts)
        # Otherwise fall back to request-scoped emit() (only works in request context)
        if self.socketio:
            self.socketio.emit(event, data, room=to)
        else:
            emit(event, data, to = to)

    def _process_bot_turn(self):
        """Process bot turns automatically until it's a human's turn."""
        # Add delay to make bot moves visible
        gevent.sleep(1.5)

        while self.deal_in_progess and not self.game_finished:
            current_player = self.players[self.player_turn_index]

            # Check if current player is a bot (bots can be active or inactive)
            if not current_player.is_bot:
                break

            # Get bot instance
            bot = self.bots.get(current_player.sid)
            if bot is None:
                break

            # Let bot make decision
            decision = bot.make_decision()

            # Execute bot's move
            self.make_move(current_player.sid, decision)

            # Delay between bot moves
            if self.deal_in_progess and not self.game_finished:
                gevent.sleep(1.5)

    def _start_bet_timer(self, player_sid: str):
        """
        Start a countdown timer for the current player's turn.
        If timer expires, convert player to bot and make automatic move.
        """
        # Check if timer is enabled
        if self.bet_timer_duration <= 0:
            return

        # Don't start timer for bot players or inactive players
        player = next((p for p in self.players if p.sid == player_sid), None)
        if not player or player.is_bot or not player.is_active:
            return

        # Cancel any existing timer
        self._cancel_bet_timer()

        # Store timer target
        self.timer_target_player_sid = player_sid

        # Calculate expiry time
        expires_at = time.time() + self.bet_timer_duration

        # Emit timer_started event for frontend countdown
        self.emit('game_update', {
            'json': {
                'action': 'timer_started',
                'player_sid': player_sid,
                'duration_seconds': self.bet_timer_duration,
                'expires_at': expires_at
            }
        })

        # Spawn timer greenlet
        self.active_timer_greenlet = gevent.spawn_later(
            self.bet_timer_duration, self._bet_timer_expired, player_sid
        )

    def _bet_timer_expired(self, player_sid: str):
        """
        Called when bet timer expires. Convert player to temporary bot and make move.
        """
        try:
            # Verify this is still the correct player's turn
            current_player = self.players[self.player_turn_index]
            if current_player.sid != player_sid:
                return  # Turn already changed

            # Verify player is still active and not already a bot
            if not current_player.is_active or current_player.is_bot:
                return

            # Notify all players that timeout occurred
            self.emit('game_update', {
                'text': f"{current_player.username} timed out. Bot taking over for this turn.",
                'json': {
                    'action': 'player_timeout',
                    'player_sid': player_sid,
                    'player_username': current_player.username
                }
            })

            gevent.sleep(1.0)  # Let players see the timeout message

            # Convert to temporary bot for this move only
            self._convert_player_to_bot(player_sid, temporary=True)

            # Make bot decision
            bot = self.bots.get(player_sid)
            if bot:
                decision = bot.make_decision()
                self.make_move(player_sid, decision)

                # If deal finished, automatically start next deal (same logic as in app.py bet handler)
                if not self.deal_in_progess and not self.game_finished:
                    self.deal()

        except gevent.GreenletExit:
            # Timer was cancelled because player made a move
            pass
        except Exception as e:
            print(f"Error in _bet_timer_expired: {e}")
            import traceback
            traceback.print_exc()

    def _cancel_bet_timer(self):
        """
        Cancel the active bet timer if one exists.
        Called when player makes a move or game state changes.
        """
        if self.active_timer_greenlet is not None:
            try:
                # Emit cancellation event for frontend
                if self.timer_target_player_sid:
                    self.emit('game_update', {
                        'json': {
                            'action': 'timer_cancelled',
                            'player_sid': self.timer_target_player_sid
                        }
                    })

                # Don't kill the greenlet if we're currently inside it
                # (this happens when bot makes a move after timeout)
                if self.active_timer_greenlet != gevent.getcurrent():
                    self.active_timer_greenlet.kill()
            except Exception as e:
                print(f"Error cancelling timer: {e}")
            finally:
                self.active_timer_greenlet = None
                self.timer_target_player_sid = None

    def _convert_player_to_bot(self, player_sid: str, temporary: bool = False):
        """
        Convert a human player to a bot player.

        Args:
            player_sid: SID of player to convert
            temporary: If True, bot only acts for one turn (timeout scenario)
                       If False, permanent bot conversion (disconnect scenario)
        """
        player = next((p for p in self.players if p.sid == player_sid), None)
        if not player or player.is_bot:
            return

        # Mark as bot and track that this was a human
        player.is_bot = True
        player.was_human = True

        # Create bot instance if needed (player must have hand and solver)
        if player_sid not in self.bots and player.hand and player.solver:
            from BotPlayer import BotPlayer
            self.bots[player_sid] = BotPlayer(player, self)

        print(f"Converted {player.username} to {'temporary' if temporary else 'permanent'} bot")

    def _restore_player_from_bot(self, player_sid: str):
        """
        Restore a temporarily converted bot back to human player.
        Only works if player.was_human is True (temporary conversion).
        """
        player = next((p for p in self.players if p.sid == player_sid), None)
        if not player or not player.was_human:
            return

        # Restore to human player
        player.is_bot = False
        # Keep was_human flag in case they timeout again

        print(f"Restored {player.username} from temporary bot to human")

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
            player.hand = Deck(hand)  # Convert list to Deck object for .combinations attribute
            player.solver = Solver(hand, n)

            # Initialize bot if this is a bot player
            if player.is_bot:
                from BotPlayer import BotPlayer
                self.bots[player.sid] = BotPlayer(player, self)

        # Ensure player_turn_index points to an active player
        self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
        if self.player_turn_index is None:
            self.game_finished = True
            return

        self.last_bet = None
        self.last_bettor_index = None  # Reset last bettor for new deal
        self.deal_in_progess = True  # Set this BEFORE emitting events

        for p in self.players:
            if not p.is_active or p.is_bot:
                continue

            self.emit('game_update', {
                'text': f"New deal! Your hand: {p.hand.cards}",
                'your_hand': p.hand.cards,
                'player_hand_counts': player_hand_counts,
                'json': {
                    'action': 'new_deal',
                    'last_bet': None,
                    'player_turn_index': self.player_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                    'deal_in_progress': self.deal_in_progess,
                    'game_finished': self.game_finished,
                    'your_hand': p.hand.cards
                }
            }, to = p.sid)

        # Start timer for first player
        current_player = self.players[self.player_turn_index]
        self._start_bet_timer(current_player.sid)

        # Process bot turn if current player is a bot
        self._process_bot_turn()

        return

    def make_move(self, sid: str, bet: str):
        # Cancel timer immediately to prevent race conditions
        self._cancel_bet_timer()

        current_player = self.players[self.player_turn_index]
        was_temporary_bot = current_player.is_bot and current_player.was_human

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
        
            # Collect all players' hands to show after check
            player_hands = {}
            for p in self.players:
                if p.hand is not None:
                    player_hands[p.sid] = p.hand.cards
                else:
                    player_hands[p.sid] = []

            self.emit('game_update', {
                'text': f"{current_player.username} checks!",
                'json': {
                    'action': 'check',
                    'current_player': current_player.sid,
                    'last_bet': self.last_bet,
                    'player_turn_index': self.player_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                    'deal_in_progress': self.deal_in_progess,
                    'game_finished': self.game_finished,
                    'player_hands': player_hands
                }
            })

            # Add delay to allow frontend to process check event
            gevent.sleep(0.5)

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

        # Restore temporary bot to human after their turn
        if was_temporary_bot:
            self._restore_player_from_bot(current_player.sid)

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

        # Add delay to allow frontend to process bet event
        gevent.sleep(0.5)

        # Start timer for next player BEFORE processing bot turns
        next_player = self.players[self.player_turn_index]
        self._start_bet_timer(next_player.sid)

        # Process bot turn if next player is a bot
        self._process_bot_turn()

        return

    def finish_deal(self, loser_player_index = None):
        # Cancel any active timer when deal finishes
        self._cancel_bet_timer()

        # Restore all temporary bots back to human for next deal
        for player in self.players:
            if player.is_bot and player.was_human:
                self._restore_player_from_bot(player.sid)

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

            # Add delay to allow frontend to process lost event
            gevent.sleep(0.5)

            player_cards = [[p.sid, p.hand.cards] for p in self.players]

            if loser.hand_count > MAX_CARDS:

                self.emit('game_update', {
                    'text': f"{loser.username} is out!"
                })

                # Add delay to allow frontend to process elimination event
                gevent.sleep(0.5)

                del self.players[loser_player_index]

        # Check if only one active player remains (win condition)
        active_players = self.get_active_players()
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                self.emit('game_update', {
                    'text': f"{winner.username} won!",
                    'json': {
                        'action': 'game_won',
                        'winner_sid': winner.sid,
                        'winner_username': winner.username,
                        'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players]
                    }
                })
                # Add delay to allow frontend to process won event
                gevent.sleep(0.5)
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

        # Note: We don't call _process_bot_turn here because finish_deal ends the current deal
        # The next deal will be started by the user/system and will handle bot turns

        return

    def end(self):
        pass
        
if __name__ == "__main__":
    player_ids = ["A", "B", "C"]
    game = Game(player_ids) # Initialize a game with 3 players
    game.deal()