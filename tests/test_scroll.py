"""
SU and SD move the lines of the scrolling region, and leave the cursor.

pyte has neither. A program that scrolls with "CSI S" instead of a
linefeed saw nothing happen before.
"""

from __future__ import annotations

from pyte import escape
from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.sequences import Csi, csi, set_mode
from pyte.streams import Stream


def _screen(lines=4, columns=8):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    return screen, stream


def _rows(screen):
    buffer = screen.page.data_buffer
    offset = screen.line_offset
    return [
        "".join(buffer[y][x].char for x in range(screen.columns)).rstrip() for y in range(offset, offset + screen.lines)
    ]


def test_scroll_up_moves_the_lines_up():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc" + csi(Csi.SU, 1))
    assert _rows(screen) == ["b", "c", "", ""]


def test_scroll_up_takes_a_count():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc" + csi(Csi.SU, 2))
    assert _rows(screen) == ["c", "", "", ""]


def test_scroll_down_moves_the_lines_down():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc" + csi(Csi.SD, 2))
    assert _rows(screen) == ["", "", "a", "b"]


def test_a_count_past_the_screen_clears_it():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc" + csi(Csi.SU, 9))
    assert _rows(screen) == ["", "", "", ""]


def test_scrolling_stays_inside_the_margins():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 1))
    assert _rows(screen) == ["a", "c", "", "d"]


def test_the_cursor_does_not_move():
    "Its row of the screen, that is: SU moves the screen under it."
    screen, stream = _screen()
    stream.feed("a\r\nb" + csi(escape.CUP, 1, 3) + csi(Csi.SU, 1))
    row = screen.pt_cursor_position.y - screen.line_offset
    assert (screen.pt_cursor_position.x, row) == (2, 0)


def test_a_region_scroll_reports_its_region_and_distance():
    """
    A reader that keeps what it drew per row rotates those rows
    instead of rebuilding them. The report is the region in buffer
    rows, the signed distance (up positive), the write count so a
    reader rotates only rows no later write touched, and the
    sequence so a reader that missed any rebuilds instead.
    Lillecarl/pymux#516.
    """
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 1))
    [(top, bottom, distance, at, seq)] = screen.scrolls
    assert (top, bottom, distance) == (1, 2, 1)
    assert at == screen.writes
    assert seq == 1


def test_a_region_scroll_down_reports_a_negative_distance():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.DECSTBM, 2, 3) + csi(Csi.SD, 2))
    [(top, bottom, distance, _at, _seq)] = screen.scrolls
    assert (top, bottom, distance) == (1, 2, -2)


def test_a_slide_reports_nothing():
    """
    A full screen scroll on the main screen slides the screen over
    the buffer: the rows do not move, so there is nothing to rotate
    with. The readers' rows stay valid where they are.
    """
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc" + csi(Csi.SU, 1))
    assert screen.scrolls == []


def test_a_rectangle_scroll_reports_nothing():
    """
    Inside left and right margins the move carries cells and not
    lines, so whole-row rotation would be wrong. Their rows were
    touched, so they rebuild as before.
    """
    screen, stream = _screen()
    stream.feed(
        "a\r\nb\r\nc\r\nd"
        + csi(escape.DECSTBM, 2, 3)
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(Csi.SU, 1)
    )
    assert screen.scrolls == []


def test_a_count_past_the_region_reports_the_steps_it_took():
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 9))
    [(top, bottom, distance, _at, _seq)] = screen.scrolls
    assert (top, bottom, distance) == (1, 2, 2)


def test_a_reset_clears_the_report_but_not_the_sequence():
    """
    A reset replaces the rows the report refers to. The sequence
    keeps counting so a reader whose mark predates what is left
    rebuilds everything instead of rotating into new rows.
    """
    screen, stream = _screen()
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 1))
    assert len(screen.scrolls) == 1
    stream.feed(csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 1) + "\x1bc")
    assert screen.scrolls == []
    stream.feed(csi(escape.DECSTBM, 2, 3) + csi(Csi.SU, 1))
    [(_top, _bottom, _distance, _at, seq)] = screen.scrolls
    assert seq == 4
