"""Tests for CSI private markers and sub-parameters.

The kitty keyboard protocol (and some xterm extensions) use CSI
sequences with ``>``, ``<`` or ``=`` markers and ``:`` sub-parameters.
"""
import pyte


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
    assert feed("\x1b[>1u") == [("debug", (1,), {"private": ">"})]


def test_kitty_push_without_flags():
    assert feed("\x1b[>u") == [("debug", (0,), {"private": ">"})]


def test_kitty_pop():
    assert feed("\x1b[<u") == [("debug", (0,), {"private": "<"})]
    assert feed("\x1b[<2u") == [("debug", (2,), {"private": "<"})]


def test_kitty_set_flags():
    assert feed("\x1b[=1;1u") == [("debug", (1, 1), {"private": "="})]
    assert feed("\x1b[=1;2u") == [("debug", (1, 2), {"private": "="})]


def test_kitty_query():
    assert feed("\x1b[?u") == [("debug", (0,), {"private": True})]


def test_subparameters():
    # Alternate key codes.
    assert feed("\x1b[97:65;2u") == [("debug", ((97, 65), 2), {})]
    # Event types.
    assert feed("\x1b[97;1:3u") == [("debug", (97, (1, 3)), {})]


def test_large_parameters():
    # Functional key codes of the kitty keyboard protocol are above 9999.
    assert feed("\x1b[57443u") == [("debug", (57443,), {})]


def test_private_device_status_report():
    # "CSI ? 6 n" must not crash the parser.
    assert feed("\x1b[?6n") == [
        ("report_device_status", (6,), {"private": True})]


def test_secondary_da_marker_is_dispatched():
    # "CSI > c" (Secondary DA) dispatches like "CSI c", with the marker
    # passed through as ``private``.
    assert feed("\x1b[>c") == [
        ("report_device_attributes", (0,), {"private": ">"})]


# ----------------------------------------------------------------------
# Intermediate bytes.


def test_a_plain_final_byte_keeps_its_handler():
    assert feed("\x1b[3D") == [("cursor_back", (3,), {})]


def test_an_intermediate_byte_names_another_sequence():
    # "CSI Ps SP D" is kitty's unscroll, not CUB. The intermediate byte
    # used to be dropped, so the two ran the same handler.
    assert feed("\x1b[3 D") == [("debug", (3,), {})]


def test_the_cursor_style_sequence_is_not_a_plain_one():
    # "CSI Ps SP q" is DECSCUSR.
    assert feed("\x1b[2 q") == [("debug", (2,), {})]


def test_a_custom_map_can_take_an_intermediate_sequence():
    class UnscrollStream(pyte.Stream):
        csi = dict(pyte.Stream.csi, **{" D": "unscroll"})

    screen = Recorder()
    UnscrollStream(screen).feed("\x1b[4 D")
    assert screen.events == [("unscroll", (4,), {})]


def test_an_intermediate_byte_keeps_the_private_marker():
    assert feed("\x1b[?3 D") == [("debug", (3,), {"private": True})]
