"""
`Page.unwrap` gives back the lines a program wrote.

A row is a line cut to fit a screen. `unwrap` joins the pieces back
together, and the answer carries no width at all. Three readers want
that shape and one of them is a reflow: copy mode, `capture-pane`, and
`Screen._reflow`. Lillecarl/pymux#135.

These judge the joining itself, on a page built by hand. The property
that a resize keeps every line is `test_reflow_keeps_the_content.py`,
and it judges the same function through the screen.
"""

from pyte.cells import PLAIN_APPEARANCE, WrittenCell
from pyte.page import Page, TextLine


def _a_page(*rows):
    """
    A page holding the given rows, from row zero.

    A row is a string, or a string with a leading "|" to say that a
    wrap brought it into being. An empty string is a row the buffer
    holds and nothing was written on.
    """
    page = Page(default_char=WrittenCell(" ", PLAIN_APPEARANCE))
    for number, text in enumerate(rows):
        wrapped = text.startswith("|")
        row = page.data_buffer[number]
        row.wrapped = wrapped
        for column, character in enumerate(text[1:] if wrapped else text):
            row[column] = WrittenCell(character, PLAIN_APPEARANCE)
    return page


def _text(lines):
    "The lines as strings, so that a failure reads."
    return ["".join(cell.char for cell in line.cells) for line in lines]


def test_a_run_of_wrapped_rows_is_one_line():
    page = _a_page("one", "|two", "|three")
    lines, found = page.unwrap(0, 2)
    assert _text(lines) == ["onetwothree"]
    assert found is None


def test_a_row_that_no_wrap_made_starts_a_line():
    page = _a_page("one", "two", "|three")
    assert _text(page.unwrap(0, 2)[0]) == ["one", "twothree"]


def test_the_answer_has_no_line_after_the_last_row():
    """
    The end of a line does not start the next one.

    A line made after the last row is a line no program wrote, and
    copy mode and `capture-pane` both print one line per entry.
    """
    page = _a_page("one", "two")
    assert _text(page.unwrap(0, 1)[0]) == ["one", "two"]


def test_a_row_of_nothing_is_a_line_of_nothing():
    "A blank line between two lines stays a line."
    page = _a_page("one", "", "two")
    assert _text(page.unwrap(0, 2)[0]) == ["one", "", "two"]


def test_a_range_starting_inside_a_line_gives_the_rest_of_it():
    """
    The caller asks for rows, so a line the range cuts into arrives
    cut. `_reflow` reads from the first row of the buffer, where this
    cannot happen; a reader that asks for the screen alone sees it.
    """
    page = _a_page("one", "|two", "three")
    assert _text(page.unwrap(1, 2)[0]) == ["two", "three"]


def test_a_range_that_holds_no_row_gives_one_empty_line():
    "Rows the buffer never held are blanks, and blanks are a line."
    page = _a_page("one")
    assert _text(page.unwrap(4, 4)[0]) == [""]


def test_the_cursor_arrives_as_a_line_and_an_offset():
    "The column of a wrapped row counts from the start of the line."
    page = _a_page("one", "|two", "three")
    lines, found = page.unwrap(0, 2, cursor=(1, 1))
    assert _text(lines) == ["onetwo", "three"]
    assert found == (0, 4)


def test_a_cursor_outside_the_range_is_not_found():
    page = _a_page("one", "two")
    assert page.unwrap(0, 1, cursor=(5, 0))[1] is None


def test_the_text_of_a_line_joins_the_rows_it_took():
    "The cheap half: the text, and no cell of it."
    page = _a_page("one", "|two", "three", "|four", "|five")
    assert page.text_lines(0, 4) == [
        TextLine("onetwo", 0, 1),
        TextLine("threefourfive", 2, 4),
    ]


def test_a_text_line_stops_where_the_caller_stopped():
    """
    The row below `last` may be a wrap of it. The caller asked for
    rows, so a line the range cuts into arrives cut.
    """
    page = _a_page("one", "|two", "|three")
    assert page.text_lines(0, 1) == [TextLine("onetwo", 0, 1)]


def test_a_row_of_nothing_is_a_text_line_of_nothing():
    page = _a_page("one", "", "")
    assert page.text_lines(0, 2) == [
        TextLine("one", 0, 0),
        TextLine("", 1, 1),
        TextLine("", 2, 2),
    ]


def test_a_range_that_holds_nothing_gives_no_text_line():
    "A buffer with no row at all asks for nothing, and gets nothing."
    assert _a_page().text_lines(0, -1) == []


def test_the_text_of_a_range_carries_no_break():
    "A caller that wants the breaks asks for the lines."
    page = _a_page("one", "two")
    assert page.text(0, 1) == "onetwo"


def test_the_rows_of_a_text_line_unwrap_to_its_cells():
    """
    The two halves agree: the rows a `TextLine` names hold that line
    and no other. That is what copy mode does when a person looks at
    a line.
    """
    page = _a_page("one", "|two", "three")
    for shown in page.text_lines(0, 2):
        lines, _ = page.unwrap(shown.first, shown.last)
        assert len(lines) == 1
        assert "".join(cell.char for cell in lines[0].cells) == shown.text


def test_nothing_is_written_by_reading():
    """
    The buffer makes a row for a number it does not hold, so a
    question that writes brings a row back from the dead.
    Lillecarl/pymux#134.
    """
    page = _a_page("one")
    page.unwrap(0, 10)
    page.text_lines(0, 10)
    page.text(0, 10)
    assert set(page.data_buffer) == {0}
