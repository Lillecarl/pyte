"""
A reflow lays out the screen, and the screen is all it has to lay out.

`Screen._reflow` used to unwrap the whole buffer and wrap it again, so
dragging a window edge cost the scrollback: 99,027,334 bytecode
instructions on fifty thousand rows, paid while a person watched the
edge move. It walks up from the last row now and stops once it holds a
line for every row of the screen, which is 97,954 whatever the history
holds. Lillecarl/pymux#135.

**So the history keeps the width it was written at.** That is safe
because nothing reads the history as rows: copy mode and `capture-pane`
both read the lines a program wrote, and a line carries no width.

This file is the proof that the bound takes nothing away. It runs the
same bytes through two screens, one bounded and one that lays out
everything, and says the person sees the same thing. `EagerScreen` is
the old behaviour, kept here and nowhere else.

`test_reflow_keeps_the_content.py` is the other half: it says a resize
keeps every line of the whole buffer, history included.
"""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from a_screen import a_screen
from pyte.screen import Screen
from pyte.streams import Stream

from test_row_versions import a_chunk


class EagerScreen(Screen):
    """
    A screen that lays the whole buffer out again on every resize.

    That is what `_reflow` did before Lillecarl/pymux#135 bounded it,
    and it is the answer this file holds the bounded one to.
    """

    def _first_row_to_lay_out(self, last: int) -> int:
        return min(self.page.data_buffer)


def what_a_person_sees(screen):
    """
    The rows of the screen, and where the cursor is on it.

    Row numbers are left out on purpose. A bounded reflow keeps the
    numbering the history had and an eager one starts again from the
    lowest row it holds, so the two agree on what is drawn and not on
    what it is called.
    """
    data_buffer = screen.page.data_buffer
    rows = []

    for number in range(screen.line_offset, screen.max_y + 1):
        row = data_buffer.get(number)
        if row is None:
            rows.append(((), None, False))
            continue
        rows.append(
            (
                tuple(
                    (row[column].char, row[column].appearance)
                    for column in range(max(row, default=-1) + 1)
                ),
                row.attribute,
                row.wrapped,
            )
        )

    return (
        tuple(rows),
        screen.pt_cursor_position.y - screen.line_offset,
        screen.pt_cursor_position.x,
    )


#: The widths to resize through. Narrower than the screen so a line
#: wraps, and wider so the rows a wrap made join up again.
WIDTHS = st.lists(st.integers(4, 24), min_size=1, max_size=4)


@given(st.lists(a_chunk(), min_size=1, max_size=40), WIDTHS)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_the_screen_is_what_laying_out_everything_gives(chunks, widths):
    """
    Feed two screens the same bytes and resize both through the same
    widths. One lays out the whole buffer and one lays out the screen.
    A person sees the same thing.
    """
    data = "".join(chunks)

    bounded = a_screen(columns=10, lines=6)
    eager = a_screen(columns=10, lines=6, kind=EagerScreen)

    for screen in (bounded, eager):
        Stream(screen).feed(data)

    for width in widths:
        bounded.resize(bounded.lines, width)
        eager.resize(eager.lines, width)
        assert what_a_person_sees(bounded) == what_a_person_sees(eager)


@given(st.lists(a_chunk(), min_size=1, max_size=40), WIDTHS)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_no_row_of_the_screen_is_wider_than_the_screen(chunks, widths):
    """
    The hazard the bound brings, said directly.

    A row of the history keeps the width it was written at, so it can
    hold more columns than the screen has now. `unscroll` slides the
    screen down over the history and is the one path that brings such
    a row into view, so it lays those rows out again.

    Nothing else needs to: a resize lays out the screen at the size it
    is becoming, and every other move of the screen goes downwards
    over rows that a program is about to write.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed("".join(chunks))

    for width in widths:
        screen.resize(screen.lines, width)

    for count in (1, 2, 3):
        screen.unscroll(count)
        data_buffer = screen.page.data_buffer
        for number in range(screen.line_offset, screen.max_y + 1):
            row = data_buffer.get(number)
            if row:
                assert max(row) < screen.columns


def test_the_history_keeps_the_width_it_was_written_at():
    """
    The point of the bound, said directly: a row well above the screen
    is not touched by a column change.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed(
        "".join("row %d is long enough to wrap\r\n" % number for number in range(40))
    )

    before = screen.page.data_buffer[0]
    screen.resize(6, 20)

    assert screen.page.data_buffer[0] is before
    assert screen.reflow_floor > 0
