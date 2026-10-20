"""
webterm
~~~~~~~

An example showing how to use :mod:`pyte` to implement a basic
single-user web terminal.

Client-side ``webterm.js`` supports
* incremental rendering: only rows changed since the last frame,
* most of the common keyboard events.

Scrollback stays on the server: rows above the page live in the
buffer and a client that wants them reads those rows.

.. note:: This example requires Python >=3.14 and version 3.0 of the
          ``aiohttp`` library, in the Nix development environment.

.. seealso::

   `The TTY demystified <http://www.linusakesson.net/programming/tty>`_
   for an introduction to the inner workings of the TTY subsystem.

:copyright: (c) 2017 by pyte authors and contributors,
            see AUTHORS for details.
:license: LGPL, see LICENSE for more details.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pty
import shlex
import signal
import webbrowser
from pathlib import Path

import aiohttp
from aiohttp import web

import pyte


class Terminal:
    def __init__(self, columns: int, lines: int, p_in) -> None:
        self.screen = pyte.Screen(lines, columns, write_process_input=lambda data: p_in.write(data.encode()))
        self.screen.set_mode(pyte.modes.AnsiMode.LINE_FEED_NEW_LINE)
        self.stream = pyte.Stream(self.screen)
        # The write count up to which rows were already sent.
        self.seen = 0

    def feed(self, data: bytes) -> None:
        self.stream.feed(data.decode("utf-8", "replace"))

    @staticmethod
    def _css(color) -> str:
        return "default" if color is None else str(color)

    def dumps(self) -> str:
        screen = self.screen
        cursor = screen.pt_cursor_position
        lines = []
        for y, written in sorted(screen.written_at.items()):
            if written > self.seen and y >= screen.line_offset:
                line = screen.page.data_buffer.get(y, {})
                data = [
                    (
                        line[x].char if x in line else " ",
                        line[x].appearance.rendition.reverse if x in line else False,
                        self._css(line[x].appearance.rendition.color) if x in line else "default",
                        self._css(line[x].appearance.rendition.bgcolor) if x in line else "default",
                    )
                    for x in range(screen.columns)
                ]
                lines.append((y - screen.line_offset, data))

        self.seen = screen.writes
        return json.dumps({"c": (cursor.x, cursor.y - screen.line_offset), "lines": lines})


def open_terminal(command="bash", columns=80, lines=24):
    p_pid, master_fd = pty.fork()
    if p_pid == 0:  # Child.
        argv = shlex.split(command)
        env = {"TERM": "linux", "LC_ALL": "en_GB.UTF-8", "COLUMNS": str(columns), "LINES": str(lines)}
        os.execvpe(argv[0], argv, env)

    # File-like object for I/O with the child process aka command.
    p_out = os.fdopen(master_fd, "w+b", 0)
    return Terminal(columns, lines, p_out), p_pid, p_out


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    request.app["websockets"].add(asyncio.current_task())

    terminal, p_pid, p_out = open_terminal()
    await ws.send_str(terminal.dumps())

    def on_master_output():
        terminal.feed(p_out.read(65536))
        asyncio.create_task(ws.send_str(terminal.dumps()))

    loop = asyncio.get_event_loop()
    loop.add_reader(p_out, on_master_output)
    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                p_out.write(msg.data.encode())
            elif msg.type == aiohttp.WSMsgType.ERROR:
                raise ws.exception()
    except asyncio.CancelledError, OSError:  # Process died?
        pass
    finally:
        loop.remove_reader(p_out)
        os.kill(p_pid, signal.SIGTERM)
        p_out.close()
        if not is_shutting_down:
            request.app["websockets"].remove(asyncio.current_task())
    await ws.close()
    return ws


is_shutting_down = False


async def on_shutdown(app):
    """Closes all WS connections on shutdown."""
    global is_shutting_down
    is_shutting_down = True
    for task in app["websockets"]:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


if __name__ == "__main__":
    app = web.Application()
    app["websockets"] = set()
    app.router.add_get("/ws", websocket_handler)
    app.router.add_static("/", Path(__file__).parent / "static", show_index=True)
    app.on_shutdown.append(on_shutdown)

    webbrowser.open_new_tab("http://localhost:8080/index.html")

    web.run_app(app)
