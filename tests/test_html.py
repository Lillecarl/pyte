"""
What a browser is given for a screen.

**The spans are read back by a parser, not by a string comparison.** A
test that held the exact markup would fail on a change that no browser
can see -- the order of two declarations, a run split in two -- and
would still not say that the characters land in the right columns. So
the document goes through `html.parser` and what comes out is a row of
text and the style of each piece, which is what a person looking at the
page would see. Lillecarl/pymux#452.
"""

from html.parser import HTMLParser
from typing import List, Tuple

import pytest

from pyte.cells import PLAIN, Rendition, appearance_of
from pyte.colors import PALETTE, Color, SgrColor
from pyte.html import (
    CSS,
    SAFE_SCHEMES,
    THEMED,
    color_value,
    html_of_page,
    html_of_row,
    style_of,
    visible_char,
)
from pyte.screen import Screen
from pyte.streams import Stream

# ----------------------------------------------------------------------
# Reading the document back.


class _Read(HTMLParser):
    "Every piece of text of a document, with the style that draws it."

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        #: (text, style, href) for each piece, in order.
        self.pieces: List[Tuple[str, str, str]] = []
        self._styles: List[str] = []
        self._hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        held = dict(attrs)
        self._styles.append(held.get("style") or "")
        self._hrefs.append(held.get("href") or "")

    def handle_endtag(self, tag):
        if self._styles:
            self._styles.pop()
        if self._hrefs:
            self._hrefs.pop()

    def handle_data(self, data):
        self.pieces.append(
            (
                data,
                self._styles[-1] if self._styles else "",
                self._hrefs[-1] if self._hrefs else "",
            )
        )

    @property
    def text(self) -> str:
        "Everything the page shows, with no markup in it."
        return "".join(text for text, _style, _href in self.pieces)


def _read(markup: str) -> _Read:
    reader = _Read()
    reader.feed(markup)
    reader.close()
    return reader


def _screen(rows: int, columns: int, text: str) -> Screen:
    "A real screen, fed real bytes. Lines first, the way `Screen` takes them."
    screen = Screen(rows, columns, write_process_input=lambda _data: None)
    Stream(screen).feed(text)
    return screen


def _drawn(text: str, columns: int = 20, rows: int = 3) -> _Read:
    "A real screen read back out of the document."
    screen = _screen(rows, columns, text)
    return _read(html_of_page(screen.page, 0, rows - 1, columns))


def _style_at(reader: _Read, character: str) -> str:
    "The style of the piece that holds a character."
    for text, style, _href in reader.pieces:
        if character in text:
            return style
    raise AssertionError("%r is nowhere in %r" % (character, reader.text))


# ----------------------------------------------------------------------
# One colour.


def test_a_themed_colour_stays_a_number():
    "The first sixteen are the theme of the terminal, so a page may set them."
    assert color_value(SgrColor(index=1)) == "var(--pyte-1)"
    assert color_value(SgrColor(index=THEMED - 1)) == "var(--pyte-15)"


def test_a_colour_of_the_cube_is_written_out():
    """
    Above the theme the palette is the same in every terminal, so there
    is nothing for a stylesheet to answer.
    """
    assert color_value(SgrColor(index=THEMED)) == PALETTE[THEMED].hex


def test_a_colour_a_program_named_is_written_out():
    assert color_value(SgrColor(rgb=Color(0x12, 0x34, 0x56))) == "#123456"


def test_the_colour_of_the_terminal_is_the_property_of_its_slot():
    assert color_value(SgrColor()) == "var(--pyte-fg)"
    assert color_value(SgrColor(), background=True) == "var(--pyte-bg)"


# ----------------------------------------------------------------------
# One appearance.


def _style(**fields) -> str:
    return style_of(appearance_of[Rendition(**fields), "", ""], False)


def test_a_plain_cell_has_no_style_at_all():
    "Nothing to say, so nothing is written and the cell needs no span."
    assert _style() == ""


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"bold": True}, "font-weight:bold"),
        ({"italic": True}, "font-style:italic"),
        ({"underline": True}, "text-decoration-line:underline"),
        ({"strike": True}, "text-decoration-line:line-through"),
        ({"hidden": True}, "color:transparent"),
        ({"blink": True}, "animation:pyte-blink 1s step-end infinite"),
        ({"baseline": "superscript"}, "vertical-align:super"),
        ({"baseline": "subscript"}, "vertical-align:sub"),
    ],
)
def test_each_part_of_a_rendition_reaches_the_style(fields, expected):
    assert expected in _style(**fields)


def test_underline_and_strike_share_one_property():
    "CSS holds both lines in `text-decoration-line`, so one may not lose."
    style = _style(underline=True, strike=True)
    assert "text-decoration-line:underline line-through" in style


@pytest.mark.parametrize(
    "shape, drawn",
    [("double", "double"), ("curly", "wavy"), ("dotted", "dotted"), ("dashed", "dashed")],
)
def test_the_shape_of_an_underline_reaches_the_style(shape, drawn):
    "What Rich cannot carry (Lillecarl/pymux#82), a browser draws."
    style = _style(underline=True, underline_style=shape)
    assert "text-decoration-style:" + drawn in style


def test_a_plain_underline_names_no_shape():
    "Solid is what CSS draws anyway, and this travels with every such cell."
    style = _style(underline=True)
    assert style == "text-decoration-line:underline"


def test_the_colour_of_an_underline_reaches_the_style():
    style = _style(
        underline=True, underline_color=SgrColor(rgb=Color(0xFF, 0x00, 0x00))
    )
    assert "text-decoration-color:#ff0000" in style


def test_an_underline_colour_nobody_draws_is_left_out():
    "It would travel with every cell for a line that is not there."
    style = _style(underline_color=SgrColor(rgb=Color(0xFF, 0x00, 0x00)))
    assert "text-decoration-color" not in style


def test_reverse_swaps_the_two_colours():
    style = _style(
        color=SgrColor(index=1), bgcolor=SgrColor(index=2), reverse=True
    )
    assert "color:var(--pyte-2)" in style
    assert "background-color:var(--pyte-1)" in style


def test_reverse_with_no_colours_names_both_of_the_terminal():
    """
    A cell that asked for neither colour still swaps, and the two
    properties of the terminal are what it swaps.
    """
    style = _style(reverse=True)
    assert "color:var(--pyte-bg)" in style
    assert "background-color:var(--pyte-fg)" in style


def test_a_reversed_cell_in_reverse_video_comes_back_round():
    "Two reversals are none, which is what DECSCNM means for such a cell."
    appearance = appearance_of[Rendition(reverse=True), "", ""]
    assert style_of(appearance, True) == ""


def test_reverse_video_reverses_a_plain_cell():
    plain = appearance_of[PLAIN, "", ""]
    style = style_of(plain, True)
    assert "color:var(--pyte-bg)" in style
    assert "background-color:var(--pyte-fg)" in style


def test_dim_mixes_the_colour_towards_the_background():
    "The one part of a rendition no spelling here draws exactly."
    style = _style(dim=True, color=SgrColor(index=7))
    assert "color:color-mix(in srgb, var(--pyte-7) 50%, var(--pyte-bg))" in style


# ----------------------------------------------------------------------
# What a cell draws.


def test_the_second_half_of_a_wide_character_draws_nothing():
    """
    **A space there would move the rest of the row along.** The screen
    keeps an empty cell after a double width character, and the
    character beside it is already two columns wide in the font.
    """
    assert visible_char("") == ""


def test_a_placeholder_draws_a_space():
    from pyte.placeholders import PLACEHOLDER

    assert visible_char(PLACEHOLDER) == " "


@pytest.mark.parametrize("char", ["\x00", "\x1b", "\x7f", "\x9b"])
def test_a_control_character_draws_a_space(char):
    assert visible_char(char) == " "


def test_an_ordinary_character_is_itself():
    assert visible_char("a") == "a"
    assert visible_char("é") == "é"


# ----------------------------------------------------------------------
# A row, and a page, against a real screen.


def test_the_text_of_a_page_is_what_was_written():
    reader = _drawn("hello")
    assert reader.text.startswith("hello")


def test_the_characters_land_in_their_columns():
    "A row is columns, so what is written at column 10 is at column 10."
    screen = _screen(2, 20, "\x1b[1;11Hx")
    row = html_of_row(screen.page.data_buffer[0], 20)
    text = _read(row).text
    assert text == " " * 10 + "x"


def test_a_double_width_character_takes_one_cell_of_text():
    """
    Two columns of the screen, one character of the document. The font
    makes it two columns wide, so a filler would be one too many.
    """
    screen = _screen(2, 20, "a中b")
    text = _read(html_of_row(screen.page.data_buffer[0], 20)).text
    assert text == "a中b"


def test_the_blanks_at_the_end_of_a_row_are_left_out():
    "Nothing draws them, and they would be trailing spaces in a copy."
    screen = _screen(2, 40, "hi")
    assert _read(html_of_row(screen.page.data_buffer[0], 40)).text == "hi"


def test_a_blank_that_carries_a_background_stays():
    "It draws, so it is content and not padding."
    screen = _screen(2, 10, "\x1b[41mhi\x1b[K")
    text = _read(html_of_row(screen.page.data_buffer[0], 10)).text
    assert text == "hi" + " " * 8


def test_every_cell_of_a_row_draws_in_reverse_video():
    "DECSCNM reverses the whole screen, so nothing is padding."
    screen = _screen(2, 10, "hi")
    text = _read(html_of_row(screen.page.data_buffer[0], 10, True)).text
    assert text == "hi" + " " * 8


def test_a_row_of_one_appearance_is_one_span():
    "A span for each cell of a wide screen is sixty thousand elements."
    screen = _screen(2, 40, "\x1b[31mred text here")
    markup = html_of_row(screen.page.data_buffer[0], 40)
    assert markup.count("<span") == 1


def test_a_page_gives_one_line_for_each_row():
    "A blank row has to take a line, which is what the newlines are for."
    screen = _screen(4, 10, "one\r\n\r\nthree")
    page = html_of_page(screen.page, 0, 3, 10)
    assert page.split("\n") == ["one", "", "three", ""]


def test_reading_a_page_makes_no_rows():
    """
    `page.data_buffer` is a defaultdict, so asking for a row it does not
    hold would make one -- and a row made below the floor of a history
    is a row that came back from the dead.
    """
    screen = _screen(4, 10, "one")
    held = set(screen.page.data_buffer)
    html_of_page(screen.page, 0, 3, 10)
    assert set(screen.page.data_buffer) == held


# ----------------------------------------------------------------------
# What a program writes into the document.


@pytest.mark.parametrize("dangerous", ["<script>", "&", "\"", "'", "</span>"])
def test_what_a_program_writes_cannot_become_markup(dangerous):
    "Every character of a cell came from a program, so all of it is escaped."
    screen = _screen(2, 40, dangerous)
    markup = html_of_row(screen.page.data_buffer[0], 40)

    assert "<script" not in markup
    # And it is still the text it was, read back.
    assert _read(markup).text == dangerous


def _linked(target: str) -> _Read:
    "A screen with one hyperlink on it, read back."
    screen = _screen(2, 20, "\x1b]8;;%s\x1b\\click\x1b]8;;\x1b\\" % target)
    return _read(html_of_row(screen.page.data_buffer[0], 20))


def test_a_hyperlink_becomes_an_anchor():
    reader = _linked("https://example.com/x")
    assert reader.pieces[0][2] == "https://example.com/x"
    assert reader.text == "click"


@pytest.mark.parametrize("scheme", sorted(SAFE_SCHEMES))
def test_every_scheme_that_is_allowed_arrives(scheme):
    reader = _linked("%s:target" % scheme)
    assert reader.pieces[0][2] == "%s:target" % scheme


@pytest.mark.parametrize(
    "target",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:x",
        # A browser drops a tab or a newline inside a scheme before it
        # reads one, so this runs a script there. It matches no scheme
        # here, so the link is not made.
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        " javascript:alert(1)",
        # No scheme at all: it would point at whatever serves the page.
        "/etc/passwd",
        "//example.com/x",
        "x.html",
    ],
)
def test_a_link_a_program_must_not_choose_is_refused(target):
    """
    **A program in a pane writes "OSC 8", so it chooses this URL.** In a
    terminal that costs little. In a document a script would run in the
    page, so the link goes away and the text stays.
    """
    reader = _linked(target)
    assert reader.pieces[0][2] == ""
    assert reader.text == "click"


def test_a_hyperlink_keeps_the_style_of_its_cells():
    "The anchor is what carries it, so a link is drawn as the program asked."
    screen = _screen(2, 20, "\x1b[1m\x1b]8;;https://x/\x1b\\bold\x1b]8;;\x1b\\")
    reader = _read(html_of_row(screen.page.data_buffer[0], 20))
    assert "font-weight:bold" in reader.pieces[0][1]


# ----------------------------------------------------------------------
# The stylesheet.


def test_the_stylesheet_answers_every_property_a_style_can_name():
    """
    A style names a custom property for a themed colour, and a page
    that defines none of them would draw nothing at all.
    """
    for index in range(THEMED):
        assert "--pyte-%d:" % index in CSS
    assert "--pyte-fg:" in CSS
    assert "--pyte-bg:" in CSS


def test_the_stylesheet_holds_the_three_rules_that_are_not_decoration():
    assert "white-space: pre" in CSS
    assert "@keyframes pyte-blink" in CSS
    # Without this a browser draws a link its own way, and a cell that
    # was not underlined would be.
    assert "text-decoration: inherit" in CSS


def test_the_stylesheet_takes_its_colours_from_the_palette():
    "One copy of the palette, and this is not it."
    assert "--pyte-1: %s;" % PALETTE[1].hex in CSS
