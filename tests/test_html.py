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
    Drawn,
    SAFE_SCHEMES,
    SCREEN_CLASS,
    THEMED,
    color_value,
    href_of,
    html_of_page,
    html_of_row,
    runs_of_row,
    style_of,
    theme_css,
    visible_char,
)
from pyte.screen import Screen
from pyte.streams import Stream

# ----------------------------------------------------------------------
# Reading the document back.


class _Read(HTMLParser):
    """
    Every piece of text of a document, with what draws it.

    Both halves of that, because a span carries its classes and its
    attribute and a reader cannot know which half a rendition took.
    Lillecarl/pymux#460.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        #: (text, drawn, href) for each piece, in order.
        self.pieces: List[Tuple[str, Drawn, str]] = []
        self._styles: List[Drawn] = []
        self._hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        held = dict(attrs)
        self._styles.append(
            Drawn(held.get("class") or "", held.get("style") or "")
        )
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
                self._styles[-1] if self._styles else Drawn("", ""),
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


def _style(**fields) -> "Drawn":
    return style_of(appearance_of[Rendition(**fields), "", ""], False)


def test_a_plain_cell_has_nothing_to_say():
    "Nothing to say, so nothing is written and the cell needs no span."
    assert _style() == Drawn("", "")
    assert not _style()


# ----------------------------------------------------------------------
# What carries no value is a class.
#
# Each of these was a declaration on every span that had it, and a
# screen of underlined text repeated the same forty characters per run.
# Lillecarl/pymux#460.


@pytest.mark.parametrize(
    "fields, expected",
    [
        ({"bold": True}, "pyte-bold"),
        ({"italic": True}, "pyte-italic"),
        ({"underline": True}, "pyte-underline"),
        ({"strike": True}, "pyte-strike"),
        ({"hidden": True}, "pyte-hidden"),
        ({"blink": True}, "pyte-blink"),
        ({"baseline": "superscript"}, "pyte-superscript"),
        ({"baseline": "subscript"}, "pyte-subscript"),
    ],
)
def test_each_part_of_a_rendition_with_no_value_is_a_class(fields, expected):
    drawn = _style(**fields)
    assert expected in drawn.classes.split()
    # And nothing at all is left for the attribute.
    assert drawn.style == ""


def test_underline_and_strike_are_one_class_and_not_two():
    """
    CSS holds both lines in `text-decoration-line`, so two rules that
    each set it do not add up: the later one wins and the other line is
    lost. The pair has a class of its own.
    """
    assert _style(underline=True, strike=True).classes == "pyte-underline-strike"


@pytest.mark.parametrize(
    "shape, drawn",
    [("double", "double"), ("curly", "wavy"), ("dotted", "dotted"), ("dashed", "dashed")],
)
def test_the_shape_of_an_underline_is_a_class(shape, drawn):
    "What Rich cannot carry (Lillecarl/pymux#82), a browser draws."
    assert "pyte-" + drawn in _style(underline=True, underline_style=shape).classes


def test_a_plain_underline_names_no_shape():
    "Solid is what CSS draws anyway, and this travels with every such cell."
    assert _style(underline=True) == Drawn("pyte-underline", "")


def test_a_hidden_cell_is_given_no_colour_to_cover():
    """
    `color:transparent` was written last so that it beat the colour
    above it. A class cannot do that -- an attribute beats every class,
    and two classes are settled by the order of the stylesheet -- so
    nothing paints the glyph of a hidden cell in the first place.
    """
    drawn = _style(hidden=True, color=SgrColor(index=1))
    assert drawn.style == ""
    assert "pyte-fg-1" not in drawn.classes


def test_a_hidden_cell_keeps_its_background():
    '"SGR 8" hides the character and not the space it sits in.'
    assert "pyte-bg-2" in _style(hidden=True, bgcolor=SgrColor(index=2)).classes


# ----------------------------------------------------------------------
# What carries a value stays in the attribute.


def test_the_colour_of_an_underline_stays_in_the_attribute():
    drawn = _style(
        underline=True, underline_color=SgrColor(rgb=Color(0xFF, 0x00, 0x00))
    )
    assert "text-decoration-color:#ff0000" in drawn.style


def test_an_underline_colour_nobody_draws_is_left_out():
    "It would travel with every cell for a line that is not there."
    assert "text-decoration-color" not in _style(
        underline_color=SgrColor(rgb=Color(0xFF, 0x00, 0x00))
    ).style


def test_a_themed_colour_is_a_class():
    "The sixteen a theme answers, which is most of what a program uses."
    assert _style(color=SgrColor(index=1)) == Drawn("pyte-fg-1", "")


def test_a_colour_above_the_theme_carries_its_value():
    "A place in the cube is the same number everywhere, and needs no rule."
    assert _style(color=SgrColor(index=208)).style == "color:#ff8700"


def test_a_colour_a_program_named_carries_its_value():
    drawn = _style(color=SgrColor(rgb=Color(0x1E, 0xAA, 0x5A)))
    assert drawn.style == "color:#1eaa5a"
    assert drawn.classes == ""


def test_reverse_swaps_the_two_colours():
    drawn = _style(color=SgrColor(index=1), bgcolor=SgrColor(index=2), reverse=True)
    assert drawn.classes == "pyte-fg-2 pyte-bg-1"


def test_reverse_with_no_colours_names_both_of_the_terminal():
    """
    A cell that asked for neither colour still swaps, and the two
    properties of the terminal are what it swaps. They stay in the
    attribute: the pair appears only on a reversed cell that named no
    colour, which is not where the bytes are.
    """
    drawn = _style(reverse=True)
    assert "color:var(--pyte-bg)" in drawn.style
    assert "background-color:var(--pyte-fg)" in drawn.style


def test_a_reversed_cell_in_reverse_video_comes_back_round():
    "Two reversals are none, which is what DECSCNM means for such a cell."
    appearance = appearance_of[Rendition(reverse=True), "", ""]
    assert not style_of(appearance, True)


def test_reverse_video_reverses_a_plain_cell():
    drawn = style_of(appearance_of[PLAIN, "", ""], True)
    assert "color:var(--pyte-bg)" in drawn.style
    assert "background-color:var(--pyte-fg)" in drawn.style


def test_dim_mixes_the_colour_towards_the_background():
    "The one part of a rendition no spelling here draws exactly."
    drawn = _style(dim=True, color=SgrColor(index=7))
    assert "color:color-mix(in srgb, var(--pyte-7) 50%, var(--pyte-bg))" in drawn.style


# ----------------------------------------------------------------------
# The stylesheet answers every class.


def test_every_class_a_cell_can_take_has_a_rule():
    """
    A class with no rule draws nothing, and nothing says so: the span
    is there, the word is there, and the cell comes out plain. So every
    way of drawing is asked what it takes, and the stylesheet is asked
    for each of them.
    """
    ways = [
        {"bold": True},
        {"italic": True},
        {"underline": True},
        {"strike": True},
        {"underline": True, "strike": True},
        {"hidden": True},
        {"blink": True},
        {"baseline": "superscript"},
        {"baseline": "subscript"},
    ]
    ways += [
        {"underline": True, "underline_style": shape}
        for shape in ("double", "curly", "dotted", "dashed")
    ]
    ways += [{"color": SgrColor(index=index)} for index in range(THEMED)]
    ways += [{"bgcolor": SgrColor(index=index)} for index in range(THEMED)]

    missing = []
    for fields in ways:
        for name in _style(**fields).classes.split():
            if ".pyte-screen .%s {" % (name,) not in CSS:
                missing.append(name)
    assert missing == []


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
    assert "pyte-bold" in reader.pieces[0][1].classes


# ----------------------------------------------------------------------
# The runs, which the markup and every other reader share.


def _runs(text: str, columns: int = 20, reverse_video: bool = False):
    "The runs of the first row, as (text, style) pairs."
    screen = _screen(3, columns, text)
    row = screen.page.data_buffer[0]
    return [
        (run, style_of(appearance, reverse_video))
        for appearance, run in runs_of_row(row, columns, reverse_video)
    ]


def test_cells_that_draw_alike_are_one_run():
    assert [run for run, _style in _runs("hello")] == ["hello"]


def test_a_change_of_appearance_starts_a_run():
    assert [run for run, _style in _runs("ab\x1b[1mcd\x1b[0mef")] == ["ab", "cd", "ef"]


def test_the_blanks_at_the_end_of_a_row_are_not_a_run():
    "Where the row ends, decided once for every reader."
    assert [run for run, _style in _runs("hi")] == ["hi"]


def test_a_row_that_draws_nothing_has_no_runs():
    assert _runs("") == []


def test_every_cell_is_a_run_in_reverse_video():
    "Nothing is blank when the screen is reversed, so the row is full."
    runs = _runs("hi", columns=5, reverse_video=True)
    assert "".join(run for run, _style in runs) == "hi   "


def test_the_markup_is_built_from_the_runs():
    """
    The markup is one caller of `runs_of_row` and not a second copy of
    the rule. A row whose runs are known says what its markup holds.
    """
    row = _screen(3, 20, "ab\x1b[1mcd\x1b[0m").page.data_buffer[0]
    runs = runs_of_row(row, 20)
    markup = html_of_row(row, 20)

    assert [run for _appearance, run in runs] == ["ab", "cd"]
    assert markup.count("<span") == 1, markup
    assert markup.endswith("cd</span>"), markup


# ----------------------------------------------------------------------
# The link allowlist, which every reader owes its own reader.


def test_a_scheme_that_is_allowed_comes_back_escaped():
    assert href_of("https://example.com/?a=1&b=2") == (
        "https://example.com/?a=1&amp;b=2"
    )


@pytest.mark.parametrize(
    "target",
    ["javascript:alert(1)", "java\tscript:alert(1)", "//example.com/x", "/x", "x"],
)
def test_a_target_a_program_must_not_choose_is_refused(target):
    assert href_of(target) == ""


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


def test_every_rule_is_written_under_the_one_class():
    "A caller that builds the element writes `SCREEN_CLASS` and not a copy."
    assert ".%s {" % SCREEN_CLASS in CSS
    assert ".%s a {" % SCREEN_CLASS in CSS


# ----------------------------------------------------------------------
# One screen's own colours.


def test_a_theme_rule_answers_the_same_properties_the_stylesheet_does():
    """
    It goes after `CSS` and wins, so anything it leaves out keeps the
    conventional colour and anything it names has to match.
    """
    rule = theme_css(_screen(3, 10, "").colors)

    for index in range(THEMED):
        assert "--pyte-%d:" % index in rule
    assert "--pyte-fg:" in rule
    assert "--pyte-bg:" in rule
    assert rule.startswith(".%s {" % SCREEN_CLASS)


def test_a_theme_rule_carries_what_a_program_set():
    'A program that sets colour one with "OSC 4" reaches the browser.'
    screen = _screen(3, 10, "\x1b]4;1;rgb:12/34/56\x1b\\")

    assert "--pyte-1: #123456;" in theme_css(screen.colors)


def test_a_theme_rule_carries_the_two_a_program_names_by_name():
    'The foreground and the background, which "OSC 10" and "OSC 11" set.'
    screen = _screen(3, 10, "\x1b]10;#ff0000\x1b\\\x1b]11;#0000ff\x1b\\")
    rule = theme_css(screen.colors)

    assert "--pyte-fg: #ff0000;" in rule
    assert "--pyte-bg: #0000ff;" in rule


def test_a_theme_rule_on_a_fresh_screen_says_what_the_stylesheet_says():
    "So a caller may always send it, and a screen nobody changed draws the same."
    rule = theme_css(_screen(3, 10, "").colors)

    for index in range(THEMED):
        assert "--pyte-%d: %s;" % (index, PALETTE[index].hex) in rule
