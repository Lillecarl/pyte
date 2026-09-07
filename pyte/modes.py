"""
The modes a program can set, and what a report says about one.

A mode is a switch that "CSI Ps h" turns on and "CSI Ps l" turns off.
There are two kinds. A mode with no marker comes from the ANSI standard
and `AnsiMode` names it. A mode written with a question mark is
private, and `PrivateMode` names it.

pyte holds both kinds in one set, `Screen.mode`, so a private mode is
shifted five bits to the left before it goes in. `flag_of` does the
shift, and `PrivateMode.flag` is the value a member carries.

Nothing here acts on a mode. This says what the numbers mean; the
screen decides what each one does, and `Screen._MODE_LEVELS` says which
conformance level admits which. Lillecarl/pymux#129.
"""
from enum import IntEnum

__all__ = (
    "PRIVATE_MODE_SHIFT",
    "AnsiMode",
    "ModeReport",
    "PrivateMode",
    "flag_of",
)


#: How far pyte shifts a private mode, to tell it from a mode that
#: carries no marker. `Screen.mode` holds the shifted value.
PRIVATE_MODE_SHIFT = 5


def flag_of(number: int) -> int:
    """
    The value that `Screen.mode` holds for a private mode number.

    `PrivateMode` names the modes a pane acts on, and this works on a
    bare number as well: a program may save and read back a mode that
    no terminal carries.
    """
    return number << PRIVATE_MODE_SHIFT


class PrivateMode(IntEnum):
    """
    A private mode, by the number that "CSI ? Ps h" carries.

    pyte shifts a private mode five bits to the left, to tell it from a
    mode that carries no marker, and `Screen.mode` holds the shifted
    value. `flag` is that value, and the member itself is the number
    that a program writes.
    """

    #: DECCKM: the cursor keys send application codes.
    APPLICATION_CURSOR_KEYS = 1

    #: DECCOLM: 132 columns instead of 80.
    COLUMNS_132 = 3

    #: DECSCLM: scroll slowly. A pane draws as fast as it can, so this
    #: one is kept and not acted on.
    SLOW_SCROLL = 4

    #: DECSCNM: reverse video over the whole screen.
    REVERSE_VIDEO = 5

    #: DECOM: the cursor is placed from the margins, not the screen.
    ORIGIN = 6

    #: DECAWM: a character past the last column wraps to the next line.
    AUTOWRAP = 7

    #: att610: does the cursor blink? DECSCUSR names the shape and the
    #: blinking in one number, and this mode names only the blinking,
    #: so both of them write `cursor_style`.
    CURSOR_BLINK = 12

    #: DECPFF: send a form feed after a print. There is no printer.
    PRINT_FORM_FEED = 18

    #: DECPEX: a print takes the page, not the scrolling region. There
    #: is no printer.
    PRINT_EXTENT = 19

    #: DECTCEM: is the cursor drawn?
    SHOW_CURSOR = 25

    #: DECHEBM: the Hebrew keyboard.
    HEBREW_KEYBOARD = 35

    #: Does DECCOLM do anything? xterm keeps the 132 column page
    #: behind this mode, because a program that sets DECCOLM by
    #: accident would otherwise resize the terminal and clear it. It
    #: is off until a program asks.
    ALLOW_80_TO_132 = 40

    #: xterm's fix for a fault in `more`. A cursor that filled the
    #: last column waits to wrap, and a tab leaves that wait alone.
    #: `more` drew to the end of a row and then wrote a tab, and the
    #: tab went nowhere. With this mode set the tab wraps first.
    MORE_FIX = 41

    #: DECNRCM: the national replacement character sets.
    NATIONAL_CHARSETS = 42

    #: A backspace in the first column goes back to the line above,
    #: but only when that line was reached by wrapping. It undoes what
    #: the typing did, and no more.
    REVERSE_WRAP = 45

    #: The alternate screen, on its own. A program that predates
    #: "?1049" sends this one.
    ALTERNATE_SCREEN = 47

    #: DECHCCM: the cursor is coupled to the horizontal scroll. No
    #: terminal that anybody uses carries it.
    HORIZONTAL_CURSOR_COUPLING = 60

    #: DECNKM: the keypad sends application codes.
    APPLICATION_KEYPAD = 66

    #: DECBKM: the backarrow key sends a backspace, not a delete.
    BACKARROW_IS_BACKSPACE = 67

    #: DECLRMM: may DECSLRM set a left and a right margin? The mode
    #: alone changes nothing. It says whether "CSI Pl ; Pr s" names the
    #: margins, and resetting it takes the margins away.
    LEFT_RIGHT_MARGIN = 69

    #: DECNCSM: do not clear the screen when the page width changes.
    #: DECCOLM clears the page it takes, and a VT510 lets a program
    #: keep what was there.
    NO_CLEAR_ON_COLUMN_CHANGE = 95

    #: Report the position of the mouse.
    MOUSE_REPORTING = 1000

    #: Report the mouse the way SGR writes it.
    SGR_MOUSE = 1006

    #: Report the mouse the way urxvt writes it.
    URXVT_MOUSE = 1015

    #: A backspace in the first column goes back to the line above,
    #: whether that line was wrapped or not, and from the first line
    #: to the last. This is what "?45" did before xterm 383 split the
    #: two apart.
    REVERSE_WRAP_ANYWHERE = 1045

    #: The alternate screen. The same screen as "?47", under the
    #: number that came later.
    ALTERNATE_SCREEN_AGAIN = 1047

    #: Save the cursor on a set, and bring it back on a reset. It is
    #: the pair of "ESC 7" and "ESC 8" written as one mode. "?1049"
    #: holds this mode and the alternate screen together.
    SAVE_CURSOR = 1048

    #: The alternate screen, with the cursor and a clear. This is the
    #: one a program sends today.
    ALTERNATE_SCREEN_WITH_CURSOR = 1049

    #: Wrap a paste in "ESC [ 200 ~" and "ESC [ 201 ~", so that a
    #: program can tell a paste from typing.
    BRACKETED_PASTE = 2004

    #: Report a resize in the input of the program, instead of only
    #: through SIGWINCH.
    INBAND_RESIZE = 2048

    @property
    def flag(self) -> int:
        "The value that `Screen.mode` holds while this mode is set."
        return flag_of(self.value)


class AnsiMode(IntEnum):
    """
    A mode that "CSI Ps h" carries, with no private marker.

    These come from the ANSI standard. They are held unshifted, because
    the shift is what tells a private mode from one of these.

    A pane acts on two of them, IRM and LNM. Nearly all of the rest come
    from a time of block mode terminals, and no terminal that anybody
    uses today acts on one.
    """

    #: GATM: transfer the guarded areas as well.
    GUARDED_AREA_TRANSFER = 1

    #: KAM: lock the keyboard.
    KEYBOARD_LOCKED = 2

    #: IRM: a character moves the ones to the right of it along, and
    #: the one past the right margin is lost. Off, a character replaces
    #: the one the cursor stands on.
    INSERT_REPLACE = 4

    #: SRTM: report a status change on its own.
    STATUS_REPORT_TRANSFER = 5

    #: VEM: an insert moves the lines up, not down.
    VERTICAL_EDITING = 7

    #: HEM: an insert moves the characters left, not right.
    HORIZONTAL_EDITING = 10

    #: PUM: the unit of a position is a millimetre, not a cell.
    POSITIONING_UNIT = 11

    #: SRM: echo what the keyboard sends.
    LOCAL_ECHO = 12

    #: FEAM: a format effector acts on the store, not the screen.
    FORMAT_EFFECTOR_ACTION = 13

    #: FETM: transfer the format effectors as well.
    FORMAT_EFFECTOR_TRANSFER = 14

    #: MATM: transfer every selected area, not only one.
    MULTIPLE_AREA_TRANSFER = 15

    #: TTM: a transfer stops at the end of the selected area.
    TRANSFER_TERMINATION = 16

    #: SATM: transfer the whole screen, not the selected area.
    SELECTED_AREA_TRANSFER = 17

    #: TSM: a tab stop belongs to one line, not to the screen.
    TABULATION_STOP = 18

    #: EBM: an edit stops at the end of the screen, not the area.
    EDITING_BOUNDARY = 19

    #: LNM: a line feed also returns the cursor to the first column.
    LINE_FEED_NEW_LINE = 20


class ModeReport(IntEnum):
    """
    What DECRQM ("CSI Ps $ p") answers about a mode.

    Zero says that the terminal never heard of the mode, and a program
    that reads it falls back to what it knows. Four says that the mode
    exists and can never be on, which is what a program needs to stop
    asking.
    """

    UNKNOWN = 0
    SET = 1
    RESET = 2
    PERMANENTLY_SET = 3
    PERMANENTLY_RESET = 4
