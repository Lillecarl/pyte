"""
A resize lays the buffer out again and changes nothing that was in it.

This is the oracle for Lillecarl/pymux#135. That issue wants the
history to stop being laid out on every column change, and the whole
risk of it is that a deferred reflow quietly loses something. So the
property has to exist and pass on the eager reflow we have now, before
anything defers: a test that only arrives with the change it judges
proves nothing about the change.

**The invariant is width-independent, which is the point.** A reflow
unwraps every run of wrapped rows back into the line a program wrote
and lays that line out again. The line itself has no width in it, so a
column change may not touch it. `logical_lines` reads exactly that, and
it is the same function `_reflow` builds and throws away, and the same
one that Lillecarl/pymux#135 would keep.

What it is not: a round trip. `_reflow` trims the erased cells off the
end of a line on purpose (Lillecarl/pymux#56), so a buffer is not equal
to itself across a resize. The content is.
"""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from a_screen import a_screen
from pyte.cells import PLAIN_APPEARANCE, WrittenCell
from pyte.streams import Stream

from test_row_versions import a_chunk


def _trimmed(cells):
    """
    One line without the blanks an erase left at the end of it.

    `_reflow` does this so that a line which was never filled does not
    carry its width around (Lillecarl/pymux#56). The test is the class
    and not the character: a space that a program drew is a
    `WrittenCell` and stays.

    It trims all the way to nothing, where `_reflow` stops at one cell.
    That last cell is there for `max_y` and not for a reader: a row of
    blanks and a row that is absent both draw as blanks, so a content
    oracle has to read them the same way. `_reflow` also materialises
    the cell the cursor stands on, which is the same thing again.
    """
    end = len(cells)
    while (
        end > 0
        and not isinstance(cells[end - 1], WrittenCell)
        and cells[end - 1].appearance == PLAIN_APPEARANCE
    ):
        end -= 1
    return cells[:end]


def logical_lines(screen):
    """
    What the buffer holds, as the lines a program wrote.

    A run of rows that a wrap made is one line. The width is gone from
    the answer, so a resize may not change it.

    **Nothing here writes.** `data_buffer` is a defaultdict, so asking
    it about a row makes one, and a row made below `history_floor` is a
    row that came back from the dead (Lillecarl/pymux#134). Every read
    goes through `.get`.
    """
    data_buffer = screen.page.data_buffer
    if not data_buffer:
        return ()

    lines = []
    cells = []
    attribute = None

    for number in range(min(data_buffer), max(data_buffer) + 1):
        row = data_buffer.get(number)

        # An absent row is a row of blanks, and a row of blanks is not
        # a wrap, so it ends the line before it.
        if row is None or not row.wrapped:
            lines.append((_trimmed(cells), attribute))
            cells = []
            attribute = None if row is None else row.attribute

        if row:
            for column in range(max(row) + 1):
                cells.append(row[column])

    lines.append((_trimmed(cells), attribute))

    # The first entry is the line before the first row, which is
    # nothing, and a line at the end that trimmed to nothing cannot be
    # told from a row the buffer never held.
    while lines and not lines[0][0] and lines[0][1] is None:
        lines.pop(0)
    while lines and not lines[-1][0] and lines[-1][1] is None:
        lines.pop()

    return tuple(
        (tuple((cell.char, cell.appearance) for cell in cells), attribute)
        for cells, attribute in lines
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
def test_a_column_change_keeps_every_line(chunks, widths):
    """
    Feed a screen, then resize it through several widths with nothing
    written in between. The lines are the same after each one.
    """
    screen = a_screen(columns=10, lines=6)
    Stream(screen).feed("".join(chunks))

    before = logical_lines(screen)
    for width in widths:
        screen.resize(screen.lines, width)
        assert logical_lines(screen) == before


@given(st.lists(a_chunk(), min_size=1, max_size=40), WIDTHS)
@settings(
    max_examples=300,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_column_change_keeps_every_line_with_a_short_history(chunks, widths):
    """
    The same, on a pane that keeps almost no scrollback, so that rows
    leave the history while the sequence runs.
    """
    screen = a_screen(columns=10, lines=6, history=5)
    Stream(screen).feed("".join(chunks))

    before = logical_lines(screen)
    for width in widths:
        screen.resize(screen.lines, width)
        assert logical_lines(screen) == before
