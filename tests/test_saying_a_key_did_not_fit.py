"""
A key a person pressed that the pane reads as something else.

**It still degrades**, and it has to: a legacy pane has no form for
super, so super+a really does deliver a plain "a", and that is what
every terminal does. Erroring on a keystroke would be worse than the
silence it replaces.

What was missing is that nothing found out. `translate_key_data` takes
a `report` now, and the caller decides whether to say anything.
Lillecarl/pymux#238.
"""

import pytest

from pyte.keys import (
    FIRST_FUNCTIONAL_KEY,
    KeyboardFlag,
    KeyEvent,
    Modifier,
    translate_key_data,
)

KITTY = KeyboardFlag.DISAMBIGUATE


def said_about(data: str, flags: int = 0, **kw) -> list:
    "What the reporter was told, for this data on this pane."
    told = []
    translate_key_data(data, flags=flags, report=lambda *args: told.append(args), **kw)
    return told


@pytest.mark.parametrize(
    "data,lost",
    [
        # super+a, from a terminal that speaks the protocol.
        ("\x1b[97;9u", Modifier.SUPER),
        ("\x1b[97;6u", Modifier.SHIFT),
    ],
)
def test_a_key_the_pane_reads_as_another_is_reported(data, lost):
    (told,) = said_about(data)
    event, reported, encoded = told

    assert reported == lost
    assert encoded


def test_a_key_with_no_form_at_all_is_reported_with_nothing():
    told = said_about("\x1b[%du" % (FIRST_FUNCTIONAL_KEY + 20,))

    (event, lost, encoded) = told[0]
    assert lost == 0
    assert encoded == ""


@pytest.mark.parametrize(
    "data",
    [
        "a",
        "\x01",
        "\x1b[2;6~",
        "\x1b[15;5~",
        "\x1b[A",
    ],
)
def test_a_key_that_fits_says_nothing(data):
    assert said_about(data) == []


def test_a_pane_that_asked_for_more_is_told_nothing():
    "Nothing about the key changed. The pane did."
    assert len(said_about("\x1b[97;9u")) == 1
    assert said_about("\x1b[97;9u", flags=KITTY) == []


def test_a_release_is_never_reported():
    """
    A pane that did not ask for the event types is meant not to read a
    release, and every press sends one. Reporting those would be a line
    per keystroke.
    """
    press = "\x1b[97;9:1u"
    release = "\x1b[97;9:3u"

    assert len(said_about(press)) == 1
    assert said_about(release) == []


def test_nothing_is_worked_out_when_nobody_is_asking():
    "The report costs nothing on the key path until it is wanted."
    assert translate_key_data("\x1b[97;9u", flags=0) == "a"


def test_what_it_reports_is_the_key_that_was_pressed():
    (told,) = said_about("\x1b[97;9u")
    event, lost, encoded = told

    assert isinstance(event, KeyEvent)
    assert event.code == ord("a")
    assert event.mods == Modifier.SUPER
    assert encoded == "a"
