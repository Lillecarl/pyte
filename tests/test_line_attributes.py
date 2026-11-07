"""
The DEC line attributes, which become kitty's text sizing, OSC 66.

"ESC # 3" and "ESC # 4" draw a line twice as high, "ESC # 6" twice as
wide, and "ESC # 5" one size again. A double height line has an exact
form, "s=2" on its top row. A double width line has none: kitty cannot
stretch a glyph sideways, so it becomes "w=2" and each glyph keeps its
own size, two cells apart. Lillecarl/pyterm#892.
"""

from __future__ import annotations

import pytest

from pyte.screen import Screen
from pyte.sequences.escapes import Sharp, sharp
from pyte.sequences.text_sizing import TextSize
from pyte.streams import Stream

LINES, COLUMNS = 5, 10


def _screen(data, lines=LINES, columns=COLUMNS):
    screen = Screen(lines, columns, write_process_input=lambda answer: None)
    Stream(screen).feed(data)
    return screen


def _text(screen, row: int) -> str:
    line = screen.page.data_buffer.get(screen.line_offset + row, {})
    return "".join((line[column].char if column in line else " ") or "" for column in range(COLUMNS))


def _sizes(screen) -> list[tuple[int, int, TextSize]]:
    return [(block.x, block.y - screen.line_offset, block.size) for block in screen.text_sizes.blocks]


@pytest.mark.parametrize("order", ["before", "after"])
def test_a_double_width_line_spaces_its_glyphs(order):
    data = sharp(Sharp.DECDWL) + "ab" if order == "before" else "ab" + sharp(Sharp.DECDWL)
    screen = _screen(data)
    assert _sizes(screen) == [(0, 0, TextSize("a", width=2)), (2, 0, TextSize("b", width=2))]
    assert _text(screen, 0) == "a b       "


def test_a_double_height_line_draws_once_from_its_top_row():
    screen = _screen(sharp(Sharp.DECDHL_TOP) + "ab\r\n" + sharp(Sharp.DECDHL_BOTTOM) + "ab")
    assert _sizes(screen) == [(0, 0, TextSize("a", scale=2)), (2, 0, TextSize("b", scale=2))]
    assert _text(screen, 1) == " " * COLUMNS
    assert screen.pt_cursor_position.x == 4


def test_single_width_puts_the_text_back():
    screen = _screen(sharp(Sharp.DECDWL) + "ab" + sharp(Sharp.DECSWL))
    assert screen.text_sizes.blocks == []
    assert _text(screen, 0) == "ab        "


def test_the_attribute_holds_while_the_cursor_stays_on_the_line():
    screen = _screen(sharp(Sharp.DECDWL) + "a\r\nb")
    assert _sizes(screen) == [(0, 0, TextSize("a", width=2))]
    assert _text(screen, 1) == "b         "


def test_a_double_width_line_shows_the_first_half():
    screen = _screen("abcdefghij" + sharp(Sharp.DECDWL))
    assert _text(screen, 0) == "a b c d e "


@pytest.mark.parametrize("kind", [Sharp.DECDWL, Sharp.DECDHL_TOP])
def test_a_line_that_turns_double_keeps_the_cursor_s_column_in_its_own_cells(kind):
    """
    vttest's double-size screen moves the cursor to column 2 and then
    sets the attribute. xterm and libvterm both draw "CSI 1;3H ESC # 6
    ab" with "a" in the fifth column. Lillecarl/pyterm#374.
    """
    screen = _screen("\x1b[1;3H" + sharp(kind) + "ab")
    assert [block.x for block in screen.text_sizes.blocks] == [4, 6]


def test_a_line_that_turns_single_again_halves_the_cursor_s_column():
    screen = _screen("\x1b[1;3H" + sharp(Sharp.DECDWL) + sharp(Sharp.DECSWL) + "ab")
    assert _text(screen, 0) == "  ab      "


def test_single_width_brings_the_second_half_back():
    """
    vttest's "Erase right half of double width lines": a long line set
    double and then single again shows all of it, as xterm and five
    more of the panel show it. Lillecarl/pyterm#374.
    """
    screen = _screen("abcdefghij" + sharp(Sharp.DECDWL) + sharp(Sharp.DECSWL))
    assert _text(screen, 0) == "abcdefghij"


def test_the_second_half_moves_with_its_line():
    "A scroll inside a region moves the row, and the held half with it."
    moved = "\x1b[2;5r\x1b[3;1H" + "abcdefghij" + sharp(Sharp.DECDWL) + "\x1b[5;1H\n\x1b[2;1H" + sharp(Sharp.DECSWL)
    screen = _screen(moved)
    assert _text(screen, 1) == "abcdefghij"


def test_an_erase_to_the_end_of_a_double_line_takes_the_second_half():
    screen = _screen("abcdefghij" + sharp(Sharp.DECDWL) + "\x1b[1;5H\x1b[K" + sharp(Sharp.DECSWL))
    assert _text(screen, 0) == "ab        "


def test_alignment_display_makes_every_line_single():
    screen = _screen(sharp(Sharp.DECDWL) + "ab" + sharp(Sharp.DECALN))
    assert screen.text_sizes.blocks == []
    assert _text(screen, 0) == "E" * COLUMNS


@pytest.mark.parametrize("kind", [Sharp.DECDHL_TOP, Sharp.DECDHL_BOTTOM, Sharp.DECSWL, Sharp.DECDWL])
def test_the_sequence_writes_nothing_on_the_screen(kind):
    "The digit is part of the sequence, so no part of it is text."
    assert _text(_screen(sharp(kind)), 0) == " " * COLUMNS
