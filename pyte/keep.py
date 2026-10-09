"""
What a hot upgrade does with each attribute of a stateful object.

A class lists every attribute of its instances in `KEEP`, a mapping of
name to `Keep`. pymux's `test_every_attribute_has_a_fate` walks a live
session and fails on an attribute with no entry, and on an entry with
no attribute. A field added without a decision cannot ship, which is
what keeps a restore from quietly losing state. Lillecarl/pymux#399.

It lives in pyte because pyte is the lowest layer: every package above
it declares with the same three words.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Keep"]


class Keep(StrEnum):
    #: Written to a snapshot and read back as it was.
    SAVED = "saved"
    #: Worked out again from saved state after a load.
    REBUILT = "rebuilt"
    #: Lost on purpose: a load starts it fresh.
    DROPPED = "dropped"
