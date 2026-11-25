# Liar's Poker — game server

Python server for the Liar's Poker app (`../liars-poker-app`). Socket.IO over
ASGI (uvicorn), state saved to SQLite so a restart or deploy does not end games.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-server.txt
.venv/bin/uvicorn --factory server.app:create_app --host 0.0.0.0 --port 4000
```

Or with Docker (state in the `/data` volume):

```bash
docker build -t liars-poker-server . && docker run -p 4000:4000 -v liars-poker-data:/data liars-poker-server
```

Environment: `PORT`, `DB_PATH` (default `data/liars_poker.db`), `CORS_ORIGINS`
(comma-separated, default `*`), `LOG_LEVEL`. `GET /health` returns `{"ok": true}`.

Run a single process: all live game state is in memory in that process (and
persisted to `DB_PATH`). Behind a proxy, enable WebSocket upgrades and keep
idle timeouts above 60 s.

## Deploy (production VPS)

Production runs on the mikr.us VPS as the systemd unit `liars-poker.service`, from a git checkout
of `mobile-app-integration` in `/var/www/liars-poker`. nginx serves `liarspoker-server.adamtomczyk.com`
(behind Cloudflare) and proxies everything, WebSockets included, to `127.0.0.1:4000`.

```bash
scp -P 10173 deploy/deploy-vps.sh root@patryk173.mikrus.xyz:/root/deploy-liars-poker.sh
ssh -p 10173 root@patryk173.mikrus.xyz 'bash /root/deploy-liars-poker.sh'
```

The script saves the running commit and unit file to `/root/backups`, pulls the branch, installs
dependencies, runs the tests, writes the unit (uvicorn, one process, `DB_PATH` in `data/`), restarts it
and checks `/health`. It prints the exact rollback command at the end. Games in progress survive the
restart; players see "Reconnecting" for a few seconds.

Error reports go to the PocketBase `feedbacks` collection by default; set `ERROR_REPORT_URL=` in the
unit to turn them off.

## Tests

```bash
.venv/bin/python -m pytest
```

Covers the rules (every bet type, the bet order the client uses), the engine
(turns, checks, eliminations, timeouts, players leaving mid-deal), rooms
(hosts, seats, spectators, bots, reconnects, forfeits, persistence) and real
Socket.IO clients over WebSocket and long-polling, including a server restart.

## Layout

| File | What it does |
| --- | --- |
| `server/rules.py` | Deck, the ordered list of 83 bets, whether a bet holds over the pooled cards |
| `server/engine.py` | One game as a pure state machine: no sockets, time and randomness passed in |
| `server/bots.py` | Bot decisions from Monte Carlo odds over the unseen cards |
| `server/rooms.py` | Players, rooms, hosts, seats, timers, bots, per-player snapshots |
| `server/store.py` | SQLite persistence |
| `server/app.py` | Socket.IO handlers and the clock that drives timeouts and bots |
| `legacy/` | The previous Flask-SocketIO server, kept for reference |
| `Deck.py`, `Solver.py`, `simulate.py`, `ui.py` | Probability solver and its Streamlit UI (separate from the server) |

## Rules as implemented

- 24 cards (9 to ace). Everyone starts with 1 card; up to 8 players.
- Bets name a combination that must exist across *all* cards in play. Each bet
  must be higher than the last (order: high card, pair, two pair, small and big
  straight, three of a kind, full house, four of a kind, flush, small and big
  poker). The first player of a deal must bet; anyone after may check instead.
- On a check all hands are shown. If the bet holds, the checker loses the deal,
  otherwise the bettor does. The loser gets one more card and opens the next
  deal. Going over the table's hand limit puts you out. The last player left
  wins.
- The hand limit is "auto" by default: 6 cards for 2 players, 4 for 3, and 3
  for 4 or more (out on the 7th, 5th and 4th card). The host can pick any limit
  from 1 to 12 in the lobby. A game lowers it if the 24-card deck cannot deal
  that many to everyone (24 ÷ players).

## Protocol

The client connects with `auth: {token, name}` and receives `welcome`
`{player_id, token, room_id, server_time}`. It keeps the token: reconnecting
with it, from any socket, is the same player in the same seat.

Requests are emits with an acknowledgement, answered `{ok: true, ...}` or
`{ok: false, error}`: `rooms`, `create_room`, `join_room {room_id}`,
`leave_room`, `start_game`, `add_bot`, `shuffle_seats`, `sit`, `stand`,
`kick {player_id}`, `set_max_hand {max_hand}` (host, lobby only; a number
from 1 to 12 or `null` for auto), `act {type: bet|check|ready, bet, turn_seq,
move_id}`, `sync`, `set_name {name}`, `ping {t}`.

`state.room.max_hand` is the limit of the game on screen (or of the next game,
in the lobby). `state.room.hand_limit` describes the next game:
`{choice, value, auto, max, max_choice}`, where `choice` is the host's pick
(`null` = auto), `value` is what the current seating would play with, and
`max` is the most the deck allows for the current seating.

Whenever a room changes, each member receives `state`: the full snapshot from
their point of view with a version `v`. Other players' cards are only included
after a check. `move_id` makes moves safe to resend; `turn_seq` rejects moves
made against an outdated table (`error: "stale"`).

Connection handling:

- A disconnected player keeps their seat. Their turn timer (60 s) keeps
  running; when it expires the server plays for them (lowest bet when opening,
  otherwise check). After 2 minutes away during a game they leave it.
- Leaving mid-deal cancels the deal and the cards are dealt again without
  that player, since every bet was made against their cards too.
- After a check the next deal starts when every connected player still in
  the game confirms, or after 20 s.
- The host role passes to another person if the host leaves. A room closes
  when its last person leaves, or after 30 minutes with nobody connected.
