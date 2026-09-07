"""
The alternate screen holds its own rows and nothing above them.

A full-screen program draws on a screen of its own. What scrolls off
the top of that screen is gone: there is no scrollback to reach it,
and taking the first screen back gives that one's history, not this
one's. So a row above the alternate screen is a row nobody can read.

They were kept anyway. `_remove_old_lines_from_history` keeps as many
rows as `history-limit` says, which is the option a person set for the
scrollback of their shell, and it runs once every hundred linefeeds.
So a program that scrolled its own screen left the rows behind until
the hundredth one, and up to a hundred of them at once.

**Copy mode is where that shows.** It reads from the lowest row of the
buffer to the highest, so those rows are lines of the document, and
the history pymux shows is taller than the screen a program drew.
Lillecarl/pymux#132.
"""
from pyte.screen import Screen
from pyte.streams import Stream

LINES = 5
COLUMNS = 10

#: A history a person would set for their shell. The alternate screen
#: may not use it: these tests fail with the buffer that deep.
HISTORY = 2000


def an_alternate_screen(lines: int = LINES, columns: int = COLUMNS):
    "A screen with a full-screen program in front of it."
    screen = Screen(
        lines,
        columns,
        write_process_input=lambda data: None,
        get_history_limit=lambda: HISTORY,
    )
    Stream(screen).feed("\x1b[?1049h")
    return screen


def lowest_row(screen) -> int:
    "The lowest row the buffer holds."
    return min(screen.page.data_buffer)


def text_of(screen, row: int) -> str:
    "What one row of the buffer holds, without making it."
    line = screen.page.data_buffer.get(row)
    if not line:
        return ""
    return "".join(line[column].char for column in range(max(line) + 1))


def test_scrolling_once_past_the_fold_leaves_no_row_behind():
    """
    Six lines on a five line screen. The first one is gone, and it may
    not sit in the buffer waiting for the hundredth linefeed.
    """
    screen = an_alternate_screen()
    Stream(screen).feed("".join("a%d\r\n" % number for number in range(6)))

    assert lowest_row(screen) == screen.line_offset


def test_scrolling_far_past_the_fold_leaves_no_row_behind():
    "Fewer than a hundred lines, so no prune has come round."
    screen = an_alternate_screen()
    Stream(screen).feed("".join("a%d\r\n" % number for number in range(60)))

    assert lowest_row(screen) == screen.line_offset


def test_the_rows_of_the_screen_itself_stay():
    "It drops what scrolled away, and nothing that is still drawn."
    screen = an_alternate_screen()
    Stream(screen).feed("".join("a%d\r\n" % number for number in range(6)))

    drawn = [text_of(screen, screen.line_offset + row) for row in range(LINES)]
    assert drawn == ["a2", "a3", "a4", "a5", ""]


def test_a_screen_that_has_not_scrolled_keeps_every_row_it_drew():
    screen = an_alternate_screen()
    Stream(screen).feed("".join("a%d\r\n" % number for number in range(4)))

    assert lowest_row(screen) == 0
    assert text_of(screen, 0) == "a0"


def test_the_first_screen_keeps_its_history_through_the_visit():
    """
    The alternate screen keeps none of its own, and takes none away
    from the screen it covers.
    """
    screen = Screen(
        LINES,
        COLUMNS,
        write_process_input=lambda data: None,
        get_history_limit=lambda: HISTORY,
    )
    stream = Stream(screen)
    stream.feed("".join("shell %d\r\n" % number for number in range(20)))
    before = lowest_row(screen)

    stream.feed("\x1b[?1049h")
    stream.feed("".join("program %d\r\n" % number for number in range(60)))
    stream.feed("\x1b[?1049l")

    assert lowest_row(screen) == before
    assert text_of(screen, before) == "shell 0"
