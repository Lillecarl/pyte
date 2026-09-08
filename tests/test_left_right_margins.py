"""
The columns of the scrolling region.

DECSLRM ("CSI Pl ; Pr s") names a left and a right margin, and private
mode 69 (DECLRMM) says whether it may. The margins are the edges of the
line for everything that draws or moves the cursor along it.
"""
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.modes import PrivateMode
from pyte.sequences import Csi, csi, set_mode
from pyte import escape
from pyte.modes import AnsiMode
from pyte.sequences import esc, reset_mode


def _screen(lines=5, columns=10):
    answers = []
    screen = Screen(lines, columns, write_process_input=answers.append)
    stream = Stream(screen)
    return screen, stream, answers


def _line(screen, row=0):
    "The text of one row of the screen, with a space for an empty cell."
    buffer = screen.data_buffer[row + screen.line_offset]
    return "".join(
        (buffer[column].char or " ") if column in buffer else " "
        for column in range(screen.columns)
    )


def _column(screen):
    return screen.reported_column


# ----------------------------------------------------------------------
# The mode and the margins themselves.


def test_the_mode_holds_the_margins():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 7))
    assert screen.horizontal_margins == (2, 6)


def test_the_margins_need_the_mode():
    "Without DECLRMM the same sequence names SCOSC, which is not this."
    screen, stream, _answers = _screen()
    stream.feed(csi(Csi.DECSLRM, 3, 7))
    assert screen.horizontal_margins is None


def test_resetting_the_mode_takes_the_margins_away():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + reset_mode(PrivateMode.LEFT_RIGHT_MARGIN)
    )
    assert screen.horizontal_margins is None


def test_the_whole_width_is_no_region():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 1, 10))
    assert screen.horizontal_margins is None


def test_a_region_of_one_column_is_refused():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 3))
    assert screen.horizontal_margins is None


def test_the_margins_home_the_cursor():
    screen, stream, _answers = _screen()
    stream.feed(
        csi(escape.CUP, 3, 5)
        + set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
    )
    assert (screen.pt_cursor_position.x, screen.pt_cursor_position.y) == (0, 0)


def test_a_resize_takes_the_margins_away():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 7))
    screen.resize(lines=6, columns=12)
    assert screen.horizontal_margins is None


# ----------------------------------------------------------------------
# The reports.


def test_the_margins_are_reported():
    _screen_, stream, answers = _screen()
    stream.feed("\x1bP$qs\x1b\\")
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 3, 7))
    stream.feed("\x1bP$qs\x1b\\")
    assert answers == ["\x1bP1$r1;10s\x1b\\", "\x1bP1$r3;7s\x1b\\"]


def test_the_mode_is_answered_by_a_mode_query():
    _screen_, stream, answers = _screen()
    stream.feed(csi(Csi.DECRQM, 69, private='?'))
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN))
    stream.feed(csi(Csi.DECRQM, 69, private='?'))
    assert answers == ["\x1b[?69;2$y", "\x1b[?69;1$y"]


# ----------------------------------------------------------------------
# Drawing.


def test_a_line_wraps_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 2, 4))
    stream.feed("abcdefgh")
    assert _line(screen, 0) == "abcd      "
    assert _line(screen, 1) == " efg      "
    assert _line(screen, 2) == " h        "


def test_a_line_without_wrap_stops_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + reset_mode(PrivateMode.AUTOWRAP)
    )
    stream.feed(csi(escape.CUP, 1, 2) + "abcdef")
    assert _line(screen, 0) == " abf      "
    assert _column(screen) == 3


def test_a_line_right_of_the_margin_runs_to_the_edge():
    "A program that draws outside the region keeps the whole line."
    screen, stream, _answers = _screen()
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 2, 4))
    stream.feed(csi(escape.CUP, 1, 9) + "xyz")
    assert _line(screen, 0) == "        xy"
    assert _line(screen, 1) == " z        "


# ----------------------------------------------------------------------
# Moving the cursor.


def test_a_carriage_return_reaches_the_left_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 6)
        + "\r"
    )
    assert _column(screen) == 2


def test_a_carriage_return_left_of_the_margin_reaches_the_first_column():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 2)
        + "\r"
    )
    assert _column(screen) == 0


def test_a_move_back_stops_at_the_left_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 5)
        + csi(escape.CUB, 99)
    )
    assert _column(screen) == 2


def test_a_backspace_stops_at_the_left_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 3)
        + "\x08"
    )
    assert _column(screen) == 2


def test_a_move_back_left_of_the_margin_reaches_the_first_column():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 2)
        + csi(escape.CUB, 99)
    )
    assert _column(screen) == 0


def test_a_move_forward_stops_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 4)
        + csi(escape.CUF, 99)
    )
    assert _column(screen) == 6


def test_a_move_forward_right_of_the_margin_reaches_the_last_column():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + csi(escape.CUP, 1, 9)
        + csi(escape.CUF, 99)
    )
    assert _column(screen) == 9


def test_a_tab_stops_at_the_right_margin():
    screen, stream, _answers = _screen(columns=40)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 10, 20)
        + csi(escape.CUP, 1, 1)
        + "\t\t\t"
    )
    assert _column(screen) == 19


def test_a_tab_left_of_the_region_stops_at_the_right_margin():
    "The DEC terminals stop a tab at the margin, wherever it starts."
    screen, stream, _answers = _screen(columns=40)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 10, 20)
        + csi(escape.CUP, 1, 1)
        + csi(Csi.CHT, 9)
    )
    assert _column(screen) == 19


# ----------------------------------------------------------------------
# Origin mode.


def test_origin_mode_counts_a_column_from_the_left_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + set_mode(PrivateMode.ORIGIN)
        + csi(escape.CUP, 1, 2)
    )
    assert _column(screen) == 3


def test_origin_mode_holds_a_column_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + set_mode(PrivateMode.ORIGIN)
        + csi(escape.CUP, 1, 99)
    )
    assert _column(screen) == 6


def test_the_column_of_a_line_follows_origin_mode():
    "CHA counts from the left margin."
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + set_mode(PrivateMode.ORIGIN)
        + csi(escape.CHA, 1)
    )
    assert _column(screen) == 2


def test_the_absolute_column_counts_from_the_margin_too():
    """
    HPA counts from the left margin in origin mode, the way CHA does.

    DEC gives HPA the column of the screen, so this looks wrong. It is
    what xterm does, and its own suite settles it: a program that moves
    to the corner in origin mode and reads the position back is told
    "1", and the character it then draws lands on the margin. Move and
    report have to agree, so both count from the margin.
    """
    screen, stream, _answers = _screen()
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 3, 7)
        + set_mode(PrivateMode.ORIGIN)
        + csi(escape.HPA, 2)
    )
    assert _column(screen) == 3


# ----------------------------------------------------------------------
# Scrolling. The region is a rectangle, so the cells outside the
# margins stay where they are.

#: Five rows of five letters each, in the first five columns.
GRID = ["abcde", "fghij", "klmno", "pqrst", "uvwxy"]


def _grid(stream, rows=GRID):
    for number, text in enumerate(rows, start=1):
        stream.feed("\x1b[%i;1H%s" % (number, text))


def _lines(screen):
    return [_line(screen, row).rstrip() for row in range(screen.lines)]


def test_a_scroll_up_carries_the_columns_of_the_region():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(Csi.SU, 2)
    )
    assert _lines(screen) == ["almne", "fqrsj", "kvwxo", "p   t", "u   y"]


def test_a_scroll_down_carries_the_columns_of_the_region():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(Csi.SD, 2)
    )
    assert _lines(screen) == ["a   e", "f   j", "kbcdo", "pghit", "ulmny"]


def test_a_scroll_holds_to_the_rows_of_the_region_as_well():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(Csi.SU, 2)
    )
    assert _lines(screen) == ["abcde", "fqrsj", "k   o", "p   t", "uvwxy"]


def test_a_line_feed_at_the_bottom_scrolls_the_region_only():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 4, 3)
        + "\n"
    )
    assert _lines(screen) == ["abcde", "flmnj", "kqrso", "p   t", "uvwxy"]


def test_a_line_feed_outside_the_columns_does_not_scroll():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 4, 7)
        + "\n"
    )
    assert _lines(screen) == GRID
    assert _column(screen) == 6


def test_a_reverse_index_at_the_top_scrolls_the_region_only():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + esc(escape.RI)
    )
    assert _lines(screen) == ["abcde", "f   j", "kghio", "plmnt", "uvwxy"]


def test_a_reverse_index_outside_the_columns_does_not_scroll():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.DECSTBM, 2, 4)
        + csi(escape.CUP, 2, 7)
        + esc(escape.RI)
    )
    assert _lines(screen) == GRID


def test_a_delete_of_lines_carries_the_columns_of_the_region():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(escape.DL)
    )
    assert _lines(screen) == ["abcde", "flmnj", "kqrso", "pvwxt", "u   y"]


def test_a_delete_of_lines_outside_the_columns_does_nothing():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 1)
        + csi(escape.DL)
    )
    assert _lines(screen) == GRID


def test_an_insert_of_lines_carries_the_columns_of_the_region():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 3)
        + csi(escape.IL)
    )
    assert _lines(screen) == ["abcde", "f   j", "kghio", "plmnt", "uqrsy"]


def test_an_insert_of_lines_outside_the_columns_does_nothing():
    screen, stream, _answers = _screen()
    _grid(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 2, 1)
        + csi(escape.IL)
    )
    assert _lines(screen) == GRID


# ----------------------------------------------------------------------
# Inserting and deleting characters.


def test_an_insert_of_characters_stops_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed("abcdefg")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(escape.CUP, 1, 3)
        + csi(escape.ICH)
    )
    assert _line(screen, 0) == "ab cdfg   "


def test_an_insert_of_characters_outside_the_margins_does_nothing():
    screen, stream, _answers = _screen()
    stream.feed("abcdefg")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(escape.CUP, 1, 1)
        + csi(escape.ICH, 10)
    )
    assert _line(screen, 0) == "abcdefg   "


def test_a_delete_of_characters_stops_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed("abcde")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 1, 3)
        + csi(escape.DCH)
    )
    assert _line(screen, 0) == "abd e     "


def test_a_delete_of_characters_reaches_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed("abcde")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 1, 3)
        + csi(escape.DCH, 99)
    )
    assert _line(screen, 0) == "ab  e     "


def test_a_delete_of_characters_outside_the_margins_does_nothing():
    screen, stream, _answers = _screen()
    stream.feed("abcde")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 4)
        + csi(escape.CUP, 1, 1)
        + csi(escape.DCH, 99)
    )
    assert _line(screen, 0) == "abcde     "


def test_insert_mode_truncates_at_the_right_margin():
    screen, stream, _answers = _screen()
    stream.feed("abcdef")
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 2, 5)
        + csi(escape.CUP, 1, 3)
        + set_mode(AnsiMode.INSERT_REPLACE)
        + "X"
    )
    assert _line(screen, 0) == "abXcdf    "


# ----------------------------------------------------------------------
# The column after the right margin holds two different cursors.


def test_a_cursor_right_of_the_margin_reports_where_it_stands():
    """
    The column after the right margin is where a wait to wrap sits, and
    it is also a place a program can put the cursor.

    A report folded the two together and named the margin for both. So
    a program that placed the cursor one column right of the margin
    read back the margin instead.
    """
    screen, stream, answers = _screen(lines=8, columns=10)
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 2, 5))
    stream.feed(csi(escape.CUP, 5, 6) + csi(escape.DSR, 6))
    assert answers == ["\x1b[5;6R"]


def test_a_cursor_waiting_to_wrap_reports_the_margin():
    "A character in the last column of the region leaves the wait."
    screen, stream, answers = _screen(lines=8, columns=10)
    stream.feed(set_mode(PrivateMode.LEFT_RIGHT_MARGIN) + csi(Csi.DECSLRM, 2, 5))
    stream.feed(csi(escape.CUP, 5, 5) + "x" + csi(escape.DSR, 6))
    assert answers == ["\x1b[5;5R"]
