"""
A screen to feed, and a way to read what it drew.

The tests of the parser want a listener with the right method names and
a look at the result. They used upstream's `Screen`, which had a
`display` property. That screen is gone, and this is the two lines that
replace it.
"""
from pyte.screen import Screen

__all__ = ("a_screen", "display")


def a_screen(columns: int = 80, lines: int = 24, kind=Screen, history=None):
    """
    A screen of the given size, answering nobody.

    The columns come first here, the way upstream's `Screen` took them.
    `Screen` takes the lines first, which is the order a terminal
    reports a size in.

    `kind` is for a test that subclasses the screen to watch one method.

    `history` is how many rows of scrollback to keep. The default keeps
    two thousand, which a short test never fills, so a test that wants
    to see a row leave the history names a small number here.
    """
    return kind(
        lines,
        columns,
        write_process_input=lambda data: None,
        get_history_limit=None if history is None else (lambda: history),
    )


def display(screen: Screen):
    """
    What the screen shows, one string per row.

    A cell that no program wrote is a space, and the second half of a
    double width character is an empty string, so a row is as wide as
    the screen unless something wide is on it.
    """
    rows = []
    for y in range(screen.lines):
        row = screen.page.data_buffer[y]
        rows.append("".join(row[x].char for x in range(screen.columns)))
    return rows
