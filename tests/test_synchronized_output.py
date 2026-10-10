"""
"?2026": the program is drawing a frame, so show the last one.

The screen only keeps the mode. Holding the picture is the job of
whoever shows the screen, the way tmux holds a pane (`MODE_SYNC` in
`screen-write.c`). Lillecarl/pymux#566.
"""

from __future__ import annotations

from a_screen import display

from pyte import escape
from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.sequences import Csi, csi, esc, reset_mode, set_mode
from pyte.streams import Stream

BEGIN = set_mode(PrivateMode.SYNCHRONIZED_OUTPUT)
END = reset_mode(PrivateMode.SYNCHRONIZED_OUTPUT)
ASK = csi(Csi.DECRQM, 2026, private="?")


def make_screen():
    "Return (screen, stream, what the screen answered)."
    answers = []
    screen = Screen(4, 20, write_process_input=answers.append)
    return screen, Stream(screen), answers


def test_a_program_that_asks_hears_the_mode_is_known():
    "An answer of 0 tells a program not to bracket its frames at all."
    _screen, stream, answers = make_screen()
    stream.feed(ASK)
    assert answers == ["\x1b[?2026;2$y"]
    answers.clear()
    stream.feed(BEGIN + ASK)
    assert answers == ["\x1b[?2026;1$y"]


def test_the_mode_lasts_from_the_set_to_the_reset():
    screen, stream, _answers = make_screen()
    assert screen.draws_a_frame is False
    stream.feed(BEGIN + "half a frame")
    assert screen.draws_a_frame is True
    stream.feed(END)
    assert screen.draws_a_frame is False


def test_the_screen_still_takes_what_is_drawn():
    screen, stream, _answers = make_screen()
    stream.feed(BEGIN + "drawn")
    assert display(screen)[0].startswith("drawn")


def test_a_hard_reset_ends_it():
    screen, stream, _answers = make_screen()
    stream.feed(BEGIN + esc(escape.RIS))
    assert screen.draws_a_frame is False
