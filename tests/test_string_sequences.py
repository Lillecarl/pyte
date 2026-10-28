"""Tests for APC, DCS, SOS and PM string sequences."""

from __future__ import annotations

from a_screen import a_screen, display
from hypothesis import given
from hypothesis import strategies as st

import pyte
from pyte.screen import Screen

#: Pieces that open, fill, end and break string sequences and OSCs.
PIECES = [
    "a",
    "Gx",
    ";",
    "7",
    "\\",
    "\x1b",
    "\x1b_",
    "\x1bP",
    "\x1bX",
    "\x1b]",
    "\x1b]2;",
    "\x1b]52;",
    "\x1b\\",
    "\x9c",
    "\x07",
    "\x18",
    "\x1a",
]


class Recording(Screen):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sequences = []

    def apc(self, data):
        self.sequences.append(("apc", data))

    def dcs(self, data):
        self.sequences.append(("dcs", data))

    def osc(self, code, param):
        self.sequences.append(("osc", code, param))

    def set_title(self, param):
        self.sequences.append(("title", param))


def what_a_feed_leaves(parts):
    screen = a_screen(20, 5, Recording)
    stream = pyte.Stream(screen)
    for part in parts:
        stream.feed(part)
    return screen.sequences, display(screen), stream.replay()


@given(st.lists(st.sampled_from(PIECES), max_size=30), st.data())
def test_a_payload_reads_the_same_however_it_is_split(pieces, data):
    """
    A payload is taken in runs, up to the next character that can end
    it. One character per feed is the parser's own pace, so any split
    has to leave what that leaves. Lillecarl/pymux#717.
    """
    text = "".join(pieces)
    cuts = sorted(data.draw(st.sets(st.integers(0, len(text)))))
    parts = [text[start:end] for start, end in zip([0, *cuts], [*cuts, len(text)], strict=True)]
    assert what_a_feed_leaves(parts) == what_a_feed_leaves(list(text))


def display_for(data, columns=20, lines=5):
    screen = a_screen(columns, lines)
    pyte.Stream(screen).feed(data.decode())
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
    pyte.Stream(screen).feed("\x1b_Ghello\x1b\\\x1bP1;2qworld\x1b\\")
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
    stream = pyte.Stream(screen)
    for part in ("ab\x1b", "_Gpay", "load\x1b", "\\cd"):
        stream.feed(part)
    assert screen.chunks == ["Gpayload"]
    assert "abcd" in "\n".join(display(screen))


def test_can_aborts_without_dispatch():
    received = []

    class Recorder(Screen):
        def apc(self, data):
            received.append(data)

    screen = a_screen(20, 5, Recorder)
    pyte.Stream(screen).feed("\x1b_Gab\x18cd\x1b\\ef")
    assert received == []
    assert "cdef" in "\n".join(display(screen))


def test_esc_inside_payload_does_not_terminate():
    received = []

    class Recorder(Screen):
        def apc(self, data):
            received.append(data)

    screen = a_screen(20, 5, Recorder)
    pyte.Stream(screen).feed("\x1b_Gab\x1bXcd\x1b\\after")
    assert received == ["Gab\x1bXcd"]
    assert "after" in "\n".join(display(screen))


def test_osc_still_works():
    screen = a_screen(20, 5)
    pyte.Stream(screen).feed("\x1b]2;my title\x07rest")
    assert screen.titles.window == "my title"
    assert "rest" in "\n".join(display(screen))


def test_an_osc_past_its_bound_is_dropped_whole(monkeypatch):
    "Nothing of it is held or drawn, and what follows it is read. Lillecarl/pymux#744."
    monkeypatch.setattr(pyte.streams, "MAX_OSC_LENGTH", 8)
    screen = a_screen(20, 5)
    stream = pyte.Stream(screen)
    stream.feed("\x1b]2;far too long a title\x07after")
    assert not screen.titles.window
    assert "after" in "\n".join(display(screen))
    assert "long" not in "\n".join(display(screen))
    stream.feed("\x1b]2;short\x07")
    assert screen.titles.window == "short"


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

    # A subclass, and not a write into the table: `escape` is an
    # attribute of the class, and the parser reads it when it is built.
    class Paging(pyte.Stream):
        escape = dict(pyte.Stream.escape, P="prev_page")

    stream = Paging(a_screen(20, 5, Recorder))
    stream.feed("\x1bP")
    assert received == ["prev"]
