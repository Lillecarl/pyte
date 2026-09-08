"""
The cells that an erase has to leave alone.

Two commands mark a cell. SPA ("ESC V") sets the mark of ISO 6429, and
ED, EL and ECH leave a cell that carries it alone. DECSCA ("CSI 1 " q")
sets the mark of the DEC terminals, and the selective erases, DECSED
("CSI ? Ps J") and DECSEL ("CSI ? Ps K"), leave that one alone.

A selective erase reads both marks. xterm does the same, for the
programs that came before DECSCA.
"""
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.sequences import Csi, csi
from pyte import escape
from pyte.sequences import esc
from pyte.sequences import Escape


def _screen(lines=4, columns=10):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


def _line(screen, row=0):
    buffer = screen.data_buffer[row + screen.line_offset]
    return "".join(
        (buffer[column].char or " ") if column in buffer else " "
        for column in range(screen.columns)
    ).rstrip()


# ----------------------------------------------------------------------
# The mark of ISO 6429.


def test_an_erase_in_line_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2)
    )
    assert _line(screen) == "  c"


def test_an_erase_in_display_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.ED, 0)
    )
    assert _line(screen) == "  c"


def test_an_erase_of_the_whole_screen_takes_a_marked_cell():
    """
    "CSI 2 J" takes the screen, marks and all.

    xterm draws it that way, and its own conformance suite counts on
    it: the suite clears the screen with "CSI 2 J" between tests, and
    a marked cell that survived would reach the test after it.
    """
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.ED, 2)
    )
    assert _line(screen) == ""


def test_a_selective_erase_of_the_whole_screen_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.ED, 2, private='?')
    )
    assert _line(screen) == "  c"


def test_an_erase_of_characters_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.ECH, 3)
    )
    assert _line(screen) == "  c"


def test_the_mark_ends_where_the_program_ends_it():
    screen, stream, _answers = _screen()
    stream.feed(
        esc(Escape.SPA)
        + "ab"
        + esc(Escape.EPA)
        + "cd"
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2)
    )
    assert _line(screen) == "ab"


def test_a_selective_erase_reads_the_mark_as_well():
    "xterm reads it, for the programs that came before DECSCA."
    screen, stream, _answers = _screen()
    stream.feed(
        "ab"
        + esc(Escape.SPA)
        + "c"
        + esc(Escape.EPA)
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2, private='?')
    )
    assert _line(screen) == "  c"


# ----------------------------------------------------------------------
# The mark of DECSCA.


def test_a_selective_erase_in_line_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "abc"
        + csi(Csi.DECSCA, 0)
        + "d"
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2, private='?')
    )
    assert _line(screen) == "abc"


def test_a_selective_erase_in_display_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "abc"
        + csi(Csi.DECSCA, 0)
        + "d"
        + csi(escape.CUP, 1, 1)
        + csi(escape.ED, 0, private='?')
    )
    assert _line(screen) == "abc"


def test_a_plain_erase_takes_a_cell_that_decsca_marked():
    "That is the whole difference between EL and DECSEL."
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "abc"
        + csi(Csi.DECSCA, 0)
        + "d"
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2)
    )
    assert _line(screen) == ""


def test_the_parameter_two_takes_the_mark_away():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "ab"
        + csi(Csi.DECSCA, 2)
        + "cd"
        + csi(escape.CUP, 1, 1)
        + csi(escape.EL, 2, private='?')
    )
    assert _line(screen) == "ab"


def test_a_selective_erase_to_the_right_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "abcde"
        + csi(escape.CUP, 1, 3)
        + csi(escape.EL, 0, private='?')
    )
    assert _line(screen) == "abcde"


def test_a_selective_erase_to_the_left_leaves_a_marked_cell():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + "abcde"
        + csi(escape.CUP, 1, 3)
        + csi(escape.EL, 1, private='?')
    )
    assert _line(screen) == "abcde"


# ----------------------------------------------------------------------
# What the mark travels with.


def test_the_mark_travels_with_a_scroll():
    screen, stream, _answers = _screen()
    stream.feed(csi(Csi.DECSCA, 1) + "keep" + csi(Csi.DECSCA, 0))
    stream.feed(csi(escape.CUP, 2, 1) + csi(Csi.SU))  # Scroll up by one.
    stream.feed(csi(escape.CUP, 1, 1) + csi(escape.EL, 2, private='?'))
    assert _line(screen) == ""
    stream.feed(csi(escape.CUP, 2, 1) + csi(escape.EL, 2, private='?'))
    assert _line(screen) == ""


def test_the_mark_stays_on_a_reset():
    "RIS clears the screen, so nothing carries a mark afterwards."
    screen, stream, _answers = _screen()
    stream.feed(csi(Csi.DECSCA, 1) + "abc" + esc(escape.RIS))
    assert screen.protection == 0


def test_a_soft_reset_takes_the_mark_off_what_comes_next():
    screen, stream, _answers = _screen()
    stream.feed(csi(Csi.DECSCA, 1) + csi(Csi.DECSTR))
    assert screen.protection == 0


# ----------------------------------------------------------------------
# The report.


def test_the_mark_is_reported():
    _screen_, stream, answers = _screen()
    stream.feed('\x1bP$q"q\x1b\\')
    stream.feed(csi(Csi.DECSCA, 1))
    stream.feed('\x1bP$q"q\x1b\\')
    assert answers == ['\x1bP1$r0"q\x1b\\', '\x1bP1$r1"q\x1b\\']


def test_a_save_and_a_restore_carry_the_mark():
    """
    DECSC remembers the marks, and DECRC brings them back.

    The marks belong to the cursor, the way the rendition does.
    """
    screen, stream, _answers = _screen()
    stream.feed(
        csi(Csi.DECSCA, 1)
        + esc(escape.DECSC)
        + csi(Csi.DECSCA, 0)
        + esc(escape.DECRC)
    )
    assert screen.protection == 2
    stream.feed("a" + csi(Csi.DECSERA, 1, 1, 1, 1))
    assert _line(screen) == "a"
