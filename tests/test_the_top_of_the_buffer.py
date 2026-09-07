"""
The highest row of the buffer is inside the screen, never in the
history.

A front end has to know how many rows there are, and it read
`max(data_buffer)` to find out: fifty thousand keys per frame, and the
depth is a number the person chooses. Lillecarl/pymux#130.

**The scan does not need the history.** A row is written where the
cursor is or inside the scrolling region, and both are inside the
screen. `max_y` is the highest row that was ever written, and
`line_offset` is `max_y - lines + 1` while that is positive, so the
screen ends at `line_offset + lines - 1`, which is `max_y` itself once
the screen has filled once. Nothing above it exists.

So the answer is `max_y`, plus at most `lines` rows to look at above it
on a screen that has not filled yet. That is a hundred rows at the very
most, whatever the history holds.

This file is the proof of the claim the bound rests on: no row of the
buffer sits above the last row of the screen. It hunts the same
generated sequences as `test_row_versions`, because the paths that move
whole ranges of rows are the ones that could put a row somewhere
nobody expects.
"""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from a_screen import a_screen
from pyte.streams import Stream
from test_row_versions import a_chunk

LINES = 6
COLUMNS = 10


def the_last_row_of_the_screen(screen) -> int:
    return screen.line_offset + screen.lines - 1


def say_nothing_sits_above_the_screen(screen) -> None:
    """
    The bound, and then the answer that rests on it.

    The bound is that no row of the buffer sits above the last row of
    the screen. The answer is `highest_row`, which searches that far and
    no further, and it has to be what reading the whole buffer says.
    """
    buffer = screen.page.data_buffer
    last = the_last_row_of_the_screen(screen)
    where = "max_y %d, line_offset %d, lines %d" % (
        screen.max_y, screen.line_offset, screen.lines
    )

    if buffer:
        assert max(buffer) <= last, (
            "row %d is above the last row of the screen, %d (%s)"
            % (max(buffer), last, where)
        )

    whole = max(buffer) if buffer else screen.max_y
    assert screen.highest_row() == max(whole, screen.max_y), (
        "highest_row said %d and the whole buffer says %d (%s)"
        % (screen.highest_row(), max(whole, screen.max_y), where)
    )

    # The other answer that rests on the same bound. A reflow asks for
    # the highest row the *buffer* holds, which can sit below `max_y`,
    # and it also has to be what reading the whole buffer says.
    # Lillecarl/pymux#145.
    if buffer:
        found = screen._highest_row_the_buffer_holds()
        assert found == max(buffer), (
            "the buffer top was read as %d and the whole buffer says %d (%s)"
            % (found, max(buffer), where)
        )


@given(st.lists(a_chunk(), min_size=1, max_size=40))
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_sequence_nobody_recorded(chunks):
    screen = a_screen(columns=COLUMNS, lines=LINES)
    stream = Stream(screen)
    for chunk in chunks:
        stream.feed(chunk)
        say_nothing_sits_above_the_screen(screen)


@given(
    st.lists(st.tuples(st.integers(2, 40), st.integers(1, 12)), min_size=1,
             max_size=12),
    st.integers(0, 30),
)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_screen_that_is_resized_over_and_over(sizes, written):
    """
    A reflow puts every character somewhere else and numbers the rows
    again, and it is the one path that sets `max_y` from the buffer
    rather than the other way round: `max_y = min(max(buffer), cursor +
    lines - 1)`. A row left above that cap is a row the bound would
    miss, so this asks for one directly.
    """
    screen = a_screen(columns=COLUMNS, lines=LINES)
    stream = Stream(screen)
    stream.feed(
        "".join("row %d of some text that wraps\r\n" % number
                for number in range(written))
    )
    for columns, lines in sizes:
        screen.resize(lines=lines, columns=columns)
        say_nothing_sits_above_the_screen(screen)
        stream.feed("more text after the resize\r\n")
        say_nothing_sits_above_the_screen(screen)


@given(st.lists(a_chunk(), min_size=1, max_size=40))
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_sequence_that_scrolls_out_of_the_history(chunks):
    "The same hunt on a pane that prunes, so `max_y` outruns the buffer."
    screen = a_screen(columns=COLUMNS, lines=LINES, history=5)
    stream = Stream(screen)
    for chunk in chunks:
        stream.feed(chunk)
        screen._remove_old_lines_from_history()
        say_nothing_sits_above_the_screen(screen)
