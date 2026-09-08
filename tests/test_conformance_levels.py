"""
DECSCL: which DEC terminal this one answers as.

Each level is one DEC terminal, and a higher level carries everything
the levels below it carry and more. A program that asks for an earlier
terminal loses the sequences that came later.

pyte does not drop every later sequence. It drops the three that
esctest2 asks about, because a program that asks for a VT220 and then
finds a VT520 has learned nothing from asking.
"""

import pytest

from pyte.screen import Screen
from pyte.streams import Stream
from pyte.sequences import Csi, csi
from pyte import escape
from pyte.modes import PrivateMode
from pyte.sequences import set_mode

#: DECSCL for each terminal, with seven bit controls.
VT200 = csi(Csi.DECSCL, 62, 1)
VT300 = csi(Csi.DECSCL, 63, 1)
VT400 = csi(Csi.DECSCL, 64, 1)
VT500 = csi(Csi.DECSCL, 65, 1)


def make_screen(lines=4, columns=10):
    "Return (screen, stream, what the screen answered)."
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    return screen, Stream(screen), answers


# ----------------------------------------------------------------------
# DECRQM arrived with the VT320.


@pytest.mark.parametrize("level", [VT300, VT400, VT500])
def test_decrqm_answers_from_the_terminal_that_brought_it(level):
    screen, stream, answers = make_screen()
    stream.feed(level + csi(Csi.DECRQM, 4))
    assert answers == ["\x1b[4;2$y"]


def test_decrqm_says_nothing_on_an_earlier_terminal():
    screen, stream, answers = make_screen()
    stream.feed(VT200 + csi(Csi.DECRQM, 4))
    assert answers == []


def test_decrqm_comes_back_with_the_level():
    screen, stream, answers = make_screen()
    stream.feed(VT200 + csi(Csi.DECRQM, 4) + VT500 + csi(Csi.DECRQM, 4))
    assert answers == ["\x1b[4;2$y"]


# ----------------------------------------------------------------------
# The columns of the scrolling region arrived with the VT420.


def test_the_column_margins_hold_from_the_terminal_that_brought_them():
    screen, stream, answers = make_screen()
    stream.feed(
        VT400 + (set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 6))
    )
    assert screen.horizontal_margins == (2, 5)


@pytest.mark.parametrize("level", [VT200, VT300])
def test_the_mode_does_not_set_on_an_earlier_terminal(level):
    screen, stream, answers = make_screen()
    stream.feed(
        level + (set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 6))
    )
    assert screen.horizontal_margins is None


def test_the_same_byte_saves_the_cursor_on_an_earlier_terminal():
    "Without the mode, 'CSI s' is SCOSC, so it saves and does not name a region."
    screen, stream, answers = make_screen()
    stream.feed(
        VT300
        + (
            csi(escape.CUP, 2, 4)
            + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
            + csi(Csi.DECSLRM, 3, 6)
        )
    )
    stream.feed(csi(escape.CUP, 1, 1) + csi(Csi.KITTY_KEYBOARD))
    assert (screen.pt_cursor_position.y, screen.pt_cursor_position.x) == (1, 3)
