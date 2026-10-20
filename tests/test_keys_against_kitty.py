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

from collections.abc import Callable
from typing import NamedTuple

import pytest
from kitty_keys import Case, disagreements, judged, kitty_keys_are_available

from pyte.keys import KeyboardFlag, Modifier

pytestmark = pytest.mark.skipif(not kitty_keys_are_available(), reason="PYTE_KITTY names no kitty")

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
        "kitty writes a keypad key by the number of its character",
        "Lillecarl/pymux#695",
        # A pane that pushed a flag but not DISAMBIGUATE or REPORT_ALL_KEYS
        # gets a modified keypad + as "CSI 43 ; 9 u" from kitty, which
        # folds the keypad first. Ghostty and WezTerm keep the keypad's
        # own number, "CSI 57413 ; 9 u", and so does pyte.
        lambda case: bool(case.flags) and not _reads_the_number(case.flags) and case.key.startswith("KP_"),
        ("KP_ADD", Modifier.SUPER, "press", KeyboardFlag.REPORT_EVENT_TYPES),
    ),
    Deviation(
        "Escape under the event types alone",
        "Lillecarl/pymux#695",
        # A lock on Escape, and its repeat and release, to a pane that
        # pushed only the event types: kitty sends ESC for the second and
        # "CSI 27 ; 65 u" for the first, Ghostty "CSI 27 ; 1 : 2 u" for the
        # repeat and WezTerm ESC for the lock. pyte takes one of them each.
        lambda case: (
            bool(case.flags & KeyboardFlag.REPORT_EVENT_TYPES)
            and not _reads_the_number(case.flags)
            and case.key == "ESCAPE"
        ),
        ("ESCAPE", Modifier.CAPS_LOCK, "press", KeyboardFlag.REPORT_EVENT_TYPES),
    ),
    Deviation(
        "kitty folds keypad 0 and 9 and no digit between",
        "kitty's own",
        # `convert_kp_key_to_normal_key` has "case GLFW_FKEY_KP_0: case
        # GLFW_FKEY_KP_9:" where a range is meant, so a modified keypad 1
        # to 8 reaches a legacy pane as "CSI 57400 ; 3 u".
        lambda case: (
            case.flags == 0 and case.key in {"KP_%d" % n for n in range(1, 9)} and case.kitty.startswith("\x1b[574")
        ),
        ("KP_1", Modifier.ALT | Modifier.NUM_LOCK, "press", 0),
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
        "shift with ctrl or alt on a key with no shifted key is dropped",
        "Lillecarl/pymux#691",
        # Space and the keypad have no shifted key, so kitty finds no
        # legacy form and writes "CSI 32 ; 8 u". Ghostty and WezTerm drop
        # the shift, as pyte does: alt+ctrl+shift+space is "ESC NUL".
        lambda case: (
            case.flags == 0
            and not case.shifted
            and bool(case.mods & Modifier.SHIFT)
            and bool(case.mods & (Modifier.ALT | Modifier.CTRL))
            and case.key not in _LETTERS
        ),
        ("' '", Modifier.ALT | Modifier.CTRL | Modifier.SHIFT, "press", 0),
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
