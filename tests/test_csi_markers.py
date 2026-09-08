"""Tests for CSI private markers and sub-parameters.

The kitty keyboard protocol (and some xterm extensions) use CSI
sequences with ``>``, ``<`` or ``=`` markers and ``:`` sub-parameters.
"""

import pyte
from pyte import escape
from pyte.sequences import Csi, csi


class Recorder:
    """Screen stub that records every dispatched event."""

    def __init__(self):
        self.events = []

    def draw(self, data):
        self.events.append(("draw", data))

    def debug(self, *args, **kwargs):
        self.events.append(("debug", args, kwargs))

    def __getattr__(self, name):
        def handler(*args, **kwargs):
            self.events.append((name, args, kwargs))

        return handler


def feed(sequence):
    screen = Recorder()
    pyte.Stream(screen).feed(sequence)
    return screen.events


def test_kitty_push():
    assert feed(csi(Csi.KITTY_KEYBOARD, 1, private=">")) == [
        ("report_kitty_keyboard", (1,), {"private": ">"})
    ]


def test_kitty_push_without_flags():
    assert feed(csi(Csi.KITTY_KEYBOARD, private=">")) == [
        ("report_kitty_keyboard", (0,), {"private": ">"})
    ]


def test_kitty_pop():
    assert feed(csi(Csi.KITTY_KEYBOARD, private="<")) == [
        ("report_kitty_keyboard", (0,), {"private": "<"})
    ]
    assert feed(csi(Csi.KITTY_KEYBOARD, 2, private="<")) == [
        ("report_kitty_keyboard", (2,), {"private": "<"})
    ]


def test_kitty_set_flags():
    assert feed(csi(Csi.KITTY_KEYBOARD, 1, 1, private="=")) == [
        ("report_kitty_keyboard", (1, 1), {"private": "="})
    ]
    assert feed(csi(Csi.KITTY_KEYBOARD, 1, 2, private="=")) == [
        ("report_kitty_keyboard", (1, 2), {"private": "="})
    ]


def test_kitty_query():
    assert feed(csi(Csi.KITTY_KEYBOARD, private="?")) == [
        ("report_kitty_keyboard", (0,), {"private": True})
    ]


def test_subparameters():
    # Alternate key codes.
    assert feed("\x1b[97:65;2u") == [("report_kitty_keyboard", ((97, 65), 2), {})]
    # Event types.
    assert feed("\x1b[97;1:3u") == [("report_kitty_keyboard", (97, (1, 3)), {})]


def test_large_parameters():
    # Functional key codes of the kitty keyboard protocol are above 9999.
    assert feed(csi(Csi.KITTY_KEYBOARD, 57443)) == [
        ("report_kitty_keyboard", (57443,), {})
    ]


def test_private_device_status_report():
    # "CSI ? 6 n" must not crash the parser.
    assert feed(csi(escape.DSR, 6, private="?")) == [
        ("report_device_status", (6,), {"private": True})
    ]


def test_secondary_da_marker_is_dispatched():
    # "CSI > c" (Secondary DA) dispatches like "CSI c", with the marker
    # passed through as ``private``.
    assert feed(csi(escape.DA, private=">")) == [
        ("report_device_attributes", (0,), {"private": ">"})
    ]


# ----------------------------------------------------------------------
# Intermediate bytes.


def test_a_plain_final_byte_keeps_its_handler():
    assert feed(csi(escape.CUB, 3)) == [("cursor_back", (3,), {})]


def test_an_intermediate_byte_names_another_sequence():
    # "CSI Ps SP D" is kitty's unscroll, not CUB. The intermediate byte
    # used to be dropped, so the two ran the same handler.
    assert feed(csi(Csi.KITTY_UNSCROLL, 3)) == [("unscroll", (3,), {})]


def test_the_cursor_style_sequence_is_not_a_plain_one():
    # "CSI Ps SP q" is DECSCUSR.
    assert feed(csi(Csi.DECSCUSR, 2)) == [("set_cursor_style", (2,), {})]


def test_a_custom_map_can_take_an_intermediate_sequence():
    class UnscrollStream(pyte.Stream):
        csi = dict(pyte.Stream.csi, **{" D": "unscroll"})

    screen = Recorder()
    UnscrollStream(screen).feed(csi(Csi.KITTY_UNSCROLL, 4))
    assert screen.events == [("unscroll", (4,), {})]


def test_an_intermediate_byte_keeps_the_private_marker():
    assert feed(csi(Csi.KITTY_UNSCROLL, 3, private="?")) == [
        ("unscroll", (3,), {"private": True})
    ]
