"""
What pyte sends a pane for a key, judged against kitty's own encoder.

Every key kitty names, with every set of modifiers that an encoder
treats apart, pressed, repeated and released, in both cursor key
modes and under every set of the five flags. `kitty_keys.py` says
where both answers come from.

**Every difference is named, or the run fails.** A port that drifts
from the original in silence is how Lillecarl/pymux#684 happened: a
lock reached bash as "CSI 1 ; 129 D", and kitty never sends that. So
a difference is one of `DEVIATIONS`, with the issue that holds it, or
it is a failure. Each entry carries one key that has to differ still,
so an entry that is fixed fails until it goes.

**Two modes are not judged here.** kitty has no xterm modifyOtherKeys
(the extended mode, XTMODKEYS) and no DECKPAM keypad, so both stay
off. `test_keys.py` holds them by hand.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple

import pytest
from kitty_keys import Case, disagreements, judged, kitty_keys_are_available

from pyte.keys import KeyboardFlag, Modifier

pytestmark = pytest.mark.skipif(not kitty_keys_are_available(), reason="PYTE_KITTY names no kitty")

#: The keys that are a modifier or a lock, as kitty names them.
_MODIFIER_KEYS = re.compile(
    r"(LEFT|RIGHT)_(SHIFT|CONTROL|ALT|SUPER|HYPER|META)|CAPS_LOCK|NUM_LOCK|SCROLL_LOCK|ISO_LEVEL[35]_SHIFT"
)

_LETTERS = ("'a'", "'z'")


def _reads_the_number(flags: int) -> bool:
    return bool(flags & (KeyboardFlag.DISAMBIGUATE | KeyboardFlag.REPORT_ALL_KEYS))


class Deviation(NamedTuple):
    "A difference from kitty that is known, and where it is held."

    name: str
    issue: str
    matches: Callable[[Case], bool]
    #: A key that differs this way: `judged` takes it as it stands.
    example: tuple


DEVIATIONS = [
    Deviation(
        "a mode that no program pushes",
        "Lillecarl/pymux#695",
        # The event types, the other keys or the text, with neither flag
        # that says how to write a key. kitty keeps the locks there and
        # folds the keypad by a rule of its own.
        lambda case: bool(case.flags) and not _reads_the_number(case.flags),
        ("KP_0", 0, "press", KeyboardFlag.REPORT_ASSOCIATED_TEXT),
    ),
    Deviation(
        "kitty folds keypad 0 and 9 and no digit between",
        "kitty's own",
        # `convert_kp_key_to_normal_key` has "case GLFW_FKEY_KP_0: case
        # GLFW_FKEY_KP_9:" where a range is meant, so keypad 1 to 8 reach
        # a legacy pane as "CSI 57400 u". A keyboard rarely sends one:
        # xkb gives KP_End without num lock, and text with it.
        lambda case: (
            case.flags == 0 and case.key in {"KP_%d" % n for n in range(1, 9)} and case.kitty.startswith("\x1b[574")
        ),
        ("KP_1", 0, "press", 0),
    ),
    Deviation(
        "a key with no legacy form is dropped",
        "Lillecarl/pymux#692",
        # F13 and up, the media keys, Menu, Pause, Print Screen and the
        # keypad separator. kitty writes "CSI number u", and Menu as
        # "CSI 29 ~". pyte sends nothing, Lillecarl/pymux#166.
        lambda case: case.flags == 0 and case.pyte == "" and case.kitty.startswith("\x1b["),
        ("F13", 0, "press", 0),
    ),
    Deviation(
        "super on a key a legacy pane reads is dropped",
        "Lillecarl/pymux#693",
        # kitty writes "CSI 97 ; 9 u". pyte drops super, hyper and meta:
        # `_MODIFIERS_THE_LEGACY_ENCODING_DROPS`.
        lambda case: case.flags == 0 and bool(case.mods & Modifier.SUPER),
        ("'a'", Modifier.SUPER, "press", 0),
    ),
    Deviation(
        "a modified F3 takes the cursor report form",
        "Lillecarl/pymux#242",
        lambda case: case.flags == 0 and case.key == "F3" and case.pyte.endswith("R"),
        ("F3", Modifier.SHIFT, "press", 0),
    ),
    Deviation(
        "ctrl and Enter is a line feed",
        "Lillecarl/pymux#694",
        lambda case: (
            case.flags == 0
            and case.key in ("ENTER", "KP_ENTER")
            and case.kitty.endswith("\r")
            and case.pyte.endswith("\n")
        ),
        ("ENTER", Modifier.CTRL, "press", 0),
    ),
    Deviation(
        "ctrl on space, slash or a bracket writes no control code",
        "Lillecarl/pymux#686",
        # kitty's `ctrled_key` gives NUL, 0x1f and ESC.
        lambda case: (
            case.flags == 0 and bool(case.mods & Modifier.CTRL) and case.key in ("' '", "'/'", "'['", "KP_DIVIDE")
        ),
        ("' '", Modifier.CTRL, "press", 0),
    ),
    Deviation(
        "ctrl and shift on a letter is the control code",
        "Lillecarl/pymux#168",
        # kitty finds no legacy form and writes "CSI 97 ; 6 u".
        lambda case: (
            case.flags == 0
            and case.mods & (Modifier.CTRL | Modifier.SHIFT) == Modifier.CTRL | Modifier.SHIFT
            and case.key in _LETTERS
        ),
        ("'a'", Modifier.CTRL | Modifier.SHIFT, "press", 0),
    ),
    Deviation(
        "shift with ctrl or alt on a key that is not a letter is lost",
        "Lillecarl/pymux#691",
        # kitty takes the shifted key from the alternates: alt+shift+1 is
        # "ESC !" and ctrl+shift+minus is ctrl+underscore. A key with no
        # shifted key is "CSI number ; mods u". pyte drops the shift.
        lambda case: (
            case.flags == 0
            and bool(case.mods & Modifier.SHIFT)
            and bool(case.mods & (Modifier.ALT | Modifier.CTRL))
            and case.key not in _LETTERS
        ),
        ("'1'", Modifier.ALT | Modifier.SHIFT, "press", 0),
    ),
    Deviation(
        "Home, End and Begin ignore the cursor key mode",
        "Lillecarl/pymux#687",
        lambda case: case.flags == 0 and case.cursor_key_mode and case.kitty in ("\x1bOH", "\x1bOF", "\x1bOE"),
        ("HOME", 0, "press", 0, True),
    ),
    Deviation(
        "a modifier key reaches a pane that did not ask for every key",
        "Lillecarl/pymux#688",
        # kitty sends a modifier key only with REPORT_ALL_KEYS
        # (`is_modifier_key` in `encode_glfw_key_event`).
        lambda case: (
            bool(_MODIFIER_KEYS.fullmatch(case.key))
            and case.kitty == ""
            and not case.flags & KeyboardFlag.REPORT_ALL_KEYS
        ),
        ("LEFT_SHIFT", 0, "press", KeyboardFlag.DISAMBIGUATE),
    ),
    Deviation(
        "shift on Enter or Backspace is lost",
        "Lillecarl/pymux#689",
        # kitty writes "CSI 13 ; 2 u" once the pane disambiguates.
        lambda case: (
            case.key in ("ENTER", "BACKSPACE", "KP_ENTER")
            and bool(case.flags & KeyboardFlag.DISAMBIGUATE)
            and case.pyte in ("\r", "\x7f")
        ),
        ("ENTER", Modifier.SHIFT, "press", KeyboardFlag.DISAMBIGUATE),
    ),
]


@pytest.mark.parametrize("flags", range(32))
def test_every_difference_from_kitty_is_known(flags):
    unknown = [case for case in disagreements(flags) if not any(d.matches(case) for d in DEVIATIONS)]
    assert not unknown, "%d differences from kitty that no deviation names, the first: %r" % (len(unknown), unknown[0])


@pytest.mark.parametrize("deviation", DEVIATIONS, ids=lambda deviation: deviation.name)
def test_the_deviation_is_still_there(deviation):
    case = judged(*deviation.example)
    assert case.pyte != case.kitty, "%s is gone: take it off DEVIATIONS (%s)" % (deviation.name, deviation.issue)
    assert deviation.matches(case), case


def test_a_lock_is_judged():
    """
    The sweep holds the locks, and #684 is in it: an arrow with num
    lock reaches a legacy pane the way kitty sends it.
    """
    case = judged("LEFT", Modifier.NUM_LOCK, "press", 0)
    assert case.source == "\x1b[1;129D"
    assert case.pyte == case.kitty == "\x1b[D"
