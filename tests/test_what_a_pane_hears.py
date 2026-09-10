"""
What a pane can read, and what it cannot.

**`KeyEvent` is the form a key is in between the two ends**, and the
translation to a pane is the writing half. Writing has to be able to
lose something: a pane in the legacy encoding has no form for super, so
a person pressing super+a really does deliver a plain "a", and that is
what every terminal does. A key that came from a keyboard has to arrive
that way.

A key that came from a name has not. Nobody typing `send-keys super+a`
means "type an a", so that caller asks with `exactly` and is told.
Lillecarl/pymux#237.

`the_modifiers_a_pane_cannot_read` is the accounting behind both, and it
names the rules of `_encode_event` rather than holding a second opinion
about them.
"""

import pytest

from pyte.keys import (
    FIRST_FUNCTIONAL_KEY,
    KeyboardFlag,
    KeyCode,
    KeyEvent,
    Modifier,
    Unhearable,
    parse_key_data,
    the_modifiers_a_pane_cannot_read,
    translate_key_event,
)

#: A key with no legacy form at all. The protocol numbers every key
#: that writes no character from here up, so `chr` of one is a
#: character no keyboard has.
A_MEDIA_KEY = KeyEvent(FIRST_FUNCTIONAL_KEY + 20, 0, "u")

#: What a pane asks for to read more than the legacy encoding.
KITTY = KeyboardFlag.DISAMBIGUATE


def sent(event: KeyEvent, flags: int = 0) -> str:
    "The bytes a pane with these flags is given for this key."
    return translate_key_event(event, flags=flags, exactly=True)


# ----------------------------------------------------------------------
# What the legacy encoding carries whole.


@pytest.mark.parametrize(
    "event",
    [
        KeyEvent(ord("a"), 0, "u"),
        KeyEvent(ord("a"), Modifier.CTRL, "u"),
        KeyEvent(ord("a"), Modifier.SHIFT, "u"),
        KeyEvent(ord("a"), Modifier.ALT, "u"),
        # The four that carry a control code.
        KeyEvent(KeyCode.ENTER, 0, "u"),
        KeyEvent(KeyCode.TAB, 0, "u"),
        KeyEvent(KeyCode.BACKSPACE, 0, "u"),
        KeyEvent(KeyCode.ESCAPE, 0, "u"),
        # ctrl on a letter is a control code, which is a form and not a
        # loss: "\r" is what ctrl+m means.
        KeyEvent(ord("m"), Modifier.CTRL, "u"),
        # The CSI forms write the modifiers into the sequence, so
        # everything the legacy encoding has fits in them.
        KeyEvent(15, 0, "~"),
        KeyEvent(15, Modifier.CTRL, "~"),
        KeyEvent(2, Modifier.CTRL | Modifier.SHIFT, "~"),
        KeyEvent(1, Modifier.SHIFT, "A"),
        KeyEvent(1, Modifier.CTRL | Modifier.SHIFT, "H"),
    ],
)
def test_a_pane_in_the_legacy_encoding_reads_these_whole(event):
    assert the_modifiers_a_pane_cannot_read(event, flags=0) == 0
    assert sent(event)


@pytest.mark.parametrize(
    "event,lost,reason",
    [
        (
            KeyEvent(ord("a"), Modifier.SUPER, "u"),
            Modifier.SUPER,
            "super has no legacy form",
        ),
        (
            KeyEvent(ord("a"), Modifier.HYPER, "u"),
            Modifier.HYPER,
            "hyper has no legacy form",
        ),
        (
            KeyEvent(2, Modifier.META, "~"),
            Modifier.META,
            "not even the CSI forms carry meta",
        ),
        (
            KeyEvent(ord("a"), Modifier.CTRL | Modifier.SHIFT, "u"),
            Modifier.SHIFT,
            "ctrl+a and ctrl+shift+a are one control code",
        ),
        (
            KeyEvent(KeyCode.TAB, Modifier.SHIFT | Modifier.CTRL, "u"),
            Modifier.CTRL,
            "back tab is CSI Z, which carries no ctrl",
        ),
        (
            KeyEvent(ord("1"), Modifier.SHIFT, "u"),
            Modifier.SHIFT,
            "shift is a capital, and there is no capital of 1",
        ),
    ],
)
def test_what_a_pane_in_the_legacy_encoding_loses(event, lost, reason):
    assert the_modifiers_a_pane_cannot_read(event, flags=0) == lost, reason


@pytest.mark.parametrize(
    "event",
    [
        KeyEvent(ord("a"), Modifier.SUPER, "u"),
        KeyEvent(ord("a"), Modifier.CTRL | Modifier.SHIFT, "u"),
        KeyEvent(ord("1"), Modifier.SHIFT, "u"),
        KeyEvent(KeyCode.TAB, Modifier.SHIFT | Modifier.CTRL, "u"),
        A_MEDIA_KEY,
    ],
)
def test_a_pane_that_asked_for_more_loses_none_of_them(event):
    """
    The same keys and the same question, with one flag turned on.

    This is why the question cannot be asked of the key alone. Nothing
    about super+a changes between these two tests.
    """
    assert the_modifiers_a_pane_cannot_read(event, flags=KITTY) == 0
    assert sent(event, flags=KITTY)


# ----------------------------------------------------------------------
# Losing it, and being told.


def test_by_default_a_key_arrives_with_what_fits():
    """
    A key a person really pressed has to reach the pane the way a
    keyboard would have delivered it. Every terminal drops the super
    here, and pymux may not do otherwise on the way in.
    """
    event = KeyEvent(ord("a"), Modifier.SUPER, "u")
    assert translate_key_event(event, flags=0) == "a"


def test_exactly_says_so_instead():
    event = KeyEvent(ord("a"), Modifier.SUPER, "u")

    with pytest.raises(Unhearable) as raised:
        translate_key_event(event, flags=0, exactly=True)

    assert raised.value.lost == Modifier.SUPER
    assert raised.value.encoded == "a"
    assert raised.value.event is event


def test_a_key_with_no_form_at_all_says_that_instead():
    "Nothing was dropped off it. There is nowhere for it to go."
    with pytest.raises(Unhearable) as raised:
        translate_key_event(A_MEDIA_KEY, flags=0, exactly=True)

    assert raised.value.lost == 0
    assert raised.value.encoded == ""


def test_a_release_alongside_the_press_is_not_a_failure():
    "A pane that asked for the event types gets both out of one send."
    event = KeyEvent(ord("a"), 0, "u")
    flags = KITTY | KeyboardFlag.REPORT_EVENT_TYPES

    both = translate_key_event(event, flags=flags, double=True, exactly=True)

    assert both.endswith("3u")
