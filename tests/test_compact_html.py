"""
What an agent reads for a screen.

Read back through `html.parser`, like `test_html.py`: what a test holds
is each piece of text with what it looks like, not the markup.
"""

from __future__ import annotations

from html.parser import HTMLParser

from pyte.colors import DEFAULT_COLORS, PALETTE
from pyte.compact_html import compact_html_of_page
from pyte.html import html_of_page
from pyte.screen import Screen
from pyte.streams import Stream


class _Read(HTMLParser):
    "Each piece of text, with the style, tags and link around it."

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[tuple[str, str, frozenset[str], str]] = []
        self.pre = ""
        self._open: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        held = dict(attrs)
        if tag == "pre":
            self.pre = held.get("style") or ""
        else:
            self._open.append((tag, held))

    def handle_endtag(self, tag):
        if tag != "pre":
            assert self._open.pop()[0] == tag

    def handle_data(self, data):
        style = ";".join(held.get("style") or "" for tag, held in self._open if tag == "span")
        href = "".join(held.get("href") or "" for tag, held in self._open if tag == "a")
        tags = frozenset(tag for tag, _held in self._open if tag not in ("span", "a"))
        self.pieces.append((data, style, tags, href))


def _screen(text: str, columns: int = 30, rows: int = 2) -> Screen:
    screen = Screen(rows, columns, write_process_input=lambda _data: None)
    Stream(screen).feed(text)
    return screen


def _read(text: str, columns: int = 30, rows: int = 1) -> _Read:
    screen = _screen(text, columns, rows)
    read = _Read()
    read.feed(compact_html_of_page(screen.page, 0, rows - 1, columns))
    return read


def test_plain_text_is_text_with_no_tag_at_all():
    assert _read("hello\r\nworld", rows=2).pieces == [("hello\nworld", "", frozenset(), "")]


def test_the_pre_paints_the_screens_own_colours():
    read = _read("x")
    assert read.pre == "color:%s;background:%s" % (DEFAULT_COLORS["foreground"].hex, DEFAULT_COLORS["background"].hex)


def test_a_space_between_two_coloured_words_joins_them():
    "A blank's foreground is drawn by nothing, so it does not split a run."
    (piece,) = _read("\x1b[31mred\x1b[39m \x1b[31mwords\x1b[0m").pieces
    assert piece == ("red words", "color:%s" % (PALETTE[1].hex,), frozenset(), "")


def test_a_bold_word_inside_a_colour_does_not_reopen_it():
    screen = _screen("\x1b[90mRan \x1b[1m2\x1b[22m commands")
    markup = compact_html_of_page(screen.page, 0, 0, 30)
    assert markup.count("<span") == 1, markup
    read = _Read()
    read.feed(markup)
    assert [(text, tags) for text, _style, tags, _href in read.pieces] == [
        ("Ran ", set()),
        ("2", {"b"}),
        (" commands", set()),
    ]


def test_a_space_with_a_background_of_its_own_stays_apart():
    pieces = _read("\x1b[31mred\x1b[41m \x1b[49mx").pieces
    assert [text for text, *_ in pieces] == ["red", " ", "x"]
    assert "background:%s" % (PALETTE[1].hex,) in pieces[1][1]


def test_renditions_are_the_tags_a_model_knows():
    pieces = _read("\x1b[1mb\x1b[22;3mi\x1b[23;4mu\x1b[24;9ms\x1b[0m").pieces
    assert [(text, tags) for text, _style, tags, _href in pieces] == [
        ("b", {"b"}),
        ("i", {"i"}),
        ("u", {"u"}),
        ("s", {"s"}),
    ]


def test_reverse_swaps_the_two_colours_the_screen_draws_with():
    ((text, style, _tags, _href),) = _read("\x1b[7mrev\x1b[0m").pieces
    assert text == "rev"
    assert style == "color:%s;background:%s" % (DEFAULT_COLORS["background"].hex, DEFAULT_COLORS["foreground"].hex)


def test_a_truecolour_is_written_as_it_stands():
    ((_text, style, _tags, _href),) = _read("\x1b[38;2;1;2;3mx").pieces
    assert style == "color:#010203"


def test_only_what_a_pre_needs_is_escaped():
    screen = _screen("a<b & 'c' \"d\"")
    markup = compact_html_of_page(screen.page, 0, 0, 30)
    assert "a&lt;b &amp; 'c' \"d\"" in markup


def test_a_blank_that_names_the_default_background_is_trimmed():
    assert _read("x\x1b[49m      ").pieces == [("x", "", frozenset(), "")]


def test_a_link_stays_a_link_and_a_script_does_not():
    pieces = _read(
        "\x1b]8;;https://example.com\x1b\\site\x1b]8;;\x1b\\ \x1b]8;;javascript:x\x1b\\bad\x1b]8;;\x1b\\"
    ).pieces
    assert ("site", "", frozenset(), "https://example.com") in pieces
    assert all(href != "javascript:x" for *_rest, href in pieces)


def test_a_coloured_screen_is_smaller_than_the_browsers_html():
    words = " ".join("\x1b[3%dmword%d\x1b[39m" % (index % 7 + 1, index) for index in range(12))
    screen = _screen(words + "\r\n" + words, columns=120)
    compact = compact_html_of_page(screen.page, 0, 1, 120)
    browser = html_of_page(screen.page, 0, 1, 120)
    assert len(compact) < len(browser), (len(compact), len(browser))
