"""
DA and DA2: what the terminal can do, and what it is.

They are two questions, not one, and they take differently shaped
answers. A program tells them apart by the prefix of the reply.
"""

import pytest

from pyte.parameters import ConformanceLevel
from pyte.screen import Screen
from pyte.terminfo import (
    DEVICE_EXTENSIONS,
    XTERM_PATCH_LEVEL,
    XTERM_TYPE,
    DeviceExtension,
)
from pyte.streams import Stream
from pyte import escape
from pyte.sequences import csi
from pyte.sequences import Escape, esc


@pytest.fixture
def pane():
    responses = []
    screen = Screen(24, 80, write_process_input=responses.append)
    return screen, Stream(screen), responses


# ----------------------------------------------------------------------
# The two questions.


@pytest.mark.parametrize("sequence", [csi(escape.DA), csi(escape.DA, 0)])
def test_da_answers_the_level_and_the_extensions(pane, sequence):
    _screen, stream, responses = pane
    stream.feed(sequence)
    assert responses == [
        "\x1b[?%i;%sc"
        % (
            ConformanceLevel.VT500,
            ";".join(str(one) for one in DEVICE_EXTENSIONS),
        )
    ]


@pytest.mark.parametrize(
    "sequence", [csi(escape.DA, private=">"), csi(escape.DA, 0, private=">")]
)
def test_da2_answers_the_type_and_the_firmware(pane, sequence):
    _screen, stream, responses = pane
    stream.feed(sequence)
    assert responses == ["\x1b[>%i;%i;0c" % (XTERM_TYPE, XTERM_PATCH_LEVEL)]


def test_the_two_answers_carry_different_prefixes(pane):
    # A program reads the prefix to tell one answer from the other. A
    # DA that answers in the DA2 shape is read as a DA2 reply, and
    # every answer after it lands one place out of step.
    _screen, stream, responses = pane
    stream.feed(csi(escape.DA) + csi(escape.DA, private=">"))
    assert responses[0].startswith("\x1b[?")
    assert responses[1].startswith("\x1b[>")


def test_da_names_nothing_that_a_pane_cannot_do(pane):
    # A capability that is claimed and not served is worse than one
    # that is missing: the program stops asking and draws what the
    # pane cannot draw.
    for absent in (
        DeviceExtension.PRINTER,
        DeviceExtension.NATIONAL_CHARSETS,
        DeviceExtension.TECHNICAL_CHARACTERS,
        DeviceExtension.LOCATOR_PORT,
        DeviceExtension.USER_WINDOWS,
        DeviceExtension.ANSI_TEXT_LOCATOR,
    ):
        assert absent not in DEVICE_EXTENSIONS


def test_the_charset_claims_follow_the_charsets_that_exist():
    """
    The rule above, tied to the code rather than to a list.

    A pane may name 9 and 15 exactly when `define_charset` does
    something for a national set and for the technical one. It does
    not: `MAPS` holds `B`, `0`, `U` and `V`, and every other code is
    dropped without a word. vttest read the answer back and found the
    claim. Lillecarl/pymux#112.

    Implementing the sets is Lillecarl/pymux#111. This test is what
    puts the numbers back with the code, and what fails if either
    moves without the other.
    """
    from pyte import charsets

    #: What `ESC ( A` and `ESC ( >` select, which are the national and
    #: the technical sets. xterm has more national codes than this;
    #: one is enough to say whether any of them work.
    A_NATIONAL_SET = "A"
    THE_TECHNICAL_SET = ">"

    has_national = A_NATIONAL_SET in charsets.MAPS
    has_technical = THE_TECHNICAL_SET in charsets.MAPS

    assert has_national == (DeviceExtension.NATIONAL_CHARSETS in DEVICE_EXTENSIONS)
    assert has_technical == (DeviceExtension.TECHNICAL_CHARACTERS in DEVICE_EXTENSIONS)


def test_selecting_a_set_that_is_not_named_changes_nothing(pane):
    "The other side of it: what a program gets if it tries anyway."
    screen, stream, _responses = pane

    was = screen.g0_charset
    stream.feed("\x1b(A")

    assert screen.g0_charset is was


def test_a_da_with_a_parameter_that_is_not_zero_is_ignored(pane):
    _screen, stream, responses = pane
    stream.feed(csi(escape.DA, 1))
    assert responses == []


def test_decid_answers_the_way_da_answers(pane):
    """
    DECID ("ESC Z") is the older way to ask what DA asks.

    A VT100 had it and xterm keeps it, so a program written for one
    still gets an answer. esctest2 asks for it in
    `DECIDTests.test_DECID_Basic`.
    """
    _screen, stream, responses = pane
    stream.feed(esc(Escape.DECID))
    first = responses[:]
    responses.clear()
    stream.feed(csi(escape.DA))
    assert first == responses
    assert first[0].startswith("\x1b[?")
