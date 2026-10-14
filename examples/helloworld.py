"""
helloworld
~~~~~~~~~~

A minimal working example for :mod:`pyte`.

:copyright: (c) 2011-2013 by Selectel, see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

from __future__ import annotations

import pyte


def rows(screen: pyte.Screen) -> list[str]:
    """The visible page, one string per row."""
    lines = []
    for idx in range(screen.lines):
        line = screen.page.data_buffer.get(screen.line_offset + idx, {})
        text = "".join(line[x].char if x in line else " " for x in range(screen.columns))
        lines.append(text.rstrip())
    return lines


if __name__ == "__main__":
    screen = pyte.Screen(24, 80, write_process_input=lambda data: None)
    stream = pyte.Stream(screen)
    stream.feed("Hello World!")

    for idx, line in enumerate(rows(screen), 1):
        print(f"{idx:2d} {line} ¶")
