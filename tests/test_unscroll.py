"""
Tests for kitty's unscroll ("CSI Ps SP D").

A shell uses it when a full-screen program ends: instead of leaving
blank space under the prompt, the lines that the program covered come
back from the scroll buffer.
"""

from __future__ import annotations

from pyte import escape
from pyte.screen import Screen
from pyte.sequences.csi import Csi, csi
from pyte.sequences.strings import apc
from pyte.streams import Stream

LINES = 5


def make_screen(lines=LINES, columns=20):
    screen = Screen(lines, columns, write_process_input=lambda d: None)
    stream = Stream(screen)
    return screen, stream


def fill(stream, count):
    "Write `count` numbered lines."
    for number in range(count):
        stream.feed("line%i\r\n" % number)


def visible(screen):
    "The text of the visible rows."
    offset = screen.line_offset
    rows = []
    for y in range(offset, offset + screen.lines):
        row = screen.page.data_buffer.get(y, {})
        text = "".join(row[x].char if x in row else " " for x in range(screen.columns))
        rows.append(text.rstrip())
    return rows


def test_the_screen_scrolls_before_anything_is_unscrolled():
    screen, stream = make_screen()
    fill(stream, 10)
    assert screen.line_offset == 6
    assert visible(screen)[0] == "line6"


def test_unscroll_brings_a_line_back():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed(csi(Csi.KITTY_UNSCROLL, 1))
    assert screen.line_offset == 5
    assert visible(screen)[0] == "line5"


def test_unscroll_takes_a_count():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed(csi(Csi.KITTY_UNSCROLL, 3))
    assert screen.line_offset == 3
    assert visible(screen)[0] == "line3"


def test_unscroll_without_a_count_means_one():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed(csi(Csi.KITTY_UNSCROLL))
    assert screen.line_offset == 5


def test_the_cursor_keeps_its_place_on_the_screen():
    screen, stream = make_screen()
    fill(stream, 10)
    row_on_screen = screen.pt_cursor_position.y - screen.line_offset
    stream.feed(csi(Csi.KITTY_UNSCROLL, 2))
    assert screen.pt_cursor_position.y - screen.line_offset == row_on_screen


def test_the_lines_that_leave_the_bottom_are_dropped():
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed(csi(Csi.KITTY_UNSCROLL, 2))
    # "line9" sat on the last row before the unscroll.
    assert "line9" not in "\n".join(visible(screen))
    assert 10 not in screen.page.data_buffer


def test_unscroll_stops_at_the_top_of_the_history():
    screen, stream = make_screen()
    fill(stream, 7)
    assert screen.line_offset == 3
    stream.feed(csi(Csi.KITTY_UNSCROLL, 99))
    assert screen.line_offset == 0
    assert visible(screen)[0] == "line0"


def test_unscroll_does_nothing_without_history():
    screen, stream = make_screen()
    fill(stream, 2)
    assert screen.line_offset == 0
    before = visible(screen)
    stream.feed(csi(Csi.KITTY_UNSCROLL, 3))
    assert screen.line_offset == 0
    assert visible(screen) == before


def test_the_plain_sequence_is_still_cursor_back():
    "Without the intermediate space it is CUB, not unscroll."
    screen, stream = make_screen()
    fill(stream, 10)
    stream.feed("abcde")
    offset_before = screen.line_offset
    stream.feed(csi(escape.CUB, 3))
    assert screen.line_offset == offset_before
    assert screen.pt_cursor_position.x == 2


def prompt_high_up(screen, stream):
    "Ten lines, then a prompt on the second row and nothing under it, as a full-screen program leaves it."
    fill(stream, 10)
    stream.feed(csi(escape.CUP, 2, 1) + csi(escape.ED, 0) + "$ ")


def test_the_cursor_goes_to_the_bottom_with_the_history_over_it():
    "kitty's scroll_prompt_to_bottom: the empty rows under the cursor give way to the history."
    screen, stream = make_screen()
    prompt_high_up(screen, stream)
    assert screen.scroll_cursor_to_bottom() == 3
    assert visible(screen) == ["line3", "line4", "line5", "line6", "$"]
    assert screen.pt_cursor_position.y - screen.line_offset == LINES - 1
    assert screen.pt_cursor_position.x == 2


def test_it_never_brings_back_more_than_the_history_holds():
    screen, stream = make_screen()
    fill(stream, 2)
    stream.feed(csi(escape.CUP, 1, 1) + csi(escape.ED, 0) + "$ ")
    assert screen.scroll_cursor_to_bottom() == 0
    assert visible(screen)[0] == "$"


def test_a_written_row_under_the_cursor_stops_it():
    screen, stream = make_screen()
    prompt_high_up(screen, stream)
    stream.feed(csi(escape.CUP, 4, 1) + "kept" + csi(escape.CUP, 2, 3))
    assert screen.scroll_cursor_to_bottom() == 1
    assert visible(screen)[-1] == "kept"


def test_the_alternate_screen_is_left_alone():
    screen, stream = make_screen()
    prompt_high_up(screen, stream)
    stream.feed(csi(escape.SM, 1049, private="?"))
    assert screen.scroll_cursor_to_bottom() == 0


def test_a_placement_that_falls_off_the_bottom_goes_away():
    screen, stream = make_screen(lines=5)
    fill(stream, 10)
    # Place an image on the last row of the screen.
    stream.feed(csi(escape.CUP, 5, 1))
    stream.feed(apc("Ga=T,f=24,s=1,v=1,c=1,r=1,C=1,i=1;AAAA"))
    assert len(screen.graphics.placements) == 1

    stream.feed(csi(Csi.KITTY_UNSCROLL, 3))
    assert screen.graphics.placements == []


def test_a_placement_above_the_screen_stays():
    screen, stream = make_screen(lines=5)
    fill(stream, 10)
    stream.feed(csi(escape.CUP, 1, 1))
    stream.feed(apc("Ga=T,f=24,s=1,v=1,c=1,r=1,C=1,i=1;AAAA"))
    placement = screen.graphics.placements[0]
    row = placement.y

    stream.feed(csi(Csi.KITTY_UNSCROLL, 2))
    assert screen.graphics.placements == [placement]
    assert placement.y == row  # Rows of the buffer do not move.
