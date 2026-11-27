"""Keeps offensive player names off the table (App Store guideline 1.2), and
the made-up names and short ids the admin dashboard shows.

A name is checked after undoing the usual disguises: letters with accents,
look-alike digits and symbols ("a$$", "sh1t"), dots or spaces between letters
("f.u.c.k") and stretched letters ("fuuuck"). Two kinds of words:

- *anywhere*: offensive even inside a longer name.
- *whole words*: short words that are only offensive on their own, because
  they also hide inside normal words ("ass" in "Cassandra", "cock" in "Hancock").

``ALLOWED`` lists real words that happen to contain an *anywhere* word.
Besides the built-in lists, the admin can add words from the dashboard
(``set_custom``). The app keeps a copy of the built-in lists in
``utils/nameFilter.ts`` (keep in sync).
"""
from __future__ import annotations

import hashlib
import itertools
import random
import re
import unicodedata
from typing import Iterable, List, Optional, Tuple

ANYWHERE_EN = (
    "fuck", "fck", "shit", "cunt", "nigger", "nigga", "faggot", "bitch", "whore", "slut",
    "asshole", "bastard", "dildo", "porn", "penis", "vagina", "pussy", "twat", "wank",
    "jizz", "retard", "tranny", "molest", "pedophil", "paedophil", "hitler", "blowjob",
    "handjob", "cocksuck", "killyourself",
)
ANYWHERE_PL = (
    "kurw", "chuj", "huj", "pizd", "pierdol", "pierdal", "jebac", "jeban", "jebie", "jebn",
    "zjeb", "dziwk", "cwel", "kutas", "cipk",
)
WHOLE_EN = (
    "ass", "cum", "tit", "tits", "dick", "cock", "fag", "nazi", "kkk", "kys", "rape",
    "rapist", "pedo", "nonce", "spic", "chink", "kike", "coon", "anal", "anus",
)
WHOLE_PL = ("cipa", "ciota", "fiut", "szmata")
ANYWHERE = ANYWHERE_EN + ANYWHERE_PL
WHOLE_WORDS = WHOLE_EN + WHOLE_PL
ALLOWED = ("scunthorpe", "penistone", "swank", "shiitake", "matsushita")

#: Look-alikes people use to slip past filters.
LOOK_ALIKES = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
                             "@": "a", "$": "s", "!": "i", "|": "i", "+": "t", "€": "e", "ł": "l"})


def _stretchy(word: str) -> str:
    """"ass" -> "a{1,}s{2,}": also matches "aaasss", never "as"."""
    return "".join(f"{re.escape(ch)}{{{len(list(run))},}}" for ch, run in itertools.groupby(word))


def _either(words: Iterable[str]) -> Optional[re.Pattern]:
    words = [w for w in words if w]
    return re.compile("|".join(_stretchy(w) for w in words)) if words else None


_ANYWHERE = _either(ANYWHERE)
_WHOLE = _either(WHOLE_WORDS)
_ALLOWED = _either(ALLOWED)
_custom_anywhere: Optional[re.Pattern] = None
_custom_whole: Optional[re.Pattern] = None


def _plain(name: str) -> str:
    """Lower case, accents dropped, look-alikes turned into letters."""
    text = name.lower().translate(LOOK_ALIKES)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def clean_word(word: str) -> str:
    """A word as the filter compares it: plain letters only."""
    return re.sub(r"[^a-z]+", "", _plain(word))


def set_custom(words: Iterable[Tuple[str, bool]]) -> None:
    """The admin's own blocked words, as (word, whole_word_only) pairs."""
    global _custom_anywhere, _custom_whole
    words = [(clean_word(w), whole) for w, whole in words]
    _custom_anywhere = _either(w for w, whole in words if not whole)
    _custom_whole = _either(w for w, whole in words if whole)


def _hits(name: str, anywhere: Optional[re.Pattern], whole: Optional[re.Pattern]) -> bool:
    plain = _plain(name)
    words = [w for w in re.split(r"[^a-z]+", plain) if w]
    letters = "".join(words)
    if anywhere and anywhere.search(_ALLOWED.sub("", letters)):
        return True
    return bool(whole) and any(whole.fullmatch(w) for w in [*words, letters])


def is_allowed(name: str) -> bool:
    return not (_hits(name, _ANYWHERE, _WHOLE) or _hits(name, _custom_anywhere, _custom_whole))


def word_matches(word: str, whole: bool, name: str) -> bool:
    """Whether one blocked word catches ``name`` (to count what it stopped)."""
    pattern = _either([clean_word(word)])
    return _hits(name, None if whole else pattern, pattern if whole else None)


def mask_word(word: str) -> str:
    """"kurwa" -> "k***a"."""
    return word if len(word) < 3 else word[0] + "*" * (len(word) - 2) + word[-1]


def mask(name: str) -> str:
    """The name with every offensive part starred out, keeping each part's first
    and last character: "bitchboy" -> "b***hboy"."""
    letters, where = [], []  # plain letters, and which character of ``name`` each came from
    for i, ch in enumerate(name):
        for letter in _plain(ch):
            if "a" <= letter <= "z":
                letters.append(letter)
                where.append(i)
    text = "".join(letters)
    spans = []
    for pattern in (_ANYWHERE, _custom_anywhere):
        if pattern:
            spans += [m.span() for m in pattern.finditer(text)]
    for pattern in (_WHOLE, _custom_whole):
        if pattern:
            spans += [m.span() for m in re.finditer(r"[a-z]+", text) if pattern.fullmatch(m.group())]
            if pattern.fullmatch(text):
                spans.append((0, len(text)))
    hidden = set()
    for start, end in spans:
        first, last = where[start], where[end - 1]
        hidden.update(range(first + 1, last))
    return "".join("*" if i in hidden and not name[i].isspace() else ch for i, ch in enumerate(name))


# ----- names and ids for the dashboard -------------------------------------

FUN_ADJECTIVES = (
    "Sly", "Cheeky", "Grumpy", "Brave", "Sneaky", "Lazy", "Bold", "Swift", "Lucky", "Shady",
    "Jolly", "Sleepy", "Clever", "Fuzzy", "Quiet", "Wily", "Dapper", "Plucky", "Calm", "Daring",
)
FUN_ANIMALS = (
    "Otter", "Badger", "Heron", "Llama", "Fox", "Raccoon", "Newt", "Mole", "Walrus", "Owl",
    "Ferret", "Goose", "Moose", "Lynx", "Panda", "Puffin", "Toad", "Weasel", "Yak", "Gecko",
)
#: Short ids are typed by hand, so the alphabet leaves out look-alikes.
ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def fun_name(seed: Optional[str] = None, rng: Optional[random.Random] = None) -> str:
    """"Sly Otter": the same name for the same seed, or a random one."""
    if seed is not None:
        n = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
        return f"{FUN_ADJECTIVES[n % len(FUN_ADJECTIVES)]} {FUN_ANIMALS[(n // 97) % len(FUN_ANIMALS)]}"
    rng = rng or random.Random()
    return f"{rng.choice(FUN_ADJECTIVES)} {rng.choice(FUN_ANIMALS)}"


def fun_names(count: int, rng: Optional[random.Random] = None) -> List[str]:
    rng = rng or random.Random()
    out: List[str] = []
    while len(out) < count:
        name = fun_name(rng=rng)
        if name not in out:
            out.append(name)
    return out


def short_id(pid: str) -> str:
    """A player's 4-character id for the dashboard, like "K7Q2"."""
    n = int(hashlib.sha1(pid.encode()).hexdigest(), 16)
    out = ""
    for _ in range(4):
        n, i = divmod(n, len(ID_ALPHABET))
        out += ID_ALPHABET[i]
    return out
