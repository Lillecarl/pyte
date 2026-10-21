"""
nanoterm
~~~~~~~~

An example showing how to feed :class:`~pyte.streams.Stream` from
a running terminal app.

:copyright: (c) 2015 by pyte authors and contributors,
            see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

from __future__ import annotations

import os
import pty
import select
import signal
import sys

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
    if len(sys.argv) <= 1:
        sys.exit("usage: %prog% command [args]")

    p_pid, master_fd = pty.fork()
    if p_pid == 0:  # Child.
        os.execvpe(sys.argv[1], sys.argv[1:], env={"TERM": "linux", "COLUMNS": "80", "LINES": "24"})

    screen = pyte.Screen(24, 80, write_process_input=lambda data: os.write(master_fd, data.encode()))
    stream = pyte.Stream(screen)

    while True:
        try:
            [_master_fd], _wlist, _xlist = select.select([master_fd], [], [], 1)
        except (
            KeyboardInterrupt,  # Stop right now!
            ValueError,
        ):  # Nothing to read.
            break
        try:
            data = os.read(master_fd, 1024)
        except OSError:  # Linux says EIO once the program has ended.
            break
        if not data:
            break

        stream.feed(data.decode("utf-8", "replace"))

    os.kill(p_pid, signal.SIGTERM)
    print(*rows(screen), sep="\n")
