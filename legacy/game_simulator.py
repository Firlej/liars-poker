#!/usr/bin/env python3
"""
Bot Game Simulator for Liar's Poker

Runs headless bot-only games to detect anomalies and bugs.
Detects: invalid turn index, deadlocks, infinite loops, state inconsistencies.

Usage:
    python game_simulator.py --games 100 --players 4 --verbose
"""

import argparse
import sys
import time
from typing import List, Dict, Any
from dataclasses import dataclass, field
from unittest.mock import Mock, patch


@dataclass
class AnomalyReport:
    """Records an anomaly detected during simulation."""
    game_id: int
    deal_number: int
    anomaly_type: str
    description: str
    game_state: Dict[str, Any]


@dataclass
class SimulationStats:
    """Statistics from simulation run."""
    total_games: int = 0
    completed_games: int = 0
    total_deals: int = 0
    total_moves: int = 0
    anomalies: List[AnomalyReport] = field(default_factory=list)
    deadlocks: int = 0
    infinite_loops: int = 0
    invalid_turn_indices: int = 0
    state_recovery_attempts: int = 0
    state_recovery_successes: int = 0

    def add_anomaly(self, anomaly: AnomalyReport):
        self.anomalies.append(anomaly)
        if anomaly.anomaly_type == "deadlock":
            self.deadlocks += 1
        elif anomaly.anomaly_type == "infinite_loop":
            self.infinite_loops += 1
        elif anomaly.anomaly_type == "invalid_turn_index":
            self.invalid_turn_indices += 1


class MockEmit:
    """Mock emit function that logs events instead of sending them."""

    def __init__(self, verbose: bool = False):
        self.events: List[Dict] = []
        self.verbose = verbose

    def __call__(self, event, data=None, to=None):
        event_record = {"event": event, "data": data, "to": to}
        self.events.append(event_record)
        if self.verbose:
            print(f"  [EMIT] {event}: {data.get('text', '') if data else ''}")


class GameSimulator:
    """Simulates bot-only games and detects anomalies."""

    def __init__(self, num_players: int = 4, verbose: bool = False):
        self.num_players = num_players
        self.verbose = verbose
        self.stats = SimulationStats()
        self.mock_emit = MockEmit(verbose=verbose)

        # Patch gevent.sleep to be a no-op during simulation
        import gevent
        self._original_sleep = gevent.sleep
        gevent.sleep = lambda *args, **kwargs: None

    def log(self, message: str):
        if self.verbose:
            print(message)

    def create_game(self, game_id: int):
        """Create a new game with all bot players."""
        # Import here to avoid circular imports
        from Game import Game

        sids = [f"bot_{game_id}_{i}" for i in range(self.num_players)]
        usernames = [f"Bot {i + 1}" for i in range(self.num_players)]
        bot_flags = [True] * self.num_players

        # Patch emit to use our mock
        with patch.object(Game, 'emit', self.mock_emit):
            game = Game(sids=sids, room=f"sim_room_{game_id}", usernames=usernames, bot_flags=bot_flags)
            # Replace emit method on the instance
            game.emit = self.mock_emit
            return game

    def capture_game_state(self, game) -> Dict[str, Any]:
        """Capture current game state for debugging."""
        return {
            "player_turn_index": game.player_turn_index,
            "num_players": len(game.players),
            "last_bet": game.last_bet,
            "last_bettor_index": game.last_bettor_index,
            "deal_in_progress": game.deal_in_progress,
            "game_finished": game.game_finished,
            "players": [
                {
                    "sid": p.sid,
                    "username": p.username,
                    "is_active": p.is_active,
                    "is_bot": p.is_bot,
                    "hand_count": p.hand_count,
                }
                for p in game.players
            ],
        }

    def validate_game_state(self, game, game_id: int, deal_number: int) -> List[AnomalyReport]:
        """Check for anomalies in game state."""
        anomalies = []
        state = self.capture_game_state(game)

        # Check 1: player_turn_index bounds
        if game.player_turn_index < 0 or game.player_turn_index >= len(game.players):
            anomalies.append(
                AnomalyReport(
                    game_id=game_id,
                    deal_number=deal_number,
                    anomaly_type="invalid_turn_index",
                    description=f"player_turn_index {game.player_turn_index} out of bounds (0-{len(game.players) - 1})",
                    game_state=state,
                )
            )

        # Check 2: Current player inactive during deal
        if game.deal_in_progress and len(game.players) > 0:
            if 0 <= game.player_turn_index < len(game.players):
                current_player = game.players[game.player_turn_index]
                if not current_player.is_active:
                    anomalies.append(
                        AnomalyReport(
                            game_id=game_id,
                            deal_number=deal_number,
                            anomaly_type="inactive_player_turn",
                            description=f"Current player {current_player.username} is inactive",
                            game_state=state,
                        )
                    )

        # Check 3: Inconsistent flags
        if game.deal_in_progress and game.game_finished:
            anomalies.append(
                AnomalyReport(
                    game_id=game_id,
                    deal_number=deal_number,
                    anomaly_type="inconsistent_flags",
                    description="deal_in_progress=True but game_finished=True",
                    game_state=state,
                )
            )

        return anomalies

    def simulate_single_deal(self, game, game_id: int, deal_number: int) -> bool:
        """
        Simulate a single deal until completion.
        Returns True if deal completed normally, False if anomaly detected.
        """
        max_moves = 1000  # Safety limit
        moves = 0

        while game.deal_in_progress and not game.game_finished:
            moves += 1
            self.stats.total_moves += 1

            # Check for infinite loop
            if moves > max_moves:
                anomaly = AnomalyReport(
                    game_id=game_id,
                    deal_number=deal_number,
                    anomaly_type="infinite_loop",
                    description=f"Deal exceeded {max_moves} moves",
                    game_state=self.capture_game_state(game),
                )
                self.stats.add_anomaly(anomaly)
                self.log(f"  [ANOMALY] Infinite loop detected after {moves} moves")
                return False

            # Validate state before each move
            anomalies = self.validate_game_state(game, game_id, deal_number)
            for anomaly in anomalies:
                self.stats.add_anomaly(anomaly)
                self.log(f"  [ANOMALY] {anomaly.anomaly_type}: {anomaly.description}")

            # Use built-in validation
            is_valid, issues = game.validate_game_state()
            if not is_valid:
                self.stats.state_recovery_attempts += 1
                self.log(f"  [STATE] Invalid state detected: {issues}")
                if game.recover_game_state():
                    self.stats.state_recovery_successes += 1
                    self.log("  [STATE] Recovery successful")
                else:
                    self.log("  [STATE] Recovery failed")
                    return False

            # Bounds check
            if game.player_turn_index < 0 or game.player_turn_index >= len(game.players):
                self.log(f"  [ERROR] Invalid turn index: {game.player_turn_index}")
                return False

            current_player = game.players[game.player_turn_index]

            # Skip inactive players
            if not current_player.is_active:
                next_index = game.get_next_active_player_index(game.player_turn_index + 1)
                if next_index is None:
                    game.game_finished = True
                    break
                game.player_turn_index = next_index
                continue

            # Only process bot turns
            if not current_player.is_bot:
                continue

            # Get bot and make decision
            bot = game.bots.get(current_player.sid)
            if bot is None:
                self.log(f"  [ERROR] Bot not found for {current_player.username}")
                return False

            try:
                decision = bot.make_decision()
                self.log(f"  {current_player.username} -> {decision}")
                game.make_move(current_player.sid, decision)
            except Exception as e:
                anomaly = AnomalyReport(
                    game_id=game_id,
                    deal_number=deal_number,
                    anomaly_type="exception",
                    description=f"Exception during bot move: {str(e)}",
                    game_state=self.capture_game_state(game),
                )
                self.stats.add_anomaly(anomaly)
                self.log(f"  [EXCEPTION] {e}")
                return False

        return True

    def simulate_game(self, game_id: int) -> bool:
        """
        Simulate a complete game.
        Returns True if game completed normally, False if anomaly detected.
        """
        self.log(f"\n=== Game {game_id + 1} ===")
        self.stats.total_games += 1

        try:
            game = self.create_game(game_id)
        except Exception as e:
            self.log(f"[ERROR] Failed to create game: {e}")
            return False

        deal_number = 0
        max_deals = 100  # Safety limit

        while not game.game_finished and deal_number < max_deals:
            deal_number += 1
            self.stats.total_deals += 1
            self.log(f"\n  --- Deal {deal_number} ---")

            try:
                game.deal()
            except Exception as e:
                anomaly = AnomalyReport(
                    game_id=game_id,
                    deal_number=deal_number,
                    anomaly_type="deal_exception",
                    description=f"Exception during deal: {str(e)}",
                    game_state=self.capture_game_state(game),
                )
                self.stats.add_anomaly(anomaly)
                self.log(f"  [EXCEPTION] Deal failed: {e}")
                return False

            if not self.simulate_single_deal(game, game_id, deal_number):
                # Anomaly detected but try to continue
                pass

            # Check for deadlock
            active_players = game.get_active_players()
            if len(active_players) > 1 and not game.deal_in_progress and not game.game_finished:
                # This is normal - waiting for ready state
                # In bot-only games, this should auto-resolve
                pass

        if deal_number >= max_deals:
            anomaly = AnomalyReport(
                game_id=game_id,
                deal_number=deal_number,
                anomaly_type="deadlock",
                description=f"Game exceeded {max_deals} deals",
                game_state=self.capture_game_state(game),
            )
            self.stats.add_anomaly(anomaly)
            self.log(f"[ANOMALY] Game deadlock - exceeded {max_deals} deals")
            return False

        self.stats.completed_games += 1
        self.log(f"  Game completed after {deal_number} deals")
        return True

    def run_simulation(self, num_games: int) -> SimulationStats:
        """Run multiple game simulations."""
        print(f"\nRunning {num_games} games with {self.num_players} bot players...\n")
        start_time = time.time()

        for i in range(num_games):
            self.simulate_game(i)

            # Progress indicator for non-verbose mode
            if not self.verbose and (i + 1) % 10 == 0:
                print(f"  Completed {i + 1}/{num_games} games...")

        elapsed = time.time() - start_time

        print(f"\n{'=' * 50}")
        print("SIMULATION RESULTS")
        print(f"{'=' * 50}")
        print(f"Total games:           {self.stats.total_games}")
        print(f"Completed games:       {self.stats.completed_games}")
        print(f"Total deals:           {self.stats.total_deals}")
        print(f"Total moves:           {self.stats.total_moves}")
        print(f"Time elapsed:          {elapsed:.2f}s")
        print(f"\n--- Anomalies ---")
        print(f"Total anomalies:       {len(self.stats.anomalies)}")
        print(f"  Deadlocks:           {self.stats.deadlocks}")
        print(f"  Infinite loops:      {self.stats.infinite_loops}")
        print(f"  Invalid turn index:  {self.stats.invalid_turn_indices}")
        print(f"\n--- State Recovery ---")
        print(f"Recovery attempts:     {self.stats.state_recovery_attempts}")
        print(f"Recovery successes:    {self.stats.state_recovery_successes}")

        if self.stats.anomalies:
            print(f"\n--- Anomaly Details ---")
            for i, anomaly in enumerate(self.stats.anomalies[:10]):  # Show first 10
                print(f"\n[{i + 1}] Game {anomaly.game_id}, Deal {anomaly.deal_number}")
                print(f"    Type: {anomaly.anomaly_type}")
                print(f"    Desc: {anomaly.description}")
            if len(self.stats.anomalies) > 10:
                print(f"\n    ... and {len(self.stats.anomalies) - 10} more anomalies")

        print(f"\n{'=' * 50}")

        return self.stats


def main():
    parser = argparse.ArgumentParser(description="Liar's Poker Bot Game Simulator")
    parser.add_argument(
        "--games", "-g", type=int, default=100, help="Number of games to simulate (default: 100)"
    )
    parser.add_argument(
        "--players", "-p", type=int, default=4, help="Number of bot players (default: 4)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed game progress")
    args = parser.parse_args()

    if args.players < 2:
        print("Error: Need at least 2 players")
        sys.exit(1)

    if args.players > 10:
        print("Warning: Many players may cause slow simulations")

    simulator = GameSimulator(num_players=args.players, verbose=args.verbose)
    stats = simulator.run_simulation(args.games)

    # Exit with error code if anomalies detected
    if stats.anomalies:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
