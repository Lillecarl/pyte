"""
The sequences that carry a payload rather than parameters.

CSI carries numbers in fixed positions. These three carry text: an
OSC names a code and then whatever that code takes, and DCS and APC
carry a whole small protocol of their own. So the builders take the
payload and put the wrapping round it, and nothing here reads what is
inside. `osc.py` says what an OSC payload means, `images.py` what an
APC one does.
"""

from __future__ import annotations

from enum import StrEnum

from ..control import BEL as _BEL
from ..control import ESC as _ESC
from ..control import OSC as _OSC
from ..control import ST as _ST

__all__ = ("Terminator", "apc", "dcs", "decrqss", "osc")


class Terminator(StrEnum):
    """
    What ends a string sequence.

    Two spellings, and a terminal reads both. ST is the one a program
    should send and the one every terminal answers with. BEL is what
    xterm has always accepted, and enough programs send it that a
    terminal which refused it would look broken.
    """

    #: "ESC \\", the string terminator.
    ST = _ST

    #: The bell, which xterm takes as the end of an OSC.
    BEL = _BEL


def osc(code: str, *fields: str, end: str = Terminator.ST) -> str:
    """
    An operating system command: "OSC <code> ; <fields> ST".

        >>> osc(Osc.PALETTE_COLOR, "3", "#aabbcc")
        '\\x1b]4;3;#aabbcc\\x1b\\\\'
        >>> osc(Osc.RESET_PALETTE_COLOR)
        '\\x1b]104\\x1b\\\\'

    `osc.py` names the codes, and a code it does not name is a string
    like any other: the dynamic colours are "10" through "19" and
    nothing gains from a member for each.

    The fields are joined with semicolons, which is all the structure
    an OSC has. What each one means belongs to its code.
    """
    return "%s%s%s" % (_OSC, ";".join((code, *fields)), end)


def dcs(payload: str, end: str = Terminator.ST) -> str:
    """
    A device control string: "DCS <payload> ST".

        >>> dcs("$qm")
        '\\x1bP$qm\\x1b\\\\'

    The payload is a protocol of its own: "$q" asks a setting back
    (DECRQSS), "$r" answers one, and "+q" reads a terminfo capability
    (XTGETTCAP). `decrqss` writes the first of those, which is the one
    a test sends most.
    """
    return "%sP%s%s" % (_ESC, payload, end)


def decrqss(setting: str, end: str = Terminator.ST) -> str:
    """
    Ask what a setting is now: "DCS $ q <setting> ST".

        >>> decrqss(escape.SGR)
        '\\x1bP$qm\\x1b\\\\'
        >>> decrqss(Csi.DECSCUSR)
        '\\x1bP$q q\\x1b\\\\'

    `setting` is the name of the sequence that would set it, which is
    why it takes the same members `csi` does.
    """
    return dcs("$q" + setting, end=end)


def apc(payload: str, end: str = Terminator.ST) -> str:
    """
    An application programming command: "APC <payload> ST".

        >>> apc("Gi=31;OK")
        '\\x1b_Gi=31;OK\\x1b\\\\'

    The kitty graphics protocol is the only one that uses it here, and
    `images.py` says what its payload means.
    """
    return "%s_%s%s" % (_ESC, payload, end)
