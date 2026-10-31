"""
The CSI sequences a terminal answers with, one class each.

A report is written by a terminal and read by the program that asked:
`str(report)` writes one, `Report.parse(text)` reads one and is None
for any other text. Every field is a number or a member, so a reader
compares `report.mode is PrivateMode.SYNCHRONIZED_OUTPUT` and never a
group of a regular expression.

Each class reads the sequence once, with `CsiSequence.parse`, and then
asks only what that sequence holds: its marker, its final byte and its
numbers. `replies.parse_reply` tries them all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar

from ..escape import DA as _DA
from ..escape import DSR as _DSR
from ..keys.events import KeyboardFlag
from ..modes import AnsiMode, ModeState, PrivateMode
from .csi import Csi, CsiSequence, Marker, csi, mode_named

__all__ = (
    "AttributesKind",
    "CellSizeReport",
    "ColorScheme",
    "ColorSchemeReport",
    "CursorPositionReport",
    "DeviceAttributes",
    "DeviceStatus",
    "FocusReport",
    "InBandSizeReport",
    "KeyboardFlagsReport",
    "ModeReport",
    "SgrMouseReport",
    "StatusReport",
    "TextAreaCellsReport",
    "TextAreaPixelsReport",
    "WindowReport",
)


@dataclass(frozen=True)
class ModeReport:
    """
    DECRPM, the answer to DECRQM: "CSI ? Pd ; Ps $ y" for a private
    mode, and the same with no "?" for an ANSI one.

        >>> ModeReport.parse("\\x1b[?2026;2$y")
        ModeReport(mode=<PrivateMode.SYNCHRONIZED_OUTPUT: 2026>, state=<ModeState.RESET: 2>, private=True)

    `mode` is the member that names it when there is one, and the
    number otherwise: a terminal answers for modes pyte never heard of.
    """

    FINAL: ClassVar[str] = "$y"

    mode: PrivateMode | AnsiMode | int
    state: ModeState
    private: bool = True

    def __str__(self) -> str:
        marker = Marker.QUESTION if self.private else Marker.NONE
        return csi(self.FINAL, int(self.mode), self.state, private=marker)

    @classmethod
    def parse(cls, text: str) -> ModeReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> ModeReport | None:
        if sequence is None or sequence.final != cls.FINAL or sequence.private not in (Marker.QUESTION, Marker.NONE):
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) != 2:
            return None
        number, state = numbers
        try:
            named = ModeState(state)
        except ValueError:
            return None
        private = sequence.private is Marker.QUESTION
        return cls(mode_named(number, private), named, private)

    @property
    def is_known(self) -> bool:
        "Whether the terminal has the mode at all, set or not."
        return self.state is not ModeState.UNKNOWN

    @property
    def is_set(self) -> bool:
        return self.state in (ModeState.SET, ModeState.PERMANENTLY_SET)


@dataclass(frozen=True)
class CursorPositionReport:
    """
    CPR, the answer to "CSI 6 n": "CSI row ; column R", both counted
    from one.

    **The same bytes are a key.** "CSI 1 ; 5 R" is F3 with control in
    the legacy encoding, so a reader of input decides which it expects.
    """

    FINAL: ClassVar[str] = "R"

    row: int
    column: int

    def __str__(self) -> str:
        return csi(self.FINAL, self.row, self.column)

    @classmethod
    def parse(cls, text: str) -> CursorPositionReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> CursorPositionReport | None:
        if sequence is None or sequence.final != cls.FINAL or sequence.private is not Marker.NONE:
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) != 2:
            return None
        return cls(*numbers)


class AttributesKind(IntEnum):
    "Which device attributes: the marker of the answer says."

    #: DA1, "CSI ? Ps ; ... c": the conformance level and the extensions.
    PRIMARY = 1

    #: DA2, "CSI > Pp ; Pv ; Pc c": the model, the version and the cartridge.
    SECONDARY = 2


_ATTRIBUTES_MARKERS = {AttributesKind.PRIMARY: Marker.QUESTION, AttributesKind.SECONDARY: Marker.GREATER}


@dataclass(frozen=True)
class DeviceAttributes:
    """
    The answer to "CSI c" or "CSI > c".

        >>> DeviceAttributes.parse("\\x1b[?62;4c").params
        (62, 4)

    In a primary answer the first number is the conformance level and
    the rest are extensions: `terminfo.DeviceExtension` names them, and
    4 is sixel.
    """

    FINAL: ClassVar[str] = _DA

    kind: AttributesKind
    params: tuple[int, ...]

    def __str__(self) -> str:
        return csi(self.FINAL, *self.params, private=_ATTRIBUTES_MARKERS[self.kind])

    @classmethod
    def parse(cls, text: str) -> DeviceAttributes | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> DeviceAttributes | None:
        if sequence is None or sequence.final != cls.FINAL:
            return None
        kind = {marker: kind for kind, marker in _ATTRIBUTES_MARKERS.items()}.get(sequence.private)
        numbers = sequence.numbers()
        if kind is None or numbers is None:
            return None
        return cls(kind, tuple(number for number in numbers))


class DeviceStatus(IntEnum):
    'The answer to "CSI 5 n".'

    OK = 0
    MALFUNCTION = 3


@dataclass(frozen=True)
class StatusReport:
    """
    DSR, the answer to "CSI 5 n": "CSI 0 n", or "CSI 3 n" for a
    terminal that is not well. A program that asks after it wrote
    something learns that the terminal read that far.
    """

    FINAL: ClassVar[str] = _DSR

    status: DeviceStatus = DeviceStatus.OK

    def __str__(self) -> str:
        return csi(self.FINAL, self.status)

    @classmethod
    def parse(cls, text: str) -> StatusReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> StatusReport | None:
        if sequence is None or sequence.final != cls.FINAL or sequence.private is not Marker.NONE:
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) != 1:
            return None
        try:
            return cls(DeviceStatus(numbers[0]))
        except ValueError:
            return None


class ColorScheme(IntEnum):
    "What a theme report says. Contour's numbers, which every terminal that sends one uses."

    DARK = 1
    LIGHT = 2


@dataclass(frozen=True)
class ColorSchemeReport:
    """
    "CSI ? 997 ; Ps n": the terminal draws dark or light. It answers
    "CSI ? 996 n", and sends one of its own at each switch while
    private mode 2031 is set.
    """

    FINAL: ClassVar[str] = _DSR
    CODE: ClassVar[int] = 997

    scheme: ColorScheme

    def __str__(self) -> str:
        return csi(self.FINAL, self.CODE, self.scheme, private=Marker.QUESTION)

    @classmethod
    def parse(cls, text: str) -> ColorSchemeReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> ColorSchemeReport | None:
        if sequence is None or sequence.final != cls.FINAL or sequence.private is not Marker.QUESTION:
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) != 2 or numbers[0] != cls.CODE:
            return None
        try:
            return cls(ColorScheme(numbers[1]))
        except ValueError:
            return None


class WindowReport(IntEnum):
    """
    The first number of an XTWINOPS answer, "CSI Ps ; ... t".

    Not `parameters.WindowOp`, which numbers the questions: "CSI 16 t"
    asks for the cell size and "CSI 6 ; h ; w t" answers it.
    """

    TEXT_AREA_PIXELS = 4
    CELL_SIZE_PIXELS = 6
    TEXT_AREA_CELLS = 8

    #: DEC 2048: the size in cells and in pixels, in one report.
    IN_BAND_SIZE = 48


def _window_numbers(sequence: CsiSequence | None, report: WindowReport, count: int) -> tuple[int, ...] | None:
    "The numbers after the report code, when `sequence` is that report with that many."
    if sequence is None or sequence.final != Csi.XTWINOPS or sequence.private is not Marker.NONE:
        return None
    numbers = sequence.numbers()
    if numbers is None or len(numbers) != count + 1 or numbers[0] != report:
        return None
    return numbers[1:]


@dataclass(frozen=True)
class CellSizeReport:
    'The answer to "CSI 16 t": "CSI 6 ; height ; width t", in pixels.'

    height: int
    width: int

    def __str__(self) -> str:
        return csi(Csi.XTWINOPS, WindowReport.CELL_SIZE_PIXELS, self.height, self.width)

    @classmethod
    def parse(cls, text: str) -> CellSizeReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> CellSizeReport | None:
        numbers = _window_numbers(sequence, WindowReport.CELL_SIZE_PIXELS, 2)
        return None if numbers is None else cls(*numbers)


@dataclass(frozen=True)
class TextAreaPixelsReport:
    'The answer to "CSI 14 t": "CSI 4 ; height ; width t", in pixels.'

    height: int
    width: int

    def __str__(self) -> str:
        return csi(Csi.XTWINOPS, WindowReport.TEXT_AREA_PIXELS, self.height, self.width)

    @classmethod
    def parse(cls, text: str) -> TextAreaPixelsReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> TextAreaPixelsReport | None:
        numbers = _window_numbers(sequence, WindowReport.TEXT_AREA_PIXELS, 2)
        return None if numbers is None else cls(*numbers)


@dataclass(frozen=True)
class TextAreaCellsReport:
    'The answer to "CSI 18 t": "CSI 8 ; rows ; columns t".'

    rows: int
    columns: int

    def __str__(self) -> str:
        return csi(Csi.XTWINOPS, WindowReport.TEXT_AREA_CELLS, self.rows, self.columns)

    @classmethod
    def parse(cls, text: str) -> TextAreaCellsReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> TextAreaCellsReport | None:
        numbers = _window_numbers(sequence, WindowReport.TEXT_AREA_CELLS, 2)
        return None if numbers is None else cls(*numbers)


@dataclass(frozen=True)
class InBandSizeReport:
    """
    DEC 2048: "CSI 48 ; rows ; columns ; height ; width t", the size in
    cells and in pixels. A terminal sends it at each resize while the
    mode is set.
    """

    rows: int
    columns: int
    height: int
    width: int

    def __str__(self) -> str:
        return csi(Csi.XTWINOPS, WindowReport.IN_BAND_SIZE, self.rows, self.columns, self.height, self.width)

    @classmethod
    def parse(cls, text: str) -> InBandSizeReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> InBandSizeReport | None:
        numbers = _window_numbers(sequence, WindowReport.IN_BAND_SIZE, 4)
        return None if numbers is None else cls(*numbers)


@dataclass(frozen=True)
class KeyboardFlagsReport:
    'The answer to "CSI ? u": "CSI ? flags u", the kitty keyboard flags in force.'

    flags: KeyboardFlag

    def __str__(self) -> str:
        return csi(Csi.KITTY_KEYBOARD, int(self.flags), private=Marker.QUESTION)

    @classmethod
    def parse(cls, text: str) -> KeyboardFlagsReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> KeyboardFlagsReport | None:
        if sequence is None or sequence.final != Csi.KITTY_KEYBOARD or sequence.private is not Marker.QUESTION:
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) > 1:
            return None
        return cls(KeyboardFlag(numbers[0] if numbers else 0))


@dataclass(frozen=True)
class FocusReport:
    """
    DEC 1004: "CSI I" when the terminal's window gains the focus and
    "CSI O" when it loses it.
    """

    GAINED: ClassVar[str] = "I"
    LOST: ClassVar[str] = "O"

    focused: bool

    def __str__(self) -> str:
        return csi(self.GAINED if self.focused else self.LOST)

    @classmethod
    def parse(cls, text: str) -> FocusReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> FocusReport | None:
        if sequence is None or sequence.params or sequence.private is not Marker.NONE:
            return None
        if sequence.final == cls.GAINED:
            return cls(True)
        if sequence.final == cls.LOST:
            return cls(False)
        return None


@dataclass(frozen=True)
class SgrMouseReport:
    """
    DEC 1006: "CSI < button ; column ; row M", and "m" for a release.

    `column` and `row` are as the terminal wrote them: counted from one
    in cells, or in pixels under DEC 1016, where a terminal may count
    from zero. `button` carries the modifier and motion bits.
    """

    PRESS: ClassVar[str] = "M"
    RELEASE: ClassVar[str] = "m"

    button: int
    column: int
    row: int
    released: bool = False

    def __str__(self) -> str:
        final = self.RELEASE if self.released else self.PRESS
        return csi(final, self.button, self.column, self.row, private=Marker.LESS)

    @classmethod
    def parse(cls, text: str) -> SgrMouseReport | None:
        return cls.read(CsiSequence.parse(text))

    @classmethod
    def read(cls, sequence: CsiSequence | None) -> SgrMouseReport | None:
        if sequence is None or sequence.private is not Marker.LESS or sequence.final not in (cls.PRESS, cls.RELEASE):
            return None
        numbers = sequence.numbers()
        if numbers is None or len(numbers) != 3:
            return None
        return cls(*numbers, released=sequence.final == cls.RELEASE)
