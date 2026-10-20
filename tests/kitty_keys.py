"""
Ask kitty's own key encoder what a pane reads, and compare pyte.

`pyte/keys.py` is a port of `kitty/key_encoding.c`, and only a
comparison against the original says whether the port is right. kitty
carries the encoder in its python extension, as `encode_key_for_tty`,
so kitty answers both halves of the question:

- what the terminal of the person sends to pymux, which pushed every
  flag (`SOURCE_FLAGS`), and
- what that same key sends to a pane that pushed `flags`.

pyte translates the first into the second, and kitty says what the
second should be. Lillecarl/pymux#684 is what the comparison would
have caught: kitty takes the locks off for a pane that pushed no flag,
and pyte did not.

`PYTE_KITTY` names the directory that holds the `kitty` package, the
way `PTTERM_KITTY` does for `ptterm/tests/kitty_oracle.py`.

**The keyboard is a model, and it only has to be one keyboard.** kitty
takes the text of a key from xkb, and nothing here runs xkb. `text_of`
gives a key the text that xkb gives it on a US layout, closely enough
that both calls to kitty and the one to pyte see the same key. Where
it guesses, all three see the same guess.
"""

from __future__ import annotations

import itertools
import os
import sys
from typing import NamedTuple

from pyte.keys import KeyboardFlag, Modifier, translate_key_data

__all__ = [
    "MODIFIER_SETS",
    "SOURCE_FLAGS",
    "Case",
    "disagreements",
    "judged",
    "keyboard",
    "kitty_encodes",
    "kitty_keys_are_available",
    "typed",
]

#: What pymux pushes to the terminal of the person: every flag.
SOURCE_FLAGS = (
    KeyboardFlag.DISAMBIGUATE
    | KeyboardFlag.REPORT_EVENT_TYPES
    | KeyboardFlag.REPORT_ALTERNATE_KEYS
    | KeyboardFlag.REPORT_ALL_KEYS
    | KeyboardFlag.REPORT_ASSOCIATED_TEXT
)

_LOCKS = Modifier.CAPS_LOCK | Modifier.NUM_LOCK

#: The modifiers that take the text off a key, in xkb as kitty reads it
#: (`glfw/xkb_glfw.c`: "xkb returns text even if alt and/or super are
#: pressed", and kitty clears it then).
_NO_TEXT = Modifier.CTRL | Modifier.ALT | Modifier.SUPER | Modifier.HYPER | Modifier.META

#: Every set of the six modifiers that an encoder treats apart. Hyper
#: and meta go the way super does in both encoders, so they would only
#: multiply the run by four.
MODIFIER_SETS = tuple(
    sum(bits)
    for n in range(7)
    for bits in itertools.combinations(
        (Modifier.SHIFT, Modifier.ALT, Modifier.CTRL, Modifier.SUPER, Modifier.CAPS_LOCK, Modifier.NUM_LOCK), n
    )
)

#: The keys that write a character, with what shift gives on a US layout.
_TEXT_KEYS = {"a": "A", "z": "Z", "1": "!", "[": "{", "/": "?", " ": " ", "-": "_"}


class Case(NamedTuple):
    "One key, in one mode, where pyte and kitty differ."

    key: str  # the name kitty gives it, or the character
    code: int
    shifted: int  # the code point shift gives the key, or 0
    mods: int
    action: str  # "press", "repeat" or "release"
    flags: int
    cursor_key_mode: bool
    source: str  # what the terminal of the person sends
    kitty: str  # what kitty sends the pane
    pyte: str  # what pyte sends it


_kitty = None


def kitty_keys_are_available() -> bool:
    global _kitty, _KEYPAD_WITHOUT_NUM_LOCK
    path = os.environ.get("PYTE_KITTY")
    if not path:
        return False
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        from kitty import fast_data_types
    except Exception:
        return False
    _kitty = fast_data_types
    _KEYPAD_WITHOUT_NUM_LOCK = frozenset(
        getattr(_kitty, "GLFW_FKEY_" + name) for name in _KEYPAD_NAMES_WITHOUT_NUM_LOCK
    )
    return True


def _keys():
    "Every key kitty names, then the text keys: (name, code, shifted)."
    names = sorted(name for name in dir(_kitty) if name.startswith("GLFW_FKEY_"))
    for name in names:
        yield name.removeprefix("GLFW_FKEY_"), getattr(_kitty, name), 0
    for char, shifted in _TEXT_KEYS.items():
        yield repr(char), ord(char), ord(shifted) if shifted != char else 0


_KEYPAD_NAMES_WITHOUT_NUM_LOCK = (
    "KP_INSERT",
    "KP_END",
    "KP_DOWN",
    "KP_PAGE_DOWN",
    "KP_LEFT",
    "KP_BEGIN",
    "KP_RIGHT",
    "KP_HOME",
    "KP_UP",
    "KP_PAGE_UP",
    "KP_DELETE",
)
_KEYPAD_WITHOUT_NUM_LOCK: frozenset[int] = frozenset()


def _actions():
    return {"press": _kitty.GLFW_PRESS, "repeat": _kitty.GLFW_REPEAT, "release": _kitty.GLFW_RELEASE}


def text_of(code: int, shifted: int, mods: int, action: str) -> str:
    "The text xkb gives this key, as near as a US layout says."
    if action == "release" or mods & _NO_TEXT:
        return ""
    return typed(code, shifted, mods)


def typed(code: int, shifted: int, mods: int) -> str:
    """
    The character this key types before ctrl or alt change it.

    kitty has no text with ctrl held, and Ghostty asks for this one
    anyway: "the unmodified character before any Ctrl/Meta
    transformations" (`ghostty/vt/key/event.h`).
    """
    if _kitty.GLFW_FKEY_KP_0 <= code <= _kitty.GLFW_FKEY_KP_9:
        # Num lock makes a digit of a keypad key, and only then does it
        # write one (`glfw/xkb_glfw.c`, under `GLFW_MOD_NUM_LOCK`).
        return chr(ord("0") + code - _kitty.GLFW_FKEY_KP_0) if mods & Modifier.NUM_LOCK else ""
    if code >= 0xE000:
        return ""
    char = chr(code)
    upper = bool(mods & Modifier.SHIFT) ^ bool(mods & Modifier.CAPS_LOCK and char.isalpha())
    return chr(shifted) if upper and shifted else char


def kitty_encodes(code: int, shifted: int, mods: int, action: str, flags: int, cursor_key_mode: bool) -> str:
    "What kitty sends for this key to a pane that pushed `flags`."
    return _kitty.encode_key_for_tty(
        key=code,
        shifted_key=shifted,
        mods=mods,
        action=_actions()[action],
        key_encoding_flags=flags,
        text=text_of(code, shifted, mods, action) or None,
        cursor_key_mode=cursor_key_mode,
    )


def _judged(key: str, code: int, shifted: int, mods: int, action: str, flags: int, cursor_key_mode: bool) -> Case:
    source = kitty_encodes(code, shifted, mods, action, SOURCE_FLAGS, cursor_key_mode)
    kitty = kitty_encodes(code, shifted, mods, action, flags, cursor_key_mode)
    pyte = translate_key_data(
        source, flags=flags, application_mode=cursor_key_mode, source_flags=SOURCE_FLAGS, synthesize=False
    )
    return Case(key, code, shifted, mods, action, flags, cursor_key_mode, source, kitty, pyte)


def judged(key: str, mods: int, action: str, flags: int, cursor_key_mode: bool = False) -> Case:
    "One key, by the name `Case.key` gives it, judged both ways."
    for name, code, shifted in _keys():
        if name == key:
            return _judged(name, code, shifted, mods, action, flags, cursor_key_mode)
    raise KeyError(key)


def _on_this_keyboard(code: int, mods: int) -> bool:
    """
    Whether xkb gives this key with these modifiers.

    A keypad key is two keys, and num lock picks which one: KP_0 with
    it, KP_INSERT without. So a digit without num lock is no key at
    all, and neither is KP_INSERT with it.
    """
    if _kitty.GLFW_FKEY_KP_0 <= code <= _kitty.GLFW_FKEY_KP_9:
        return bool(mods & Modifier.NUM_LOCK)
    if code in _KEYPAD_WITHOUT_NUM_LOCK:
        return not mods & Modifier.NUM_LOCK
    return True


def keyboard():
    "Every key, modifier set, event and cursor key mode the sweep tries."
    for (key, code, shifted), mods, action, cursor_key_mode in itertools.product(
        list(_keys()), MODIFIER_SETS, _actions(), (False, True)
    ):
        if _on_this_keyboard(code, mods):
            yield key, code, shifted, mods, action, cursor_key_mode


def disagreements(flags: int):
    "Every key, modifier set and event where pyte and kitty differ."
    for key, code, shifted, mods, action, cursor_key_mode in keyboard():
        case = _judged(key, code, shifted, mods, action, flags, cursor_key_mode)
        if case.pyte != case.kitty:
            yield case
