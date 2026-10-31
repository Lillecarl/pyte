"""
Every attribute SGR turns on, another SGR number turns off.

ECMA-48 8.3.117 pairs them: 1 and 2 end at 22, 3 at 23, 4 at 24, 5 at
25, 7 at 27, 8 at 28 and 9 at 29. A screen that reads the first of a
pair and not the second keeps the attribute until a reset. pyte read 8
and not 28, so text a program hid stayed hidden. Lillecarl/pymux#848.

The numbers are written as the standard writes them, and not through
`Sgr`: this judges the reader, and a wrong member would pass a test
that took its numbers from the same place.
"""

from __future__ import annotations

import pytest

from pyte.cells import PLAIN
from pyte.sgr import after_sgr


@pytest.mark.parametrize(
    ("on", "off", "attribute"),
    [
        (1, 22, "bold"),
        (2, 22, "dim"),
        (3, 23, "italic"),
        (4, 24, "underline"),
        (5, 25, "blink"),
        (7, 27, "reverse"),
        (8, 28, "hidden"),
        (9, 29, "strike"),
    ],
)
def test_an_attribute_ends_at_its_own_number(on, off, attribute):
    turned_on = after_sgr(PLAIN, (on,))
    assert getattr(turned_on, attribute)
    assert not getattr(after_sgr(turned_on, (off,)), attribute)


def test_revealing_leaves_the_other_attributes():
    hidden = after_sgr(PLAIN, (1, 8))
    revealed = after_sgr(hidden, (28,))
    assert revealed.bold
    assert not revealed.hidden
