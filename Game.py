from typing import List
from Deck import Deck
from collections import namedtuple
import random
import time
import gevent
from gevent.lock import BoundedSemaphore

from Solver import Solver, combinations# Player = namedtuple("Player", ["name", "hand", "solver"])

class Player:
    def __init__(self, sid, hand_count, username, hand=None, solver=None, is_bot=False):
        self.sid = sid
        self.hand_count = hand_count
        self.hand = hand
        self.solver = solver
        self.last_bet = None
        self.username = username
        self.is_active = True  # Track if player is still connected/active
        self.is_bot = is_bot  # Track if player is a bot
        self.ready_for_next_deal = False  # Track if player is ready for next deal

    def __repr__(self) -> str:
        return f"Player(sid={self.sid}, hand_count={self.hand_count}, last_bet={self.last_bet}, is_active={self.is_active}, is_bot={self.is_bot}, ready={self.ready_for_next_deal}, hand={self.hand}, solver={self.solver})"
    

class Game:
    # Timeout constants (in seconds)
    TURN_TIMEOUT_SECONDS = 60  # How long to wait for a player's turn
    READY_TIMEOUT_SECONDS = 60  # How long to wait for ready confirmations

    def __init__(self, sids: List[str], room: str, usernames: List[str], bot_flags: List[bool] = None, socketio=None):

        print("usernames", usernames)
        self.room = room
        self.sids = sids
        self.usernames = usernames
        self.socketio = socketio  # Store socketio instance for emitting events

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
        self.last_bet = None  # Initialize last_bet to prevent AttributeError
        self.bot_processing_lock = BoundedSemaphore(1)  # Prevent concurrent bot turn processing

        self.deal_in_progress = False
        self.game_finished = False

        # Turn timeout tracking
        self.turn_start_time = None

        # Ready phase timeout tracking
        self.ready_phase_start_time = None

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

    def get_player_index_by_sid(self, sid: str):
        """Find player index by their SID. Returns None if not found."""
        for i, player in enumerate(self.players):
            if player.sid == sid:
                return i
        return None

    def mark_player_inactive(self, sid: str):
        """Mark a player as inactive (disconnected) but keep them in the game."""
        player = next((p for p in self.players if p.sid == sid), None)
        if player:
            player.is_active = False
            return player
        return None

    def start_turn_timer(self):
        """Start the turn timer for the current player."""
        self.turn_start_time = time.time()

    def check_turn_timeout(self) -> bool:
        """Check if the current turn has timed out. Returns True if timeout exceeded."""
        if self.turn_start_time is None:
            return False
        if not self.deal_in_progress:
            return False
        # Don't timeout bots - they handle their own timing
        if self.player_turn_index < len(self.players):
            current_player = self.players[self.player_turn_index]
            if current_player.is_bot:
                return False
        return (time.time() - self.turn_start_time) > self.TURN_TIMEOUT_SECONDS

    def handle_turn_timeout(self):
        """Handle a turn timeout by marking the player inactive and advancing the turn."""
        if not self.deal_in_progress or self.game_finished:
            return False

        if self.player_turn_index < 0 or self.player_turn_index >= len(self.players):
            return False

        current_player = self.players[self.player_turn_index]

        # Don't timeout bots
        if current_player.is_bot:
            return False

        print(f"[TIMEOUT] Turn timeout for {current_player.username}")

        # Mark player as inactive (treat timeout as disconnect)
        current_player.is_active = False

        # Emit timeout event
        self.emit('game_update', {
            'text': f"{current_player.username}'s turn timed out. They have been marked as disconnected.",
            'json': {
                'action': 'turn_timeout',
                'timed_out_player_sid': current_player.sid,
                'timed_out_player_username': current_player.username,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                'deal_in_progress': self.deal_in_progress,
                'game_finished': self.game_finished
            }
        })

        # Find next active player
        next_index = self.get_next_active_player_index(self.player_turn_index + 1)
        if next_index is None:
            # No active players left
            self.game_finished = True
            self.emit('game_update', {
                'text': "Game ended - no active players remaining.",
                'json': {
                    'action': 'game_end',
                    'deal_in_progress': False,
                    'game_finished': True
                }
            })
            return True

        # Check if only one active player remains
        active_players = self.get_active_players()
        if len(active_players) == 1:
            winner = active_players[0]
            self.emit('game_update', {
                'text': f"{winner.username} won! All other players have timed out or disconnected.",
                'json': {
                    'action': 'game_won',
                    'winner_sid': winner.sid,
                    'winner_username': winner.username,
                    'deal_in_progress': False,
                    'game_finished': True
                }
            })
            self.game_finished = True
            return True

        # Advance to next player
        self.player_turn_index = next_index
        next_player = self.players[next_index]

        # Reset turn timer for the new player
        self.start_turn_timer()

        self.emit('game_update', {
            'text': f"Turn skipped to {next_player.username}.",
            'json': {
                'action': 'turn_skipped',
                'player_turn_index': self.player_turn_index,
                'current_player_sid': next_player.sid,
                'current_player_username': next_player.username,
                'last_bet': self.last_bet,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                'deal_in_progress': self.deal_in_progress,
                'game_finished': self.game_finished,
                'turn_timeout_seconds': self.TURN_TIMEOUT_SECONDS
            }
        })

        # Process bot turn if next player is a bot
        if next_player.is_bot and next_player.is_active:
            self._process_bot_turn()

        return True

    def start_ready_timer(self):
        """Start the ready phase timer."""
        self.ready_phase_start_time = time.time()

    def check_ready_timeout(self) -> bool:
        """Check if the ready phase has timed out. Returns True if timeout exceeded."""
        if self.ready_phase_start_time is None:
            return False
        if self.deal_in_progress:
            return False
        if self.game_finished:
            return False
        return (time.time() - self.ready_phase_start_time) > self.READY_TIMEOUT_SECONDS

    def handle_ready_timeout(self):
        """Handle ready phase timeout by auto-readying inactive players and starting the deal."""
        if self.deal_in_progress or self.game_finished:
            return False

        print("[TIMEOUT] Ready phase timeout - auto-readying disconnected players")

        # Mark all inactive players as ready (they won't be included in the deal anyway)
        # Also auto-ready any players who haven't clicked ready
        for player in self.players:
            if not player.is_active or not player.ready_for_next_deal:
                if not player.is_bot:
                    print(f"[TIMEOUT] Auto-readying {player.username} (active: {player.is_active})")
                player.ready_for_next_deal = True

        # Emit event about timeout
        self.emit('game_update', {
            'text': 'Ready phase timed out. Starting next deal...',
            'json': {
                'action': 'ready_timeout',
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active, 'ready_for_next_deal': p.ready_for_next_deal} for p in self.players],
                'deal_in_progress': self.deal_in_progress,
                'game_finished': self.game_finished
            }
        })

        # Reset ready phase timer
        self.ready_phase_start_time = None

        # Reset ready states and start the deal
        self.reset_ready_states()
        self.deal()
        return True

    def get_player_by_username(self, username: str):
        """Find a player by their username. Returns None if not found."""
        return next((p for p in self.players if p.username == username), None)

    def reconnect_player(self, username: str, new_sid: str):
        """
        Reconnect a player with a new SID after reconnection.
        Updates the player's SID and marks them as active.
        Returns the player if found, None otherwise.
        """
        player = self.get_player_by_username(username)
        if player:
            old_sid = player.sid
            player.sid = new_sid
            player.is_active = True

            # Update the sids list
            for i, sid in enumerate(self.sids):
                if sid == old_sid:
                    self.sids[i] = new_sid
                    break

            # If this was a bot, update the bots dict
            if old_sid in self.bots:
                self.bots[new_sid] = self.bots.pop(old_sid)

            print(f"[RECONNECT] Player {username} reconnected: {old_sid[-4:] if old_sid else 'None'} -> {new_sid[-4:]}")
            return player
        return None

    def validate_game_state(self):
        """
        Check for invalid game states that could cause the game to become stuck.
        Returns a tuple: (is_valid, list_of_issues)
        """
        issues = []

        # Check 1: player_turn_index bounds
        if self.player_turn_index < 0 or self.player_turn_index >= len(self.players):
            issues.append(f"player_turn_index {self.player_turn_index} out of bounds (0-{len(self.players)-1})")

        # Check 2: Current player is active (only if deal is in progress)
        if self.deal_in_progress and len(self.players) > 0:
            if 0 <= self.player_turn_index < len(self.players):
                current_player = self.players[self.player_turn_index]
                if not current_player.is_active:
                    issues.append(f"current player {current_player.username} is inactive but it's their turn")

        # Check 3: At least one active player exists
        active_players = self.get_active_players()
        if len(active_players) == 0 and not self.game_finished:
            issues.append("no active players but game not marked as finished")

        # Check 4: Inconsistent flags - deal in progress but game finished
        if self.deal_in_progress and self.game_finished:
            issues.append("deal_in_progress=True but game_finished=True")

        # Check 5: last_bettor_index bounds (if set)
        if self.last_bettor_index is not None:
            if self.last_bettor_index < 0 or self.last_bettor_index >= len(self.players):
                issues.append(f"last_bettor_index {self.last_bettor_index} out of bounds")

        return (len(issues) == 0, issues)

    def recover_game_state(self):
        """
        Attempt to recover from invalid game states.
        Returns True if recovery was successful, False if game should end.
        """
        is_valid, issues = self.validate_game_state()

        if is_valid:
            return True  # Nothing to recover

        print(f"[RECOVERY] Detected issues: {issues}")

        # Recovery 1: Fix out-of-bounds player_turn_index
        if self.player_turn_index < 0 or self.player_turn_index >= len(self.players):
            if len(self.players) > 0:
                self.player_turn_index = self.player_turn_index % len(self.players)
                print(f"[RECOVERY] Corrected player_turn_index to {self.player_turn_index}")
            else:
                self.game_finished = True
                print("[RECOVERY] No players left, ending game")
                return False

        # Recovery 2: Find next active player if current is inactive
        if self.deal_in_progress:
            current_player = self.players[self.player_turn_index]
            if not current_player.is_active:
                next_index = self.get_next_active_player_index(self.player_turn_index)
                if next_index is not None:
                    self.player_turn_index = next_index
                    print(f"[RECOVERY] Moved turn to next active player at index {next_index}")
                else:
                    self.game_finished = True
                    print("[RECOVERY] No active players, ending game")
                    return False

        # Recovery 3: Fix inconsistent flags
        if self.deal_in_progress and self.game_finished:
            self.deal_in_progress = False
            print("[RECOVERY] Reset deal_in_progress to False since game is finished")

        # Recovery 4: No active players
        if len(self.get_active_players()) == 0:
            self.game_finished = True
            print("[RECOVERY] No active players, ending game")
            return False

        # Recovery 5: Fix out-of-bounds last_bettor_index
        if self.last_bettor_index is not None:
            if self.last_bettor_index < 0 or self.last_bettor_index >= len(self.players):
                self.last_bettor_index = None
                print("[RECOVERY] Reset invalid last_bettor_index to None")

        # Emit state update to clients after recovery
        self.emit('game_update', {
            'text': 'Game state recovered',
            'json': {
                'action': 'state_recovered',
                'player_turn_index': self.player_turn_index,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                'deal_in_progress': self.deal_in_progress,
                'game_finished': self.game_finished,
                'last_bet': self.last_bet
            }
        })

        return True

    def all_players_ready_for_next_deal(self):
        """Check if all active human players are ready for the next deal. Bots are always considered ready."""
        active_players = self.get_active_players()
        has_human = False
        for player in active_players:
            # Bots are always ready
            if player.is_bot:
                continue
            # Found a human player
            has_human = True
            # Human players must explicitly be ready
            if not player.ready_for_next_deal:
                return False
        # If no human players exist, return False (should use all_bots check instead)
        # This prevents the ready system from triggering when only bots remain
        return has_human

    def reset_ready_states(self):
        """Reset all players' ready states to False."""
        for player in self.players:
            player.ready_for_next_deal = False

    def mark_player_ready(self, sid: str):
        """Mark a player as ready for the next deal. Returns True if all players are now ready."""
        player = next((p for p in self.players if p.sid == sid), None)
        if player:
            player.ready_for_next_deal = True

            # Emit update to all players about ready status
            self.emit('game_update', {
                'text': f'{player.username} is ready for next deal',
                'json': {
                    'action': 'player_ready',
                    'player_sid': sid,
                    'players_ready': [p.sid for p in self.players if p.ready_for_next_deal],
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active, 'ready_for_next_deal': p.ready_for_next_deal} for p in self.players],
                    'player_turn_index': self.player_turn_index,
                    'deal_in_progress': self.deal_in_progress,
                    'game_finished': self.game_finished
                }
            })

            # Check if all players are ready
            if self.all_players_ready_for_next_deal():
                # Reset ready states
                self.reset_ready_states()
                # Start the next deal
                self.deal()
                return True
        return False

    def emit(self, event, data = {}, to = None):

        if to is None:
            to = self.room

        print(f"Emmiting {data} to {to}")

        if self.socketio:
            self.socketio.emit(event, data, room=to)
        else:
            # Fallback for backwards compatibility (won't work in background tasks)
            from flask_socketio import emit
            emit(event, data, to=to)

    def _process_bot_turn(self):
        """Process bot turns automatically until it's a human's turn."""
        # Try to acquire lock (non-blocking) to prevent concurrent bot processing
        acquired = self.bot_processing_lock.acquire(blocking=False)
        if not acquired:
            return

        try:
            # Add delay to make bot moves visible
            gevent.sleep(1.5)

            # Safety counter to prevent infinite loops
            # 500 is high enough for legitimate games (even with many bots)
            # but still catches true infinite loops
            max_iterations = 500
            iterations = 0

            while self.deal_in_progress and not self.game_finished:
                iterations += 1
                if iterations > max_iterations:
                    print(f"[BOT WARNING] Exceeded max iterations ({max_iterations}), breaking loop")
                    break

                # Validate state before processing
                if not self.recover_game_state():
                    break

                # Bounds check before accessing players
                if self.player_turn_index < 0 or self.player_turn_index >= len(self.players):
                    print(f"[BOT ERROR] Invalid player_turn_index: {self.player_turn_index}")
                    break

                current_player = self.players[self.player_turn_index]

                # Check if current player is a bot
                if not current_player.is_bot or not current_player.is_active:
                    break

                # Get bot instance
                bot = self.bots.get(current_player.sid)
                if bot is None:
                    print(f"[BOT ERROR] Bot instance not found for {current_player.username}")
                    break

                try:
                    # Let bot make decision
                    decision = bot.make_decision()

                    # Execute bot's move
                    self.make_move(current_player.sid, decision)
                except Exception as e:
                    print(f"[BOT ERROR] Exception during bot turn: {e}")
                    # Skip this bot's turn to prevent infinite loop
                    next_index = self.get_next_active_player_index(self.player_turn_index + 1)
                    if next_index is not None:
                        self.player_turn_index = next_index
                    else:
                        self.game_finished = True
                    break

                # Delay between bot moves
                if self.deal_in_progress and not self.game_finished:
                    gevent.sleep(1.5)
        finally:
            # Always release the lock
            self.bot_processing_lock.release()

    def deal(self):

        assert not self.deal_in_progress

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
        self.deal_in_progress = True  # Set this BEFORE emitting events

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
                    'deal_in_progress': self.deal_in_progress,
                    'game_finished': self.game_finished,
                    'your_hand': p.hand.cards,
                    'turn_timeout_seconds': self.TURN_TIMEOUT_SECONDS
                }
            }, to = p.sid)

        # Start turn timer for human players
        current_player = self.players[self.player_turn_index]
        if not current_player.is_bot:
            self.start_turn_timer()

        # Process bot turn if current player is a bot
        self._process_bot_turn()

        return

    def make_move(self, sid: str, bet: str):

        # State validation before processing any move
        is_valid, issues = self.validate_game_state()
        if not is_valid:
            print(f"[MAKE_MOVE] Invalid state detected: {issues}")
            if not self.recover_game_state():
                self.emit('game_update', {
                    'text': "Game error: Unable to recover game state. Please start a new game.",
                    'json': {
                        'action': 'game_error',
                        'error': 'unrecoverable_state',
                        'issues': issues
                    }
                }, to=sid)
                return

        # Bounds check before accessing players array
        if self.player_turn_index < 0 or self.player_turn_index >= len(self.players):
            self.emit('game_update', {
                'text': "Game error: Invalid turn index. Please wait for game state to sync.",
                'json': {
                    'action': 'game_error',
                    'error': 'invalid_turn_index'
                }
            }, to=sid)
            return

        current_player = self.players[self.player_turn_index]

        # Check if current player is still active
        if not current_player.is_active:
            # Skip to next active player
            self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
            if self.player_turn_index is None:
                self.game_finished = True
                return
            current_player = self.players[self.player_turn_index]

        # CRITICAL: Validate that the move is from the current player
        # This prevents disconnected players' moves from being applied to active players
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
                    'deal_in_progress': self.deal_in_progress,
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

        # Move to next active player
        next_index = self.get_next_active_player_index(self.player_turn_index + 1)
        if next_index is None:
            self.game_finished = True
            return
        self.player_turn_index = next_index

        # Start turn timer for the next player (if human)
        next_player = self.players[next_index]
        if not next_player.is_bot:
            self.start_turn_timer()

        self.emit('game_update', {
            'text': f"{current_player.username} bets {bet}",
            'json': {
                'action': 'bet',
                'current_player': current_player.sid,
                'last_bet': self.last_bet,
                'player_turn_index': self.player_turn_index,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                'deal_in_progress': self.deal_in_progress,
                'game_finished': self.game_finished,
                'turn_timeout_seconds': self.TURN_TIMEOUT_SECONDS
            }
        })

        # Add delay to allow frontend to process bet event
        gevent.sleep(0.5)

        # Process bot turn if next player is a bot
        self._process_bot_turn()

        return

    def finish_deal(self, loser_player_index = None):

        loser = self.players[loser_player_index]
        loser_sid = loser.sid  # Store SID before potential deletion

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

            # Calculate the next turn index BEFORE emitting
            # Set next turn to the loser by SID (for when they're not eliminated)
            next_turn_index = loser_player_index

            self.emit('game_update', {
                'text': f"{loser.username} lost the deal!",
                'json': {
                    'action': 'deal_result',
                    'loser_sid': loser.sid,
                    'loser_username': loser.username,
                    'player_turn_index': next_turn_index,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                    'deal_in_progress': self.deal_in_progress,
                    'game_finished': self.game_finished
                }
            })

            # Add delay to allow frontend to process lost event
            gevent.sleep(0.5)

            # Note: player_cards variable is not used, removing to avoid AttributeError
            # player_cards = [[p.sid, p.hand.cards] for p in self.players]

            if loser.hand_count > MAX_CARDS:

                # After elimination, next player should be the one after loser
                # But we need to recalculate after deletion
                next_turn_after_elimination = loser_player_index % max(1, len(self.players) - 1)

                self.emit('game_update', {
                    'text': f"{loser.username} is out!",
                    'json': {
                        'action': 'player_eliminated',
                        'eliminated_sid': loser.sid,
                        'eliminated_username': loser.username,
                        'player_turn_index': next_turn_after_elimination,
                        'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                        'deal_in_progress': self.deal_in_progress,
                        'game_finished': self.game_finished
                    }
                })

                # Add delay to allow frontend to process elimination event
                gevent.sleep(0.5)

                del self.players[loser_player_index]

        # Check if only one active player remains (win condition)
        active_players = self.get_active_players()
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                winner_index = self.get_player_index_by_sid(winner.sid)
                self.emit('game_update', {
                    'text': f"{winner.username} won!",
                    'json': {
                        'action': 'game_won',
                        'winner_sid': winner.sid,
                        'winner_username': winner.username,
                        'player_turn_index': winner_index if winner_index is not None else 0,
                        'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in self.players],
                        'deal_in_progress': False,
                        'game_finished': True
                    }
                })
                # Add delay to allow frontend to process won event
                gevent.sleep(0.5)
            else:
                self.emit('game_update', {
                    'text': "Game ended - no active players remaining.",
                    'json': {
                        'action': 'game_end',
                        'deal_in_progress': False,
                        'game_finished': True
                    }
                })
            self.game_finished = True
            return


        # Set next turn to the loser by SID (indices may have shifted after deletion)
        new_loser_index = self.get_player_index_by_sid(loser_sid)
        if new_loser_index is not None:
            # Loser is still in game, they start next deal
            self.player_turn_index = new_loser_index
        else:
            # Loser was eliminated, start with the player who was after them
            # After deletion, loser_player_index now points to the next player
            # (unless it was the last player, then wrap to 0)
            self.player_turn_index = loser_player_index % len(self.players) if len(self.players) > 0 else 0

        # Ensure we're pointing to an active player
        self.player_turn_index = self.get_next_active_player_index(self.player_turn_index)
        if self.player_turn_index is None:
            self.game_finished = True
            return

        self.deal_in_progress = False

        # Check if all players are bots - if so, start next deal immediately
        active_players = self.get_active_players()
        all_bots = all(p.is_bot for p in active_players)

        if all_bots:
            # All bots - start next deal immediately
            self.deal()
        else:
            # There are human players - wait for them to be ready
            # Start the ready phase timer
            self.start_ready_timer()

            # Emit a waiting_for_ready event to notify clients
            self.emit('game_update', {
                'text': 'Waiting for players to be ready...',
                'json': {
                    'action': 'waiting_for_ready',
                    'players_ready': [p.sid for p in self.players if p.ready_for_next_deal],
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active, 'ready_for_next_deal': p.ready_for_next_deal} for p in self.players],
                    'player_turn_index': self.player_turn_index,
                    'deal_in_progress': self.deal_in_progress,
                    'game_finished': self.game_finished,
                    'ready_timeout_seconds': self.READY_TIMEOUT_SECONDS
                }
            })

        return

    def get_game_state(self, for_sid=None):
        """
        Returns a serializable dict of the current game state.
        Used for state resync when clients request it.

        Args:
            for_sid: If provided, include that player's hand in the response
        """
        player_list = []
        for p in self.players:
            player_data = {
                'sid': p.sid,
                'username': p.username,
                'hand_count': p.hand_count,
                'last_bet': p.last_bet,
                'is_active': p.is_active,
                'is_bot': p.is_bot,
                'ready_for_next_deal': p.ready_for_next_deal
            }
            player_list.append(player_data)

        state = {
            'room': self.room,
            'player_turn_index': self.player_turn_index,
            'last_bet': self.last_bet,
            'last_bettor_index': self.last_bettor_index,
            'deal_in_progress': self.deal_in_progress,
            'game_finished': self.game_finished,
            'players': player_list,
            'players_ready': [p.sid for p in self.players if p.ready_for_next_deal]
        }

        # Include the requesting player's hand if they're in the game
        if for_sid:
            player = next((p for p in self.players if p.sid == for_sid), None)
            if player and player.hand is not None:
                state['your_hand'] = player.hand.cards

        # Include validation status
        is_valid, issues = self.validate_game_state()
        state['state_valid'] = is_valid
        if not is_valid:
            state['state_issues'] = issues

        return state

    def end(self):
        pass

if __name__ == "__main__":
    player_ids = ["A", "B", "C"]
    game = Game(player_ids) # Initialize a game with 3 players
    game.deal()