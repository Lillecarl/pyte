"""
The DEC line attributes, which this screen reads and drops.

"ESC # 3", "ESC # 4", "ESC # 5" and "ESC # 6" draw a line at twice the
width or twice the height on a VT100. kitty, Ghostty and Alacritty
implement none of them, esctest has no test for them, and no recorded
program in this repository sends one. xterm and libvterm are the two
that do. So a line here is one line high and one cell wide, whatever a
program asks for. Lillecarl/pymux#141.

What still has to be true is that the bytes go away. An escape sequence
nobody reads ends at the "#", and the digit after it lands on the screen
as text.
"""

import pytest

from pyte.screen import Screen
from pyte.streams import Stream
from pyte.sequences import Sharp, sharp

LINES, COLUMNS = 5, 10

#: The four of them, and DECALN, which this screen does act on.
ATTRIBUTES = [
    sharp(Sharp.DECDHL_TOP),
    sharp(Sharp.DECDHL_BOTTOM),
    sharp(Sharp.DECSWL),
    sharp(Sharp.DECDWL),
]


def _screen(data, lines=LINES, columns=COLUMNS):
    screen = Screen(lines, columns, write_process_input=lambda answer: None)
    Stream(screen).feed(data)
    return screen


def _text(screen, row: int) -> str:
    "One row of the visible screen, as characters."
    line = screen.page.data_buffer.get(screen.line_offset + row)
    if line is None:
        return " " * COLUMNS
    return "".join((line[column].char or " ") for column in range(COLUMNS))


@pytest.mark.parametrize("sequence", ATTRIBUTES)
def test_the_sequence_writes_nothing_on_the_screen(sequence):
    "The digit is part of the sequence, so no part of it is text."
    assert _text(_screen(sequence + "abc"), 0) == "abc" + " " * 7


@pytest.mark.parametrize("sequence", ATTRIBUTES)
def test_the_sequence_makes_no_row(sequence):
    "A line that is drawn the plain way holds nothing of its own."
    assert _screen(sequence).page.data_buffer == {}


@pytest.mark.parametrize("sequence", ATTRIBUTES)
def test_the_line_holds_every_column_it_was_given(sequence):
    """
    A line drawn twice as wide holds half as many columns on a VT100.
    This one holds them all, which is what a terminal that ignores the
    attribute does.
    """
    screen = _screen(sequence + "a" * COLUMNS)
    assert _text(screen, 0) == "a" * COLUMNS
