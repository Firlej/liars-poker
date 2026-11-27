"""Keeps offensive player names off the table (App Store guideline 1.2).

A name is checked after undoing the usual disguises: letters with accents,
look-alike digits and symbols ("a$$", "sh1t"), dots or spaces between letters
("f.u.c.k") and stretched letters ("fuuuck"). Two lists:

- ``ANYWHERE``: words that are offensive even inside a longer name.
- ``WHOLE_WORDS``: short words that are only offensive on their own, because
  they also hide inside normal words ("ass" in "Cassandra", "cock" in "Hancock").

``ALLOWED`` lists real words that happen to contain an ``ANYWHERE`` word.
The app keeps a copy of these lists in ``utils/nameFilter.ts`` (keep in sync).
"""
from __future__ import annotations

import itertools
import re
import unicodedata

ANYWHERE = (
    # English
    "fuck", "fck", "shit", "cunt", "nigger", "nigga", "faggot", "bitch", "whore", "slut",
    "asshole", "bastard", "dildo", "porn", "penis", "vagina", "pussy", "twat", "wank",
    "jizz", "retard", "tranny", "molest", "pedophil", "paedophil", "hitler", "blowjob",
    "handjob", "cocksuck", "killyourself",
    # Polish
    "kurw", "chuj", "huj", "pizd", "pierdol", "pierdal", "jebac", "jeban", "jebie", "jebn",
    "zjeb", "dziwk", "cwel", "kutas", "cipk",
)
WHOLE_WORDS = (
    "ass", "cum", "tit", "tits", "dick", "cock", "fag", "nazi", "kkk", "kys", "rape",
    "rapist", "pedo", "nonce", "spic", "chink", "kike", "coon", "anal", "anus",
    "cipa", "ciota", "fiut", "szmata",
)
ALLOWED = ("scunthorpe", "penistone", "swank", "shiitake", "matsushita")

#: Look-alikes people use to slip past filters.
LOOK_ALIKES = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b",
                             "@": "a", "$": "s", "!": "i", "|": "i", "+": "t", "€": "e", "ł": "l"})


def _stretchy(word: str) -> str:
    """"ass" -> "a+s{2,}": also matches "aaasss", never "as"."""
    return "".join(f"{ch}{{{len(list(run))},}}" for ch, run in itertools.groupby(word))


_ANYWHERE = re.compile("|".join(_stretchy(w) for w in ANYWHERE))
_WHOLE = re.compile("|".join(_stretchy(w) for w in WHOLE_WORDS))
_ALLOWED = re.compile("|".join(_stretchy(w) for w in ALLOWED))


def _plain(name: str) -> str:
    """Lower case, accents dropped, look-alikes turned into letters."""
    text = name.lower().translate(LOOK_ALIKES)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def is_allowed(name: str) -> bool:
    plain = _plain(name)
    words = [w for w in re.split(r"[^a-z]+", plain) if w]
    letters = "".join(words)
    if _ANYWHERE.search(_ALLOWED.sub("", letters)):
        return False
    return not any(_WHOLE.fullmatch(w) for w in [*words, letters])
