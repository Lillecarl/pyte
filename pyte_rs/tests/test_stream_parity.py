"""
`pyte_rs.take_ground` reads what the parser would read, and no more.

Two streams take the same text in the same chunks: one through the
Python ground step and one through Rust, each driving a screen that
records every call it gets. The two records have to be the same call
for call, with the same arguments, and so do the exceptions a feed
raised and what each stream holds open at the end. Lillecarl/pymux#570.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte.streams
import pyte_rs
from pyte.streams import Stream

#: The reference, taken before any test could have installed the kernel.
PURE = pyte.streams._take_ground


class Recorder:
    "A screen that has every handler, and writes down every call."

    def __init__(self) -> None:
        self.calls: list = []

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)

        def record(*args, **kwargs):
            self.calls.append((name, args, tuple(sorted(kwargs.items()))))

        return record


PIECES = [
    "text",
    "漢",
    " ",
    "\r",
    "\n",
    "\r\n",
    "\t",
    "\x07",
    "\x08",
    "\x0b",
    "\x0c",
    "\x0e",
    "\x0f",
    "\x00",
    "\x7f",
    "\x1b",
    "[",
    "\x1b[",
    "0",
    "1",
    "38",
    "99999999999999999999999",
    ";",
    ":",
    "?",
    "<",
    "=",
    ">",
    " ",
    "$",
    '"',
    "!",
    "m",
    "H",
    "J",
    "K",
    "q",
    "p",
    "A",
    "@",
    "~",
    "(",
    ")",
    "*",
    "+",
    "B",
    "%",
    "]",
    "\\",
    "#",
    "7",
    "8",
    "c",
    "P",
    "_",
    "\x9b",
    "\x9d",
    "\x84",
    "\x18",
    "\x1a",
    "٣",
    "²",
    "\udcff",
    "\x1b[1;31m",
    "\x1b[0m",
    "\x1b[?1049h",
    "\x1b[38:5:99m",
    "\x1b[>4;1m",
    "\x1b[2 q",
    "\x1b(B",
    "\x1b(0",
    "\x1b]0;title\x07",
]

chunked = st.lists(st.lists(st.sampled_from(PIECES), max_size=12), min_size=1, max_size=6)


def run(take, chunks):
    screen = Recorder()
    stream = Stream(screen)
    saved = pyte.streams._take_ground
    pyte.streams._take_ground = take
    try:
        for chunk in chunks:
            try:
                stream.feed("".join(chunk))
            except Exception as error:
                screen.calls.append(("raised", type(error).__name__))
    finally:
        pyte.streams._take_ground = saved
    return screen.calls, stream._taking_plain_text, stream._pending, stream.replay()


@given(chunked)
@settings(max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_same_calls_are_made(chunks):
    assert run(PURE, chunks) == run(pyte_rs.take_ground, chunks)


def test_a_screen_draws_the_same_through_either():
    "The real screen, over what a styled full-screen program writes."
    from pyte.screen import Screen

    text = "".join(
        "\x1b[%d;1H\x1b[1;36m%6d\x1b[0m  line %d \x1b(B\x1b[m\x1b[K\r\n" % (row, row, row) for row in range(1, 40)
    )
    screens = []
    for take in (PURE, pyte_rs.take_ground):
        saved = pyte.streams._take_ground
        pyte.streams._take_ground = take
        try:
            screen = Screen(20, 40, write_process_input=lambda _: None)
            Stream(screen).feed(text)
        finally:
            pyte.streams._take_ground = saved
        screens.append(screen)
    pure, fast = screens
    assert [sorted(pure.page.data_buffer[y].items()) for y in range(60)] == [
        sorted(fast.page.data_buffer[y].items()) for y in range(60)
    ]
    assert (pure.pt_cursor_position.x, pure.pt_cursor_position.y) == (
        fast.pt_cursor_position.x,
        fast.pt_cursor_position.y,
    )
