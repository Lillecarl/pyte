"""
Dropping the oldest rows costs the rows it drops, not the rows it keeps.

`_remove_old_lines_from_history` read every key of the buffer and kept
the ones above the limit. A pane at fifty thousand rows drops about a
hundred of them at a time, so that read was five hundred rows of work
for each row of output. Printing a hundred lines cost three times as
much at fifty thousand rows as at two thousand, and the depth is what a
person chooses. Lillecarl/pymux#8.

`history_floor` is the lowest row the buffer can hold, so a prune walks
from there and stops. **The shortcut is only right while nothing lives
under the floor**, and that is what this file hunts: after every chunk
it prunes by hand and says that the buffer holds nothing the old full
read would have taken.

The alphabet comes from `test_row_versions`, because the paths that
move whole ranges of rows are the ones that could put a row under the
floor, and that file already names them.
"""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyte.screen import Screen
from pyte.streams import Stream
from test_row_versions import a_chunk
from pyte.modes import PrivateMode
from pyte.sequences import Csi, csi, reset_mode, set_mode

#: How deep the history goes in this file. It is tiny so that a prune
#: happens over and over in a short run, where two thousand rows would
#: mean nothing was ever dropped.
LIMIT = 5

LINES = 6
COLUMNS = 10


def a_short_history(lines: int = LINES, columns: int = COLUMNS):
    "A screen that keeps almost no scrollback."
    return Screen(
        lines,
        columns,
        write_process_input=lambda data: None,
        get_history_limit=lambda: LIMIT,
    )


def say_the_floor_holds(screen) -> None:
    """
    Prune by hand, and say the buffer holds what a full read would have
    left behind.

    A prune of its own accord happens once per hundred linefeeds, which
    is too rare to hunt with. This forces one after every chunk, and
    then asks the question the shortcut has to answer: is there a row
    left that the old read over every key would have taken away?
    """
    screen._remove_old_lines_from_history()
    remove_above = max(0, screen.pt_cursor_position.y - LIMIT)

    buffer = screen.page.data_buffer
    left = sorted(row for row in buffer if row < remove_above)
    assert not left, "these rows should have gone: %s" % left

    assert not buffer or min(buffer) >= screen.history_floor

    # A row that left the history takes its count with it, or
    # `written_at` grows with the session instead of with the history.
    # The wrap mark needs no check of its own: it rides on the row, so
    # dropping the row drops it. Lillecarl/pymux#134.
    counts = sorted(row for row in screen.written_at if row < remove_above)
    assert not counts, "these counts should have gone: %s" % counts


@given(st.lists(a_chunk(), min_size=1, max_size=40))
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_sequence_nobody_recorded(chunks):
    screen = a_short_history()
    stream = Stream(screen)
    for chunk in chunks:
        stream.feed(chunk)
        say_the_floor_holds(screen)


def test_the_buffer_stops_growing_at_the_limit():
    "A long run of output leaves the history and nothing more."
    screen = a_short_history()
    stream = Stream(screen)
    stream.feed("".join("line %d\r\n" % number for number in range(500)))
    screen._remove_old_lines_from_history()
    assert len(screen.page.data_buffer) <= LIMIT + LINES + 1


def test_the_notes_about_a_row_go_when_the_row_does():
    """
    A wrap mark rides on the row, so a prune that drops the row drops
    it with it.

    It was a dictionary keyed by row number once, and the row numbers of
    a session never come back around, so a note outlived its row and
    both grew with the session. Lillecarl/pymux#134 put it where it
    cannot. This says the buffer really is written on, so the test would
    have failed before that change.
    """
    screen = a_short_history()
    stream = Stream(screen)
    # Every line wraps, so a mark is written on nearly every row.
    stream.feed(
        "".join("row %d " % number + "x" * COLUMNS + "\r\n" for number in range(300))
    )
    screen._remove_old_lines_from_history()

    rows = screen.page.data_buffer.values()
    assert any(line.wrapped for line in rows)
    assert len(screen.page.data_buffer) <= LIMIT + LINES + 1
    assert len(screen.written_at) <= LIMIT + LINES + 1


def test_the_other_page_has_a_floor_of_its_own():
    """
    The alternate screen keeps its own history, so it keeps its own
    floor. A floor that stayed behind would leave the rows under it
    unprunable for the life of the pane.
    """
    screen = a_short_history()
    stream = Stream(screen)
    stream.feed("".join("line %d\r\n" % number for number in range(500)))
    screen._remove_old_lines_from_history()
    deep = screen.history_floor
    assert deep > 0

    stream.feed(set_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR))
    assert screen.history_floor == 0
    stream.feed(reset_mode(PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR))
    assert screen.history_floor == deep


def test_unscroll_brings_the_floor_down_with_the_screen():
    """
    `unscroll` slides the screen down over rows a prune took away, so
    the floor has to follow.

    Without that the screen covers rows that sit under the floor, a
    program writes on one of them, and the next prune walks from the
    floor and never reaches it. Hypothesis found it with a wrap, an
    unscroll and a rectangle erase.
    """
    screen = a_short_history()
    stream = Stream(screen)
    stream.feed("\nwider text that wraps around the end of a short row")
    screen._remove_old_lines_from_history()
    assert screen.history_floor > 0

    stream.feed(csi(Csi.KITTY_UNSCROLL, 1))
    assert screen.history_floor <= screen.line_offset

    # The row at the new top of the screen is written on, and it is not
    # under the floor.
    stream.feed(csi(Csi.DECERA, 0, 0, 0, 0))
    buffer = screen.page.data_buffer
    assert min(buffer) >= screen.history_floor
