"""
The kitty keyboard protocol's own sequences: push, pop, set and ask.

All four end in "u" and differ by their marker alone, which is why
each has a name here: "CSI > 31 u" pushes every flag and "CSI ? u"
asks which ones hold, and a typo between the two is a terminal that
never answers. `keys.events` names the flags and the set modes, and
`reports.KeyboardFlagsReport` reads the answer.
"""

from __future__ import annotations

from ..keys.events import FlagsMode, KeyboardFlag
from .csi import Csi, Marker, csi

__all__ = ("ask_flags", "pop_flags", "push_flags", "set_flags")


def push_flags(flags: KeyboardFlag) -> str:
    """
    "CSI > flags u": put these flags on the terminal's stack.

        >>> push_flags(KeyboardFlag(31))
        '\\x1b[>31u'
    """
    return csi(Csi.KITTY_KEYBOARD, int(flags), private=Marker.GREATER)


def pop_flags(count: int = 1) -> str:
    """
    "CSI < count u": take that many entries off the stack, and the
    flags under them hold again.
    """
    return csi(Csi.KITTY_KEYBOARD, count, private=Marker.LESS)


def set_flags(flags: KeyboardFlag, mode: FlagsMode = FlagsMode.SET_EXACTLY) -> str:
    """
    "CSI = flags ; mode u": change the entry on top of the stack.

        >>> set_flags(KeyboardFlag(1))
        '\\x1b[=1;1u'
    """
    return csi(Csi.KITTY_KEYBOARD, int(flags), mode, private=Marker.EQUALS)


def ask_flags() -> str:
    """
    "CSI ? u": which flags hold now. A terminal that speaks the
    protocol answers with a `KeyboardFlagsReport`.
    """
    return csi(Csi.KITTY_KEYBOARD, private=Marker.QUESTION)
