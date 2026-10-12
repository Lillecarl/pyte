"""
The links that some rows of a page show: the ones a program made with
"OSC 8", and the URLs in the text.

pymux's URL mode labels these so a person can open or copy one by key.
The text is read in lines and not in rows, so a URL that wrapped is one
URL. Where a link and a URL in the text overlap, the link wins: it is
what the program meant, and the text may only show its name.

The pattern is foot's (`[url].regex` in `foot.ini`), which is where URL
mode comes from. Lillecarl/pymux#608.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from .page import Page, TextLine

__all__ = ["URL_PATTERN", "Link", "links_in"]

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


def links_in(page: Page, first: int, last: int) -> list[Link]:
    "The links rows `first` to `last` show, top to bottom."
    links = _osc8_links(page, first, last)
    for line in page.text_lines(first, last):
        where = _cells_of(page, line)
        for match in URL_PATTERN.finditer(line.text):
            (row, column), (end_row, end_column) = where[match.start()], where[match.end() - 1]
            found = Link(match.group(), row, column, end_row, end_column, False)
            if not any(_overlaps(found, link) for link in links if link.osc8):
                links.append(found)
    return sorted(links, key=lambda link: (link.row, link.column))
