from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room, close_room, rooms
import logging

from Game import Game

logging.getLogger("werkzeug").setLevel(logging.ERROR)

app = Flask(__name__)
socketio = SocketIO(app)


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
    # print('connect', request.sid, request.__dict__.keys())
    users.add(request.sid)
    print("connect", request.sid[-4:])
    emit("connected", {'sid': request.sid}, sid = request.sid)
    # print(users)

@socketio.on("play")
def play(data=None):
    global queue
    if data and 'username' in data:
        username = data['username']
    else:
        username = request.sid[-4:]

    # TODO check if player is not in a game currently
    
    if request.sid not in [sid for sid, _ in queue]:
        queue.append((request.sid, username))
        
    print("play", request.sid[-4:], queue)
    socketio.emit("queue_update", {'queue': queue})
    
    if len(queue) >= 2:
        
        sids = [sid for sid, _ in queue[:2]]
        usernames = [username for _, username in queue[:2]]
        
        room = get_room_name()
        
        print(f"Adding {sids} to room {room}")
        for sid in sids:
            join_room(room = room, sid = sid)
            queue = [item for item in queue if item[0] != sid]
            
        game = Game(sids = sids, room = room, usernames = usernames)
        game.deal()
            
        games[room] = game

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



@socketio.on("disconnect")
def disconnect():
    users.remove(request.sid)
    queue = [item for item in queue if item[0] != request.sid]
    # TODO remove from games
    print("disconnect", request.sid[-4:])


if __name__ == "__main__":
    socketio.run(app = app, host='0.0.0.0', port=5001)
