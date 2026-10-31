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

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from ..control import BEL as _BEL
from ..control import ESC as _ESC
from ..control import OSC as _OSC
from ..control import ST as _ST
from ..control import ST_C1 as _ST_C1

__all__ = (
    "CapabilityReport",
    "ChecksumReport",
    "OscString",
    "SettingReport",
    "StringKind",
    "StringReport",
    "StringSequence",
    "Terminator",
    "TitleKind",
    "TitleReport",
    "VersionReport",
    "apc",
    "dcs",
    "decrqss",
    "osc",
)


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

    #: The 8-bit ST. A terminal answers with it after an 8-bit request.
    ST_C1 = _ST_C1


class StringKind(StrEnum):
    "Which string sequence: the byte after ESC that opens it."

    OSC = "]"
    DCS = "P"
    APC = "_"


#: The 8-bit introducer of each, one byte in place of ESC and the byte.
_C1 = {"\x9d": StringKind.OSC, "\x90": StringKind.DCS, "\x9f": StringKind.APC}


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


# ----------------------------------------------------------------------
# Reading one.


class StringReport:
    """
    What a terminal answers with a string sequence.

    `str(report)` writes it with 7-bit controls. A screen writes the
    `kind` and the `payload` of `sequence()` between the controls that
    S8C1T picks, and always ends with ST: `end` is how a sequence that
    was read ended, and says nothing about how an answer ends.
    """

    def sequence(self) -> StringSequence:
        raise NotImplementedError

    def __str__(self) -> str:
        return str(self.sequence())


@dataclass(frozen=True)
class StringSequence(StringReport):
    """
    One OSC, DCS or APC, whole: what opens it, what it carries, and
    what ends it.

        >>> StringSequence.parse("\\x1b]11;rgb:0000/0000/0000\\x07")
        StringSequence(kind=<StringKind.OSC: ']'>, payload='11;rgb:0000/0000/0000', end=<Terminator.BEL: '\\x07'>)

    The payload never holds an ESC, so the first ST ends it. Only an
    OSC ends at a bell: xterm's rule, and the one every terminal that
    answers a colour query with a bell follows.
    """

    kind: StringKind
    payload: str
    end: Terminator = Terminator.ST

    def __str__(self) -> str:
        return "%s%s%s%s" % (_ESC, self.kind, self.payload, self.end)

    def sequence(self) -> StringSequence:
        return self

    @classmethod
    def parse(cls, text: str) -> StringSequence | None:
        "The string sequence `text` is, whole, or None."
        if text[:1] in _C1:
            kind, body = _C1[text[0]], text[1:]
        elif text[:1] == _ESC and text[1:2] in StringKind._value2member_map_:
            kind, body = StringKind(text[1]), text[2:]
        else:
            return None
        for end in (Terminator.ST, Terminator.ST_C1, Terminator.BEL):
            if end is Terminator.BEL and kind is not StringKind.OSC:
                continue
            if body.endswith(end):
                payload = body[: -len(end)]
                if _ESC in payload or _ST_C1 in payload:
                    return None
                return cls(kind, payload, end)
        return None


@dataclass(frozen=True)
class OscString(StringReport):
    """
    An OSC by its code: "OSC code ; payload ST".

        >>> OscString.parse("\\x1b]52;c;aGk=\\x1b\\\\")
        OscString(code='52', payload='c;aGk=', end=<Terminator.ST: '\\x1b\\\\'>)

    `osc.Osc` names the codes. What the payload means belongs to the
    code, so it stays one string here.
    """

    code: str
    payload: str = ""
    end: Terminator = Terminator.ST

    def sequence(self) -> StringSequence:
        payload = "%s;%s" % (self.code, self.payload) if self.payload else self.code
        return StringSequence(StringKind.OSC, payload, self.end)

    @classmethod
    def parse(cls, text: str) -> OscString | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> OscString | None:
        if sequence is None or sequence.kind is not StringKind.OSC:
            return None
        code, _, payload = sequence.payload.partition(";")
        if not code.isdigit():
            return None
        return cls(code, payload, sequence.end)


@dataclass(frozen=True)
class SettingReport(StringReport):
    """
    DECRPSS, the answer to DECRQSS: "DCS Ps $ r <setting> ST".

        >>> SettingReport.parse("\\x1bP1$r0;38:2::1:2:3m\\x1b\\\\").setting
        '0;38:2::1:2:3m'

    `setting` is the sequence that would set it again, final byte and
    all, so a colour probe reads its colour back from it.

    **`code` is the number as sent, and says little.** DEC's manuals and
    xterm disagree about which of 0 and 1 means a valid request, and
    some terminals write none. A reader judges the setting itself.
    """

    MARK: ClassVar[str] = "$r"

    setting: str = ""
    code: int | None = 1

    def sequence(self) -> StringSequence:
        code = "" if self.code is None else "%d" % self.code
        return StringSequence(StringKind.DCS, "%s%s%s" % (code, self.MARK, self.setting))

    @classmethod
    def parse(cls, text: str) -> SettingReport | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> SettingReport | None:
        if sequence is None or sequence.kind is not StringKind.DCS:
            return None
        code, mark, setting = sequence.payload.partition(cls.MARK)
        if not mark or (code and not code.isdigit()):
            return None
        return cls(setting, int(code) if code else None)


@dataclass(frozen=True)
class VersionReport(StringReport):
    """
    The answer to XTVERSION, "CSI > q": "DCS > | name and version ST".
    A terminal answers it whatever TERM says.
    """

    MARK: ClassVar[str] = ">|"

    version: str

    def sequence(self) -> StringSequence:
        return StringSequence(StringKind.DCS, self.MARK + self.version)

    @classmethod
    def parse(cls, text: str) -> VersionReport | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> VersionReport | None:
        if sequence is None or sequence.kind is not StringKind.DCS or not sequence.payload.startswith(cls.MARK):
            return None
        return cls(sequence.payload[len(cls.MARK) :])


@dataclass(frozen=True)
class ChecksumReport(StringReport):
    """
    DECCKSR: "DCS request ! ~ checksum ST", the answer to DECRQCRA and
    to "CSI ? 63 ; request n". `request` is the number the question
    carried, and the sum goes out as four hexadecimal digits.
    """

    MARK: ClassVar[str] = "!~"

    request: int
    checksum: int

    def sequence(self) -> StringSequence:
        return StringSequence(StringKind.DCS, "%d%s%04X" % (self.request, self.MARK, self.checksum))

    @classmethod
    def parse(cls, text: str) -> ChecksumReport | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> ChecksumReport | None:
        if sequence is None or sequence.kind is not StringKind.DCS:
            return None
        request, mark, checksum = sequence.payload.partition(cls.MARK)
        if not mark or not request.isdigit() or len(checksum) != 4:
            return None
        try:
            return cls(int(request), int(checksum, 16))
        except ValueError:
            return None


@dataclass(frozen=True)
class CapabilityReport(StringReport):
    """
    XTGETTCAP's answer, one for each name asked: "DCS 1 + r name =
    value ST" for a capability the terminal has, "DCS 1 + r name ST"
    for a flag it has, and "DCS 0 + r name ST" for one it lacks.

    Both travel as hexadecimal. `name` stays that way, so a name that
    was not hexadecimal comes back as it was asked; `value` is the
    text, and the writer encodes it.
    """

    MARK: ClassVar[str] = "+r"

    name: str
    value: str | None = None
    known: bool = True

    def sequence(self) -> StringSequence:
        payload = "%d%s%s" % (self.known, self.MARK, self.name)
        if self.value is not None:
            payload += "=" + self.value.encode("utf-8").hex()
        return StringSequence(StringKind.DCS, payload)

    @classmethod
    def parse(cls, text: str) -> CapabilityReport | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> CapabilityReport | None:
        if sequence is None or sequence.kind is not StringKind.DCS:
            return None
        known, mark, rest = sequence.payload.partition(cls.MARK)
        if not mark or known not in ("0", "1"):
            return None
        name, equals, value = rest.partition("=")
        if not equals:
            return cls(name, None, known == "1")
        try:
            return cls(name, bytes.fromhex(value).decode("utf-8"), known == "1")
        except ValueError:
            return None


class TitleKind(StrEnum):
    "Which title a report carries: the letter after the OSC."

    #: "CSI 20 t" asks for it.
    ICON = "L"

    #: "CSI 21 t" asks for it.
    WINDOW = "l"


@dataclass(frozen=True)
class TitleReport(StringReport):
    'The answer to "CSI 20 t" and "CSI 21 t": "OSC L label ST" and "OSC l title ST".'

    kind: TitleKind
    title: str

    def sequence(self) -> StringSequence:
        return StringSequence(StringKind.OSC, self.kind + self.title)

    @classmethod
    def parse(cls, text: str) -> TitleReport | None:
        return cls.read(StringSequence.parse(text))

    @classmethod
    def read(cls, sequence: StringSequence | None) -> TitleReport | None:
        if sequence is None or sequence.kind is not StringKind.OSC:
            return None
        letter = sequence.payload[:1]
        if letter not in TitleKind._value2member_map_:
            return None
        return cls(TitleKind(letter), sequence.payload[1:])
