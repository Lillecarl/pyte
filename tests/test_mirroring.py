"""
A screen mirrored from a seed and its reads stays the screen it mirrors.

A pymux server shows a pane of another server by holding a copy of its
screen: a freeze to start from, then every read the pane takes, with
the ground timer's decision beside each. While nobody watches, the
reads stop, and a later freeze of the same `Freezer`, counted from the
pause, brings the copy up to date. Lillecarl/pymux#759.

The copy has to equal the original after anything a program writes,
cut anywhere, through resizes, pauses and resumes. That is the
convergence oracle of Lillecarl/pymux#386, for one pane.
"""

from __future__ import annotations

import json
import random

import pytest
from a_screen import a_screen
from test_freeze import AFTER, BEFORE, STEPS, _cells, _same

from pyte.freeze import Freezer, Frozen, Thawer, freeze, thaw
from pyte.streams import Stream

SIZE = (40, 12)
HISTORY = 50


def _wire(frozen: Frozen) -> Frozen:
    "A freeze as the far side reads it, after JSON."
    return Frozen(*json.loads(json.dumps(frozen)))


class Mirror:
    "The far side: a screen that only ever takes what the wire carries."

    def __init__(self, seed: Frozen, parser: Frozen) -> None:
        self.screen = a_screen(*SIZE, history=HISTORY)
        self.stream = Stream(self.screen)
        self.thawer = Thawer()
        self.catch_up(seed, parser)

    def read(self, data: str, expired: bool) -> None:
        if expired:
            self.stream.ground_timer_expired()
        self.stream.feed(data)

    def catch_up(self, delta: Frozen, parser: Frozen) -> None:
        self.thawer.thaw(_wire(delta), self.screen)
        thaw(_wire(parser), self.stream)


def _pieces(program: str, choose: random.Random) -> list[str]:
    "The program cut at random places, inside sequences too."
    pieces, start = [], 0
    while start < len(program):
        end = start + choose.randint(1, 40)
        pieces.append(program[start:end])
        start = end
    return pieces


@pytest.mark.parametrize("seed", range(60))
def test_the_mirror_equals_the_screen_through_pauses_and_resizes(seed):
    choose = random.Random(seed)
    screen = a_screen(*SIZE, history=HISTORY)
    stream = Stream(screen)
    stream.feed("".join(choose.choice(STEPS[:-1]) for _ in range(10)))

    freezer = Freezer()
    mirror = Mirror(freezer.freeze(screen), freeze(stream))
    paused = False

    program = BEFORE + "".join(choose.choice([*STEPS[:-1], AFTER]) for _ in range(30))
    for number, piece in enumerate(_pieces(program, choose)):
        roll = choose.random()
        if roll < 0.05:
            lines, columns = choose.randint(5, 30), choose.randint(20, 100)
            screen.resize(lines, columns)
            if not paused:
                mirror.screen.resize(lines, columns)
        elif roll < 0.10 and not paused:
            freezer.caught_up(screen)
            paused = True
        elif roll < 0.15 and paused:
            mirror.catch_up(freezer.freeze(screen), freeze(stream))
            paused = False

        expired = stream.ground_timer_active and choose.random() < 0.2
        if expired:
            stream.ground_timer_expired()
        stream.feed(piece)
        if not paused:
            mirror.read(piece, expired)
            assert _cells(mirror.screen) == _cells(screen), "piece %d (%r)" % (number, piece)

    if paused:
        mirror.catch_up(freezer.freeze(screen), freeze(stream))
    assert _cells(mirror.screen) == _cells(screen)
    _same(freeze(mirror.screen), freeze(screen))
    _same(freeze(mirror.stream), freeze(stream))


def test_a_row_written_and_erased_during_a_pause_leaves_the_mirror():
    """
    The trap `caught_up` exists for. The mirror took the row live; the
    pause erased it; a delta counted from the seed would not name it.
    """
    screen = a_screen(*SIZE, history=HISTORY)
    stream = Stream(screen)
    freezer = Freezer()
    mirror = Mirror(freezer.freeze(screen), freeze(stream))

    for piece in ["a row\r\n" * 3]:
        stream.feed(piece)
        mirror.read(piece, False)
    freezer.caught_up(screen)
    stream.feed("\x1b[3J\x1b[2J\x1b[H")
    mirror.catch_up(freezer.freeze(screen), freeze(stream))
    assert _cells(mirror.screen) == _cells(screen)


def test_a_resume_patches_the_mirror_and_sends_only_what_changed():
    screen = a_screen(80, 24, history=10_000)
    stream = Stream(screen)
    stream.feed("".join("row %d\r\n" % number for number in range(5_000)))
    freezer = Freezer()
    mirror_screen = a_screen(80, 24, history=10_000)
    thawer = Thawer()
    thawer.thaw(_wire(freezer.freeze(screen)), mirror_screen)
    buffer = mirror_screen.page.data_buffer

    freezer.caught_up(screen)
    stream.feed("one more\r\n")
    delta = freezer.freeze(screen)
    assert sum(len(rows) for rows in delta.buffers.values()) <= 3
    thawer.thaw(_wire(delta), mirror_screen)
    assert mirror_screen.page.data_buffer is buffer
    assert _cells(mirror_screen) == _cells(screen)
