"""
A page makes its rows from whatever `pyte.page.Row` is when it makes them.

`checks.pyte-rs-unit` runs this suite with `pyte_rs.install()` in
`conftest.py`, and a green run there says something only if the pages
really held Rust rows. Without `PYTE_RS` they hold the dict.
Lillecarl/pymux#570.
"""

from __future__ import annotations

import os

from pyte.page import Page
from pyte.screen import Screen
from pyte.streams import Stream


def test_a_page_holds_the_row_that_is_installed():
    expected = "pyte_rs" if os.environ.get("PYTE_RS", "") not in ("", "0") else "pyte.page"
    page = Page()
    assert type(page.data_buffer[0]).__module__ == expected


def test_a_screen_draws_into_the_row_that_is_installed():
    expected = "pyte_rs" if os.environ.get("PYTE_RS", "") not in ("", "0") else "pyte.page"
    screen = Screen(2, 10, write_process_input=lambda _: None)
    Stream(screen).feed("hi\x1b[2Kthere")
    assert {type(row).__module__ for row in screen.page.data_buffer.values()} == {expected}
