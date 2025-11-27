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
manual_rooms = {}  # {room_id: {'players': [(sid, username)], 'created_by': sid, 'creator_username': str}}

def get_room_name():
    global game_index
    room_name = f"Room-{game_index}"
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

@socketio.on("create_room")
def create_room(data=None):
    """Create a manual room - creator is automatically added"""
    username = data.get('username', request.sid[-4:]) if data else request.sid[-4:]

    print(f"create_room called by {request.sid[-4:]} ({username})")
    print(f"Current manual_rooms: {list(manual_rooms.keys())}")

    # Check if user already created a room (by sid or username)
    for room_id, room_data in manual_rooms.items():
        if room_data['created_by'] == request.sid:
            error_msg = "You already have an active room. Leave it before creating a new one."
            print(f"ERROR: User {request.sid[-4:]} tried to create multiple rooms. Existing room: {room_id}")
            emit("error", {'message': error_msg, 'event': 'create_room'}, to=request.sid)
            return
        # Check if this username already created a room (reconnection case)
        if room_data['creator_username'] == username:
            # User reconnected - update their sid in the room
            print(f"User {username} reconnected to their room {room_id} - updating sid from {room_data['created_by'][-4:]} to {request.sid[-4:]}")
            old_sid = room_data['created_by']
            room_data['created_by'] = request.sid
            # Update player list too
            for i, (sid, uname) in enumerate(room_data['players']):
                if sid == old_sid:
                    room_data['players'][i] = (request.sid, username)
                    break

            # Join socket.io room
            join_room(room=room_id, sid=request.sid)

            # Send you_joined_queue so frontend knows their sid
            emit("you_joined_queue", {'your_sid': request.sid}, to=request.sid)

            # Notify them they're back in their room
            emit("room_created", {
                'roomId': room_id,
                'roomName': room_id
            }, sid=request.sid)

            # Update room list
            socketio.emit("rooms_update", {'rooms': get_rooms_list()})
            return

    room_id = get_room_name()
    print(f"Creating new room {room_id} for {request.sid[-4:]}")

    # Create room with creator as first player
    manual_rooms[room_id] = {
        'players': [(request.sid, username)],
        'created_by': request.sid,
        'creator_username': username
    }

    # Join creator to socket.io room
    join_room(room=room_id, sid=request.sid)

    print(f"Room {room_id} created by {username} ({request.sid[-4:]})")

    # Send you_joined_queue so frontend knows their sid for game logic
    emit("you_joined_queue", {'your_sid': request.sid}, to=request.sid)

    # Notify the creator
    emit("room_created", {
        'roomId': room_id,
        'roomName': room_id
    }, sid=request.sid)

    # Broadcast updated room list to all clients
    socketio.emit("rooms_update", {'rooms': get_rooms_list()})

@socketio.on("join_manual_room")
def join_manual_room(data):
    """Join a specific manual room"""
    room_id = data.get('roomId')
    username = data.get('username', request.sid[-4:])

    # Validate room exists
    if not room_id or room_id not in manual_rooms:
        emit("error", {'message': f"Room does not exist"}, sid=request.sid)
        return

    room_data = manual_rooms[room_id]

    # Check if already in room by sid (exact match)
    already_in_room_by_sid = any(sid == request.sid for sid, _ in room_data['players'])

    # Check if already in room by username (reconnection with new sid)
    existing_player_by_username = None
    for i, (sid, uname) in enumerate(room_data['players']):
        if uname == username and sid != request.sid:
            existing_player_by_username = i
            break

    if already_in_room_by_sid:
        print(f"{username} ({request.sid[-4:]}) already in room {room_id}")
    elif existing_player_by_username is not None:
        # User reconnected with new sid - update their sid
        old_sid = room_data['players'][existing_player_by_username][0]
        room_data['players'][existing_player_by_username] = (request.sid, username)

        # If this user is the creator, update created_by as well
        if room_data['created_by'] == old_sid:
            room_data['created_by'] = request.sid
            print(f"Creator {username} reconnected to room {room_id} - updated sid from {old_sid[-4:]} to {request.sid[-4:]}")
        else:
            print(f"{username} reconnected to room {room_id} - updated sid from {old_sid[-4:]} to {request.sid[-4:]}")
    else:
        # Add player to room
        room_data['players'].append((request.sid, username))
        print(f"{username} ({request.sid[-4:]}) joined room {room_id}")

    # Join socket.io room (idempotent)
    join_room(room=room_id, sid=request.sid)

    # Send you_joined_queue so frontend knows their sid for game logic
    emit("you_joined_queue", {'your_sid': request.sid}, to=request.sid)

    # Notify the player who joined
    emit("joined_room", {
        'roomId': room_id,
        'roomName': room_id,
        'players': room_data['players'],
        'isCreator': room_data['created_by'] == request.sid,
        'creatorSid': room_data['created_by']
    }, sid=request.sid)

    # Broadcast if new player or reconnection (not just re-join with same sid)
    if not already_in_room_by_sid:
        # Notify all players in the room
        socketio.emit("room_update", {
            'roomName': room_id,
            'players': room_data['players'],
            'creatorSid': room_data['created_by']
        }, room=room_id)

        # Update rooms list for everyone (reconnections don't change player count but updates are good)
        if existing_player_by_username is None:
            # Only update room list if it's a truly new player (not a reconnection)
            socketio.emit("rooms_update", {'rooms': get_rooms_list()})

@socketio.on("remove_player_from_room")
def remove_player_from_room(data):
    """Remove a player from a manual room (creator only)"""
    room_id = data.get('roomId')
    player_sid = data.get('playerId')

    if not room_id or not player_sid:
        emit("error", {'message': "Room ID and player ID are required"}, sid=request.sid)
        return

    if room_id not in manual_rooms:
        emit("error", {'message': f"Room {room_id} does not exist"}, sid=request.sid)
        return

    room_data = manual_rooms[room_id]

    # Check if the requester is the room creator
    if room_data['created_by'] != request.sid:
        emit("error", {'message': "Only the room creator can remove players"}, sid=request.sid)
        return

    # Check if the player is in the room
    player_to_remove = None
    for sid, username in room_data['players']:
        if sid == player_sid:
            player_to_remove = (sid, username)
            break

    if not player_to_remove:
        emit("error", {'message': "Player is not in this room"}, sid=request.sid)
        return

    # Remove the player
    room_data['players'].remove(player_to_remove)
    removed_username = player_to_remove[1]

    print(f"Player {player_sid[-4:]} ({removed_username}) removed from room {room_id} by creator")

    # Notify the removed player
    print(f"Sending removed_from_room to removed player {player_sid[-4:]}")
    emit("removed_from_room", {
        'roomId': room_id,
        'reason': f"You were removed from the room by the creator"
    }, to=player_sid)

    # Notify the creator
    print(f"Sending player_removed to creator {request.sid[-4:]}")
    emit("player_removed", {
        'playerId': player_sid,
        'playerName': removed_username
    }, to=request.sid)

    # Notify all remaining players in the room
    socketio.emit("room_update", {
        'roomName': room_id,
        'players': room_data['players'],
        'creatorSid': room_data['created_by']
    }, room=room_id)

    # Broadcast updated room list to all clients
    socketio.emit("rooms_update", {'rooms': get_rooms_list()})

@socketio.on("add_bot_to_room")
def add_bot_to_room(data):
    """Add a bot player to a manual room"""
    room_id = data.get('roomId')

    # Validate room exists
    if not room_id or room_id not in manual_rooms:
        emit("error", {'message': "Room does not exist"}, sid=request.sid)
        return

    room_data = manual_rooms[room_id]

    # Only creator can add bots
    if room_data['created_by'] != request.sid:
        emit("error", {'message': "Only room creator can add bots"}, sid=request.sid)
        return

    # Generate unique bot ID
    import uuid
    bot_sid = f"bot_{uuid.uuid4().hex[:8]}"
    bot_count = sum(1 for _, username in room_data['players'] if username.startswith("Bot "))
    bot_username = f"Bot {bot_count + 1}"

    # Add bot to room
    room_data['players'].append((bot_sid, bot_username))
    print(f"Bot {bot_username} ({bot_sid[-8:]}) added to room {room_id}")

    # Notify all players in the room
    socketio.emit("room_update", {
        'roomName': room_id,
        'players': room_data['players'],
        'creatorSid': room_data['created_by']
    }, room=room_id)

    # Update rooms list for everyone
    socketio.emit("rooms_update", {'rooms': get_rooms_list()})

@socketio.on("start_manual_room_game")
def start_manual_room_game(data):
    """Start game from manual room"""
    room_id = data.get('roomId')

    # Validate room exists
    if not room_id or room_id not in manual_rooms:
        emit("error", {'message': "Room does not exist"}, sid=request.sid)
        return

    room_data = manual_rooms[room_id]

    # Only creator can start
    if room_data['created_by'] != request.sid:
        emit("error", {'message': "Only room creator can start the game"}, sid=request.sid)
        return

    # Need at least 2 players
    if len(room_data['players']) < 2:
        emit("error", {'message': "Need at least 2 players to start"}, sid=request.sid)
        return

    # Extract player data
    sids = [sid for sid, _ in room_data['players']]
    usernames = [username for _, username in room_data['players']]

    # Determine which players are bots
    bot_flags = [sid.startswith('bot_') for sid in sids]

    print(f"Starting game in room {room_id} with {len(sids)} players ({sum(bot_flags)} bots)")

    # Create and start the game
    game = Game(sids=sids, room=room_id, usernames=usernames, bot_flags=bot_flags)
    game.deal()
    games[room_id] = game

    # Remove room from manual_rooms (game is now active)
    del manual_rooms[room_id]

    # Update rooms list for everyone
    socketio.emit("rooms_update", {'rooms': get_rooms_list()})

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

    # First check if player is in a manual room (not yet started game)
    player_room_id = None
    for room_id, room_data in manual_rooms.items():
        if any(sid == request.sid for sid, _ in room_data['players']):
            player_room_id = room_id
            break

    if player_room_id:
        # Player is in a manual room
        room_data = manual_rooms[player_room_id]
        is_creator = room_data['created_by'] == request.sid
        player_username = next((username for sid, username in room_data['players'] if sid == request.sid), 'Unknown')

        print(f"Player {request.sid[-4:]} ({player_username}) leaving room {player_room_id} (is_creator: {is_creator})")

        # If room creator is leaving, notify other players BEFORE modifying the room
        if is_creator:
            print(f"Room creator leaving {player_room_id}, notifying all players")
            # Get list of other players to notify
            other_players = [sid for sid, _ in room_data['players'] if sid != request.sid]
            print(f"Notifying {len(other_players)} other players: {[sid[-4:] for sid in other_players]}")

            # Notify each player individually to be sure they get it
            for player_sid in other_players:
                emit("removed_from_room", {
                    'roomId': player_room_id,
                    'reason': "Room creator left the room"
                }, to=player_sid)
                print(f"Sent removed_from_room to {player_sid[-4:]}")

        # Remove player from room
        room_data['players'] = [p for p in room_data['players'] if p[0] != request.sid]
        print(f"Player removed. Remaining players: {len(room_data['players'])}")

        # Leave socket.io room
        leave_room(room=player_room_id, sid=request.sid)

        # If room creator left, delete the room
        if is_creator:
            del manual_rooms[player_room_id]
            print(f"Room {player_room_id} deleted because creator left")
        else:
            # Notify remaining players
            socketio.emit("room_update", {
                'roomName': player_room_id,
                'players': room_data['players'],
                'creatorSid': room_data['created_by']
            }, room=player_room_id)
            print(f"Sent room_update to remaining players in {player_room_id}")

        # Broadcast updated rooms list to ALL clients
        rooms_list = get_rooms_list()
        print(f"Broadcasting rooms_update to all clients: {len(rooms_list)} rooms")
        socketio.emit("rooms_update", {'rooms': rooms_list})
        print(f"Rooms after update: {[room['id'] for room in rooms_list]}")

        # Send confirmation to the leaving player
        emit("left_room", {'success': True, 'roomId': player_room_id}, to=request.sid)
        return

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

@socketio.on("get_rooms")
def get_rooms():
    """Get list of available manual rooms"""
    rooms_list = get_rooms_list()
    emit("rooms_list", {'rooms': rooms_list}, sid=request.sid)

def get_rooms_list():
    """Helper to format rooms list for frontend"""
    return [
        {
            'id': room_id,
            'name': room_id,
            'creator': room_data['creator_username'],
            'playerCount': len(room_data['players']),
            'maxPlayers': 10,
            'status': 'waiting'
        }
        for room_id, room_data in manual_rooms.items()
    ]

@socketio.on("disconnect")
def disconnect(data=None):
    global queue
    users.discard(request.sid)  # Use discard to avoid KeyError if not present
    queue = [item for item in queue if item[0] != request.sid]

    print(f"User {request.sid[-4:]} disconnected")

    # Check if user is in a manual room
    # Note: We don't immediately remove them - they might reconnect (page reload)
    # The reconnection logic in join_manual_room/create_room handles updating their sid
    for room_id, room_data in list(manual_rooms.items()):
        for i, (sid, username) in enumerate(room_data['players']):
            if sid == request.sid:
                print(f"User {username} ({request.sid[-4:]}) disconnected from room {room_id} - keeping in room for potential reconnection")
                # Don't remove them yet - let them reconnect with same username
                break

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
    socketio.run(app = app, host='0.0.0.0', port=port, debug=False)
