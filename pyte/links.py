"""
The links that some rows of a page show: the ones a program made with
"OSC 8", and the URLs in the text.

pymux's URL mode labels these so a person can open or copy one by key.
The text is read in lines and not in rows, so a URL that wrapped is one
URL. Where a link and a URL in the text overlap, the link wins: it is
what the program meant, and the text may only show its name.

The pattern is foot's (`[url].regex` in `foot.ini`), which is where URL
mode comes from. Lillecarl/pymux#608.

A caller may add rules that make a link of text that is not one: an
issue number, say. A rule's match never takes a place a link or a URL
already holds. Lillecarl/pymux#776.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .page import Page, TextLine

__all__ = ["URL_PATTERN", "Link", "LinkRule", "links_in"]

_SCHEMES = (
    r"(?:https?://|mailto:|ftp://|file:|ssh:|ssh://|git://|tel:|magnet:"
    r"|ipfs://|ipns://|gemini://|gopher://|news:|www\.)"
)
_BRACKETED = (
    r"\([\]\[\"0-9a-zA-Z:/?#@!$&'*+,;=.~_%^\-]+\)"
    r"|\[[()\"0-9a-zA-Z:/?#@!$&'*+,;=.~_%^\-]+\]"
    r"|\"[\]\[()0-9a-zA-Z:/?#@!$&'*+,;=.~_%^\-]+\""
    r"|'[\]\[()0-9a-zA-Z:/?#@!$&*+,;=.~_%^\-]+'"
)

#: A URL in text. It ends on a character that ends a URL, so the full
#: stop or comma after one in a sentence stays out, and brackets and
#: quotes are taken in pairs.
URL_PATTERN = re.compile(
    _SCHEMES
    + r"(?:[0-9a-zA-Z:/?#@!$&*+,;=.~_%^'\-]+|"
    + _BRACKETED
    + r")+(?:[0-9a-zA-Z/#@$&*+=~_%^\-]|"
    + _BRACKETED
    + r")"
)


class Link(NamedTuple):
    "One link: where it starts and ends, both inside it, as page rows and columns."

    url: str
    row: int
    column: int
    end_row: int
    end_column: int
    #: Made with "OSC 8", and not found in the text.
    osc8: bool


class LinkRule(NamedTuple):
    """
    Text that `pattern` matches is a link to `url`, a `str.format`
    template: `{0}` is the whole match, `{1}` its first group, and a
    named group goes by its name.
    """

    pattern: re.Pattern[str]
    url: str

    def url_of(self, match: re.Match[str]) -> str:
        return self.url.format(match.group(0), *match.groups(""), **match.groupdict(""))


def _cells_of(page: Page, line: TextLine) -> list[tuple[int, int]]:
    """
    The row and column of each character of `line.text`, in order.

    `Page.text_lines` joins every cell's character, and a cell can hold
    none (the second half of a wide one) or several (combining marks).
    """
    where = []
    for row_number in range(line.first, line.last + 1):
        row = page.data_buffer.get(row_number)
        if not row:
            continue
        for column in range(max(row) + 1):
            where.extend([(row_number, column)] * len(row[column].char))
    return where


#: A URL that runs to the end of the text, its last character kept
#: even where `URL_PATTERN` would leave it out: a row can break after
#: the dot of `github.com`.
_RUNS_TO_THE_END = re.compile(_SCHEMES + r"[0-9a-zA-Z:/?#@!$&*+,;=.~_%^'\-\[\]()\"]*\Z")
_URL_CHARACTER = re.compile(r"[0-9a-zA-Z:/?#@!$&*+,;=.~_%^'\-\[\]()\"]")


def _joined(page: Page, lines: list[TextLine], columns: int | None) -> list[tuple[str, list[tuple[int, int]]]]:
    """
    Each line's text with the row and column of each character, and a
    line that a URL runs off the right edge of joined to the next.

    Claude Code and other programs wrap their own text: the row ends
    with a hard break, and the next one starts with their indentation.
    So a URL whose last character sits on the last column goes on after
    the next row's leading spaces. kitty does the same, across a hard
    break, but stops at a space. Lillecarl/pymux#926.
    """
    joined: list[tuple[str, list[tuple[int, int]]]] = []
    for line in lines:
        where = _cells_of(page, line)
        if joined and columns is not None:
            text, cells = joined[-1]
            indent = len(line.text) - len(line.text.lstrip(" "))
            if (
                cells
                and cells[-1][1] == columns - 1
                and _RUNS_TO_THE_END.search(text)
                and _URL_CHARACTER.match(line.text, indent)
            ):
                joined[-1] = (text + line.text[indent:], cells + where[indent:])
                continue
        joined.append((line.text, where))
    return joined


def _osc8_links(page: Page, first: int, last: int) -> list[Link]:
    "Each run of cells inside one link, one run per row."
    links = []
    for row_number in range(first, last + 1):
        row = page.data_buffer.get(row_number)
        if not row:
            continue
        open_at = None
        target = ""
        for column in range(max(row) + 2):
            appearance = row[column].appearance if column in row else None
            here = appearance.hyperlink if appearance is not None else ""
            if here == target:
                continue
            if target:
                links.append(Link(target, row_number, open_at, row_number, column - 1, True))
            target, open_at = here, column
    return links


def _overlaps(one: Link, other: Link) -> bool:
    return (one.row, one.column) <= (other.end_row, other.end_column) and (other.row, other.column) <= (
        one.end_row,
        one.end_column,
    )


def links_in(
    page: Page, first: int, last: int, rules: Sequence[LinkRule] = (), *, columns: int | None = None
) -> list[Link]:
    """
    The links rows `first` to `last` show, top to bottom. With the
    page's `columns`, a URL that reaches the last column goes on to the
    next row though a program broke the line there.
    """
    links = _osc8_links(page, first, last)
    for text, where in _joined(page, page.text_lines(first, last), columns):
        for match in URL_PATTERN.finditer(text):
            (row, column), (end_row, end_column) = where[match.start()], where[match.end() - 1]
            found = Link(match.group(), row, column, end_row, end_column, False)
            if not any(_overlaps(found, link) for link in links if link.osc8):
                links.append(found)
        for rule in rules:
            for match in rule.pattern.finditer(text):
                if match.end() == match.start():
                    continue
                (row, column), (end_row, end_column) = where[match.start()], where[match.end() - 1]
                found = Link(rule.url_of(match), row, column, end_row, end_column, False)
                if not any(_overlaps(found, link) for link in links):
                    links.append(found)
    return sorted(links, key=lambda link: (link.row, link.column))
