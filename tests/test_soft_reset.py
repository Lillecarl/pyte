"""
DECSTR ("CSI ! p"): the soft reset.

It keeps the text and the cursor, and puts the settings back. A program
sends it when it starts and when it ends, so that the terminal that the
next program finds is the one it knows.
"""

from pyte.modes import AnsiMode, PrivateMode
from pyte.screen import Screen
from pyte.streams import Stream
from pyte import escape
from pyte.sequences import Csi, csi, reset_mode, set_mode
from pyte.sequences import esc
from pyte.sequences import decrqss


def _screen(lines=5, columns=10):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


def test_the_cursor_stays_where_it_is():
    screen, stream, _answers = _screen()
    stream.feed(csi(escape.CUP, 3, 5) + csi(Csi.DECSTR))
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (4, 2)


def test_the_text_stays_on_the_screen():
    screen, stream, _answers = _screen()
    stream.feed("hello" + csi(Csi.DECSTR))
    assert screen.data_buffer[0][0].char == "h"


def test_the_rows_of_the_region_go_back():
    screen, stream, _answers = _screen()
    stream.feed(csi(escape.DECSTBM, 2, 4) + csi(Csi.DECSTR))
    assert screen.margins is None


def test_the_columns_of_the_region_go_back():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(Csi.DECSTR)
    )
    assert screen.horizontal_margins is None
    assert (LEFT_RIGHT_MODE << 5) not in screen.mode


LEFT_RIGHT_MODE = 69


def test_origin_mode_goes_off():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(escape.DECSTBM, 2, 4) + set_mode(PrivateMode.ORIGIN) + csi(Csi.DECSTR)
    )
    assert PrivateMode.ORIGIN.flag not in screen.mode


def test_insert_mode_goes_off():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(AnsiMode.INSERT_REPLACE) + csi(Csi.DECSTR))
    assert AnsiMode.INSERT_REPLACE not in screen.mode


def test_autowrap_stays_on():
    "The DEC manuals turn it off. xterm keeps it on, and so do we."
    screen, stream, _answers = _screen()
    stream.feed(reset_mode(PrivateMode.AUTOWRAP) + csi(Csi.DECSTR))
    assert PrivateMode.AUTOWRAP.flag in screen.mode


def test_the_cursor_stays_visible():
    screen, stream, _answers = _screen()
    stream.feed(reset_mode(PrivateMode.SHOW_CURSOR) + csi(Csi.DECSTR))
    assert screen.page.show_cursor is True


def test_the_saved_cursor_goes_home():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(escape.CUP, 3, 5) + esc(escape.DECSC) + csi(Csi.DECSTR) + esc(escape.DECRC)
    )
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (0, 0)


def test_the_rendition_goes_back_to_plain():
    _screen_, stream, answers = _screen()
    stream.feed(csi(escape.SGR, 1, 4, 31) + csi(Csi.DECSTR))
    stream.feed(decrqss(escape.SGR))
    assert answers == ["\x1bP1$r0m\x1b\\"]


def test_the_alternate_screen_stays_in_front():
    "A soft reset is not a way out of the alternate screen."
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR) + csi(Csi.DECSTR))
    assert screen.in_alternate_screen is True
