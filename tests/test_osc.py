"""
Tests for the OSC sequences that a pane sends.

A pane has no palette of its own, but a program that asks for one needs
an answer: without it, it waits forever.
"""

import pytest

from pyte.colors import DEFAULT_COLORS, PALETTE, Color
from pyte.osc import COLOR_BASE, ColorBase, ColorOverrides, parse_kitty_color_query
from pyte.screen import Screen
from pyte.streams import Stream
from pyte.osc import Osc
from pyte.sequences import Terminator, osc

BLACK = "rgb:0000/0000/0000"
WHITE = "rgb:ffff/ffff/ffff"


def make_screen():
    responses = []
    screen = Screen(24, 80, write_process_input=responses.append)
    stream = Stream(screen)
    return screen, stream, responses


# ----------------------------------------------------------------------
# The colour helpers.


def test_a_colour_is_written_with_doubled_components():
    assert Color(0x12, 0x34, 0x56).spec == "rgb:1212/3434/5656"
    assert Color(0, 0, 0).spec == BLACK
    assert Color(255, 255, 255).spec == WHITE


def test_the_palette_has_the_full_256_colours():
    assert len(PALETTE) == 256
    assert PALETTE[0] == (0, 0, 0)
    assert PALETTE[15] == (255, 255, 255)
    assert PALETTE[16] == (0, 0, 0)  # Start of the cube.
    assert PALETTE[231] == (255, 255, 255)  # End of the cube.
    assert PALETTE[232] == (8, 8, 8)  # Start of the grey ramp.
    assert PALETTE[255] == (238, 238, 238)


def test_reading_a_kitty_colour_query():
    assert parse_kitty_color_query("foreground=?;cursor=?") == [
        ("foreground", True),
        ("cursor", True),
    ]
    assert parse_kitty_color_query("foreground=green") == [("foreground", False)]
    assert parse_kitty_color_query("background") == [("background", False)]
    assert parse_kitty_color_query("") is None
    assert parse_kitty_color_query(";;") is None


# ----------------------------------------------------------------------
# The xterm colour queries.


def test_the_background_query():
    # yazi asks this on startup.
    _screen, stream, responses = make_screen()
    stream.feed(osc("11", "?", end=Terminator.BEL))
    assert responses == ["\x1b]11;%s\x1b\\" % BLACK]


def test_the_foreground_query():
    _screen, stream, responses = make_screen()
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses == ["\x1b]10;%s\x1b\\" % WHITE]


def test_the_cursor_colour_query():
    _screen, stream, responses = make_screen()
    stream.feed(osc("12", "?"))
    assert responses == ["\x1b]12;%s\x1b\\" % WHITE]


def test_the_selection_colour_queries():
    _screen, stream, responses = make_screen()
    stream.feed(osc("17", "?", end=Terminator.BEL))
    stream.feed(osc("19", "?", end=Terminator.BEL))
    assert responses == [
        "\x1b]17;%s\x1b\\" % DEFAULT_COLORS["selection_background"].spec,
        "\x1b]19;%s\x1b\\" % DEFAULT_COLORS["selection_foreground"].spec,
    ]


def test_setting_a_colour_answers_nothing_and_holds_it():
    # A set is not a query, so it gets no answer. The pane keeps the
    # colour, and the next query reads it back.
    _screen, stream, responses = make_screen()
    stream.feed(osc("11", "rgb:ff/00/00", end=Terminator.BEL))
    assert responses == []
    stream.feed(osc("11", "?", end=Terminator.BEL))
    assert responses == ["\x1b]11;rgb:ffff/0000/0000\x1b\\"]


# ----------------------------------------------------------------------
# The palette query.


def test_a_palette_query():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "?", end=Terminator.BEL))
    assert responses == ["\x1b]4;1;rgb:cdcd/0000/0000\x1b\\"]


def test_several_palette_entries_at_once():
    # One answer for each question. xterm sends them apart, and a
    # program reads them apart: it reads up to the terminator once for
    # each query it sent. Joining them leaves it reading the second
    # answer as part of the first.
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.PALETTE_COLOR, "0", "?", "15", "?", end=Terminator.BEL))
    assert responses == [
        "\x1b]4;0;%s\x1b\\" % BLACK,
        "\x1b]4;15;%s\x1b\\" % WHITE,
    ]


def test_a_palette_entry_that_does_not_exist():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.PALETTE_COLOR, "999", "?", end=Terminator.BEL))
    assert responses == []


def test_setting_a_palette_entry_is_ignored():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "rgb:00/ff/00", end=Terminator.BEL))
    assert responses == []


# ----------------------------------------------------------------------
# The kitty colour query.


def test_a_kitty_colour_query():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.KITTY_COLORS, "background=?"))
    assert responses == ["\x1b]21;background=%s\x1b\\" % BLACK]


def test_several_kitty_keys_at_once():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.KITTY_COLORS, "foreground=?", "background=?"))
    assert responses == ["\x1b]21;foreground=%s;background=%s\x1b\\" % (WHITE, BLACK)]


def test_a_kitty_query_for_a_palette_entry():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.KITTY_COLORS, "3=?"))
    assert responses == ["\x1b]21;3=rgb:cdcd/cdcd/0000\x1b\\"]


def test_a_kitty_query_for_a_colour_we_do_not_hold():
    # An empty value is how a terminal says "not set".
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.KITTY_COLORS, "visual_bell=?"))
    assert responses == ["\x1b]21;visual_bell=\x1b\\"]


def test_a_kitty_colour_set_is_ignored():
    _screen, stream, responses = make_screen()
    stream.feed(osc(Osc.KITTY_COLORS, "background=green"))
    assert responses == []


# ----------------------------------------------------------------------
# The base an embedder hands in.
#
# The terminal of the user paints the palette that a program asks for
# by number, so the pane's answers describe the theme of that
# terminal, once the embedder has learned it.

_BASE_FG = Color(0xAA, 0x00, 0x00)
_BASE_BG = Color(0x00, 0x00, 0xBB)
_LEARNED = [Color(1 + index, 0x20 + index, 0x30 + index) for index in range(16)]
_BASE_PALETTE = _LEARNED + list(PALETTE[16:])


def make_screen_on_a_base(defaults=None):
    responses = []
    base = ColorBase(
        _BASE_PALETTE,
        defaults if defaults is not None else {"foreground": _BASE_FG, "background": _BASE_BG},
    )
    screen = Screen(24, 80, write_process_input=responses.append, color_base=base)
    stream = Stream(screen)
    return screen, stream, responses


def test_a_base_palette_query():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "?", end=Terminator.BEL))
    assert responses == ["\x1b]4;1;%s\x1b\\" % Color(2, 0x21, 0x31).spec]


def test_a_base_defaults_query():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses == ["\x1b]10;%s\x1b\\" % _BASE_FG.spec]
    stream.feed(osc("11", "?", end=Terminator.BEL))
    assert responses[-1] == "\x1b]11;%s\x1b\\" % _BASE_BG.spec


def test_a_base_kitty_query():
    # kitty joins its answers into one sequence, which is what its own
    # protocol says.
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc(Osc.KITTY_COLORS, "foreground=?", "3=?"))
    assert responses == [
        "\x1b]21;foreground=%s;3=%s\x1b\\" % (_BASE_FG.spec, _BASE_PALETTE[3].spec)
    ]


def test_the_cube_of_a_base_is_convention():
    # An embedder asks for the theme of the terminal of the user, and
    # the sixteen ANSI colours are the only ones that differ between
    # terminals: the cube and the grey ramp are convention, so the
    # base they hand in carries the conventional ones. A query for the
    # cube answers the convention.
    base = ColorBase(_LEARNED + list(PALETTE[16:]), {})
    responses = []
    screen = Screen(24, 80, write_process_input=responses.append, color_base=base)
    stream = Stream(screen)
    stream.feed(osc(Osc.PALETTE_COLOR, "20", "?", end=Terminator.BEL))
    assert responses == ["\x1b]4;20;%s\x1b\\" % PALETTE[20].spec]


def test_a_base_that_is_not_the_whole_palette_is_refused():
    # The indexes of "OSC 4" name a table of 256 on the wire, and the
    # special colours follow it. A short table would answer a cube
    # query with the colour of the text, which is a lie, so it is not
    # a base at all.
    with pytest.raises(ValueError):
        ColorOverrides(ColorBase(_LEARNED, {}))


def test_a_program_set_wins_over_the_base():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc("10", "rgb:00/ff/00", end=Terminator.BEL))
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "rgb:00/ff/00", end=Terminator.BEL))
    stream.feed(osc("10", "?", end=Terminator.BEL))
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "?", end=Terminator.BEL))
    green = "rgb:0000/ffff/0000"
    assert responses[-2:] == [
        "\x1b]10;%s\x1b\\" % green,
        "\x1b]4;1;%s\x1b\\" % green,
    ]


def test_a_reset_of_the_set_colours_lands_on_the_base():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "rgb:00/ff/00", end=Terminator.BEL))
    stream.feed(osc("10", "rgb:00/ff/00", end=Terminator.BEL))
    stream.feed(osc(Osc.RESET_PALETTE_COLOR, end=Terminator.BEL))
    stream.feed(osc("110", end=Terminator.BEL))
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "?", end=Terminator.BEL))
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses[-2:] == [
        "\x1b]4;1;%s\x1b\\" % _BASE_PALETTE[1].spec,
        "\x1b]10;%s\x1b\\" % _BASE_FG.spec,
    ]


def test_a_terminal_reset_keeps_the_base():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc("10", "rgb:00/ff/00", end=Terminator.BEL))
    stream.feed("\x1bc")
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses == ["\x1b]10;%s\x1b\\" % _BASE_FG.spec]


def test_the_base_can_be_swapped_mid_life():
    screen, stream, responses = make_screen_on_a_base()
    later = Color(0x77, 0x88, 0x99)
    screen.set_color_base(
        ColorBase([later] * len(PALETTE), {"foreground": later, "background": later})
    )
    stream.feed(osc(Osc.PALETTE_COLOR, "1", "?", end=Terminator.BEL))
    stream.feed(osc("10", "rgb:00/ff/00", end=Terminator.BEL))
    green = "rgb:0000/ffff/0000"
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses[-1] == "\x1b]10;%s\x1b\\" % green

    # The swap keeps what a program set: an explicit ask is not taken
    # back by a different base. A reset does.
    screen.set_color_base(COLOR_BASE)
    stream.feed(osc("10", "?", end=Terminator.BEL))
    assert responses[-1] == "\x1b]10;%s\x1b\\" % green


def test_a_default_the_base_does_not_name_falls_back():
    screen, stream, responses = make_screen_on_a_base()
    stream.feed(osc("12", "?", end=Terminator.BEL))
    assert responses == ["\x1b]12;%s\x1b\\" % DEFAULT_COLORS["cursor"].spec]


# ----------------------------------------------------------------------
# Everything else.


def test_the_title_still_works():
    screen, stream, responses = make_screen()
    stream.feed(osc("2", "a title", end=Terminator.BEL))
    assert screen.titles.window == "a title"
    assert responses == []


def test_the_icon_name_still_works():
    screen, stream, responses = make_screen()
    stream.feed(osc("1", "an icon", end=Terminator.BEL))
    assert screen.titles.icon == "an icon"


def test_an_unknown_sequence_is_consumed():
    screen, stream, responses = make_screen()
    stream.feed(osc(Osc.CLIPBOARD, "c", "aGVsbG8=", end=Terminator.BEL))
    stream.feed(osc(Osc.NOTIFICATION, "i=1", "body"))
    stream.feed("hello")
    assert responses == []
    row = screen.page.data_buffer[0]
    assert "".join(row[i].char for i in range(5)) == "hello"


def test_a_hyperlink_does_not_reach_the_screen():
    screen, stream, responses = make_screen()
    stream.feed(
        osc(Osc.HYPERLINK, "", "https://example.com")
        + "link"
        + osc(Osc.HYPERLINK, "", "")
    )
    row = screen.page.data_buffer[0]
    assert "".join(row[i].char for i in range(4)) == "link"
