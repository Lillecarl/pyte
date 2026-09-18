"""
A scroll of a region that starts at the first row keeps the rows.

A program that draws a transcript above a fixed composer does not
linefeed the whole screen. It sets a region from the first row to the
row above the composer, puts the cursor at the bottom of that region
and feeds lines there. Every line of the transcript therefore leaves
through the top of a region, and never through the top of the screen.

pyte kept nothing for that: a region moved its own rows and dropped the
one that left. codex draws exactly this way, so a pymux pane held no
scrollback for it while kitty held all of it.

**Every terminal that has a scrollback fills it here.** kitty takes
`margin_top == 0` on the main screen (`screen.c`, `add_to_history`),
xterm `top_marg == 0` with no left or right margin (`util.c`,
`scroll_all_lines`), Alacritty `region.start == 0` (`grid/mod.rs`,
`scroll_up`), Ghostty `scrolling_region.top == 0` (`Terminal.zig`) and
libvterm `rect.start_row == 0` over the full width (`screen.c`,
`premove`). Lillecarl/pymux#423.
"""

from pyte import escape
from pyte.modes import PrivateMode
from pyte.screen import Screen
from pyte.sequences import Csi, csi, set_mode
from pyte.streams import Stream

LINES = 6
COLUMNS = 8

#: The last row of the region, counted the way DECSTBM counts. The two
#: rows under it are the composer, which stays where it is.
REGION_BOTTOM = LINES - 2


def _screen(lines: int = LINES, columns: int = COLUMNS):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    return screen, Stream(screen)


def _row(screen: Screen, row: int) -> str:
    "The text of one absolute row of the buffer."
    line = screen.page.data_buffer.get(row)
    if line is None:
        return ""
    return "".join(line[x].char for x in range(screen.columns)).rstrip()


def _screen_rows(screen: Screen) -> list[str]:
    offset = screen.line_offset
    return [_row(screen, offset + row) for row in range(screen.lines)]


def _history(screen: Screen) -> list[str]:
    return [_row(screen, row) for row in range(screen.line_offset)]


def _rows_above_the_screen(screen: Screen) -> list[int]:
    "The rows the buffer really holds above the screen."
    return sorted(row for row in screen.page.data_buffer if row < screen.line_offset)


def _fill(stream: Stream) -> None:
    "Write one named row on every row of the screen."
    stream.feed("\r\n".join("row%d" % row for row in range(LINES)))


def _at_the_bottom_of_the_region() -> str:
    "Set the region, and put the cursor on its last row."
    return csi(escape.DECSTBM, 1, REGION_BOTTOM) + csi(escape.CUP, REGION_BOTTOM, 1)


def test_a_region_from_the_first_row_keeps_the_row_that_leaves():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(_at_the_bottom_of_the_region() + "\n" + "next")

    assert _history(screen) == ["row0"]
    assert _screen_rows(screen) == ["row1", "row2", "row3", "next", "row4", "row5"]


def test_the_rows_under_the_region_stay_where_they_are():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(_at_the_bottom_of_the_region() + "\n\n\n")

    assert _history(screen) == ["row0", "row1", "row2"]
    assert _screen_rows(screen) == ["row3", "", "", "", "row4", "row5"]


def test_the_cursor_keeps_its_row_of_the_screen():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(_at_the_bottom_of_the_region() + "\n")

    assert screen.pt_cursor_position.y - screen.line_offset == REGION_BOTTOM - 1


def test_su_over_a_region_from_the_first_row_keeps_the_rows():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(csi(escape.DECSTBM, 1, REGION_BOTTOM) + csi(Csi.SU, 2))

    assert _history(screen) == ["row0", "row1"]
    assert _screen_rows(screen) == ["row2", "row3", "", "", "row4", "row5"]


def test_su_with_no_region_at_all_keeps_the_rows():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(csi(Csi.SU, 2))

    assert _history(screen) == ["row0", "row1"]
    assert _screen_rows(screen) == ["row2", "row3", "row4", "row5", "", ""]


def test_a_count_past_the_region_stops_at_the_height_of_it():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(csi(escape.DECSTBM, 1, REGION_BOTTOM) + csi(Csi.SU, LINES))

    # The region is four rows, so four rows leave it however big the
    # count is. xterm, Alacritty and Ghostty all clamp this way; kitty
    # alone counts rows and puts blanks in the history for the rest.
    assert _history(screen) == ["row0", "row1", "row2", "row3"]
    assert _screen_rows(screen) == ["", "", "", "", "row4", "row5"]


def test_a_screen_that_has_not_filled_once_still_keeps_the_row():
    """
    The buffer is sparse, so a fresh screen has no room above it:
    `line_offset` is `max_y - lines + 1` and `max_y` is still low. That
    is ours alone. Every other terminal holds `lines` rows whatever has
    been drawn, and keeps the row that leaves a region at the top.

    A program that scrolls a region is using the whole height anyway:
    the rows under the region are on the screen, and the row that
    leaves the top of it has to go somewhere. Lillecarl/pymux#424.
    """
    screen, stream = _screen()
    # Two rows written, four never touched.
    stream.feed("row0\r\nrow1")
    stream.feed(_at_the_bottom_of_the_region() + "\n")

    assert _history(screen) == ["row0"]
    assert _screen_rows(screen)[:2] == ["row1", ""]


def test_a_region_below_the_first_row_keeps_nothing():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(
        csi(escape.DECSTBM, 2, REGION_BOTTOM) + csi(escape.CUP, REGION_BOTTOM, 1) + "\n"
    )

    assert _history(screen) == []
    assert _screen_rows(screen) == ["row0", "row2", "row3", "", "row4", "row5"]


def test_a_left_margin_keeps_nothing():
    screen, stream = _screen()
    _fill(stream)
    stream.feed(
        set_mode(PrivateMode.LEFT_RIGHT_MARGIN)
        + csi(Csi.DECSLRM, 1, 4)
        + _at_the_bottom_of_the_region()
        + "\n"
    )

    assert _history(screen) == []


def test_the_alternate_screen_keeps_nothing_above_itself():
    screen, stream = _screen()
    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR))
    _fill(stream)
    stream.feed(_at_the_bottom_of_the_region() + "\n\n")

    assert _rows_above_the_screen(screen) == []
    assert _screen_rows(screen) == ["row2", "row3", "", "", "row4", "row5"]


def test_the_alternate_screen_does_not_slide_at_all():
    """
    The rows move there, and the screen stays where it is.

    **This is the cost and not only the answer.** Sliding the screen
    over the buffer makes a row of history for the prune to take again
    on the very next line, one per scrolled row, and on the alternate
    screen nobody can read that row. Ghostty says the same in as many
    words, and kitty gates on `linebuf == main_linebuf`.

    vim measured it: `vim_24bitcolors_bce` takes the alternate screen
    and then scrolls a region 641 times, and each scroll paid for a
    prune. The suites beside it in `checks.all` began to fail on
    timing. Lillecarl/pymux#425.

    `line_offset` is what says which path ran, and it is cheap to
    assert. A prune on every row leaves the same rows behind as no
    prune at all.
    """
    screen, stream = _screen()
    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR))
    _fill(stream)
    before = screen.line_offset

    stream.feed(csi(escape.DECSTBM, 1, REGION_BOTTOM))
    stream.feed(csi(escape.CUP, REGION_BOTTOM, 1) + "\n" * 20)
    stream.feed(csi(Csi.SU, 20))

    assert screen.line_offset == before
    assert _rows_above_the_screen(screen) == []
