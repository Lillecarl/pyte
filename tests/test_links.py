"""
The links some rows of a page show. Lillecarl/pymux#608.
"""

from __future__ import annotations

from pyte.links import links_in
from pyte.screen import Screen
from pyte.streams import Stream


def page_of(text: str, lines: int = 6, columns: int = 20):
    screen = Screen(lines, columns, write_process_input=lambda data: None)
    Stream(screen).feed(text)
    top = screen.line_offset
    return screen.page, top, top + lines - 1


def found(text: str, **size):
    page, first, last = page_of(text, **size)
    return [(link.url, link.row - first, link.column, link.osc8) for link in links_in(page, first, last)]


def test_a_url_in_the_text_is_found_where_it_stands():
    assert found("see https://a.io/x now") == [("https://a.io/x", 0, 4, False)]


def test_the_full_stop_after_a_url_is_not_part_of_it():
    assert found("go to www.a.io.")[0][0] == "www.a.io"


def test_brackets_are_taken_in_pairs():
    assert found("(https://a.io/x_(y))")[0][0] == "https://a.io/x_(y)"


def test_a_url_that_wrapped_is_one_url():
    "Twenty columns: the URL runs on to the second row."
    links = links_in(*page_of("1234567 https://example.org/long/path"))
    assert [link.url for link in links] == ["https://example.org/long/path"]
    (link,) = links
    assert (link.end_row - link.row, link.end_column) == (1, 16)


def test_a_link_a_program_made_is_found_by_its_target():
    assert found("\x1b]8;;https://a.io/doc\x1b\\docs\x1b]8;;\x1b\\ here") == [("https://a.io/doc", 0, 0, True)]


def test_a_link_wins_over_the_url_its_text_shows():
    text = "\x1b]8;;https://a.io/real\x1b\\https://a.io/shown\x1b]8;;\x1b\\"
    assert found(text, columns=40) == [("https://a.io/real", 0, 0, True)]


def test_a_wide_character_before_a_url_does_not_move_it():
    "The wide one takes two columns and one character of the text."
    assert found("漢 https://a.io")[0][2] == 3


def test_links_come_top_to_bottom():
    urls = [url for url, *_ in found("https://b.io\r\nhttps://a.io")]
    assert urls == ["https://b.io", "https://a.io"]
