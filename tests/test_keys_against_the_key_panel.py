"""
What pyte sends a pane for a key, put to kitty, Ghostty and WezTerm.

`test_keys_against_kitty.py` holds pyte to kitty alone, and every
difference there is a named deviation. That is one terminal's opinion,
so this file takes the vote of all three on each deviation, and keeps
it: a vote that changes fails, the way an example that stops differing
does there.

It also judges what kitty cannot: xterm's modifyOtherKeys (the
extended mode) and DECKPAM, at every level, for every key. There no
difference needs a name unless the panel is against pyte: "pyte-wrong"
and "pyte-alone" fail, "split" and "lone" do not. `key_panel.py` says
what each verdict means.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

import pytest
from key_panel import Request, ask, judges_are_available, verdict
from kitty_keys import SOURCE_FLAGS, judged, keyboard, kitty_encodes
from test_keys_against_kitty import DEVIATIONS

from pyte.keys import Modifier, ModifyOtherKeys, translate_key_data

pytestmark = pytest.mark.skipif(not judges_are_available(), reason="the key judges are not there")

#: The vote on the example of each deviation in `test_keys_against_kitty.py`:
#: the judges that send what pyte sends, then the ones that do not.
VOTES = {
    "a mode that no program pushes": ((), ("kitty", "ghostty", "wezterm")),
    "kitty folds keypad 0 and 9 and no digit between": (("ghostty", "wezterm"), ("kitty",)),
    "a key with no legacy form is dropped": (("ghostty",), ("kitty", "wezterm")),
    "super on a key a legacy pane reads is dropped": (("ghostty", "wezterm"), ("kitty",)),
    "a modified F3 takes the cursor report form": (("wezterm",), ("kitty", "ghostty")),
    "ctrl and Enter is a line feed": ((), ("kitty", "ghostty", "wezterm")),
    "ctrl and shift on a letter is the control code": (("wezterm",), ("kitty", "ghostty")),
    "shift with ctrl or alt on a key that is not a letter is lost": ((), ("kitty", "ghostty", "wezterm")),
    "Home, End and Begin ignore the cursor key mode": ((), ("kitty", "ghostty", "wezterm")),
    "a modifier key reaches a pane that did not ask for every key": ((), ("kitty", "ghostty")),
    "shift on Enter or Backspace is lost": ((), ("kitty", "ghostty", "wezterm")),
}


def _request(case) -> Request:
    return Request(case.key, case.code, case.shifted, case.mods, case.action, case.flags, case.cursor_key_mode)


def test_every_deviation_has_a_vote():
    assert sorted(VOTES) == sorted(deviation.name for deviation in DEVIATIONS)


@pytest.mark.parametrize("deviation", DEVIATIONS, ids=lambda deviation: deviation.name)
def test_the_vote_on_a_deviation(deviation):
    case = judged(*deviation.example)
    vote = verdict(case.pyte, ask([_request(case)])[0])
    assert (vote.with_pyte, vote.against) == VOTES[deviation.name], (deviation.issue, case)


class ExtendedCase(NamedTuple):
    request: Request
    pyte: str
    answers: dict[str, str | None]


class ExtendedDeviation(NamedTuple):
    "A verdict against pyte in the extended mode or DECKPAM, and its issue."

    name: str
    issue: str
    matches: Callable[[ExtendedCase], bool]


EXTENDED_DEVIATIONS = [
    ExtendedDeviation(
        "super is dropped",
        "Lillecarl/pymux#693",
        # Ghostty writes super as xterm's meta, "CSI 27 ; 9 ; 97 ~", and
        # WezTerm as no modifier at all, "CSI 27 ; 1 ; 97 ~".
        lambda case: bool(case.request.mods & Modifier.SUPER),
    ),
    ExtendedDeviation(
        "Home, End and Begin ignore the cursor key mode",
        "Lillecarl/pymux#687",
        lambda case: case.request.cursor_key_mode and set(case.answers.values()) & {"\x1bOH", "\x1bOF", "\x1bOE"},
    ),
    # The rest wait for xterm, whose mode this is: the two judges and
    # pyte give three answers, or the two agree against pyte's reading
    # of xterm's own rule.
    ExtendedDeviation(
        "alt and Escape is an escape code",
        "Lillecarl/pymux#698",
        # Ghostty and WezTerm write "ESC ESC"; pyte "CSI 27 ; 3 ; 27 ~".
        lambda case: case.request.key == "ESCAPE" and bool(case.request.mods & Modifier.ALT),
    ),
    ExtendedDeviation(
        "ctrl and Backspace",
        "Lillecarl/pymux#698",
        # pyte "CSI 27 ; 5 ; 127 ~", Ghostty BS, WezTerm "CSI 27 ; 5 ; 8 ~".
        lambda case: case.request.key == "BACKSPACE" and bool(case.request.mods & Modifier.CTRL),
    ),
    ExtendedDeviation(
        "a shifted key is written by its unshifted code",
        "Lillecarl/pymux#698",
        # alt+shift+minus: pyte "CSI 27 ; 4 ; 45 ~", Ghostty "CSI 27 ; 4 ;
        # 95 ~", WezTerm "ESC _". Caps lock on a letter splits the same way.
        # Space has no shifted character, so it is not one of these.
        lambda case: (
            case.request.key.startswith("'")
            and bool(case.request.shifted)
            and bool(case.request.mods & (Modifier.SHIFT | Modifier.CAPS_LOCK))
        ),
    ),
    ExtendedDeviation(
        "alt and keypad Enter",
        "Lillecarl/pymux#698",
        # pyte "CSI 27 ; 3 ; 13 ~", Ghostty CR, WezTerm "ESC CR".
        lambda case: case.request.key == "KP_ENTER" and bool(case.request.mods & Modifier.ALT),
    ),
]


def _extended_cases(other_keys: int, keypad: bool) -> list[ExtendedCase]:
    requests, pytes = [], []
    for key, code, shifted, mods, action, cursor_key_mode in keyboard():
        if action != "press":
            continue
        requests.append(Request(key, code, shifted, mods, action, 0, cursor_key_mode, other_keys, keypad))
        source = kitty_encodes(code, shifted, mods, action, SOURCE_FLAGS, cursor_key_mode)
        pytes.append(
            translate_key_data(
                source,
                flags=0,
                application_mode=cursor_key_mode,
                source_flags=SOURCE_FLAGS,
                synthesize=False,
                modify_other_keys=other_keys,
                application_keypad=keypad,
            )
        )
    return [ExtendedCase(*fields) for fields in zip(requests, pytes, ask(requests), strict=True)]


#: Every mode kitty cannot judge. modifyOtherKeys off with the normal
#: keypad is flags 0, which `test_keys_against_kitty.py` holds.
EXTENDED_MODES = [(level, keypad) for level in ModifyOtherKeys for keypad in (False, True) if level or keypad]


@pytest.mark.parametrize(
    ("other_keys", "keypad"),
    EXTENDED_MODES,
    ids=["%s%s" % (level.name, ", DECKPAM" if keypad else "") for level, keypad in EXTENDED_MODES],
)
def test_the_panel_is_not_against_pyte_in_the_extended_mode(other_keys, keypad):
    against = []
    for case in _extended_cases(other_keys, keypad):
        vote = verdict(case.pyte, case.answers)
        if vote.verdict in ("pyte-wrong", "pyte-alone") and not any(d.matches(case) for d in EXTENDED_DEVIATIONS):
            against.append((vote, case))
    assert not against, "%d keys the panel says pyte sends wrong, the first: %r" % (len(against), against[0])


def test_an_arrow_with_num_lock_is_judged_by_the_whole_panel():
    """
    #684 is in the vote: every judge sends "CSI D" for Left with num
    lock to a legacy pane, so a pyte that kept the lock is pyte-wrong.
    """
    case = judged("LEFT", Modifier.NUM_LOCK, "press", 0)
    answers = ask([_request(case)])[0]
    assert answers == {"kitty": "\x1b[D", "ghostty": "\x1b[D", "wezterm": "\x1b[D"}
    assert verdict("\x1b[1;129D", answers).verdict == "pyte-wrong"
