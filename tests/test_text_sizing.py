"""
kitty's text sizing protocol, OSC 66: text in a block of cells.
https://sw.kovidgoyal.net/kitty/text-sizing-protocol/.
Lillecarl/pymux#890.
"""

from __future__ import annotations

import pytest

from pyte import escape
from pyte.freeze import freeze, thaw
from pyte.screen import Screen
from pyte.sequences.csi import Csi, csi
from pyte.sequences.text_sizing import Malformed, TextSize
from pyte.streams import Stream

LINES, COLUMNS = 5, 10


def _screen(data: str, lines: int = LINES, columns: int = COLUMNS) -> Screen:
    screen = Screen(lines, columns, write_process_input=lambda answer: None)
    Stream(screen).feed(data)
    return screen


def _text(screen: Screen, row: int) -> str:
    line = screen.page.data_buffer.get(screen.line_offset + row, {})
    return "".join((line[column].char if column in line else " ") or "" for column in range(screen.columns))


def _blocks(screen: Screen) -> list[tuple[int, int, int, int, str]]:
    return [(b.x, b.y - screen.line_offset, b.columns, b.rows, b.size.text) for b in screen.text_sizes.blocks]


def test_the_sequence_reads_and_writes():
    assert TextSize.decode("s=2:w=1;Hi") == TextSize("Hi", scale=2, width=1)
    assert str(TextSize("Hi", scale=2)) == "\x1b]66;s=2;Hi\x1b\\"
    assert TextSize.decode(TextSize("a;b", numerator=1, denominator=2).param()).text == "a;b"


def test_values_are_clamped_as_kitty_keeps_them():
    assert TextSize.decode("s=9:w=0:n=20;x") == TextSize("x", scale=7, numerator=15)
    assert TextSize.decode("s=0;x").scale == 1


@pytest.mark.parametrize("param", ["q=1;x", "s=x;x", "s;x", "s=2"])
def test_kitty_drops_what_it_cannot_read(param):
    with pytest.raises(Malformed):
        TextSize.decode(param)
    assert _screen("\x1b]66;" + param + "\x1b\\").text_sizes.blocks == []


def test_a_scale_gives_each_grapheme_a_block():
    screen = _screen(str(TextSize("ab", scale=2)))
    assert _blocks(screen) == [(0, 0, 2, 2, "a"), (2, 0, 2, 2, "b")]
    assert _text(screen, 0) == "a b       "
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (4, 0)


def test_a_width_puts_the_whole_text_in_one_block():
    screen = _screen(str(TextSize("abc", width=3)) + "d")
    assert _blocks(screen) == [(0, 0, 3, 1, "abc")]
    assert _text(screen, 0) == "abcd      "


def test_text_on_the_first_cell_takes_the_block_away():
    screen = _screen(str(TextSize("A", scale=2)) + "\rx")
    assert screen.text_sizes.blocks == []
    assert _text(screen, 0) == "x         "
    assert _text(screen, 1) == " " * COLUMNS


def test_text_on_a_lower_row_goes_past_the_block():
    screen = _screen(str(TextSize("A", scale=2)) + "\r\nx")
    assert _blocks(screen) == [(0, 0, 2, 2, "A")]
    assert _text(screen, 1) == "  x       "


def test_a_mark_joins_the_block():
    screen = _screen(str(TextSize("e", scale=2)) + "́")
    assert _blocks(screen) == [(0, 0, 2, 2, "é")]


def test_a_block_that_does_not_fit_on_the_line_wraps():
    screen = _screen("x" * 9 + str(TextSize("A", scale=2)))
    assert _blocks(screen) == [(0, 1, 2, 2, "A")]


def test_a_block_taller_than_the_screen_is_dropped():
    screen = _screen(str(TextSize("A", scale=7)))
    assert screen.text_sizes.blocks == []
    assert screen.pt_cursor_position.x == 0


def test_a_tall_block_on_the_last_row_scrolls_the_screen():
    screen = _screen("top" + csi(escape.CUP, LINES, 1) + str(TextSize("A", scale=2)))
    assert _blocks(screen) == [(0, LINES - 2, 2, 2, "A")]


def test_an_erase_takes_the_block_away():
    screen = _screen(str(TextSize("A", scale=2)) + csi(escape.ED, 2))
    assert screen.text_sizes.blocks == []


def test_inserting_moves_a_block_of_one_row():
    screen = _screen(str(TextSize("ab", width=2)) + "\r" + csi(escape.ICH, 3))
    assert _blocks(screen) == [(3, 0, 2, 1, "ab")]
    assert _text(screen, 0) == "   ab     "


def test_deleting_into_a_block_takes_it_away():
    screen = _screen("x" + str(TextSize("ab", width=2)) + "\r" + csi(escape.DCH, 2))
    assert screen.text_sizes.blocks == []


def test_a_scroll_moves_the_block():
    screen = _screen("\r\n\r\n" + str(TextSize("A", scale=2)) + csi(Csi.SU, 1))
    assert _blocks(screen) == [(0, 1, 2, 2, "A")]


def test_the_alternate_screen_has_its_own_blocks():
    screen = _screen(str(TextSize("A", scale=2)) + "\x1b[?1049h")
    assert screen.text_sizes.blocks == []
    Stream(screen).feed("\x1b[?1049l")
    assert _blocks(screen) == [(0, 0, 2, 2, "A")]


def test_a_block_survives_a_snapshot():
    screen = _screen("\x1b[31m" + str(TextSize("A", scale=2, numerator=1, denominator=2)))
    copy = Screen(LINES, COLUMNS, write_process_input=lambda answer: None)
    thaw(freeze(screen), copy)
    (block,) = copy.text_sizes.blocks
    assert block.size == TextSize("A", scale=2, numerator=1, denominator=2)
    assert block.appearance is screen.text_sizes.blocks[0].appearance
