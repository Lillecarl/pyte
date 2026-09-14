"""
The national replacement sets, and the DEC technical set.

A national set is ASCII with a handful of positions replaced by the
letters one country needs. That is what a seven bit terminal did
instead of having an eighth bit, and a program that selects one and
gets ASCII draws the wrong glyph with nothing to say it has.
Lillecarl/pymux#111.

The tables themselves are checked against xterm's `charsets.h`, which
is where they come from. What is checked here is that a name reaches a
table and that the table reaches the screen.
"""

import pytest

from pyte import charsets as cs
from pyte.screen import Screen
from pyte.streams import Stream


def _drawn(sequence, columns=20):
    "The first row of a screen the sequence was fed to."
    screen = Screen(2, columns, write_process_input=lambda data: None)
    Stream(screen).feed(sequence)
    line = screen.page.data_buffer.get(screen.line_offset)
    if line is None:
        return ""
    return "".join(
        (line[column].char or " ") for column in range(columns)
    ).rstrip()


def test_the_british_set_draws_a_pound_sign():
    "The one position that made a VT100 British."
    assert _drawn("\x1b(A#") == "£"


def test_the_ascii_set_comes_back():
    assert _drawn("\x1b(A#\x1b(B#") == "£#"


def test_a_national_set_applies_with_no_mode_asked_for():
    """
    **Five judges against one.**

    kitty, WezTerm, libvterm, Ghostty and xterm.js all draw the pound
    sign here. xterm alone waits for DECNRCM, and Alacritty has no
    national sets at all. `ptterm/tests/DEVIATIONS.md` holds the vote.

    "CSI ? 42 l" turns the mode off, so this asks with it off and not
    merely unasked for.
    """
    assert _drawn("\x1b[?42l\x1b(A#") == "£"


def test_the_german_set_moves_eight_positions():
    assert _drawn("\x1b(K@[\\]{|}~") == "§ÄÖÜäöüß"


def test_the_portuguese_set_needs_two_bytes_to_name():
    """
    `ESC ( % 6`. The parser read one byte after the "(" until
    Lillecarl/pymux#111, so "%" named nothing and "6" was drawn.
    """
    assert _drawn("\x1b(%6[\\]") == "ÃÇÕ"


def test_the_byte_after_a_two_byte_name_is_not_drawn():
    assert _drawn("\x1b(%6ABC") == "ABC"


def test_the_technical_set_draws_mathematics():
    assert _drawn("\x1b(>ABC") == "∝∞÷"


def test_the_technical_set_leaves_a_sigma_piece_alone():
    """
    0x31 to 0x37 are the seven pieces of a large sigma, and Unicode
    has no character for one. xterm draws them out of its own private
    area, which a screen of characters cannot do.
    """
    assert _drawn("\x1b(>1234567") == "1234567"


def test_g1_takes_a_national_set_too():
    assert _drawn("\x1b)A\x0e#\x0f#") == "£#"


@pytest.mark.parametrize("alias, name", sorted(cs.NATIONAL_ALIASES.items()))
def test_every_alias_names_the_same_table(alias, name):
    "DEC gave several of these two or three names over the models."
    assert cs.MAPS[alias] is cs.MAPS[name]


@pytest.mark.parametrize("name", sorted(cs.NATIONAL))
def test_a_national_set_only_moves_what_it_names(name):
    "Everything else is ASCII, which is what makes it a replacement."
    table = cs.MAPS[name]
    moved = {
        position
        for position in range(0x20, 0x7F)
        if table[position] != chr(position)
    }
    assert moved == set(cs.NATIONAL[name])


def test_an_unknown_name_leaves_the_set_alone():
    assert _drawn("\x1b(0lqk\x1b(!lqk") == "┌─┐┌─┐"
