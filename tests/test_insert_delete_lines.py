"""
Inserting and deleting lines.

An empty line that one of these leaves takes the background that is
set, the same way an erased cell does.
"""
from pyte.screen import Screen
from pyte.streams import Stream
from pyte import escape
from pyte.sequences import csi


def _screen(lines=4, columns=8):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    stream = Stream(screen)
    return screen, stream


def _rows(screen):
    buffer = screen.page.data_buffer
    offset = screen.line_offset
    return [
        "".join(buffer[y][x].char for x in range(screen.columns)).rstrip()
        for y in range(offset, offset + screen.lines)
    ]


def test_insert_lines_leaves_the_lines_above_the_cursor():
    # "CSI 2 L" on the second row used to drag the first row down.
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.CUP, 2, 1) + csi(escape.IL, 2))
    assert _rows(screen) == ["a", "", "", "b", "c"]


def test_insert_lines_by_one():
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.CUP, 2, 1) + csi(escape.IL, 1))
    assert _rows(screen) == ["a", "", "b", "c", "d"]


def test_delete_lines_moves_the_lines_below_up():
    screen, stream = _screen(lines=5)
    stream.feed("a\r\nb\r\nc\r\nd" + csi(escape.CUP, 2, 1) + csi(escape.DL, 2))
    assert _rows(screen) == ["a", "d", "", "", ""]


def _cursor(screen):
    return (screen.pt_cursor_position.y - screen.line_offset,
            screen.pt_cursor_position.x)


def test_delete_lines_moves_the_cursor_to_the_first_column():
    screen, stream = _screen()
    stream.feed("ab\r\ncd" + csi(escape.CUP, 1, 2) + csi(escape.DL, 1))
    assert _cursor(screen) == (0, 0)


def test_insert_lines_moves_the_cursor_to_the_first_column():
    screen, stream = _screen()
    stream.feed("ab\r\ncd" + csi(escape.CUP, 1, 2) + csi(escape.IL, 1))
    assert _cursor(screen) == (0, 0)
