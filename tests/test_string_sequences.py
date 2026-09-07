"""Tests for APC, DCS, SOS and PM string sequences."""
import pyte
from pyte.screen import Screen

from a_screen import a_screen, display


def display_for(data, columns=20, lines=5):
    screen = a_screen(columns, lines)
    pyte.ByteStream(screen).feed(data)
    return "\n".join(display(screen))


def test_apc_is_not_drawn():
    # Kitty graphics protocol style APC: must not corrupt the text.
    out = display_for(b"before\x1b_Gf=32,s=10,v=10;AAAA\x1b\\after")
    assert "beforeafter" in out
    assert "AAAA" not in out
    assert "f=32" not in out


def test_dcs_is_not_drawn():
    # Sixel style DCS: the payload must never reach the cells as text.
    #
    # "before" and "after" are on two rows and not one, because this
    # screen really draws a sixel: the image takes the cells it covers
    # and leaves the cursor on the row below. Upstream's screen threw
    # the sequence away, so the two ran together there.
    out = display_for(b"before\x1bP0;1;0q#0;2;0;0;0#0~~;;~~\x1b\\after")
    assert "before" in out
    assert "after" in out
    assert "0;1;0q" not in out
    assert "#0;2;0;0;0" not in out


def test_sos_and_pm_are_not_drawn():
    out = display_for(b"a\x1bXsos-data\x1b\\b\x1b^pm-data\x1b\\c")
    assert out.splitlines()[0].rstrip() == "abc"


def test_apc_is_dispatched():
    class Recorder(Screen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.sequences = []

        def apc(self, data):
            self.sequences.append(("apc", data))

        def dcs(self, data):
            self.sequences.append(("dcs", data))

    screen = a_screen(20, 5, Recorder)
    pyte.ByteStream(screen).feed(b"\x1b_Ghello\x1b\\\x1bP1;2qworld\x1b\\")
    # The first payload byte is part of the data: for the kitty
    # graphics protocol it is the 'G' that starts the grammar.
    assert screen.sequences == [("apc", "Ghello"), ("dcs", "1;2qworld")]


def test_fragmented_across_feeds():
    class Recorder(Screen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.chunks = []

        def apc(self, data):
            self.chunks.append(data)

    screen = a_screen(20, 5, Recorder)
    stream = pyte.ByteStream(screen)
    for part in (b"ab\x1b", b"_Gpay", b"load\x1b", b"\\cd"):
        stream.feed(part)
    assert screen.chunks == ["Gpayload"]
    assert "abcd" in "\n".join(display(screen))


def test_can_aborts_without_dispatch():
    received = []

    class Recorder(Screen):
        def apc(self, data):
            received.append(data)

    screen = a_screen(20, 5, Recorder)
    pyte.ByteStream(screen).feed(b"\x1b_Gab\x18cd\x1b\\ef")
    assert received == []
    assert "cdef" in "\n".join(display(screen))


def test_esc_inside_payload_does_not_terminate():
    received = []

    class Recorder(Screen):
        def apc(self, data):
            received.append(data)

    screen = a_screen(20, 5, Recorder)
    pyte.ByteStream(screen).feed(b"\x1b_Gab\x1bXcd\x1b\\after")
    assert received == ["Gab\x1bXcd"]
    assert "after" in "\n".join(display(screen))


def test_osc_still_works():
    screen = a_screen(20, 5)
    pyte.ByteStream(screen).feed(b"\x1b]2;my title\x07rest")
    assert screen.titles.window == "my title"
    assert "rest" in "\n".join(display(screen))


def test_legacy_sequences_untouched():
    out = display_for(b"\x1b[1;31mred\x1b[0m plain")
    assert "red plain" in out


def test_escape_map_takes_precedence():
    # A custom escape mapping for "P" (like the history screen's page
    # keys) must keep working: the string-sequence handling only
    # applies to finals that the escape table does not claim.
    received = []

    class Recorder(Screen):
        def prev_page(self):
            received.append("prev")

    screen = a_screen(20, 5, Recorder)
    stream = pyte.Stream(screen)
    # A copy, and not the table itself. `escape` is an attribute of the
    # class, so writing into it reaches every stream that any later test
    # builds, and each of those attaches a screen that has no
    # `prev_page`. One test then breaks every test that runs after it.
    stream.escape = dict(stream.escape)
    stream.escape["P"] = "prev_page"
    # The parser snapshots the escape table at construction time; force
    # a new parser.
    stream.attach(screen)
    stream.feed("\x1bP")
    assert received == ["prev"]
