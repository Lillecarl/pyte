#!/usr/bin/env python3
"""
Write one page of HTML for a person to look at.

`tests/test_html.py` reads the spans back with a parser, which says
that the characters land in the right columns and that the styles say
what they should. **It cannot say that the page draws.** A declaration
CSS does not understand is dropped by the browser in silence, so a
wrong colour or an underline nobody asked for passes every test here.

So this writes a screen that holds one of everything, and the work is
opening it. Lillecarl/pymux#452.

    python tests/render_a_sample_page.py /tmp/sample.html
"""

from __future__ import annotations

import sys

from pyte.html import CSS, html_of_page
from pyte.screen import Screen
from pyte.streams import Stream

#: One line for each thing a rendition can ask for, and a few that only
#: a browser draws.
LINES = [
    (
        "\x1b[1mbold\x1b[0m  \x1b[2mdim\x1b[0m  \x1b[3mitalic\x1b[0m  "
        "\x1b[4munderline\x1b[0m  \x1b[9mstrike\x1b[0m  \x1b[5mblink\x1b[0m"
    ),
    (
        "\x1b[4:2mdouble\x1b[0m  \x1b[4:3mcurly\x1b[0m  \x1b[4:4mdotted\x1b[0m  "
        "\x1b[4:5mdashed\x1b[0m  \x1b[4;58;5;1mred line\x1b[0m"
    ),
    "\x1b[7mreverse\x1b[0m  \x1b[8mhidden\x1b[0m(hidden)  x\x1b[73m2\x1b[0m  H\x1b[74m2\x1b[0mO",
    "".join("\x1b[3%dm%d\x1b[0m " % (index, index) for index in range(8)),
    "".join("\x1b[4%dm %d \x1b[0m" % (index, index) for index in range(8)),
    "\x1b[38;5;208m256 colour\x1b[0m  \x1b[38;2;80;250;123mtrue colour\x1b[0m",
    "wide: 中文こんにちは  combining: é å",
    (
        "link: \x1b]8;;https://example.com/\x1b\\example.com\x1b]8;;\x1b\\  "
        "refused: \x1b]8;;javascript:alert(1)\x1b\\click\x1b]8;;\x1b\\"
    ),
    'markup a program wrote: <script>alert(1)</script> & "quotes"',
    "trailing blanks are trimmed, so a copy of this line ends here.",
]

ROWS = len(LINES) + 2
COLUMNS = 78


def page() -> str:
    "The whole document, with the stylesheet in it."
    screen = Screen(ROWS, COLUMNS, write_process_input=lambda _data: None)
    Stream(screen).feed("\r\n".join(LINES))
    body = html_of_page(screen.page, 0, ROWS - 1, COLUMNS)
    return (
        "<!doctype html>\n<html>\n<head>\n<meta charset='utf-8'>\n"
        "<title>pyte.html</title>\n<style>\n%s</style>\n</head>\n<body>\n"
        '<pre class="pyte-screen">%s</pre>\n</body>\n</html>\n' % (CSS, body)
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: render_a_sample_page.py <file.html>")
    with open(sys.argv[1], "w", encoding="utf-8") as out:
        out.write(page())
    print("wrote %s" % sys.argv[1])


if __name__ == "__main__":
    main()
