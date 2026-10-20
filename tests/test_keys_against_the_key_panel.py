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
    "super on a key a legacy pane reads is dropped": (("ghostty", "wezterm", "xterm"), ("kitty",)),
    "a modified F3 takes the cursor report form": (("wezterm", "xterm"), ("kitty", "ghostty")),
    "ctrl and shift on a letter is the control code": (("wezterm", "xterm"), ("kitty", "ghostty")),
    "shift with ctrl or alt on a key with no shifted key is dropped": (("ghostty", "wezterm"), ("kitty",)),
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
    #: A key the panel still says pyte sends wrong this way.
    example: Request


def _press(key: str, code: int, shifted: int, mods: int, other_keys: int, keypad: bool = False) -> Request:
    return Request(key, code, shifted, mods, "press", 0, False, other_keys, keypad)


EXTENDED_DEVIATIONS = [
    ExtendedDeviation(
        "super is written and dropped by turns",
        "Lillecarl/pymux#693",
        # pyte drops super where a character is written and keeps it in a
        # CSI form: super+Delete is "CSI 3 ; 9 ~", where xterm and WezTerm
        # drop it, "CSI 3 ~". Ghostty writes it as xterm's meta.
        lambda case: bool(case.request.mods & Modifier.SUPER),
        _press("DELETE", 57349, 0, Modifier.SUPER, ModifyOtherKeys.ALT_AND_META),
    ),
    ExtendedDeviation(
        "caps lock on keypad Begin at level 3",
        "Lillecarl/pymux#700",
        # xterm "CSI 1 ; 1 E", WezTerm "CSI E", pyte "SS3 E" with DECCKM:
        # three answers, and only a lock to tell them apart.
        lambda case: (
            case.request.key == "KP_BEGIN"
            and bool(case.request.mods & Modifier.CAPS_LOCK)
            and case.request.other_keys == ModifyOtherKeys.EVERY_KEY
        ),
        Request("KP_BEGIN", 57427, 0, Modifier.CAPS_LOCK, "press", 0, True, ModifyOtherKeys.EVERY_KEY, False),
    ),
    ExtendedDeviation(
        "ctrl on a shifted key from 0x60 to 0x7F has no control code",
        "Lillecarl/pymux#704",
        # ctrl+shift+[: pyte and kitty "{", xterm ESC, Ghostty CSI u.
        lambda case: (
            case.request.key.startswith("'")
            and 0x60 <= case.request.shifted <= 0x7F
            and case.request.mods & (Modifier.CTRL | Modifier.SHIFT) == Modifier.CTRL | Modifier.SHIFT
        ),
        _press("'['", 91, 123, Modifier.CTRL | Modifier.SHIFT, ModifyOtherKeys.OFF, keypad=True),
    ),
]


def _pyte_reads(request: Request) -> str:
    "What pyte sends for this request, from what the terminal of the person sends."
    source = kitty_encodes(
        request.code, request.shifted, request.mods, request.action, SOURCE_FLAGS, request.cursor_key_mode
    )
    return translate_key_data(
        source,
        flags=0,
        application_mode=request.cursor_key_mode,
        source_flags=SOURCE_FLAGS,
        synthesize=False,
        modify_other_keys=request.other_keys,
        application_keypad=request.keypad,
    )


def _extended_cases(other_keys: int, keypad: bool) -> list[ExtendedCase]:
    requests = [
        Request(key, code, shifted, mods, action, 0, cursor_key_mode, other_keys, keypad)
        for key, code, shifted, mods, action, cursor_key_mode in keyboard()
        if action == "press"
    ]
    pytes = [_pyte_reads(request) for request in requests]
    return [ExtendedCase(*fields) for fields in zip(requests, pytes, ask(requests), strict=True)]


@pytest.mark.parametrize("deviation", EXTENDED_DEVIATIONS, ids=lambda deviation: deviation.name)
def test_the_extended_deviation_is_still_there(deviation):
    case = ExtendedCase(deviation.example, _pyte_reads(deviation.example), ask([deviation.example])[0])
    vote = verdict(case.pyte, case.answers)
    assert vote.verdict in ("pyte-wrong", "pyte-alone"), "%s is gone: take it off (%s) %r" % (
        deviation.name,
        deviation.issue,
        vote,
    )
    assert deviation.matches(case), case


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
    assert answers == {"kitty": "\x1b[D", "ghostty": "\x1b[D", "wezterm": "\x1b[D", "xterm": "\x1b[D"}
    assert verdict("\x1b[1;129D", answers).verdict == "pyte-wrong"
