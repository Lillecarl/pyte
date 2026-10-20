"""
What a terminal that widens a text emoji with U+FE0F is given instead.
Lillecarl/pymux#539.
"""

from __future__ import annotations

import pytest

from pyte.cells import without_widening_selectors


@pytest.mark.parametrize(
    ("text", "given"),
    [
        # A one-column character loses the selector.
        ("✳️X", "✳X"),
        ("a⚠️ b❤️", "a⚠ b❤"),
        # A wide one keeps it: that emoji is two columns everywhere.
        ("✅️X", "✅️X"),
        # A selector with nothing before it, or after another, stays.
        ("️X", "️X"),
        ("✳️️", "✳️"),
        ("plain", "plain"),
    ],
)
def test_a_selector_after_a_one_column_character_goes(text, given):
    assert without_widening_selectors(text) == given
