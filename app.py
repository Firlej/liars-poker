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
    global queue
    print("leave_game", request.sid[-4:])
    # Find the game the player is in
    game: Game = next(filter(lambda g: request.sid in g.sids, games.values()), None)
    
    if game is None:
        emit("message", {'text': "You're not in any game to leave"}, sid=request.sid)
        return
    
    # Remove player from the game room
    leave_room(room=game.room, sid=request.sid)
    
    # Notify other players
    emit("game_update", {'sid': request.sid, 'text': f"{next(p.username for p in game.players if p.sid == request.sid)} left the game. Room is closed."}, room=game.room)
    
    # Close the game and clean up
    close_room(game.room)
    queue = []
    del games[game.room]
    
    print(f"Player {request.sid[-4:]} left game {game.room}")

@socketio.on("disconnect")
def disconnect(data=None):
    global queue
    users.remove(request.sid)
    queue = [item for item in queue if item[0] != request.sid]
    
    # Remove player from any active games
    game_to_remove = None
    for room, game in games.items():
        if request.sid in game.sids:
            emit("game_update", {'sid': request.sid, 'text': f"{next(p.username for p in game.players if p.sid == request.sid)} left the game. Room is closed."}, room=game.room)
            close_room(game.room)
            queue = []
            game_to_remove = room
            break
            
    if game_to_remove:
        del games[game_to_remove]
        
    print("disconnect", request.sid[-4:])


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 4000))
    # socketio.run(app = app, host='0.0.0.0', port=port, debug=True)
