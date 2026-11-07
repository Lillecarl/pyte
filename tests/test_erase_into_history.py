"""
ED 22, kitty's: the screen moves into the history, images too, and is
then left as ED 2 leaves it. kitty's `screen_move_into_scrollback`
(kitty/screen.c) moves the rows down to the last one that holds
anything, and only on the first screen with no region. Lillecarl/pyterm#898.
"""

from __future__ import annotations

from pyte import escape
from pyte.images import GraphicsPlacement
from pyte.modes import PrivateMode
from pyte.parameters import EraseExtent
from pyte.screen import Screen
from pyte.sequences.csi import csi, set_mode
from pyte.streams import Stream

LINES = 6
COLUMNS = 8


def _screen():
    screen = Screen(LINES, COLUMNS, write_process_input=lambda data: None)
    return screen, Stream(screen)


def _row(screen: Screen, row: int) -> str:
    line = screen.page.data_buffer.get(row)
    if line is None:
        return ""
    return "".join(line[x].char for x in range(screen.columns)).rstrip()


def _screen_rows(screen: Screen) -> list[str]:
    return [_row(screen, screen.line_offset + row) for row in range(screen.lines)]


def _history(screen: Screen) -> list[str]:
    return [_row(screen, row) for row in range(screen.line_offset)]


def test_the_rows_go_into_the_history_and_the_screen_is_clear():
    screen, stream = _screen()
    stream.feed("one\r\ntwo\r\nthree")
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    assert _history(screen)[-3:] == ["one", "two", "three"]
    assert _screen_rows(screen) == [""] * LINES


def test_the_cursor_stays_where_it_was_on_the_screen():
    screen, stream = _screen()
    stream.feed("one\r\ntwo")

    def on_screen():
        return screen.pt_cursor_position.x, screen.pt_cursor_position.y - screen.line_offset

    before = on_screen()
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    assert on_screen() == before


def test_an_image_goes_with_its_rows():
    screen, stream = _screen()
    stream.feed("one\r\ntwo")
    top = screen.line_offset
    screen.graphics.placements.append(GraphicsPlacement(1, 0, 0, top, 2, 1))
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    (placement,) = screen.graphics.placements
    assert placement.y == top
    assert placement.y < screen.line_offset


def test_an_empty_screen_moves_nothing():
    screen, stream = _screen()
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    assert _history(screen) == []


def test_the_alternate_screen_only_clears():
    screen, stream = _screen()
    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + "one")
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    assert _history(screen) == []
    assert _screen_rows(screen) == [""] * LINES


def test_a_region_only_clears():
    screen, stream = _screen()
    stream.feed("one\r\ntwo" + csi(escape.DECSTBM, 2, 4))
    stream.feed(csi(escape.ED, EraseExtent.INTO_HISTORY))
    assert "one" not in _history(screen)
    assert _screen_rows(screen) == [""] * LINES
