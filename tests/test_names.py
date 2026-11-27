import pytest

from server.names import is_allowed
from server.rooms import Lobby, LobbyError


@pytest.mark.parametrize("name", [
    "fuck", "F.U.C.K", "fuuuck", "a$$", "sh1t", "Kurwa", "kurrrwa", "Chuj", "ASS", "a s s",
    "dick", "KYS", "N1gga", "Pizda", "spierdalaj", "Hitler88", "kill yourself", "Jebać",
])
def test_offensive_names_are_refused(name):
    assert not is_allowed(name)


@pytest.mark.parametrize("name", [
    "Cassandra", "Scunthorpe", "Hancock", "Dickens", "As", "Kasia_77", "Assassin", "therapist",
    "grapes", "torpedo", "Peacock", "Swanky", "Shiitake", "Nigel", "Niger", "Michał", "AceHunter",
    "Analyst", "Pedal", "Raccoon", "Player", "Bluffotron",
])
def test_normal_names_pass(name):
    assert is_allowed(name)


def test_lobby_keeps_offensive_names_off_the_table():
    lobby = Lobby()
    p = lobby.hello(None, "a$$hole", 0)
    assert p.name == "Player"
    lobby.rename(p.id, "Ada", 1)
    with pytest.raises(LobbyError, match="name_not_allowed"):
        lobby.rename(p.id, "kurwa", 2)
    assert p.name == "Ada"
    assert lobby.hello(p.token, "shit", 3).name == "Ada"  # a bad name on reconnect is ignored
    assert [e["player"] for e in lobby.stats if e["type"] == "name_blocked"] == [p.id] * 3


def test_saved_offensive_names_are_cleaned_on_restart():
    lobby = Lobby()
    lobby.restore([{"id": "p_1", "token": "t", "name": "fuck", "room_id": None}], [], 0)
    assert lobby.profiles["p_1"].name == "Player"
