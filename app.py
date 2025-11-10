from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room, close_room, rooms
import logging

from Game import Game

# logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")


@app.route("/")
def index():
    return render_template("index.html")


users = set()

queue = []

game_index = 0
games = {}

def get_room_name():
    global game_index
    room_name = f"Game #{game_index}"
    game_index += 1
    return room_name

@socketio.on("connect")
def connect():
    try:
        users.add(request.sid)
        print("connect", request.sid[-4:])
        emit("connected", {'sid': request.sid}, sid=request.sid)
    except Exception as e:
        print(f"Connection error for {request.sid[-4:]}: {e}")

@socketio.on("play")
def play(data=None):
    global queue
    if data and 'username' in data:
        username = data['username']
    else:
        username = request.sid[-4:]
    
    if request.sid not in [sid for sid, _ in queue]:
        queue.append((request.sid, username))
        socketio.emit("you_joined_queue", {'your_sid': request.sid}, to=request.sid)
        
    print("play", request.sid[-4:], queue)
    socketio.emit("queue_update", {'queue': queue})
    
@socketio.on("start_game")
def start_game():
    global queue
    sids = [sid for sid, _ in queue]
    usernames = [username for _, username in queue]

    room = get_room_name()

    print(f"Adding {sids} to room {room}")
    for sid in sids:
        join_room(room = room, sid = sid)
        queue = [item for item in queue if item[0] != sid]

    game = Game(sids = sids, room = room, usernames = usernames)
    game.deal()

    games[room] = game

    queue = []
    socketio.emit("queue_update", {'queue': queue})

@socketio.on("clear_queue")
def clear_queue():
    global queue
    print(f"clear_queue called by {request.sid[-4:]}")

    # Clear the entire queue
    queue = []

    # Notify all clients that the queue has been cleared
    socketio.emit("queue_update", {'queue': queue})
    socketio.emit("message", {'text': "Queue has been cleared"})

    print("Queue cleared")

@socketio.on("bet")
def bet(data):
    print("bet", request.sid[-4:], data)
    
    game: Game = next(filter(lambda g: request.sid in g.sids, games.values()), None)
    
    if game is None:
        emit("message", {'text': "youre not in game. join a game to make a bet"}, sid=request.sid)
        return
    
    assert "bet" in data.keys()
    
    game.make_move(request.sid, data["bet"])
                
    if game.game_finished:
        close_room(game.room)
        del games[game.room]
    
    if not game.deal_in_progess:
        game.deal()

@socketio.on("leave_game")
def leave_game():
    print("leave_game", request.sid[-4:])
    # Find the game the player is in
    game: Game = next(filter(lambda g: request.sid in g.sids, games.values()), None)

    if game is None:
        emit("message", {'text': "You're not in any game to leave"}, sid=request.sid)
        return

    # Remove player from the game room
    leave_room(room=game.room, sid=request.sid)

    # Mark player as inactive
    player = game.mark_player_inactive(request.sid)
    if player:
        # Notify other players
        emit("game_update", {
            'sid': request.sid,
            'text': f"{player.username} left the game. Game continues with remaining players.",
            'json': {
                'action': 'player_left',
                'left_player_sid': request.sid,
                'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'is_active': p.is_active} for p in game.players]
            }
        }, room=game.room)

        # If it was their turn, skip to next active player
        if game.players[game.player_turn_index].sid == request.sid:
            next_index = game.get_next_active_player_index(game.player_turn_index + 1)
            if next_index is not None:
                game.player_turn_index = next_index
                next_player = game.players[game.player_turn_index]
                emit("game_update", {
                    'text': f"Turn skipped to {next_player.username}.",
                    'json': {
                        'action': 'turn_skipped',
                        'player_turn_index': game.player_turn_index,
                        'current_player_sid': next_player.sid,
                        'current_player_username': next_player.username,
                        'last_bet': game.last_bet,
                        'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in game.players],
                        'deal_in_progress': game.deal_in_progess,
                        'game_finished': game.game_finished
                    }
                }, room=game.room)

        # Check if game should end (only 1 or 0 active players remaining)
        active_players = game.get_active_players()
        if len(active_players) <= 1:
            if len(active_players) == 1:
                winner = active_players[0]
                emit("game_update", {
                    'text': f"{winner.username} won! All other players have left."
                }, room=game.room)
            else:
                emit("game_update", {
                    'text': "Game ended - no active players remaining."
                }, room=game.room)
            game.game_finished = True
            close_room(game.room)
            del games[game.room]

    print(f"Player {request.sid[-4:]} left game {game.room}")

@socketio.on("disconnect")
def disconnect(data=None):
    global queue
    users.discard(request.sid)  # Use discard to avoid KeyError if not present
    queue = [item for item in queue if item[0] != request.sid]

    # Find player's game and mark them as inactive
    game: Game = next(filter(lambda g: request.sid in g.sids, games.values()), None)

    if game:
        player = game.mark_player_inactive(request.sid)
        if player:
            # Notify other players
            emit("game_update", {
                'sid': request.sid,
                'text': f"{player.username} disconnected. Game continues with remaining players.",
                'json': {
                    'action': 'player_disconnected',
                    'disconnected_player_sid': request.sid,
                    'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'is_active': p.is_active} for p in game.players]
                }
            }, room=game.room)

            # If it was their turn, notify that turn is being skipped
            if game.players[game.player_turn_index].sid == request.sid:
                next_index = game.get_next_active_player_index(game.player_turn_index + 1)
                if next_index is not None:
                    game.player_turn_index = next_index
                    next_player = game.players[game.player_turn_index]
                    emit("game_update", {
                        'text': f"Turn skipped to {next_player.username}.",
                        'json': {
                            'action': 'turn_skipped',
                            'player_turn_index': game.player_turn_index,
                            'current_player_sid': next_player.sid,
                            'current_player_username': next_player.username,
                            'last_bet': game.last_bet,
                            'players': [{'sid': p.sid, 'username': p.username, 'hand_count': p.hand_count, 'last_bet': p.last_bet, 'is_active': p.is_active} for p in game.players],
                            'deal_in_progress': game.deal_in_progess,
                            'game_finished': game.game_finished
                        }
                    }, room=game.room)

            # Check if game should end (only 1 or 0 active players remaining)
            active_players = game.get_active_players()
            if len(active_players) <= 1:
                if len(active_players) == 1:
                    winner = active_players[0]
                    emit("game_update", {
                        'text': f"{winner.username} won! All other players have left."
                    }, room=game.room)
                else:
                    emit("game_update", {
                        'text': "Game ended - no active players remaining."
                    }, room=game.room)
                game.game_finished = True
                close_room(game.room)
                del games[game.room]

    print("disconnect", request.sid[-4:])


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 4000))
    # socketio.run(app = app, host='0.0.0.0', port=port, debug=False)
