"""
history
~~~~~~~

A tiny example showing scrollback: rows the page scrolled past stay
in the buffer above the visible page, up to the history limit.

:copyright: (c) 2011-2013 by Selectel, see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

from __future__ import annotations

import os
import random
import string

import pyte
from pyte.modes import AnsiMode


def rows(screen: pyte.Screen) -> list[str]:
    """The visible page, one string per row."""
    lines = []
    for idx in range(screen.lines):
        line = screen.page.data_buffer.get(screen.line_offset + idx, {})
        text = "".join(line[x].char if x in line else " " for x in range(screen.columns))
        lines.append(text.rstrip())
    return lines


def print_screen(screen: pyte.Screen, text: str) -> None:
    print(pyte.control.ESC + pyte.escape.RIS)

    for idx, line in enumerate(rows(screen), 1):
        print(f"{idx:2d} {line} ¶")

    input(os.linesep + os.linesep + text)


def random_string(n: int, alphabet: str = string.ascii_letters + " ") -> str:
    return "".join(random.choice(alphabet) for _ in range(n))


if __name__ == "__main__":
    screen = pyte.Screen(12, 80, write_process_input=lambda data: None)
    screen.set_mode(AnsiMode.LINE_FEED_NEW_LINE)
    stream = pyte.Stream(screen)

    pages = 3
    stream.feed(os.linesep.join(random_string(screen.columns) for _ in range(screen.lines * pages)))

    held = len(screen.page.data_buffer)
    first, last = screen.line_offset + 1, screen.line_offset + screen.lines
    print(f"{held} rows held, the page shows rows {first}..{last}.")
    print_screen(screen, "The two pages above this one are still in the buffer!")
