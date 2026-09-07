"""
The screen: what a program has drawn, cell by cell.

**It parses and holds, and it draws nothing.** No I/O, no toolkit, and
no opinion about how a cell is spelled for a renderer. A cell holds an
`Appearance`, which is a model; `ptterm/style.py` spells one for
prompt_toolkit and `txterm/style.py` builds a `rich.style.Style` from
the same object, and neither reads a word the other wrote.

That is why this file is here and not in a widget. Lillecarl/pymux#11.

It replaces the `Screen` of upstream pyte, which is gone. What was
different, and is now simply what this package does:
    - The cells live in a `Page`, one per screen, so a swap to the
      alternate screen carries the cells and the cursor together.
    - 256 colours, true colour, and colours a program names itself.
    - CPR, device attributes, and the other reports a program reads.
"""
from collections import namedtuple
from enum import IntEnum
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Set,
    Tuple,
)

from . import charsets as cs
from .images import (
    ASSUMED_CELL_HEIGHT,
    ASSUMED_CELL_WIDTH,
    GraphicsState,
)
from . import kitty_keys
from .cells import (
    BASELINE_PARAMETERS,
    UNDERLINE_PARAMETERS,
    UNDERLINE_SHAPES,
    _CHAR_CACHE,
    _PROTECTED_CHAR_CACHE,
    PLAIN,
    PLAIN_APPEARANCE,
    Appearance,
    Cell,
    ErasedCell,
    Protection,
    ProtectedCell,
    Rendition,
    WrittenCell,
    appearance_of,
    character_width,
    protection_of,
)
from .page import (
    PLAIN_LINE,
    CursorPosition,
    DoubleHeight,
    HorizontalMargins,
    LineAttribute,
    LogicalLine,
    Margins,
    Page,
    Row,
)
from .modes import AnsiMode, ModeReport, PrivateMode, flag_of
from .parameters import (
    DEFAULT_CONFORMANCE_LEVEL,
    DEFAULT_CURSOR_STYLE,
    FIRST_PAGE_LENGTH,
    AttributeExtent,
    ConformanceLevel,
    CursorShape,
    StatusDisplay,
    StatusLineType,
    WindowOp,
)
from .colors import (
    COLOR_OF_A_BACKGROUND,
    COLOR_OF_A_FOREGROUND,
    DEFAULT_COLOR,
    PALETTE,
    sgr_code_of,
    sgr_color,
    sgr_color_parameters,
)
from .osc import (
    DYNAMIC_COLOR_CODES,
    DYNAMIC_COLOR_RESET_OFFSET,
    FIRST_SPECIAL_COLOR,
    FORWARDED_OSC,
    SPECIAL_COLOR_NAMES,
    ColorOverrides,
    Osc,
    PointerShapes,
    asks_for_the_clipboard,
    parse_hyperlink,
)
from .placeholders import PlaceholderRun, merge_runs, runs_in_line
from .sixel import decode_sixel
from .titles import Titles
from .terminfo import (
    CAPABILITIES,
    DEVICE_EXTENSIONS,
    TERMINAL_VERSION,
    XTERM_PATCH_LEVEL,
    XTERM_TYPE,
)

__all__ = ("Screen",)


def _four(params: Tuple[int, ...], first: int) -> Tuple[int, int, int, int]:
    """
    Four parameters, counting from `first`, with zero for a missing one.

    A sender drops the parameters it leaves at the default, so a
    command that names four corners can arrive with fewer. Zero is what
    an empty parameter gives, so the two read the same way.
    """
    read = params[first : first + 4]
    return tuple(read) + (0,) * (4 - len(read))  # type: ignore[return-value]


# Custom Savepoint that also stores the rendition.
_Savepoint = namedtuple(
    "_Savepoint",
    [
        "cursor_x",
        # The row within the screen, not within the buffer.
        "cursor_y",
        "g0_charset",
        "g1_charset",
        "charset",
        "origin",
        "rendition",
        # The marks that SPA and DECSCA set. They belong to the cursor,
        # the way the rendition does, so a save remembers them.
        "protection",
    ],
)


class Screen:
    """
    Custom screen class. Most of the methods are called from a vt100 Pyte
    stream.

    The cells are stored in a :class:`Page`. A front end reads them and
    makes what its own toolkit draws: `ptterm/terminal.py` builds a
    `UIContent` of style strings and text.
    """

    #: The state that the alternate screen keeps for itself. The
    #: scrolling region is not in the list: it belongs to the terminal,
    #: so a region set on one screen holds on the other. xterm and
    #: kitty both work that way.
    swap_variables = [
        "mode",
        "charset",
        # The cursor that "ESC 7" saves belongs to one screen. A
        # restore on the alternate screen may not read the one that the
        # first screen holds.
        "savepoints",
        "g0_charset",
        "g1_charset",
        "tabstops",
        "pointer_shapes",
        "data_buffer",
        # The floor of the buffer belongs to the buffer, so the two go
        # together. The alternate screen has a history of its own, and
        # it is usually empty.
        "history_floor",
        # The same: it says which rows of this buffer are laid out at
        # the width the screen has now.
        "reflow_floor",
        "pt_cursor_position",
        # The wait to wrap belongs to the cursor, so it travels with it.
        "pending_wrap",
        "max_y",
        # The continuation mark and the DEC line attribute are not here.
        # They belong to the lines of one screen, and they now ride on
        # the rows themselves, so the buffer carries them across a
        # switch on its own. Lillecarl/pymux#134.
        #
        # The kitty keyboard protocol keeps separate flag stacks for the
        # main and the alternate screen. (Immutable tuple: safe to swap.)
        "kitty_flags_stack",
        # The graphics state is swapped by reference: the alternate
        # screen gets a fresh GraphicsState, the main screen one is
        # restored when leaving the alternate screen.
        "graphics",
    ]

    def __init__(
        self,
        lines: int,
        columns: int,
        write_process_input: Callable[[str], None],
        bell_func: Callable[[], None] | None = None,
        get_history_limit: Callable[[], int] | None = None,
        osc_func: Callable[[str, str], None] | None = None,
        resize_func: Callable[[int | None, int | None], None] | None = None,
        may_resize: Callable[[], bool] | None = None,
    ) -> None:
        bell_func = bell_func or (lambda: None)
        get_history_limit = get_history_limit or (lambda: 2000)
        osc_func = osc_func or (lambda code, param: None)
        # A pane cannot resize itself: it sits in a layout that somebody
        # else owns. So the ask goes out, and the embedder decides. With
        # no embedder the ask goes nowhere, which is the old answer.
        resize_func = resize_func or (lambda lines, columns: None)
        # Whether the embedder would grant such an ask, read at the time
        # of the ask and never cached: a person can turn it on and off
        # while a pane runs. With no embedder every ask is granted,
        # because nothing is in the way.
        may_resize = may_resize or (lambda: True)

        self._history_cleanup_counter = 0

        # How many times this screen has written a row, and the count at
        # which each row last changed. Together they say which rows a
        # reader has to draw again. `touch` says why the state is shaped
        # this way. Lillecarl/pymux#126.
        self.writes = 0
        self.written_at: Dict[int, int] = {}

        # The count that a row with no count of its own carries. A
        # reader reads it as the default of `written_at`, so it costs a
        # reader nothing. `touch_everything` says why it exists.
        self.everything_at = 0

        self.savepoints: List[_Savepoint] = []
        self.lines = lines
        self.columns = columns
        self.write_process_input = write_process_input
        self.bell_func = bell_func
        self.get_history_limit = get_history_limit
        self.osc_func = osc_func
        self.resize_func = resize_func
        self.may_resize = may_resize

        # Stack of kitty keyboard protocol flags. ("CSI > flags u" pushes,
        # "CSI < number u" pops. See `report_kitty_keyboard`.)
        self.kitty_flags_stack: Tuple[int, ...] = ()

        # What the terminal that feeds this pane its keys can report,
        # in the same flags. The host sets it; zero means a terminal
        # that speaks the legacy encoding only. It belongs to the host
        # and not to the screen, so a reset leaves it alone.
        self.keyboard_source_flags: int = 0

        # Whether to make up the halves of a key event that such a
        # terminal cannot send. With it, a pane gets what it asked for
        # from any keyboard; without it, a pane hears that it does not
        # have it. The host sets this one as well.
        self.synthesize_key_events: bool = True

        # The shapes of the pointer that "OSC 22" pushed. Each screen
        # keeps its own, the way kitty does.
        self.pointer_shapes = PointerShapes()

        # Kitty graphics protocol state: transmitted images and their
        # placements. (Reset and alternate screen switching replace the
        # whole state; see `reset` and `set_mode`.)
        self.graphics = GraphicsState()

        self.reset()

    # ------------------------------------------------------------------
    # What a program turned on, as somebody outside asks it.
    #
    # A widget draws the screen and sends it keys. These say what the
    # program in it wants, so the widget does not read `self.mode`.

    @property
    def in_application_mode(self) -> bool:
        """
        True when we are in application mode. This means that the process is
        expecting some other key sequences as input. (Like for the arrows.)
        """
        # Not in cursor mode.
        return PrivateMode.APPLICATION_CURSOR_KEYS.flag in self.mode

    @property
    def mouse_support_enabled(self) -> bool:
        "True when mouse support has been enabled by the application."
        return PrivateMode.MOUSE_REPORTING.flag in self.mode

    @property
    def urxvt_mouse_support_enabled(self) -> bool:
        return PrivateMode.URXVT_MOUSE.flag in self.mode

    @property
    def sgr_mouse_support_enabled(self) -> bool:
        "Xterm Sgr mouse support."
        return PrivateMode.SGR_MOUSE.flag in self.mode

    @property
    def bracketed_paste_enabled(self) -> bool:
        return PrivateMode.BRACKETED_PASTE.flag in self.mode

    @property
    def kitty_keyboard_flags(self) -> int:
        """
        The currently effective kitty keyboard protocol flags. (The top of
        the flag stack, or zero when the stack is empty.)
        """
        return kitty_keys.current_flags(self.kitty_flags_stack)

    @property
    def deliverable_kitty_keyboard_flags(self) -> int:
        "The flags that this pane really gets, of the ones it asked for."
        return kitty_keys.deliverable_flags(
            self.kitty_keyboard_flags,
            self.keyboard_source_flags,
            self.synthesize_key_events,
        )

    @property
    def has_reverse_video(self) -> bool:
        "The whole screen is set to reverse video."
        return PrivateMode.REVERSE_VIDEO.flag in self.mode

    def encode_key(self, data: str) -> str:
        """
        The bytes that one key press sends to the program on this
        screen.

        Two modes decide it, and the screen holds both: the kitty
        keyboard protocol that the program turned on, and the
        application cursor keys of DECCKM. Neither belongs to whoever
        drew the keyboard, so a Textual widget and a prompt_toolkit
        widget send the same bytes for the same key.

        The kitty flags are the ones this pane really gets, and not the
        ones it asked for. One value answers the query of the pane and
        drives the encoding, so the answer holds.
        """
        return kitty_keys.translate_key_data(
            data,
            flags=self.deliverable_kitty_keyboard_flags,
            application_mode=self.in_application_mode,
            source_flags=self.keyboard_source_flags,
            synthesize=self.synthesize_key_events,
        )

    def wrap_paste(self, text: str) -> str:
        """
        Text that a person pasted, as the program on this screen wants
        it.

        A program that turned bracketed paste on is told where the
        paste starts and ends, so it can tell pasted text from typing.
        A program that did not gets the text as it stands.
        """
        if self.bracketed_paste_enabled:
            return "\x1b[200~" + text + "\x1b[201~"
        return text

    # ------------------------------------------------------------------
    # Answering a program.
    #
    # Every reply goes out through one of these, so the choice between
    # seven and eight bit controls is made in one place.

    def _control(self, final: str) -> str:
        """
        A C1 control, spelled the way the program asked for.

        Every C1 control has two spellings. Seven bits is `ESC` and a
        letter, and eight bits is the single byte 0x40 above that
        letter: `CSI` is `ESC [` or 0x9b. S8C1T ("ESC SP G") picks the
        second and S7C1T ("ESC SP F") picks the first.

        The mode exists so that a program can parse an answer without
        the escape. It has to reach every control the terminal writes,
        or the program still finds two bytes where it looks for one.
        xterm switches all of them in `unparseputc1`, and so does
        libvterm in `vterm_push_output_sprintf_ctrl`.

        A C1 byte is a byte and not a character, so UTF-8 has no
        spelling for it. It travels as a surrogate, which is Python's
        channel for exactly that, and the backend encodes it back with
        "surrogateescape".
        """
        if self.seven_bit_controls:
            return "\x1b" + final
        return chr(0xDC00 + 0x40 + ord(final))

    def reply_csi(self, body: str) -> None:
        "Answer with a control sequence."
        self.write_process_input(self._control("[") + body)

    def reply_dcs(self, body: str) -> None:
        "Answer with a device control string, closed with ST."
        self.write_process_input(self._control("P") + body + self._control("\\"))

    def reply_osc(self, body: str) -> None:
        "Answer with an operating system command, closed with ST."
        self.write_process_input(self._control("]") + body + self._control("\\"))

    def reply_apc(self, body: str) -> None:
        "Answer with an application program command, closed with ST."
        self.write_process_input(self._control("_") + body + self._control("\\"))

    def set_seven_bit_controls(self) -> None:
        'S7C1T ("ESC SP F"): answer with "ESC" and a letter.'
        self.seven_bit_controls = True

    def set_eight_bit_controls(self) -> None:
        'S8C1T ("ESC SP G"): answer with one C1 byte.'
        self.seven_bit_controls = False

    # ------------------------------------------------------------------
    # Starting over.
    #
    # RIS takes everything, DECSTR takes the settings and leaves the
    # text, and `_reset_screen` takes the cells alone.

    def reset(self) -> None:
        """Resets the terminal to its initial state.

        * Scroll margins are reset to screen boundaries.
        * Cursor is moved to home location -- ``(0, 0)`` and its
          attributes are set to defaults (see :attr:`default_char`).
        * Screen is cleared -- each character is reset to
          :attr:`default_char`.
        * Tabstops are reset to "every eight columns".

        .. note::

           Neither VT220 nor VT102 manuals mentioned that terminal modes
           and tabstops should be reset as well, thanks to
           :manpage:`xterm` -- we now know that.
        """
        # Is the terminal on the 132 column page, and was it allowed
        # onto it? Read both before the modes go. Reading them after is
        # the fault that `RISTests.test_RIS_ResetDECCOLM` of esctest2
        # names: an older xterm dropped DECCOLM first and then found
        # nothing to undo, so the page stayed wide.
        # `__init__` builds the state by calling this, so there are no
        # modes yet the first time round. A terminal that does not
        # exist yet is on no page.
        modes = getattr(self, "mode", frozenset())
        on_the_wide_page = (
            PrivateMode.ALLOW_80_TO_132.flag in modes
            and PrivateMode.COLUMNS_132.flag in modes
        )

        self._reset_screen()

        # What "ESC 7" saved goes with everything else. RIS is the
        # power-up state, and a terminal that has just been turned on
        # remembers no cursor.
        #
        # DECSTR already emptied this, and RIS did not, which is the
        # wrong way round: the soft reset is the weaker of the two.
        # Alacritty, Ghostty, kitty and xterm.js all forget the save on
        # RIS; libvterm and WezTerm keep it, and they keep it on DECSTR
        # as well, so neither of them is drawing the line where ptterm
        # drew it.
        #
        # A list of its own, because a save writes into the list that is
        # there rather than making a new one.
        self.savepoints: List[_Savepoint] = []

        # The window title, the icon label, the stack that "CSI 22 t"
        # pushes them onto and the modes that say how they are written.
        # A reset gives a fresh one, the way it takes away everything
        # else that a program set.
        self.titles = Titles()

        # Reset the kitty keyboard protocol flag stack as well. (RIS is a
        # full terminal reset. It also clears all graphics.)
        self.kitty_flags_stack = ()
        self.graphics.clear()

        # The shape of the cursor, as DECSCUSR names it. A reset puts
        # it back to the shape that the terminal starts with.
        self.cursor_style = DEFAULT_CURSOR_STYLE

        # Has a program in here ever said what the cursor should look
        # like? Until one does, the shape above is a guess and not an
        # ask, and whoever draws this pane has to leave the cursor of
        # the person alone. A pane that names a shape nobody asked for
        # takes away the one they chose.
        self.cursor_style_asked = False

        # The marks that SPA and DECSCA put on the cells that a
        # program draws next. Nothing is marked to start with.
        self.protection = 0

        # The character that REP repeats. Nothing is drawn yet, so a
        # repeat now draws nothing.
        self.last_character = ""

        # The private modes that XTSAVE put away, by the number that
        # the sequence carries. XTRESTORE reads them. A mode that was
        # never saved is not here, and a restore of it changes
        # nothing.
        self.saved_modes: Dict[int, bool] = {}

        # The colours that a program set with "OSC 4", "OSC 5" and
        # "OSC 10". A pane starts with nothing set and answers a query
        # from the defaults. A reset gives a fresh one, so every colour
        # a program asked for goes away together.
        self.colors = ColorOverrides()

        # Does the cursor wait to wrap? A character in the last column
        # of the line leaves the cursor one column further, and the
        # next character starts the line below.
        #
        # The place alone does not say so. With a right margin the wait
        # sits one column after the margin, and a program can put the
        # cursor there itself. The two look the same and behave
        # differently, so the wait is a flag and not a place.
        self.pending_wrap = False

        # The settings that a program writes and reads back with
        # DECRQSS. ptterm keeps each one and acts on none of them; the
        # docstring of each handler says what it would do.
        self.attribute_extent = AttributeExtent.STREAM
        self.active_display = StatusDisplay.MAIN
        self.status_line = StatusLineType.NONE
        self.conformance_level = DEFAULT_CONFORMANCE_LEVEL
        self.seven_bit_controls = True
        self.lines_per_screen = self.lines

        # Reset modes.
        self.mode = {
            # Autowrap mode. (default: disabled).
            PrivateMode.AUTOWRAP.flag,
            # Text cursor enable mode. (default enabled).
            PrivateMode.SHOW_CURSOR.flag,
        }

        # According to VT220 manual and ``linux/drivers/tty/vt.c``
        # the default G0 charset is latin-1, but for reasons unknown
        # latin-1 breaks ascii-graphics; so G0 defaults to cp437.

        # XXX: The comment above comes from the original Pyte implementation,
        #      it seems for us that LAT1_MAP should indeed be the default, if
        #      not a French version of Vim would incorrectly show some
        #      characters.
        # Has a double width character ever reached the screen? Nearly
        # no pane draws one, and the repair that a broken pair needs
        # costs a lookup for every character. The flag skips it.
        self._wide_chars = False

        # Has a cell that an erase has to leave alone ever reached the
        # screen? Nearly no program marks one, and the flag keeps the
        # erasing of a whole screen from looking at every cell.
        self._protected_chars = False

        # G1 holds ASCII as well until a program names something
        # else. pyte starts it on the line drawing set, and a stray
        # shift out then turned every letter into a box character.
        self.charset = 0
        # self.g0_charset = cs.IBMPC_MAP
        self.g0_charset = cs.LAT1_MAP
        self.g1_charset = cs.LAT1_MAP

        # From ``man terminfo`` -- "... hardware tabs are initially
        # set every `n` spaces when the terminal is powered up. Since
        # we aim to support VT102 / VT220 and linux -- we use n = 8.

        # (We choose to create tab stops until x=1000, because we keep the
        # tab stops when the screen increases in size. The OS X 'ls' command
        # relies on the stops to be there.)
        self.tabstops = set(range(8, 1000, 8))

        # The first page, while the alternate screen is in front.
        self._original_screen: Page | None = None
        # The alternate screen, while the first one is in front. A
        # terminal keeps one alternate screen for its whole life and
        # hands it back with what it held, so this outlives a visit.
        # `None` means that nothing was ever drawn on it.
        self._alternate_screen: Page | None = None
        self._alternate_screen_vars: dict = {}

        # A reset gives the 80 column page back. The ask goes out last,
        # because the modes above decide whether it goes out at all,
        # and the embedder answers it by resizing this screen.
        #
        # The page is clear already, so this does not clear it again
        # the way DECCOLM does.
        if on_the_wide_page:
            self.resize_func(None, self.NARROW_PAGE)

    def soft_reset(self, *params: int, **kwargs) -> None:
        """
        DECSTR ("CSI ! p"): put the settings back, and keep the screen.

        A soft reset leaves the text and the cursor where they are. It
        takes away what a program changed about the terminal, so that
        the next program starts from one that it knows. A program that
        ends sends this, and a program that starts sends it as well.

        The scrolling region goes back to the whole screen, in the rows
        and in the columns, and the cursor that a save remembers goes
        home. Autowrap stays on: the DEC manuals turn it off, and xterm
        keeps it on because programs came to count on it.

        The alternate screen is not a setting of this kind. A soft
        reset on it leaves it in front, the way xterm does.
        """
        self.margins = None
        self.horizontal_margins = None

        alternate = self.mode.intersection(self._ALTERNATE_SCREEN_MODES)
        self.mode = {PrivateMode.AUTOWRAP.flag, PrivateMode.SHOW_CURSOR.flag}
        self.mode.update(alternate)
        self.page.show_cursor = True

        # A list of its own, because a save writes into the list that
        # is there rather than making a new one.
        self.savepoints = []

        self.charset = 0
        self.g0_charset = cs.LAT1_MAP
        self.g1_charset = cs.LAT1_MAP

        # A soft reset takes the mark off what a program draws next.
        # The cells that carry one already keep it.
        self.protection = 0

        self._reset_rendition()

    # ------------------------------------------------------------------
    # Protection: which cells an erase leaves alone.
    #
    # Two commands mark a cell and each one holds a different erase
    # away from it. `cells.Protection` carries both marks.

    def start_protected_area(self) -> None:
        """
        SPA ("ESC V"): mark the cells that a program draws next.

        ED, EL and ECH leave a marked cell alone. The mark comes from
        ISO 6429, and it is not the mark that DECSCA sets: the
        selective erases read both, and these three read only this
        one.
        """
        self.protection |= Protection.ISO

    def end_protected_area(self) -> None:
        "EPA (\"ESC W\"): stop marking the cells that a program draws."
        self.protection &= ~Protection.ISO

    def set_character_protection(self, *params: int, **kwargs) -> None:
        """
        DECSCA ("CSI Ps " q"): mark the cells that a program draws next.

        One marks them, and zero and two take the mark away. DECSED and
        DECSEL leave a marked cell alone, and ED, EL and ECH do not:
        that is the whole difference between the two pairs.
        """
        if (params[0] if params else 0) == 1:
            self.protection |= Protection.DEC
        else:
            self.protection &= ~Protection.DEC

    def _erase_holds(self, cell: Cell, selective: bool) -> bool:
        """
        True when an erase has to leave this cell alone.

        A selective erase reads both marks. xterm reads the mark of
        ISO 6429 there as well, for the programs that came before
        DECSCA, and this follows xterm.
        """
        if not self._protected_chars:
            return False

        marks = protection_of(cell)
        if not marks:
            return False
        return True if selective else bool(marks & Protection.ISO)

    def _reset_rendition(self) -> None:
        """
        Draw what comes next plainly, and under no hyperlink.

        A screen carries neither: its cells hold the rendition and the
        link that they were drawn with. Taking a screen therefore
        starts plain, whether the screen is a new one or the one that
        the last visit left.
        """
        self._rendition = PLAIN
        # The target of the hyperlink that is open ("OSC 8"), and the
        # id that joins its pieces. These two are what a program last
        # sent, and a program may send an id with no target. **A cell
        # carries `appearance.hyperlink_id`, which is empty whenever
        # there is no link.** Read that one to draw.
        self.hyperlink = ""
        self.hyperlink_id = ""
        # The two together, which is what a cell carries. They change
        # apart from each other, so this is rebuilt from both.
        self._appearance = PLAIN_APPEARANCE

    # -- which rows have changed ------------------------------------------
    #
    # A front end draws every visible row of every frame, because
    # nothing says which rows moved. These three say it.
    #
    # **The state that decides a redraw lives on the reader.** A set of
    # dirty rows here would need somebody to empty it, and there is no
    # such person: two widgets draw one screen, and pymux gives several
    # clients one pane. A screen that knew its readers would have to
    # register them, and a pure layer that tracks its consumers is not
    # pure. A count that only goes up needs no emptying. Each reader
    # keeps the count it last drew, per row, and a reader that attaches
    # late remembers nothing, so every row looks new and it draws the
    # whole screen once. Lillecarl/pymux#126.

    # ------------------------------------------------------------------
    # What a reader has to draw again.
    #
    # The screen counts writes per row and every reader keeps its own
    # mark, because two widgets and several clients read one screen.
    # Lillecarl/pymux#128.

    def touch(self, row: int) -> None:
        "Say that one row of `data_buffer` has changed."
        self.writes += 1
        self.written_at[row] = self.writes

    def touch_rows(self, rows: Iterable[int]) -> None:
        "Say that each of these rows has changed."
        writes = self.writes
        written_at = self.written_at
        for row in rows:
            writes += 1
            written_at[row] = writes
        self.writes = writes

    def touch_everything(self) -> None:
        """
        Say that every row a reader could hold has changed.

        A reset, a switch to the other page and a reflow all replace the
        buffer rather than write into it. The rows a reader remembers
        are gone, and the rows that take their numbers are new, so both
        sets have to say so. A row that no longer exists says so as
        well: without that, a reader keeps drawing one that went.

        **It says it once, and not once per row.** Every row takes its
        count from `everything_at` while it has none of its own, so
        emptying `written_at` moves all of them at the same time. A row
        written afterwards takes a larger count and moves again.

        Writing on each row instead cost the whole buffer. Opening a
        full screen program and closing it again touches every row four
        times, which at fifty thousand rows of history was a million
        and a half bytecode instructions for two escape sequences.
        Lillecarl/pymux#8.
        """
        self.writes += 1
        self.everything_at = self.writes
        self.written_at.clear()

    def _reset_screen(self) -> None:
        """Reset the Screen content. (also called when switching from/to
        alternate buffer."""
        # Before the page goes, so that the rows it held are counted.
        # The first call of all builds the page, and there is nothing to
        # count then.
        if hasattr(self, "page"):
            self.touch_everything()
        self.page = Page(default_char=Cell(" ", PLAIN_APPEARANCE))

        self.data_buffer = self.page.data_buffer
        self.pt_cursor_position = CursorPosition(0, 0)

        self._reset_rendition()

        self.margins = None
        self.horizontal_margins: HorizontalMargins | None = None

        # One of its own, because the stack is changed in place and the
        # screen this one replaces still holds the old object.
        self.pointer_shapes = PointerShapes()

        self.max_y = 0  # Max 'y' position to which is written.

        #: The lowest row number the buffer can hold. Everything under
        #: it left the history and is gone for good.
        #:
        #: It is here so that a prune costs the rows it drops and not
        #: the rows it keeps. A pane at fifty thousand rows prunes a
        #: hundred of them at a time, and reading the whole buffer to
        #: find those hundred made printing a line three times as
        #: expensive as it is at two thousand. Lillecarl/pymux#8.
        self.history_floor = 0

        #: The lowest row that is laid out at the width the screen has
        #: now. A reflow lays out the screen and the lines that reach
        #: it, and leaves the history alone, so a row under this one
        #: keeps the width it was written at. Lillecarl/pymux#135.
        self.reflow_floor = 0

    #: The two page widths that DECCOLM names.
    NARROW_PAGE = 80
    WIDE_PAGE = 132

    #: The private modes that a later DEC terminal brought, and the
    #: level that brought each one. DECSCL can ask for an earlier
    #: terminal, and then the mode is not there to set.
    _MODE_LEVELS = {
        PrivateMode.LEFT_RIGHT_MARGIN: ConformanceLevel.VT400,
        PrivateMode.NO_CLEAR_ON_COLUMN_CHANGE: ConformanceLevel.VT500,
    }

    # ------------------------------------------------------------------
    # Which modes this terminal has at all.
    #
    # DECSCL can ask for an earlier terminal, and a mode a later one
    # brought is then not there to set. The embedder gates a few more.

    def _level_carries(self, number: int) -> bool:
        """
        Does the terminal that DECSCL named carry this private mode?

        A mode that no DEC terminal ever had is carried at every level:
        the levels say what a DEC terminal is, and xterm adds its own
        modes on top of all of them.
        """
        needed = self._MODE_LEVELS.get(number)
        return needed is None or self.conformance_level >= needed

    #: The private modes that exist only where the embedder will give a
    #: pane room. They are not features of the emulator: they are ways
    #: for a program to ask for a different page, and a pane that cannot
    #: have one has no honest answer but "I do not know that mode".
    #:
    #: xterm keeps DECNCSM behind its `allowWindowOps` resource, and
    #: esctest2 marks `DECRQMTests.test_DECRQM_DEC_DECNCSM`
    #: `optionRequired` on it. A pane's version of that resource is
    #: `allow-program-resize`.
    #:
    #: **DECCOLM and its mode 40 are not in here, and the suite is why.**
    #: `DECSCLTests.test_DECSCL_Level4_SupportsDECSLRMDoesntSupportDECNCSM`
    #: carries no such marker, so xterm takes mode 40 whatever the
    #: resource says, and DECCOLM still clears the page. Refusing the
    #: mode would stop the clear as well, and that test would fail.
    _MODES_THE_EMBEDDER_GATES = frozenset([PrivateMode.NO_CLEAR_ON_COLUMN_CHANGE])

    def _embedder_carries(self, number: int) -> bool:
        """
        Will the embedder let this screen carry this private mode?

        Read every time and never cached: a person can turn
        `allow-program-resize` on and off while a pane runs, and a
        program that asks twice deserves the answer that holds now.

        Only the modes in `_MODES_THE_EMBEDDER_GATES` can be refused.
        Everything else the embedder has no opinion about.
        """
        if number not in self._MODES_THE_EMBEDDER_GATES:
            return True
        return self.may_resize()

    def _carries(self, number: int) -> bool:
        """
        Does this screen carry this private mode at all, right now?

        Two things can take a mode away. DECSCL names a terminal that
        never had it, and the embedder refuses the room that the mode is
        about.
        """
        return self._level_carries(number) and self._embedder_carries(number)

    def _may_change_the_page_width(self) -> bool:
        """
        May DECCOLM take the page between 80 and 132 columns?

        Only while private mode 40 is set. xterm keeps the width behind
        that mode because DECCOLM clears the screen, and a program that
        sets it by accident would throw the screen away.
        """
        return PrivateMode.ALLOW_80_TO_132.flag in self.mode

    def _ask_for_page_width(self, columns: int) -> None:
        """
        DECCOLM: ask for a page of `columns` columns, and clear it.

        The width goes through `resize_func`, the way every other ask
        for room does. A pane is not a window: it sits in a layout, and
        the embedder decides whether it may grow and how far. So the
        pane may end up no wider than it was.

        The screen is cleared and the cursor goes home. That is what a
        DEC terminal does, and a program that sends DECCOLM expects to
        start from an empty page. DECNCSM ("?95") is how a program says
        it wants to keep what is there.
        """
        self.resize_func(None, columns)
        if self._keeps_the_page_through_a_width_change():
            return
        self.erase_in_display(2)
        self.cursor_position()

    def _keeps_the_page_through_a_width_change(self) -> bool:
        """
        Does DECNCSM hold the page through a DECCOLM?

        The VT510 brought the mode, so a program that asked for an
        earlier terminal with DECSCL does not get it. esctest2 asks for
        both readings, at level 4 and at level 5.
        """
        if self.conformance_level < ConformanceLevel.VT500:
            return False
        return PrivateMode.NO_CLEAR_ON_COLUMN_CHANGE.flag in self.mode

    # ------------------------------------------------------------------
    # The size of the screen.
    #
    # A resize lays the buffer out again at the new width; `_reflow` at
    # the end of this file does that work.

    def resize(
        self, lines: int | None = None, columns: int | None = None
    ) -> None:
        # Save the dimensions.
        lines = lines if lines is not None else self.lines
        columns = columns if columns is not None else self.columns

        if self.lines != lines or self.columns != columns:
            self.lines = lines
            self.columns = columns

            self._reset_offset_and_margins()

            # If the height was reduced, and there are lines below
            # `cursor_position_y+lines`. Remove them by setting 'max_y'.
            # (If we don't do this. Clearing the screen, followed by reducing
            # the height will keep the cursor at the top, hiding some content.)
            self.max_y = min(self.max_y, self.pt_cursor_position.y + lines - 1)

            self._reflow()

            # A program that asked for it learns the new size in band.
            self.notify_of_resize()

    def notify_of_resize(self) -> None:
        """
        Tell the program in this pane how big the pane is, in band.

        A program that sets private mode 2048 reads the size from its
        own input instead of from SIGWINCH. That is what a program
        behind a multiplexer or an ssh connection needs: the signal
        does not travel, the escape sequence does.

        The pixel size follows the cell that `pyte.images` assumes,
        so it agrees with what "CSI 14 t" and "CSI 16 t" report.
        """
        if PrivateMode.INBAND_RESIZE.flag not in self.mode:
            return

        self.reply_csi(
            "48;%i;%i;%i;%it"
            % (
                self.lines,
                self.columns,
                self.lines * ASSUMED_CELL_HEIGHT,
                self.columns * ASSUMED_CELL_WIDTH,
            )
        )

    # ------------------------------------------------------------------
    # The rows of the buffer.
    #
    # The buffer holds the history above the screen, so a row number is
    # not a row of the screen. `line_offset` is the first row shown.
    # A note about a row lives on the `Row`. Lillecarl/pymux#134.

    @property
    def line_offset(self) -> int:
        "Return the index of the first visible line."
        cpos_y = self.pt_cursor_position.y

        # NOTE: the +1 is required because `max_y` starts counting at 0 for the
        #       first line, while `self.lines` is the number of lines, starting
        #       at 1 for one line. The offset refers to the index of the first
        #       visible line.
        #       For instance, if we have: max_y=14 and lines=15. Then all lines
        #       from 0..14 have been used. This means 15 lines are used, and
        #       the first index should be 0.
        return max(0, self.max_y - self.lines + 1)

    def is_wrapped(self, row: int) -> bool:
        """
        Whether a wrap brought this row into being, so that it holds
        the rest of the row above it.

        **It does not make the row.** The buffer answers a missing row
        with a new one, and a question must not write: a row under
        `history_floor` would come back from the dead, and a row above
        the screen would move the top of the buffer.
        """
        line = self.page.data_buffer.get(row)
        return line is not None and line.wrapped

    def set_wrapped(self, row: int, wrapped: bool = True) -> None:
        """
        Say that a wrap did or did not bring this row into being.

        Saying that one did makes the row, because the text that
        wrapped onto it is about to be written there. Saying that one
        did not leaves a row that is not there alone.
        """
        if wrapped:
            self.page.data_buffer[row].wrapped = True
            return
        line = self.page.data_buffer.get(row)
        if line is not None:
            line.wrapped = False

    def attribute_of(self, row: int) -> "LineAttribute | None":
        "The DEC line attribute of a row, without making the row."
        line = self.page.data_buffer.get(row)
        return None if line is None else line.attribute

    def highest_row(self) -> int:
        """
        The highest row a front end has to draw.

        That is the highest row of the buffer, or `max_y` when the
        buffer stops above it. A front end counts its rows with this,
        and it counts them on every frame.

        **It does not read the buffer.** `max(data_buffer)` walks every
        key, and the buffer holds the history: fifty thousand rows on a
        pane a person set up to scroll back a long way, once per frame.
        Lillecarl/pymux#130.

        The search is the screen instead, and usually nothing at all. A
        row is written where the cursor stands or inside the scrolling
        region, and both are inside the screen, so **no row of the
        buffer sits above `line_offset + lines - 1`**. Once the screen
        has filled once, `line_offset` is `max_y - lines + 1` and that
        last row is `max_y` itself, so the loop below runs no times. It
        runs at most `lines` times on a screen that has not filled yet,
        whatever the history holds.

        `pyte/tests/test_the_top_of_the_buffer.py` is the proof: it
        hunts generated output for a row above the screen, and for an
        answer here that differs from reading the whole buffer.
        """
        data_buffer = self.page.data_buffer
        highest = self.max_y
        for row in range(highest + 1, self.line_offset + self.lines):
            if row in data_buffer:
                highest = row
        return highest

    # ------------------------------------------------------------------
    # The margins, and where the cursor says it is.
    #
    # DECSTBM names the first and the last row, DECSLRM the first and
    # the last column. Origin mode counts the cursor from the margins,
    # so what the cursor reports is not where it stands in the buffer.

    def set_margins(self, *params: int, **kwargs) -> None:
        """Selects top and bottom margins for the scrolling region.
        Margins determine which screen lines move during scrolling
        (see :meth:`index` and :meth:`reverse_index`). Characters added
        outside the scrolling region do not cause the screen to scroll.
        :param int top: the smallest line number that is scrolled.
        :param int bottom: the biggest line number that is scrolled.

        With the private marker the same final byte is XTRESTORE, which
        brings back the modes that XTSAVE put away. One byte, two
        commands, and the marker says which; xterm does the same.
        """
        if kwargs.get("private") is True:
            self.restore_modes(*params)
            return

        # A parameter that is missing and a parameter that is zero both
        # mean the default, which is the first row and the last. So
        # "CSI r" names the whole screen, and that is how a program
        # gives the screen back after it has used a region.
        first = params[0] if len(params) > 0 else 0
        last = params[1] if len(params) > 1 else 0

        # The parameters count from one and the margins count from
        # zero, and both stay on the screen.
        top = max(0, min((first or 1) - 1, self.lines - 1))
        bottom = max(0, min((last or self.lines) - 1, self.lines - 1))

        # Even though VT102 and VT220 require DECSTBM to ignore regions
        # of width less than 2, some programs (like aptitude for example)
        # rely on it. Practicality beats purity.
        if bottom - top < 1:
            return

        if top == 0 and bottom == self.lines - 1:
            # The whole screen is no region at all. `None` is what the
            # rest of the screen reads as "there is no region", the way
            # DECSLRM writes it for the columns.
            self.margins = None
        else:
            self.margins = Margins(top, bottom)

        # The cursor moves to the home position when the top and
        # bottom margins of the scrolling region (DECSTBM) changes.
        self.cursor_position()

    @property
    def left_right(self) -> Tuple[int, int]:
        """
        The first and the last column of the scrolling region.

        Without margins the region is the whole width, so the answer is
        the first and the last column of the screen. Every caller then
        reads one pair and needs no test of its own.
        """
        margins = self.horizontal_margins
        if margins is None:
            return 0, self.columns - 1
        return margins

    @property
    def reported_column(self) -> int:
        """
        The column that the cursor stands on, counted from zero.

        A character in the last column leaves the cursor one column
        further, where it waits to wrap. The cursor still stands on the
        last column, and that is the column that a report names. With a
        right margin the wait sits one column after the margin instead.

        A program can put the cursor on that column itself, and then it
        really stands there. Only the wait folds back, so the flag
        decides and not the place.
        """
        column = self.pt_cursor_position.x
        _left, right = self.left_right
        if self.pending_wrap and column == right + 1:
            return right
        return min(column, self.columns - 1)

    @property
    def reported_position(self) -> Tuple[int, int]:
        """
        The row and the column that a cursor report names, counted
        from one.

        Origin mode moves the origin to the corner of the scrolling
        region. It moves it for a report as well as for a move: a
        program that places the cursor at the corner and reads the
        position back has to read the corner. So the margins come off
        the answer while the mode is on.

        The two have to agree. `cursor_position` adds the margins to a
        place that a program writes, and this takes them off a place
        that a program reads.
        """
        row = self.pt_cursor_position.y - self.line_offset
        column = self.reported_column
        if PrivateMode.ORIGIN.flag in self.mode:
            top, _bottom = self.margins or Margins(0, self.lines - 1)
            left, _right = self.left_right
            row -= top
            column -= left
        return row + 1, column + 1

    def _cursor_is_between_the_left_and_right_margins(self) -> bool:
        """
        True when the cursor stands in the columns of the region.

        A line feed scrolls the region only from inside it, and the
        commands that insert or delete do nothing from outside it.
        Without margins the answer is always true.
        """
        if self.horizontal_margins is None:
            return True
        left, right = self.horizontal_margins
        return left <= self.pt_cursor_position.x <= right

    def set_left_right_margins(self, *params: int, **kwargs) -> None:
        """
        DECSLRM ("CSI Pl ; Pr s"): the columns of the scrolling region.

        The sequence works only while private mode 69 (DECLRMM) is set.
        Without the mode the same final byte names SCOSC, which saves
        the cursor. So a terminal reads one byte two ways, and the mode
        says which. xterm does the same.

        A region needs two columns, the way the rows of DECSTBM do, and
        the whole width is no region at all. The cursor goes home
        afterwards, which is what DECSTBM does as well.
        """
        if kwargs.get("private") is True:
            # XTSAVE. The private marker makes the same final byte put
            # modes away instead of naming a region.
            self.save_modes(*params)
            return

        if PrivateMode.LEFT_RIGHT_MARGIN.flag not in self.mode:
            # SCOSC. It saves what DECSC saves, and SCORC ("CSI u")
            # brings it back.
            self.save_cursor()
            return

        left = (params[0] if len(params) > 0 else 0) or 1
        right = (params[1] if len(params) > 1 else 0) or self.columns

        left = max(1, min(left, self.columns))
        right = max(1, min(right, self.columns))
        if right - left < 1:
            return

        if left == 1 and right == self.columns:
            self.horizontal_margins = None
        else:
            self.horizontal_margins = HorizontalMargins(left - 1, right - 1)

        self.cursor_position()

    def _reset_offset_and_margins(self) -> None:
        """
        Recalculate offset and move cursor (make sure that the bottom is
        visible.)
        """
        self.margins = None
        self.horizontal_margins = None

    # ------------------------------------------------------------------
    # The character sets.
    #
    # Two slots and a shift between them. `draw` translates through the
    # one that is in, so `charsets.py` holds the tables.

    def define_charset(self, code: str, mode: str = "(") -> None:
        """Define the ``G0`` or the ``G1`` charset.

        :param str code: character set code, should be a character
                         from ``"B0UK"`` -- otherwise ignored.
        :param str mode: if ``"("`` ``G0`` charset is set, if
                         ``")"`` -- we operate on ``G1``.

        ``ESC ( 0`` picks the line drawing set of the DEC terminals,
        which is how a program without a Unicode font draws a box.

        .. warning:: User-defined charsets are currently not supported.
        """
        if code in cs.MAPS:
            charset_map = cs.MAPS[code]
            if mode == "(":
                self.g0_charset = charset_map
            elif mode == ")":
                self.g1_charset = charset_map

    # ------------------------------------------------------------------
    # Turning a mode on and off.
    #
    # `self.mode` holds both kinds, with a private one shifted; see
    # `modes.py`. The alternate screen hangs off three of them, so the
    # swap of the two pages is here as well.

    def set_mode(self, *modes, **kwargs) -> None:
        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = tuple(flag_of(mode) for mode in modes if self._carries(mode))

        self.mode.update(modes)

        if PrivateMode.CURSOR_BLINK.flag in modes:
            self.set_cursor_blink(True)

        if PrivateMode.SAVE_CURSOR.flag in modes:
            self.save_cursor()

        # The program asked to be told the size in band. Tell it now,
        # so that it need not ask separately. (kitty answers a repeated
        # set the same way.)
        if PrivateMode.INBAND_RESIZE.flag in modes:
            self.notify_of_resize()

        # DECLRMM takes the DEC line attributes off every line. A left
        # or a right margin cuts a line in two, and half a double width
        # line is not a thing a terminal can draw. libvterm clears them
        # here too, in the DECVSSM branch of its `src/state.c`.
        if PrivateMode.LEFT_RIGHT_MARGIN.flag in modes:
            for line in self.page.data_buffer.values():
                line.attribute = None

        # DECCOLM takes the page to 132 columns, clears it and puts the
        # cursor home.
        if (
            PrivateMode.COLUMNS_132.flag in modes
            and self._may_change_the_page_width()
        ):
            self._ask_for_page_width(self.WIDE_PAGE)

        # According to `vttest`, DECOM should also home the cursor, see
        # vttest/main.c:303.
        if PrivateMode.ORIGIN.flag in modes:
            self.cursor_position()

        # Make the cursor visible.
        if PrivateMode.SHOW_CURSOR.flag in modes:
            self.page.show_cursor = True

        # On "\e[?1049h", enter alternate screen mode. Backup the current
        # state. "?47" and "?1047" name the same screen; they are what a
        # program that predates "?1049" sends.
        taken_by = self._alternate_screen_modes(modes)
        if taken_by and not self._original_screen:
            # "?1049" saves the cursor of the first screen, the same
            # way "ESC 7" does: the place, the rendition and the
            # character sets all come back with it. The two older modes
            # save nothing.
            if PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag in taken_by:
                self.save_cursor()

            # Where the cursor stands, as a row of the screen rather
            # than a row of the buffer. Taking the other screen moves
            # the buffer under it.
            held_column = self.pt_cursor_position.x
            held_row = self.pt_cursor_position.y - self.line_offset

            self._original_screen = self.page
            self._original_screen_vars = {
                v: getattr(self, v) for v in self.swap_variables
            }
            # The scrolling region belongs to the terminal and not to
            # one of its screens, so it survives the switch. xterm and
            # kitty both keep it.
            margins = self.margins
            horizontal_margins = self.horizontal_margins

            # "?1049" clears the screen it takes. The two older modes
            # do not, so they find what the last visit left.
            keeps_the_content = (
                PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag not in taken_by
                and self._alternate_screen is not None
            )
            if keeps_the_content:
                # The buffer is replaced rather than written into, so
                # both sets of rows have to say so: the ones a reader
                # holds, and the ones that take their numbers.
                # Lillecarl/pymux#126.
                self.touch_everything()
                self.page = self._alternate_screen
                for name, value in self._alternate_screen_vars.items():
                    setattr(self, name, value)
                self.touch_everything()
                self._alternate_screen = None
                self._alternate_screen_vars = {}

                # The cursor is not part of what the screen held, so
                # the wait for a wrap on the other screen goes away.
                self.pending_wrap = False
                # A screen carries no rendition and no link of its own:
                # its cells hold the ones they were drawn with.
                self._reset_rendition()
            else:
                self._reset_screen()
                # What "ESC 7" saved on the alternate screen comes back
                # with the screen. "?1049h" clears the content, and it
                # does not touch the saved cursor: xterm keeps one per
                # screen, for the life of the terminal, so a program
                # that takes the alternate screen again finds the save
                # that the last one left.
                #
                # kitty, WezTerm, Alacritty, libvterm, Ghostty and
                # xterm.js all give that save back. Only ptterm sent
                # the cursor home instead.
                #
                # It is the list the leave put away, so a save on the
                # alternate screen writes into that one and not into
                # the list the first screen holds.
                self.savepoints = self._alternate_screen_vars.get("savepoints", [])

                # The alternate screen has its own, empty kitty keyboard
                # flag stack and its own graphics state. (The main screen
                # state is restored by the swap variables when leaving
                # the alternate screen.)
                self.kitty_flags_stack = ()
                self.graphics = GraphicsState()

            self.margins = margins
            self.horizontal_margins = horizontal_margins

            # "?47" and "?1047" leave the cursor where it stands.
            # xterm does, and so do WezTerm, Alacritty, libvterm,
            # Ghostty and xterm.js; only kitty puts it home.
            #
            # "?1049" does put it home here, and that is a choice and
            # not an answer: kitty and WezTerm put it home, and
            # Alacritty, Ghostty, libvterm and xterm.js leave it.
            # Entry 17 of `tests/DEVIATIONS.md` holds the argument, and
            # Lillecarl/pymux#34 holds the question.
            if PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag not in taken_by:
                self.pt_cursor_position.x = held_column
                self.pt_cursor_position.y = held_row + self.line_offset
                self.ensure_bounds()

    def reset_mode(self, *modes_args, **kwargs) -> None:
        """Resets (disables) a given list of modes.

        :param list modes: modes to reset -- hopefully, each mode is a
                           member of `AnsiMode` or the `flag` of a
                           `PrivateMode`.
        """
        modes = list(modes_args)

        # Private mode codes are shifted, to be distingiushed from non
        # private ones.
        if kwargs.get("private"):
            modes = [mode << 5 for mode in modes]

        self.mode.difference_update(modes)

        if PrivateMode.CURSOR_BLINK.flag in modes:
            self.set_cursor_blink(False)

        if PrivateMode.SAVE_CURSOR.flag in modes:
            self.restore_cursor()

        # DECLRMM off takes the columns of the region away. The region
        # is the whole width again, and a later DECSLRM does nothing
        # until a program sets the mode again.
        if PrivateMode.LEFT_RIGHT_MARGIN.flag in modes:
            self.horizontal_margins = None

        # Lines below follow the logic in :meth:`set_mode`.
        if (
            PrivateMode.COLUMNS_132.flag in modes
            and self._may_change_the_page_width()
        ):
            self._ask_for_page_width(self.NARROW_PAGE)

        if PrivateMode.ORIGIN.flag in modes:
            self.cursor_position()

        # Hide the cursor.
        if PrivateMode.SHOW_CURSOR.flag in modes:
            self.page.show_cursor = False

        # On "\e[?1049l", restore from alternate screen mode. "?47" and
        # "?1047" give the screen back as well.
        given_back = self._alternate_screen_modes(modes)
        if self._original_screen and given_back:
            restores_the_cursor = (
                PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag in given_back
            )
            row = self.pt_cursor_position.y - self.line_offset
            column = self.pt_cursor_position.x

            # The screen that is given back is kept, not thrown away:
            # a terminal has one alternate screen for its whole life
            # and hands it back with what it held. "?1047" is the
            # exception. xterm clears the alternate screen before it
            # switches back, and libvterm does the same; kitty keeps it.
            if PrivateMode.ALTERNATE_SCREEN_AGAIN.flag in given_back:
                self._alternate_screen = None
                self._alternate_screen_vars = {}
            else:
                self._alternate_screen = self.page
                self._alternate_screen_vars = {
                    name: getattr(self, name) for name in self.swap_variables
                }

            # The rows of the screen that is being left, and then the
            # rows of the one that comes back. Lillecarl/pymux#126.
            self.touch_everything()
            for k, v in self._original_screen_vars.items():
                setattr(self, k, v)
            self.page = self._original_screen
            self.touch_everything()

            self._original_screen = None
            self._original_screen_vars = {}

            # A link that the program on the alternate screen left open
            # belongs to that screen. Without this, everything the shell
            # writes afterwards is a link to whatever it opened.
            self.set_hyperlink("")

            if restores_the_cursor:
                # The same as "ESC 8". With nothing saved it is the
                # home position, and the character sets of the start.
                self.restore_cursor()
            else:
                # "?47" and "?1047" save no cursor, so the cursor stays
                # where the program that drew the alternate screen left
                # it.
                self.pt_cursor_position.y = row + self.line_offset
                self.pt_cursor_position.x = column
                self.ensure_bounds()

    #: The private modes that name the alternate screen. "?1049" also
    #: saves the cursor; the two older ones do not.
    _ALTERNATE_SCREEN_MODES = (
        PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR.flag,
        PrivateMode.ALTERNATE_SCREEN_AGAIN.flag,
        PrivateMode.ALTERNATE_SCREEN.flag,
    )

    @classmethod
    def _alternate_screen_modes(cls, modes) -> "List[int]":
        "The modes of this list that name the alternate screen."
        return [mode for mode in cls._ALTERNATE_SCREEN_MODES if mode in modes]

    @property
    def in_alternate_screen(self) -> bool:
        return bool(self._original_screen)

    def shift_in(self) -> None:
        "Activates ``G0`` character set."
        self.charset = 0

    def shift_out(self) -> None:
        "Activates ``G1`` character set."
        self.charset = 1

    # ------------------------------------------------------------------
    # Drawing.
    #
    # The one hot path of this file. Everything it needs is read as a
    # field, and the wait to wrap is the state it keeps between calls.

    def repair_wide_char(self, row, column: int) -> None:
        """
        Take away the half of a double width character that an edit at
        `column` leaves on its own.

        A double width character lives in two cells: the character in
        the first and an empty string in the second. An edit that
        touches one of the two leaves half a character behind. No
        terminal draws that, so the other half goes away as well.

        The two cells around `column` are the ones an edit can break:
        the cell before it and the cell itself.
        """
        columns = self.columns
        for position in (column - 1, column):
            if position < 0 or position >= columns:
                continue
            cell = row.get(position)
            if cell is None:
                continue
            if cell.width > 1:
                # The empty second half has to follow.
                after = row.get(position + 1)
                if position + 1 >= columns or after is None or after.char != "":
                    row.pop(position, None)
            elif cell.char == "":
                # The character has to come before.
                before = row.get(position - 1)
                if position == 0 or before is None or before.width < 2:
                    row.pop(position, None)

    def draw(self, chars: str) -> None:
        """
        Draw characters.
        `chars` is supposed to *not* contain any special characters.
        No newlines or control codes.
        """
        # Aliases for variables that are used more than once in this function.
        # Local lookups are always faster.
        # (This draw function is called for every printable character that a
        # process outputs; it should be as performant as possible.)
        page = self.page
        data_buffer = page.data_buffer
        cursor_position = self.pt_cursor_position
        cursor_position_x = cursor_position.x
        cursor_position_y = cursor_position.y

        in_irm = AnsiMode.INSERT_REPLACE in self.mode
        char_cache = _CHAR_CACHE
        columns = self.columns
        wide_chars = self._wide_chars
        _left, right_margin = self.left_right

        # The marks that SPA and DECSCA put on what comes next. Nearly
        # no program sets one, so the cells stay in the cache that
        # holds no mark and cost nothing.
        protection = self.protection
        if protection:
            char_cache = _PROTECTED_CHAR_CACHE
            key_tail = (self._appearance, protection)
            self._protected_chars = True
        else:
            key_tail = (self._appearance,)

        # What REP repeats. It is kept before the translation, so that
        # a repeat travels the same road the character did.
        if chars:
            self.last_character = chars[-1]

        # Translating a given character.
        if self.charset:
            chars = chars.translate(self.g1_charset)
        else:
            chars = chars.translate(self.g0_charset)

        # The column after the last one a character may take. The loop
        # works it out for each character it draws.
        edge = columns

        # Only the first character of a run can find the cursor waiting
        # to wrap. After that the loop has placed the cursor itself.
        waiting_to_wrap = self.pending_wrap

        # The row this run starts on. A run that wraps writes to the
        # rows below as well, and the cursor only ever moves down while
        # it draws, so the rows this run changed are the ones from here
        # to wherever the cursor ends up. Counting them after the loop
        # keeps the loop itself, which runs once per character, exactly
        # as it was. Lillecarl/pymux#126.
        first_row = cursor_position_y

        for char in chars:
            # Create 'Cell' instance.
            pt_char = char_cache[(char,) + key_tail]
            char_width = pt_char.width

            # A character that does not fit in what is left of the line
            # goes to the next line when auto wrap mode is on, and takes
            # the place at the right edge when it is off. A double width
            # character needs two columns, so it moves one column
            # earlier than a narrow one.
            #
            # A right margin is the edge of the line. A cursor that
            # stands right of the margin keeps the edge of the screen,
            # because a program that draws there draws outside the
            # region.
            # The column after the margin is where the wait to wrap
            # sits, so a cursor that waits there counts as inside. A
            # cursor that a program put on that column does not.
            if cursor_position_x <= right_margin or (
                waiting_to_wrap and cursor_position_x == right_margin + 1
            ):
                edge = right_margin + 1
            else:
                edge = columns

            if char_width > 0 and cursor_position_x + char_width > edge:
                if PrivateMode.AUTOWRAP.flag in self.mode:
                    # The moves below read the cursor from the screen,
                    # and this loop keeps it in a local. Write it back
                    # first, so that a carriage return finds the column
                    # that the last character left.
                    cursor_position.x = cursor_position_x
                    self.carriage_return()
                    self.linefeed()
                    cursor_position = self.pt_cursor_position
                    cursor_position_x = cursor_position.x
                    cursor_position_y = cursor_position.y

                    self.set_wrapped(cursor_position_y)
                else:
                    cursor_position_x = edge - char_width

            # If Insert mode is set, new characters move old characters to
            # the right, otherwise terminal is in Replace mode and new
            # characters replace old characters at cursor position.
            if in_irm:
                cursor_position.x = cursor_position_x
                self.insert_characters(max(0, char_width))

            row = data_buffer[cursor_position_y]
            if char_width == 1:
                # A write over one half of a double width character
                # leaves the other half on its own. Only a cell that
                # holds a half needs the repair, so the test stays
                # here, and a screen that never saw such a character
                # does not even look.
                if wide_chars:
                    broken = row.get(cursor_position_x)
                    row[cursor_position_x] = pt_char
                    if broken is not None and (
                        broken.char == "" or broken.width > 1
                    ):
                        self.repair_wide_char(row, cursor_position_x)
                        self.repair_wide_char(row, cursor_position_x + 1)
                else:
                    row[cursor_position_x] = pt_char
            elif char_width > 1:  # 2
                # Double width character. Put an empty string in the second
                # cell, because this is different from every character and
                # causes the render engine to clear this character, when
                # overwritten.
                row[cursor_position_x] = pt_char
                row[cursor_position_x + 1] = char_cache[("",) + key_tail]
                self.repair_wide_char(row, cursor_position_x)
                self.repair_wide_char(row, cursor_position_x + 2)
                if not wide_chars:
                    wide_chars = self._wide_chars = True
            elif char_width == 0:
                # A mark of no width of its own belongs to the character
                # before it. See:
                # https://en.wikipedia.org/wiki/Unicode_equivalence
                # The cell before can be the empty second half of a
                # double width character. The character itself then sits
                # one cell further back.
                previous = cursor_position_x - 1
                cell = row.get(previous)
                if cell is not None and cell.char == "":
                    previous -= 1
                    cell = row.get(previous)
                # A cell that an erase left holds no character, so a
                # mark has nothing to hang on and goes away. kitty and
                # WezTerm both drop it there.
                if (
                    previous >= 0
                    and cell is not None
                    and not isinstance(cell, ErasedCell)
                ):
                    # The mark belongs to the cell that is there, so it
                    # keeps the marks of that cell and not the ones
                    # that are set now.
                    marks = protection_of(cell)
                    if marks:
                        row[previous] = _PROTECTED_CHAR_CACHE[
                            cell.char + pt_char.char, cell.appearance, marks
                        ]
                    else:
                        row[previous] = _CHAR_CACHE[
                            cell.char + pt_char.char, cell.appearance
                        ]
            else:  # char_width < 0
                # (Should not happen.)
                char_width = 0

            # .. note:: We can't use :meth:`cursor_forward()`, because that
            #           way, we'll never know when to linefeed.
            cursor_position_x += char_width

            # This character filled the edge column, so the next one
            # starts the line below.
            waiting_to_wrap = cursor_position_x >= edge

        # Update max_y. (Don't use 'max()' for comparing only two values, that
        # is less efficient.)
        if cursor_position_y > self.max_y:
            self.max_y = cursor_position_y

        cursor_position.x = cursor_position_x
        # A run that draws nothing leaves the wait as it was, and it
        # changed no row either.
        if chars:
            self.pending_wrap = waiting_to_wrap
            # Nearly every run stays on one row, so that case is
            # written out rather than called. A run that began with the
            # cursor waiting to wrap counts the row it came from as
            # well, which costs a reader one row it need not have
            # drawn and never costs it a row it should have.
            if cursor_position_y == first_row:
                self.writes += 1
                self.written_at[first_row] = self.writes
            else:
                self.touch_rows(range(first_row, cursor_position_y + 1))

    def _leave_the_pending_wrap(self) -> None:
        """
        Bring a cursor that sits past the last column back onto it.

        A character written in the last column leaves the cursor one
        column further, which is what makes the next character wrap.
        A move of the cursor ends that wait, so the cursor lands on the
        last column and not past it.

        With a right margin the wait sits one column after the margin,
        which is a column of the screen like any other. So the flag
        says where the cursor came from, and the place does not.
        """
        if self.pending_wrap:
            self.pt_cursor_position.x -= 1
            self.pending_wrap = False

    def carriage_return(self) -> None:
        """
        Move the cursor to the beginning of the current line.

        With a left margin the beginning is the margin. A cursor that
        stands left of the margin goes to the first column instead, so
        a program that draws outside the region keeps that column.
        """
        left, _right = self.left_right
        if self.pt_cursor_position.x < left:
            left = 0
        self.pt_cursor_position.x = left
        # A move of the cursor ends the wait to wrap.
        self.pending_wrap = False

    # ------------------------------------------------------------------
    # Moving the screen over the buffer.
    #
    # Outside a scrolling region the screen slides down and the rows it
    # leaves become the history. Inside one the rows themselves move.
    # The history is pruned from `history_floor` and never walked whole.

    def index(self) -> None:
        """Move the cursor down one line in the same column. If the
        cursor is at the last line, create a new line at the bottom.
        """
        # A character at the right edge leaves the cursor one column
        # past the line, which is where the next one wraps from. A move
        # down takes the cursor out of that place: the column it lands
        # in is the last one.
        self._leave_the_pending_wrap()

        margins = self.margins

        # When scrolling over the full screen height -> keep history.
        # A left or a right margin makes the region narrower than the
        # screen, and a rectangle carries no history.
        if margins is None and self.horizontal_margins is None:
            # Simply move the cursor one position down.
            cursor_position = self.pt_cursor_position

            # A linefeed on the last row of the screen brings a new
            # line in. Anywhere else it only moves the cursor, and the
            # row below is already there.
            brings_a_line_in = (
                cursor_position.y - self.line_offset == self.lines - 1
            )

            cursor_position.y += 1

            # A new line takes the background that is set. That is what
            # `bce` means, and the terminfo entry of a pane claims it.
            # A scrolling region already paints the line it brings in,
            # so without this the same linefeed paints or does not paint
            # by whether a program has set a region.
            if brings_a_line_in:
                self._erase_row(cursor_position.y)

            self.max_y = max(self.max_y, cursor_position.y)

            # Cleanup the history, but only every 100 calls.
            self._history_cleanup_counter += 1
            if self._history_cleanup_counter == 100:
                self._remove_old_lines_from_history()
                self._history_cleanup_counter = 0
        else:
            # Move cursor down, but scroll in the scrolling region.
            top, bottom = margins or Margins(0, self.lines - 1)

            if self.pt_cursor_position.y - self.line_offset != bottom:
                self.cursor_down()
            elif self._cursor_is_between_the_left_and_right_margins():
                self._move_rows(top, bottom, 1)
            # Outside the columns of the region the cursor stays where
            # it is, and nothing scrolls.

    def scroll_up(self, count: int | None = None) -> None:
        """
        SU ("CSI Ps S"): move the lines of the scrolling region up.

        The cursor does not move. This is what a program sends to
        scroll a region without a linefeed.
        """
        self._scroll_region(count or 1)

    def scroll_down(
        self, *params: int, private: object = False, **kwargs
    ) -> None:
        """
        SD ("CSI Ps T"): move the lines of the scrolling region down.

        The cursor does not move.

        With the private marker the same final byte is RM_Title
        ("CSI > Ps T"), which takes a title mode away. xterm reads the
        two apart by the marker.
        """
        if private == ">":
            self.titles.change_modes(params, False)
            return
        count = params[0] if params else None
        self._scroll_region(-(count or 1))

    def _scroll_region(self, amount: int) -> None:
        """
        Move the lines of the scrolling region by `amount`.

        A positive amount moves them up, which is what SU asks for. The
        lines that come in are empty, and the ones that go out are
        dropped, so this keeps no history.
        """
        top, bottom = self.margins or Margins(0, self.lines - 1)
        self._move_rows(top, bottom, amount)

    def _move_rows(self, top: int, bottom: int, amount: int) -> None:
        """
        Move the rows from `top` to `bottom` by `amount` rows.

        A positive amount moves them up. The rows that come in are
        empty, and the ones that go out are dropped, so this keeps no
        history. The rows are counted from the top of the screen.

        Left and right margins hold the move to the columns between
        them. The cells outside them stay where they are, so the move
        carries a rectangle and not whole lines.
        """
        steps = min(abs(amount), bottom - top + 1)
        if steps == 0:
            return

        if amount > 0:
            rows = range(top, bottom + 1)
            source = steps
        else:
            rows = range(bottom, top - 1, -1)
            source = -steps

        line_offset = self.line_offset
        data_buffer = self.data_buffer
        horizontal = self.horizontal_margins

        # Every row of the region takes new content, whether it comes
        # from another row or is empty. A scroll is the commonest thing
        # a program does, so this is one call for the whole region
        # rather than one per row. It comes before the move, so that a
        # helper the move calls counts on top of a number that is
        # already written back. Lillecarl/pymux#126.
        self.touch_rows(row + line_offset for row in rows)

        for row in rows:
            origin = row + source
            inside = top <= origin <= bottom

            if horizontal is None:
                if inside:
                    data_buffer[row + line_offset] = data_buffer[
                        origin + line_offset
                    ]
                else:
                    self._erase_row(row + line_offset)
            elif inside:
                self._copy_columns(
                    data_buffer[origin + line_offset],
                    data_buffer[row + line_offset],
                    horizontal,
                )
            else:
                self._erase_columns(data_buffer[row + line_offset], horizontal)

        if horizontal is None:
            # Graphics placements scroll with the text. An image sits on
            # whole lines, so it moves only when whole lines move.
            self.graphics.scroll(top + line_offset, bottom + line_offset, amount)

            # The DEC line attribute and the continuation mark move with
            # the line, because the line carries them. A rectangle
            # carries cells and not lines, so a left or a right margin
            # leaves them alone: the loop above copies columns then, and
            # the rows themselves stay where they are.

    def _copy_columns(self, source, target, horizontal: HorizontalMargins) -> None:
        "Copy the cells between the margins from one row to another."
        left, right = horizontal
        for column in range(left, right + 1):
            cell = source.get(column)
            if cell is None:
                target.pop(column, None)
            else:
                target[column] = cell

    def _erase_columns(self, row, horizontal: HorizontalMargins) -> None:
        """
        Make the cells between the margins empty.

        They take the background that is set now, the same way an
        erased cell does.
        """
        left, right = horizontal
        appearance = self.erase_appearance()

        if appearance:
            blank = ErasedCell(" ", appearance)
            for column in range(left, right + 1):
                row[column] = blank
        else:
            for column in range(left, right + 1):
                row.pop(column, None)

    def _remove_old_lines_from_history(self) -> None:
        """
        Remove top from the scroll buffer. (Outside bounds of history limit.)
        """
        remove_above = max(0, self.pt_cursor_position.y - self.get_history_limit())
        data_buffer = self.page.data_buffer
        for line in range(self.history_floor, remove_above):
            data_buffer.pop(line, None)
            self._forget(line)
        self.history_floor = max(self.history_floor, remove_above)
        self.graphics.prune_above(remove_above)

    def _forget(self, row: int) -> None:
        """
        Drop the count of a row that has left the history for good.

        This is the one thing about a row that the row does not carry,
        and it is outside on purpose: the *reader* owns it, and a pure
        screen may not track its readers. Lillecarl/pymux#126. Whether a
        wrap brought the row into being and what DEC line attribute it
        has both ride on the row, so dropping the row drops them.

        The count is taken away rather than moved on, so `written_at`
        stays as big as the history and not as big as the session.
        **Nothing draws a row that left the history**, so it needs no
        count to say that it went: it is under `history_floor`, and a
        reader asks for the rows the buffer holds. A pane draws the rows
        of the screen, and copy mode draws from the lowest row of the
        buffer to the highest.
        """
        self.written_at.pop(row, None)

    def clear_history(self) -> None:
        """
        Delete all history from the scroll buffer.
        """
        data_buffer = self.data_buffer
        for line in range(self.history_floor, self.line_offset):
            data_buffer.pop(line, None)
            self._forget(line)
        self.history_floor = max(self.history_floor, self.line_offset)

    def reverse_index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)

        if self.pt_cursor_position.y - self.line_offset != top:
            self.cursor_up()
        elif self._cursor_is_between_the_left_and_right_margins():
            self._move_rows(top, bottom, -1)
        # Outside the columns of the region the cursor stays where it
        # is, and nothing scrolls.

    def linefeed(self) -> None:
        """Performs an index and, if `AnsiMode.LINE_FEED_NEW_LINE` is
        set, a carriage return.
        """
        self.index()

        if AnsiMode.LINE_FEED_NEW_LINE in self.mode:
            self.carriage_return()

    def next_line(self) -> None:
        """When `EscE` has been received. Go to the next line, even when LNM has
        not been set."""
        self.index()
        self.carriage_return()
        self.ensure_bounds()

    # ------------------------------------------------------------------
    # The tab stops.
    #
    # `set_tab_stop` and `clear_tab_stop` are further down, with the
    # other settings a program picks with one number.

    def tab(self) -> None:
        """Move to the next tab stop, or to the last column when no stop
        is left on the line.

        The tab stops do not know how wide the screen is, so a stop can
        sit past the last column. The last column stops the cursor: a
        tab never moves it off the line.

        A cursor that already sits past the last column waits to wrap.
        A tab leaves that wait alone, so the next character starts the
        line below. Every other cursor move ends the wait. This one
        does not. kitty, WezTerm, Alacritty and libvterm all agree.

        Private mode 41 is the one exception. `more` drew to the end of
        a row and then wrote a tab, and the tab went nowhere; xterm
        added the mode so that the tab wraps first. It is off unless a
        program asks for it.
        """
        cursor_position = self.pt_cursor_position
        if self.pending_wrap:
            if PrivateMode.MORE_FIX.flag not in self.mode:
                return
            self.carriage_return()
            self.linefeed()
            cursor_position = self.pt_cursor_position
            # The line above was full and the cursor moved on because
            # of it, which is what the wrap flag records.
            self.set_wrapped(cursor_position.y)

        # With a right margin the tab stops there, and not at the last
        # column. That holds even for a cursor that starts left of the
        # left margin: the DEC terminals stop a tab at the margin, and
        # xterm does the same.
        _left, right = self.left_right
        last = right if cursor_position.x <= right else self.columns - 1
        for stop in sorted(self.tabstops):
            if cursor_position.x < stop:
                column = min(stop, last)
                break
        else:
            column = last

        cursor_position.x = column

    def cursor_to_next_tab(self, count: int | None = None) -> None:
        """
        CHT ("CSI Ps I"): move forward over `count` tab stops.

        pyte has no handler for it. ncurses uses it to reach a column
        without drawing the blanks in between.
        """
        for _ in range(count or 1):
            self.tab()

    def cursor_to_previous_tab(self, count: int | None = None) -> None:
        """
        CBT ("CSI Ps Z"): move back over `count` tab stops.

        The first column stops the cursor, the way the last column
        stops a tab.
        """
        for _ in range(count or 1):
            for stop in sorted(self.tabstops, reverse=True):
                if stop < self.pt_cursor_position.x:
                    column = stop
                    break
            else:
                column = 0
            self.pt_cursor_position.x = column

    def repeat_last_character(self, count: int | None = None) -> None:
        """
        REP ("CSI Pn b"): draw the last character again, `count` times.

        It saves a program the bytes of a run of one character, which
        is what a box or a rule is made of.

        The repeat goes through `draw`, so it wraps at the right
        margin and scrolls at the bottom one exactly the way the
        typing would have. ECMA-48 says nothing about margins; xterm
        reads it this way to match the rest of the terminal, and
        esctest2 asks for it.

        A repeat before anything is drawn draws nothing. There is no
        character to repeat, and a space would be a guess.
        """
        if self.last_character:
            self.draw(self.last_character * (count or 1))

    # ------------------------------------------------------------------
    # Going back over what was typed.
    #
    # A backspace in the first column can reach the row above, and two
    # modes say when. It undoes the typing, so it reads the wrap mark.

    def backspace(self) -> None:
        """
        Move the cursor one column left.

        In the first column it normally stays where it is. Two private
        modes send it to the end of the line above instead, which lets
        a program rub out a line it wrapped:

        - "?45" goes back only when the line was reached by wrapping.
          A backspace then undoes what the typing did, and stops where
          the typing began.
        - "?1045" goes back from any line, and from the first line of
          the region to the last. xterm did this under "?45" until it
          split the two apart in 2023.

        Both need DECAWM. A terminal that does not wrap forward has
        nothing to unwrap.
        """
        # A cursor that waits to wrap sits one column past the last one
        # it wrote, so leaving the wait is itself a move left. With a
        # reverse wrap mode on, that move is the whole backspace and
        # the cursor stays on the character it wrote. Without one the
        # backspace goes on to the character before it.
        #
        # xterm asks for both: `test_BS_CursorStartsInDoWrapPosition`
        # writes "ab", backspaces and writes "X" for "Xb", and
        # `test_BS_ReverseWrapStartingInDoWrapPosition` does the same
        # with the mode on for "aX".
        if self.pending_wrap:
            self._leave_the_pending_wrap()
            if self._reverse_wrap_mode() is not None:
                return

        self.cursor_back()

    def _reverse_wrap_mode(self) -> PrivateMode | None:
        """
        The reverse wrap mode that is on, or `None` when neither is.

        Both need DECAWM: a terminal that does not wrap forward has
        nothing to unwrap. The wider mode wins when both are set.
        """
        if PrivateMode.AUTOWRAP.flag not in self.mode:
            return None
        if PrivateMode.REVERSE_WRAP_ANYWHERE.flag in self.mode:
            return PrivateMode.REVERSE_WRAP_ANYWHERE
        if PrivateMode.REVERSE_WRAP.flag in self.mode:
            return PrivateMode.REVERSE_WRAP
        return None

    def _backspace_wraps(self) -> bool:
        """
        Send the cursor to the end of the line above, and say whether
        it went.

        The line above ends at the right margin, because that is where
        the wrap that put the cursor here came from.
        """
        mode = self._reverse_wrap_mode()
        if mode is None:
            return False
        anywhere = mode is PrivateMode.REVERSE_WRAP_ANYWHERE

        cursor_position = self.pt_cursor_position
        left, right = self.left_right
        # The left edge counts as well as the margin. A cursor placed
        # left of the margin has nowhere to go but the line above.
        if cursor_position.x > left and cursor_position.x != 0:
            return False

        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = cursor_position.y - self.line_offset
        if row > top:
            if not anywhere and not self.is_wrapped(cursor_position.y):
                return False  # The typing did not reach this line by wrapping.
            cursor_position.y -= 1
        elif anywhere:
            # From the top of the region back to the bottom of it.
            cursor_position.y = bottom + self.line_offset
        else:
            return False

        cursor_position.x = right
        self.pending_wrap = False
        return True

    # ------------------------------------------------------------------
    # Saving the cursor and bringing it back.
    #
    # A savepoint holds more than a position: the rendition, the
    # charsets, origin mode and the protection marks travel with it.

    def save_cursor(self) -> None:
        """
        Remember the cursor, so that a restore can bring it back.

        A terminal remembers one cursor, not a stack of them: a second
        save replaces the first, and a restore leaves what it read in
        place, so two restores in a row give the same answer. kitty and
        xterm both work that way.
        """
        self.savepoints[:] = [
            _Savepoint(
                self.pt_cursor_position.x,
                # The row within the screen, not within the buffer. A
                # save remembers a place on the screen, so a scroll
                # between the save and the restore must not drag the
                # cursor back into the history.
                self.pt_cursor_position.y - self.line_offset,
                self.g0_charset,
                self.g1_charset,
                self.charset,
                PrivateMode.ORIGIN.flag in self.mode,
                # DECAWM is not here. xterm does not bring the wrap
                # back on a restore, and its own suite asks for that:
                # a save with the wrap on, a reset, and a restore
                # leaves the wrap off.
                # The rendition alone. A hyperlink is not part of the
                # cursor that "ESC 7" remembers.
                self._rendition,
                self.protection,
            )
        ]

    def restore_cursor(self) -> None:
        """
        Bring back the cursor that a save remembered.

        The saved cursor stays, so a second restore gives the same
        answer as the first.
        """
        if self.savepoints:
            savepoint = self.savepoints[-1]

            self.g0_charset = savepoint.g0_charset
            self.g1_charset = savepoint.g1_charset
            self.charset = savepoint.charset
            self._rendition = savepoint.rendition
            self.protection = savepoint.protection
            self._rebuild_appearance()

            # Origin mode is part of the cursor, so it comes back the
            # way it was saved. Both ways: a save with the mode off
            # takes the mode off again.
            if savepoint.origin:
                self.set_mode(PrivateMode.ORIGIN.flag)
            else:
                self.reset_mode(PrivateMode.ORIGIN.flag)

            # `line_offset` follows the cursor, so read it before the
            # cursor moves.
            line_offset = self.line_offset

            self.pt_cursor_position.x = savepoint.cursor_x
            self.pt_cursor_position.y = savepoint.cursor_y + line_offset
            # Only the screen bounds hold the cursor here. A restore
            # brings back the place that was saved, which may sit
            # outside the margins that are set now: "CSI r" homes the
            # cursor, so a save from before it is usually above the top
            # margin. kitty and xterm both keep it there.
            self.ensure_bounds()
        else:
            # Nothing was saved, so the restore brings back the state
            # that a terminal starts with: the home position, no origin
            # mode and the character sets of the start. kitty does the
            # same. :todo: DECAWM?
            self.reset_mode(PrivateMode.ORIGIN.flag)
            self.g0_charset = cs.LAT1_MAP
            self.g1_charset = cs.LAT1_MAP
            self.charset = 0
            self.cursor_position()

    def _erase_row(self, row: int) -> None:
        """
        Make the absolute row `row` an empty row.

        A row takes the background that is set now, the same way an
        erased cell does. Without a background the row can go away,
        which keeps the screen sparse.
        """
        data_buffer = self.data_buffer
        appearance = self.erase_appearance()
        self.touch(row)

        if appearance is None:
            data_buffer.pop(row, None)
            return

        # A fresh row, so the continuation mark and the DEC line
        # attribute of whatever stood here go with the cells.
        line = Row(Cell(" ", PLAIN_APPEARANCE))
        erased = ErasedCell(" ", appearance)
        for column in range(self.columns):
            line[column] = erased
        data_buffer[row] = line

    # ------------------------------------------------------------------
    # Inserting and deleting rows and columns.
    #
    # Each one moves what is there and leaves blanks behind. A margin
    # bounds every one of them, and what falls outside is gone.

    def insert_lines(self, count: int | None = None) -> None:
        """Inserts the indicated # of lines at line with cursor. Lines
        displayed **at** and below the cursor move down. Lines moved
        past the bottom margin are lost.

        :param count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins or Margins(0, self.lines - 1)
        first = self.pt_cursor_position.y - self.line_offset

        # The cursor has to stand inside the region, in both the rows
        # and the columns of it. Outside it, IL does nothing.
        if not top <= first <= bottom:
            return
        if not self._cursor_is_between_the_left_and_right_margins():
            return

        self._move_rows(first, bottom, -count)
        self.carriage_return()

    def delete_lines(self, count: int | None = None) -> None:
        """Deletes the indicated # of lines, starting at line with
        cursor. As lines are deleted, lines displayed below cursor
        move up. Lines added to bottom of screen have spaces with same
        character attributes as last line moved up.

        :param int count: number of lines to delete.
        """
        count = count or 1
        top, bottom = self.margins or Margins(0, self.lines - 1)
        first = self.pt_cursor_position.y - self.line_offset

        # The cursor has to stand inside the region, in both the rows
        # and the columns of it. Outside it, DL does nothing.
        if not top <= first <= bottom:
            return
        if not self._cursor_is_between_the_left_and_right_margins():
            return

        self._move_rows(first, bottom, count)

        # DL moves the cursor to the first column, the same way IL does.
        self.carriage_return()

    def insert_characters(self, count: int | None = None) -> None:
        """Inserts the indicated # of blank characters at the cursor
        position. The cursor does not move and remains at the beginning
        of the inserted blank characters. Data on the line is shifted
        forward.

        :param int count: number of characters to insert.

        A right margin is the edge of the line, and the cells after it
        stay where they are. From outside the margins ICH does nothing.
        """
        count = count or 1
        cursor_x = self.pt_cursor_position.x
        left, right = self.left_right
        if not left <= cursor_x <= right:
            return

        edge = right + 1
        line = self.data_buffer[self.pt_cursor_position.y]
        self.touch(self.pt_cursor_position.y)

        # Move what sits at and after the cursor to the right. What
        # falls off the right edge is lost.
        moved = {}
        for column in list(line.keys()):
            if column < cursor_x or column > right:
                continue
            cell = line.pop(column)
            if column + count < edge:
                moved[column + count] = cell
        line.update(moved)

        appearance = self.erase_appearance()
        if appearance:
            blank = ErasedCell(" ", appearance)
            for column in range(cursor_x, min(cursor_x + count, edge)):
                line[column] = blank

        # The cursor and the right edge are where a double width
        # character can lose half of itself.
        self.repair_wide_char(line, cursor_x)
        self.repair_wide_char(line, edge)

    def delete_characters(self, count: int | None = None) -> None:
        """
        DCH ("CSI Ps P"): delete characters at the cursor.

        A right margin is the edge of the line, and the cells after it
        stay where they are. From outside the margins DCH does nothing.
        """
        count = count or 1
        cursor_x = self.pt_cursor_position.x
        left, right = self.left_right
        if not left <= cursor_x <= right:
            return

        edge = right + 1
        line = self.data_buffer[self.pt_cursor_position.y]
        self.touch(self.pt_cursor_position.y)

        # Move what sits after the deleted characters to the left.
        moved = {}
        for column in list(line.keys()):
            if column < cursor_x or column > right:
                continue
            cell = line.pop(column)
            if column - count >= cursor_x:
                moved[column - count] = cell
        line.update(moved)

        appearance = self.erase_appearance()
        if appearance:
            blank = ErasedCell(" ", appearance)
            for column in range(max(cursor_x, edge - count), edge):
                line[column] = blank

        self.repair_wide_char(line, cursor_x)
        self.repair_wide_char(line, max(cursor_x, edge - count))

    # ------------------------------------------------------------------
    # Placing the cursor.
    #
    # Origin mode decides what a number counts from, so every one of
    # these ends at `ensure_bounds`.

    def cursor_position(
        self, line: int | None = None, column: int | None = None
    ) -> None:
        """Set the cursor to a specific `line` and `column`.

        In origin mode the region is the whole page that a program
        sees. A row past the bottom of it holds at the bottom, the way
        a column past the right margin holds at the margin, and the way
        a row past the last row of the screen holds there without the
        mode. The move still happens: the column is set either way.

        pyte leaves the cursor where it stands instead. The whole
        panel moves it, and so does xterm.

        :param int line: line number to move the cursor to.
        :param int column: column number to move the cursor to.
        """
        column = (column or 1) - 1
        line = (line or 1) - 1

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        margins = self.margins

        if margins is not None and PrivateMode.ORIGIN.flag in self.mode:
            line = min(line + margins.top, margins.bottom)

        column = self._column_in_origin_mode(column)

        self.pt_cursor_position.x = column
        self.pt_cursor_position.y = line + self.line_offset
        self.ensure_bounds()

    def _column_in_origin_mode(self, column: int) -> int:
        """
        Read a column that a program counted from the left margin.

        In origin mode the region is the whole page that a program
        sees, so column one is the left margin and the right margin
        holds the cursor. Without the mode, or without margins, the
        column is the column of the screen.
        """
        margins = self.horizontal_margins
        if margins is None or PrivateMode.ORIGIN.flag not in self.mode:
            return column
        return min(column + margins.left, margins.right)

    def cursor_to_column(self, column: int | None = None) -> None:
        """
        CHA ("CSI Ps G"): move to a column of the current line.

        The column is counted from the left margin in origin mode.

        :param int column: column number to move the cursor to.
        """
        self.pt_cursor_position.x = self._column_in_origin_mode(
            (column or 1) - 1
        )
        self.ensure_bounds()

    def cursor_to_absolute_column(self, column: int | None = None) -> None:
        """
        HPA ("CSI Ps `"): move to a column of the line.

        DEC gives HPA the column of the screen and CHA the column of
        the region, so origin mode would move one and not the other.
        xterm moves both, and a program that asks where the cursor
        landed is told the same way, so the two have to agree: a
        report in origin mode counts from the margin, and a move that
        did not would answer a column the program never asked for.

        `reported_position` is the other half of this.

        :param int column: column number to move the cursor to.
        """
        self.cursor_to_column(column)

    def cursor_to_line(self, line: int | None = None) -> None:
        """Moves cursor to a specific line in the current column.

        :param int line: line number to move the cursor to.
        """
        self.pt_cursor_position.y = (line or 1) - 1 + self.line_offset

        # If origin mode (DECOM) is set, line number are relative to
        # the top scrolling margin.
        margins = self.margins

        if PrivateMode.ORIGIN.flag in self.mode and margins is not None:
            self.pt_cursor_position.y += margins.top

            # FIXME: should we also restrict the cursor to the scrolling
            # region?

        self.ensure_bounds()

    def bell(self, *args) -> None:
        "Bell"
        self.bell_func()

    def cursor_down(self, count: int | None = None) -> None:
        """Moves cursor down the indicated # of lines in same column.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self._leave_the_pending_wrap()

        cursor_position = self.pt_cursor_position
        margins = self.margins or Margins(0, self.lines - 1)

        # Ensure bounds.
        # (Following code is faster than calling `self.ensure_bounds`.)
        top, bottom = margins
        row = cursor_position.y - self.line_offset
        if row < top or row > bottom:
            # Outside the region the bottom of the screen stops the
            # cursor, not the margin. Below the region the margin would
            # move the cursor up, which a move down never does. Above
            # the region it would stop the cursor too early.
            limit = self.lines - 1
        else:
            limit = bottom
        cursor_position.y = min(
            cursor_position.y + (count or 1), limit + self.line_offset
        )

        self.max_y = max(self.max_y, cursor_position.y)

    def cursor_down1(self, count: int | None = None) -> None:
        """Moves cursor down the indicated # of lines to column 1.
        Cursor stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_down(count)
        self.carriage_return()

    def cursor_up(self, count: int | None = None) -> None:
        """Moves cursor up the indicated # of lines in same column.
        Cursor stops at top margin.

        :param int count: number of lines to skip.
        """
        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = self.pt_cursor_position.y - self.line_offset
        outside_the_region = row < top or row > bottom

        self.pt_cursor_position.y -= count or 1

        # Outside the region the top of the screen stops the cursor,
        # not the margin. Above the region the margin would move the
        # cursor down, and below it the margin would stop it too early.
        self.ensure_bounds(use_margins=not outside_the_region)

    def cursor_up1(self, count: int | None = None) -> None:
        """Moves cursor up the indicated # of lines to column 1. Cursor
        stops at bottom margin.

        :param int count: number of lines to skip.
        """
        self.cursor_up(count)
        self.carriage_return()

    def cursor_back(self, count: int | None = None) -> None:
        """Moves cursor left the indicated # of columns. Cursor stops
        at left margin.

        :param int count: number of columns to skip.

        The left margin stops the cursor, but only when the cursor
        starts at or right of it. Left of the margin the first column
        stops it, because the margin would move the cursor right, and
        a move left never does that.

        With a reverse wrap mode on, the first column does not stop it
        either: the cursor carries on at the end of the line above,
        one column at a time. `backspace` says what the two modes do.
        """
        count = count or 1
        if self._reverse_wrap_mode() is not None:
            self._walk_back(count)
            return

        cursor_position = self.pt_cursor_position
        left, _right = self.left_right
        if cursor_position.x < left:
            left = 0

        cursor_position.x = max(left, cursor_position.x - count)
        self.ensure_bounds()

    def _walk_back(self, count: int) -> None:
        """
        Move `count` columns left, over the end of a line where a
        reverse wrap mode allows it.

        This walks a column at a time, because each step may leave the
        line. A program may ask for more steps than the screen holds,
        so the count is cut down first: the wider mode brings the
        cursor round to the same place every full turn of the region,
        and the narrower one has stopped long before.
        """
        top, bottom = self.margins or Margins(0, self.lines - 1)
        left, right = self.left_right
        turn = (bottom - top + 1) * (right - left + 1)
        if count > 2 * turn:
            count = turn + count % turn

        cursor_position = self.pt_cursor_position
        for _step in range(count):
            # Left of the margin the first column is the limit, the
            # way it is for a move that does not wrap.
            limit = left if cursor_position.x >= left else 0
            if cursor_position.x > limit:
                cursor_position.x -= 1
            elif not self._backspace_wraps():
                break
        self.ensure_bounds()

    def cursor_forward(self, count: int | None = None) -> None:
        """Moves cursor right the indicated # of columns. Cursor stops
        at right margin.

        :param int count: number of columns to skip.

        The right margin stops the cursor, but only when the cursor
        starts at or left of it. Right of the margin the last column
        stops it.
        """
        cursor_position = self.pt_cursor_position
        _left, right = self.left_right
        if cursor_position.x > right:
            right = self.columns - 1

        cursor_position.x = min(right, cursor_position.x + (count or 1))
        self.ensure_bounds()

    # ------------------------------------------------------------------
    # Erasing.
    #
    # An erased cell takes the background that is set now, and it is an
    # `ErasedCell`: a combining mark falls off one and hangs on a space
    # that a program wrote. Lillecarl/pymux#56.

    def erase_appearance(self) -> "Appearance | None":
        """
        How an erased cell is drawn.

        A terminal paints an erased cell with the background that is set
        now. xterm, kitty and tmux all do this, and programs count on
        it: htop draws the header of its table with "CSI K" and expects
        the colour to reach the end of the line.

        The background carries over, and the underline does not. Five
        judges take the underline off an erased cell and only kitty
        keeps it, for both ED and EL; the background is the other way
        round, five keeping it and only Ghostty dropping it.
        `test_the_panel.py` holds both tallies.

        Reverse video is a split, so it stays. kitty and WezTerm paint
        the cell; Alacritty, Ghostty, libvterm and xterm do not. Four to
        two is a choice and not a rule, and a program that reverses and
        then erases means the block to be seen.

        DCH and ICH read this style as well, and the panel splits there
        too. Ghostty and WezTerm colour a delete with nothing at all,
        not even the background, so they take no side. Of the five that
        do colour it, kitty and ptterm paint the reverse, libvterm keeps
        the foreground without it, and Alacritty and xterm keep only the
        background. Alacritty's `delete_chars_reset` reference test is
        that difference and nothing else: twelve cells at the end of one
        row.

        `None` means that nothing paints the cell, so the cell can go
        away instead, which keeps the screen sparse.

        A hyperlink is never part of it. An erase takes the content of
        a cell away, and a link that covers nothing is not a link.
        """
        rendition = self._rendition

        if not rendition.reverse and not rendition.bgcolor:
            return None

        return appearance_of[
            PLAIN._replace(
                reverse=rendition.reverse,
                # Reverse video paints the cell with the foreground, so
                # that colour is part of an erase only then.
                color=rendition.color if rendition.reverse else None,
                bgcolor=rendition.bgcolor,
            ),
            "",
            "",
        ]

    def erase_characters(self, count: int | None = None) -> None:
        """Erases the indicated # of characters, starting with the
        character at cursor position. Character attributes are set
        cursor attributes. The cursor remains in the same position.

        :param int count: number of characters to erase.

        .. warning::

           Even though *ALL* of the VTXXX manuals state that character
           attributes **should be reset to defaults**, ``libvte``,
           ``xterm`` and ``ROTE`` completely ignore this. Same applies
           too all ``erase_*()`` and ``delete_*()`` methods.
        """
        count = count or 1
        cursor_position = self.pt_cursor_position
        row = self.data_buffer[cursor_position.y]
        self.touch(cursor_position.y)
        # ECH writes a cell even when nothing paints it: the erase has
        # to take the content away whether or not it has a colour.
        erased = ErasedCell(" ", self.erase_appearance() or PLAIN_APPEARANCE)

        end = min(cursor_position.x + count, self.columns)
        for column in range(cursor_position.x, end):
            # ECH leaves a cell that SPA marked alone.
            cell = row.get(column)
            if cell is not None and self._erase_holds(cell, False):
                continue
            row[column] = erased

        self.repair_wide_char(row, cursor_position.x)
        self.repair_wide_char(row, end)

    def _move_columns(
        self, top: int, bottom: int, left: int, right: int, amount: int
    ) -> None:
        """
        Move the cells between `left` and `right` by `amount` columns.

        Every row from `top` to `bottom` moves, so this carries a
        rectangle. A positive amount moves the cells right, which is
        what DECIC asks for. The cells that come in are empty, and the
        ones that go past a margin are dropped.
        """
        steps = min(abs(amount), right - left + 1)
        if steps == 0:
            return

        if amount > 0:
            columns = range(right, left - 1, -1)
            source = -steps
        else:
            columns = range(left, right + 1)
            source = steps

        line_offset = self.line_offset
        data_buffer = self.data_buffer
        appearance = self.erase_appearance()
        blank = ErasedCell(" ", appearance) if appearance else None

        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            self.touch(row + line_offset)
            for column in columns:
                origin = column + source
                cell = line.get(origin) if left <= origin <= right else None
                if cell is not None:
                    line[column] = cell
                elif blank is None:
                    line.pop(column, None)
                else:
                    line[column] = blank

            # Both edges are where a double width character can lose
            # half of itself.
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def _region_holds_the_cursor(self) -> bool:
        "True when the cursor stands inside the scrolling region."
        top, bottom = self.margins or Margins(0, self.lines - 1)
        row = self.pt_cursor_position.y - self.line_offset
        if not top <= row <= bottom:
            return False
        return self._cursor_is_between_the_left_and_right_margins()

    def insert_columns(self, count: int | None = None) -> None:
        """
        DECIC ("CSI Pn ' }"): insert columns at the cursor.

        Every row of the scrolling region moves, and not the row of the
        cursor alone. The cells that go past the right margin are lost.
        From outside the region DECIC does nothing.
        """
        if not self._region_holds_the_cursor():
            return

        top, bottom = self.margins or Margins(0, self.lines - 1)
        _left, right = self.left_right
        self._move_columns(
            top, bottom, self.pt_cursor_position.x, right, count or 1
        )

    def delete_columns(self, count: int | None = None) -> None:
        """
        DECDC ("CSI Pn ' ~"): delete columns at the cursor.

        Every row of the scrolling region moves, the way DECIC moves
        them. From outside the region DECDC does nothing.
        """
        if not self._region_holds_the_cursor():
            return

        top, bottom = self.margins or Margins(0, self.lines - 1)
        _left, right = self.left_right
        self._move_columns(
            top, bottom, self.pt_cursor_position.x, right, -(count or 1)
        )

    def forward_index(self) -> None:
        """
        DECFI ("ESC 9"): move the cursor one column to the right.

        At the right margin the cursor stays, and the region moves one
        column to the left instead. Right of the margin the cursor
        moves on its own until the edge of the screen stops it.

        A cursor that waits to wrap past the last column stands on the
        last column, so it moves the region as well.
        """
        cursor_position = self.pt_cursor_position
        _left, right = self.left_right
        # A cursor that waits to wrap stands on the column before it.
        if self.pending_wrap:
            column = cursor_position.x - 1
        else:
            column = min(cursor_position.x, self.columns - 1)

        if column == right:
            top, bottom = self.margins or Margins(0, self.lines - 1)
            self._move_columns(top, bottom, *self.left_right, -1)
        elif column < self.columns - 1:
            cursor_position.x = column + 1
        self.pending_wrap = False

    def back_index(self) -> None:
        """
        DECBI ("ESC 6"): move the cursor one column to the left.

        At the left margin the cursor stays, and the region moves one
        column to the right instead. Left of the margin the cursor
        moves on its own until the first column stops it.
        """
        cursor_position = self.pt_cursor_position
        left, _right = self.left_right

        if cursor_position.x == left:
            top, bottom = self.margins or Margins(0, self.lines - 1)
            self._move_columns(top, bottom, *self.left_right, 1)
        elif cursor_position.x > 0:
            cursor_position.x -= 1
        self.pending_wrap = False

    def erase_in_line(self, type_of: int = 0, private: bool = False) -> None:
        """Erases a line in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of line, including cursor
              position.
            * ``1`` -- Erases from beginning of line to cursor,
              including cursor position.
            * ``2`` -- Erases complete line.
        :param bool private: ``True`` for DECSEL ("CSI ? Ps K"), the
                             selective erase. It leaves a cell that
                             DECSCA marked alone; EL does not.
        """
        data_buffer = self.data_buffer
        pt_cursor_position = self.pt_cursor_position
        appearance = self.erase_appearance()

        if type_of == 0:
            columns = range(pt_cursor_position.x, self.columns)
        elif type_of == 1:
            columns = range(0, pt_cursor_position.x + 1)
        else:
            columns = range(0, self.columns)

        line = data_buffer[pt_cursor_position.y]
        self.touch(pt_cursor_position.y)
        holds = self._erase_holds
        erased = ErasedCell(" ", appearance) if appearance else None

        for column in columns:
            cell = line.get(column)
            if cell is not None and holds(cell, private is True):
                continue
            if erased is None:
                line.pop(column, None)
            else:
                line[column] = erased

        self._end_the_wrap_out_of_this_line(columns)

        if erased is None and not line:
            # The line holds nothing, so it can go away and keep the
            # screen sparse.
            data_buffer.pop(pt_cursor_position.y, None)
            return

        self._repair_erased_line(line, columns)

    def _end_the_wrap_out_of_this_line(self, columns: range) -> None:
        """
        An erase that clears the end of a line ends the wrap out of it.

        A line that a wrap started carries a mark saying it continues
        the line above, and a resize joins the two again. Once the text
        that wrapped away is erased, nothing wrapped out of this line,
        so the mark on the line below goes as well.

        An erase that stops before the last column leaves the mark: text
        is still there to have wrapped.

        libvterm asks for this in `32state_flow.test`, and it is the
        only thing that can: no judge on the panel reports the mark, and
        it is visible only through a resize.
        """
        if columns.stop < self.columns:
            return
        below = self.pt_cursor_position.y + 1
        self.set_wrapped(below, False)

    def _repair_erased_line(self, line, columns: range) -> None:
        "Repair the two ends of a range of cells that an erase took away."
        self.repair_wide_char(line, columns.start)
        self.repair_wide_char(line, columns.stop)

    def erase_in_display(self, type_of: int = 0, private: bool = False) -> None:
        """Erases display in a specific way.

        :param int type_of: defines the way the line should be erased in:

            * ``0`` -- Erases from cursor to end of screen, including
              cursor position.
            * ``1`` -- Erases from beginning of screen to cursor,
              including cursor position.
            * ``2`` -- Erases complete display. All lines are erased
              and changed to single-width. Cursor does not move.
            * ``3`` -- Erase saved lines. (Xterm) Clears the history.
        :param bool private: when ``True`` character attributes aren left
                             unchanged **not implemented**.
        """
        if type_of in (2, 3):
            # Clearing the screen (ED 2) or the history (ED 3) removes
            # all graphics placements. (The image data is kept.)
            self.graphics.remove_all_placements()

        line_offset = self.line_offset
        pt_cursor_position = self.pt_cursor_position
        try:
            max_line = max(self.page.data_buffer)
        except ValueError:
            # max() called on empty sequence: no line holds a cell yet.
            # There is nothing to take away, but a background still has
            # to reach the whole screen.
            max_line = line_offset - 1

        if type_of == 3:
            # "CSI 3 J" takes the history away and leaves the screen
            # as it is. xterm draws it that way, and a program that
            # wants the screen cleared as well sends "CSI 2 J" first.
            self.clear_history()
        else:
            appearance = self.erase_appearance()

            # A line that holds nothing needs no cell, so the erasing
            # stops at the last line in use. A background has to reach
            # the bottom of the screen, though.
            last_line = (
                max(max_line, line_offset + self.lines - 1)
                if appearance
                else max_line
            )

            try:
                interval = (
                    # a) erase from cursor to the end of the display, including
                    # the cursor,
                    range(pt_cursor_position.y + 1, last_line + 1),
                    # b) erase from the beginning of the display to the cursor,
                    # including it,
                    range(line_offset, pt_cursor_position.y),
                    # c) erase the whole display.
                    range(line_offset, last_line + 1),
                )[type_of]
            except IndexError:
                return

            data_buffer = self.data_buffer
            erased = ErasedCell(" ", appearance) if appearance else None

            # "CSI 2 J" takes the whole screen, marks and all. Only
            # the two that erase a part of it read the marks, and the
            # selective erase reads them whatever its parameter is.
            # xterm draws it that way, and its own conformance suite
            # clears the screen with "CSI 2 J" between tests.
            reads_the_marks = self._protected_chars and (
                private is True or type_of != 2
            )

            # A row that is erased is no longer the tail of a line that
            # wrapped: the text that wrapped onto it is gone. The note
            # has to go with the text, or it outlives what it
            # describes. A reflow then joins two lines that were never
            # one, and a reverse wrap walks back over a line the
            # typing never reached.
            # A DEC line attribute goes with the line, so an erase that
            # takes the whole line takes the attribute too. libvterm
            # clears it over the same rows: `set_lineinfo` with FORCE in
            # each of the three ED branches of its `src/state.c`. The
            # row the cursor stands on keeps its attribute, because ED 0
            # and ED 1 only take a part of that row.
            self._forget_line_notes(interval)

            self.touch_rows(interval)

            for line in interval:
                if reads_the_marks:
                    # A cell that carries a mark stays, so the row
                    # cannot go away whole.
                    self._erase_row_in_place(
                        data_buffer[line], erased, private is True
                    )
                    continue

                data_buffer[line] = Row(Cell(" ", PLAIN_APPEARANCE))
                if erased is not None:
                    # A background is set, so the erased cells take it.
                    row = data_buffer[line]
                    for column in range(self.columns):
                        row[column] = erased

            # In case of 0 or 1 we have to erase the line with the cursor.
            if type_of in [0, 1]:
                self.erase_in_line(type_of, private=private)

    def _erase_row_in_place(self, row, erased, selective: bool) -> None:
        "Erase every cell of a row that carries no mark."
        for column in range(self.columns):
            cell = row.get(column)
            if cell is not None and self._erase_holds(cell, selective):
                continue
            if erased is None:
                row.pop(column, None)
            else:
                row[column] = erased

    # ------------------------------------------------------------------
    # The rectangles: DECFRA, DECERA, DECSERA and DECCRA.
    #
    # Two corners name an area, and DECSACE says whether that is a
    # rectangle or the stream between them.

    def _rectangle(
        self, top: int, left: int, bottom: int, right: int
    ) -> Tuple[int, int, int, int] | None:
        """
        Read the four corners that a rectangle command names.

        The numbers count from one. Origin mode counts them from the
        margins, so the corners move with the region and a missing
        corner is a margin. A margin does not hold the rectangle in:
        DECFRA, DECERA, DECSERA and DECCRA all reach the whole screen.

        A corner past the screen stops at the edge. A rectangle that
        ends before it starts is no rectangle, and the answer is None.
        """
        lines, columns = self.lines, self.columns
        in_origin_mode = PrivateMode.ORIGIN.flag in self.mode

        vertical = self.margins
        if in_origin_mode and vertical is not None:
            first_row, last_row = vertical.top, vertical.bottom
        else:
            first_row, last_row = 0, lines - 1

        horizontal = self.horizontal_margins
        if in_origin_mode and horizontal is not None:
            first_column, last_column = horizontal
        else:
            first_column, last_column = 0, columns - 1

        top, left = self._corner(top, left)
        bottom = first_row + bottom - 1 if bottom else last_row
        right = first_column + right - 1 if right else last_column

        # The order is read before the edge of the screen cuts the
        # rectangle down. A rectangle that starts past the screen would
        # otherwise fold onto the last row and fill it.
        if bottom < top or right < left:
            return None
        if top >= lines or left >= columns:
            return None

        return top, left, min(bottom, lines - 1), min(right, columns - 1)

    def _corner(self, top: int, left: int) -> Tuple[int, int]:
        """
        Read the row and the column of one corner of a rectangle.

        The numbers count from one, and origin mode counts them from
        the margins. Nothing here holds the corner on the screen: the
        caller knows what it wants to do with a corner past the edge.
        """
        row = (top or 1) - 1
        column = (left or 1) - 1

        if PrivateMode.ORIGIN.flag in self.mode:
            vertical = self.margins
            if vertical is not None:
                row += vertical.top
            horizontal = self.horizontal_margins
            if horizontal is not None:
                column += horizontal.left

        return row, column

    #: The characters that DECFRA writes. They are the two ranges of a
    #: Latin-1 terminal, and xterm drops a code outside them.
    FILL_RANGES = ((32, 126), (160, 255))

    def fill_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECFRA ("CSI Pch ; Pt ; Pl ; Pb ; Pr $ x"): fill a rectangle
        with one character.

        Pch is the code of the character. Each cell takes the rendition
        that is set now, the way a drawn cell does, so a fill under
        DECSCA carries the mark of DECSCA.

        The cursor does not move.
        """
        code = params[0] if params else 0
        if not any(low <= code <= high for low, high in self.FILL_RANGES):
            return

        corners = self._rectangle(*_four(params, 1))
        if corners is None:
            return
        top, left, bottom, right = corners

        protection = self.protection
        if protection:
            cell = _PROTECTED_CHAR_CACHE[(chr(code), self._appearance, protection)]
            self._protected_chars = True
        else:
            cell = _CHAR_CACHE[(chr(code), self._appearance)]

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            self.touch(row + line_offset)
            for column in range(left, right + 1):
                line[column] = cell
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def erase_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECERA ("CSI Pt ; Pl ; Pb ; Pr $ z"): erase a rectangle.

        Each cell takes the background that is set now, the way every
        other erase leaves a cell. No mark holds DECERA away from a
        cell. DECSERA is the one that reads a mark.

        The cursor does not move.
        """
        self._erase_rectangle(self._rectangle(*_four(params, 0)), False)

    def selective_erase_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECSERA ("CSI Pt ; Pl ; Pb ; Pr $ {"): erase a rectangle, and
        leave the cells that DECSCA marked alone.

        Only the mark of DECSCA holds DECSERA away from a cell. The
        mark of ISO 6429 does not, and that is where DECSERA and DECSEL
        part: DECSEL reads both marks, and xterm's own conformance
        suite asks for each of the two.

        The cursor does not move.
        """
        self._erase_rectangle(self._rectangle(*_four(params, 0)), True)

    def _erase_rectangle(
        self, corners: Tuple[int, int, int, int] | None, selective: bool
    ) -> None:
        "Erase every cell of a rectangle that no mark holds back."
        if corners is None:
            return
        top, left, bottom, right = corners

        appearance = self.erase_appearance()
        erased = ErasedCell(" ", appearance) if appearance else None
        reads_the_marks = selective and self._protected_chars

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        for row in range(top, bottom + 1):
            line = data_buffer[row + line_offset]
            self.touch(row + line_offset)
            for column in range(left, right + 1):
                if reads_the_marks:
                    cell = line.get(column)
                    if cell is not None and protection_of(cell) & Protection.DEC:
                        continue
                if erased is None:
                    line.pop(column, None)
                else:
                    line[column] = erased
            self.repair_wide_char(line, left)
            self.repair_wide_char(line, right + 1)

    def copy_rectangle(self, *params: int, **kwargs) -> None:
        """
        DECCRA ("CSI Pts ; Pls ; Pbs ; Prs ; Pps ; Ptd ; Pld ; Ppd $ v"):
        copy a rectangle to another place on the screen.

        The first four parameters name the rectangle to read. The sixth
        and the seventh name the top left corner to write it to, and
        the rectangle that lands there keeps the size of the one that
        was read. Both page numbers are ignored, because ptterm holds
        one page.

        The two rectangles may overlap, so every cell is read before
        any cell is written. A cell that holds nothing clears the cell
        it lands on.

        The cursor does not move.
        """
        corners = self._rectangle(*_four(params, 0))
        if corners is None:
            return
        top, left, bottom, right = corners

        target_top, target_left = self._corner(
            params[5] if len(params) > 5 else 0,
            params[6] if len(params) > 6 else 0,
        )
        if target_top >= self.lines or target_left >= self.columns:
            return

        # A rectangle that would hang over the edge is cut down to what
        # fits, and the rest of it is dropped.
        height = min(bottom - top + 1, self.lines - target_top)
        width = min(right - left + 1, self.columns - target_left)

        data_buffer = self.data_buffer
        line_offset = self.line_offset
        read = [
            [
                data_buffer[top + row + line_offset].get(left + column)
                for column in range(width)
            ]
            for row in range(height)
        ]

        for row in range(height):
            line = data_buffer[target_top + row + line_offset]
            self.touch(target_top + row + line_offset)
            for column, cell in enumerate(read[row]):
                if cell is None:
                    line.pop(target_left + column, None)
                else:
                    line[target_left + column] = cell
            self.repair_wide_char(line, target_left)
            self.repair_wide_char(line, target_left + width)

    # ------------------------------------------------------------------
    # The settings a program picks with one number.
    #
    # Each one reads a `parameters.py` enum, keeps the choice, and
    # reports it back when DECRQSS asks.

    def set_attribute_extent(self, *params: int, **kwargs) -> None:
        """
        DECSACE ("CSI Ps * x"): what DECCARA and DECRARA reach.

        ptterm has neither of those two yet, so the setting is kept and
        nothing acts on it. A program writes it and reads it back with
        DECRQSS, and an answer that says nothing sends it to a guess.
        """
        value = params[0] if params else 0
        if value in tuple(AttributeExtent):
            self.attribute_extent = AttributeExtent(value)

    def set_active_display(self, *params: int, **kwargs) -> None:
        """
        DECSASD ("CSI Ps $ }"): send the output to the status line.

        A pane draws no status line of its own, because pymux draws one
        for the whole window. So the setting is kept and the output
        stays on the screen.
        """
        value = params[0] if params else 0
        if value in tuple(StatusDisplay):
            self.active_display = StatusDisplay(value)

    def set_status_line_type(self, *params: int, **kwargs) -> None:
        """
        DECSSDT ("CSI Ps $ ~"): what the status line holds.

        Kept, for the same reason as DECSASD.
        """
        value = params[0] if params else 0
        if value in tuple(StatusLineType):
            self.status_line = StatusLineType(value)

    def set_conformance_level(self, *params: int, **kwargs) -> None:
        """
        DECSCL ("CSI Ps ; Ps " p"): the level this terminal answers at.

        A real DEC terminal drops the sequences above the level it is
        set to, and a hard reset comes with the change. ptterm reads
        the level for DECNCSM and answers every other sequence it
        knows whatever the level says.

        The second parameter picks the form of a C1 control that this
        terminal writes back. xterm's ctlseqs.txt gives it three values:
        1 is seven bit, which is the DEC factory default, and 0 and 2
        are both eight bit. It is optional, and level 1 ignores it.
        S7C1T and S8C1T set the same thing.
        """
        level = params[0] if params else 0
        if level in tuple(ConformanceLevel):
            self.conformance_level = ConformanceLevel(level)
        if len(params) > 1 and self.conformance_level != ConformanceLevel.VT100:
            self.seven_bit_controls = params[1] == 1

    def set_lines_per_screen(self, *params: int, **kwargs) -> None:
        """
        DECSNLS ("CSI Ps * |"): how many lines the screen shows.

        On a VT420 the page can be longer than the screen, and this
        names the part that a reader sees. A pane is its own page, and
        pymux owns how big it is, so ptterm keeps the number and does
        not resize anything.
        """
        self.lines_per_screen = (params[0] if params else 0) or self.lines

    def set_tab_stop(self) -> None:
        "Set a horizontal tab stop at cursor position."
        self.tabstops.add(self.pt_cursor_position.x)

    def clear_tab_stop(self, type_of: int | None = None) -> None:
        """Clears a horizontal tab stop in a specific way, depending
        on the ``type_of`` value:
        * ``0`` or nothing -- Clears a horizontal tab stop at cursor
          position.
        * ``3`` -- Clears all horizontal tab stops.
        """
        if not type_of:
            # Clears a horizontal tab stop at cursor position, if it's
            # present, or silently fails if otherwise.
            self.tabstops.discard(self.pt_cursor_position.x)
        elif type_of == 3:
            self.tabstops = set()  # Clears all horizontal tab stops.

    def ensure_bounds(self, use_margins: bool | None = None) -> None:
        """Ensure that current cursor position is within screen bounds.

        :param bool use_margins: when ``True`` or when
                                 `PrivateMode.ORIGIN` is set,
                                 cursor is bounded by top and and bottom
                                 margins, instead of ``[0; lines - 1]``.
        """
        margins = self.margins
        if margins and (use_margins or PrivateMode.ORIGIN.flag in self.mode):
            top, bottom = margins
        else:
            top, bottom = 0, self.lines - 1

        cursor_position = self.pt_cursor_position
        line_offset = self.line_offset

        cursor_position.x = min(max(0, cursor_position.x), self.columns - 1)
        cursor_position.y = min(
            max(top + line_offset, cursor_position.y), bottom + line_offset
        )

        # A move of the cursor ends the wait to wrap. Every command
        # that places the cursor comes through here, so this is the one
        # place that has to say it. A tab is the exception, and it
        # never reaches this.
        self.pending_wrap = False

    # ------------------------------------------------------------------
    # The DEC line attributes, and the pattern that shows them.
    #
    # An attribute belongs to the line and rides on the `Row`. The
    # screen holds it and draws nothing: how wide a line looks is the
    # renderer's decision. Lillecarl/pymux#55.

    def alignment_display(self) -> None:
        """
        DECALN ("ESC # 8"): fill the screen with "E".

        The margins go back to the whole screen and the cursor goes
        home afterwards. The DEC manuals say so and kitty does both;
        libvterm does neither.

        Every cell holds a character that a program asked for, so it
        comes out of the cache that `draw` uses. A plain `Cell` reads as
        a cell that nobody wrote, which is what an erase leaves, and
        anything that tells the two apart then reads a blank screen.
        """
        for y in range(0, self.lines):
            line = self.data_buffer[y + self.line_offset]
            self.touch(y + self.line_offset)
            for x in range(0, self.columns):
                line[x] = _CHAR_CACHE["E", PLAIN_APPEARANCE]
        self.margins = None
        self.horizontal_margins = None
        self.cursor_position()

    def _set_line_attribute(self, attribute: LineAttribute) -> None:
        """
        Give the line the cursor stands on a DEC line attribute.

        A plain line carries none, and a row the program never wrote to
        is plain already, so taking one off does not make the row.
        """
        row = self.pt_cursor_position.y
        if attribute == PLAIN_LINE:
            line = self.page.data_buffer.get(row)
            if line is not None:
                line.attribute = None
            return
        self.page.data_buffer[row].attribute = attribute

    def single_width(self) -> None:
        """
        DECSWL ("ESC # 5"): draw this line the plain way.

        It takes both attributes off, which is what libvterm does:
        `set_lineinfo` in its `src/state.c` gets DWL_OFF and DHL_OFF
        from the same call.
        """
        self._set_line_attribute(PLAIN_LINE)

    def double_width(self) -> None:
        "DECDWL (\"ESC # 6\"): draw this line at twice the width."
        self._set_line_attribute(LineAttribute(True, DoubleHeight.NONE))

    def double_height_top(self) -> None:
        """
        DECDHL ("ESC # 3"): the top half of a double height line.

        A double height line is a double width line as well. A program
        writes the same text twice, once on each half, and the terminal
        draws the top of the glyphs on one line and the bottom on the
        other.
        """
        self._set_line_attribute(LineAttribute(True, DoubleHeight.TOP))

    def double_height_bottom(self) -> None:
        "DECDHL (\"ESC # 4\"): the bottom half of one."
        self._set_line_attribute(LineAttribute(True, DoubleHeight.BOTTOM))

    def _forget_line_notes(self, rows) -> None:
        """
        Take the DEC line attribute and the continuation mark off these
        lines, without making a line that is not there.
        """
        data_buffer = self.page.data_buffer
        for row in rows:
            line = data_buffer.get(row)
            if line is not None:
                line.attribute = None
                line.wrapped = False

    # ------------------------------------------------------------------
    # How the characters after this are drawn.
    #
    # SGR builds a `Rendition` and "OSC 8" opens a hyperlink. The two
    # arrive apart and a cell holds both, as one interned `Appearance`.

    def select_graphic_rendition(self, *attrs_tuple: int, private: bool = False) -> None:
        """
        SGR ("CSI Ps m"): the style of the cells that come next.

        A private marker makes another sequence, and none of them is
        SGR. "CSI > Ps m" is XTMODKEYS, which says how xterm encodes a
        key with a modifier; a program sends "CSI > 4 m" to put
        modifyOtherKeys back to where it started. Reading that as SGR
        turns the underline on, and everything the program draws after
        it carries a line it never asked for.
        """
        if private:
            return

        replace: Dict[str, object] = {}

        if not attrs_tuple:
            attrs = [0]
        else:
            attrs = list(attrs_tuple[::-1])

        while attrs:
            attr = attrs.pop()

            # A parameter with colons in it arrives as a tuple, and
            # holds everything the colour needs.
            if isinstance(attr, tuple):
                if attr[0] in (38, 48):
                    color = sgr_color(list(attr))
                    if color is not None:
                        replace["color" if attr[0] == 38 else "bgcolor"] = color
                elif attr[0] == 58:
                    replace["underline_color"] = sgr_color(list(attr))
                elif attr[0] == 4:
                    number = attr[1] if len(attr) > 1 else 1
                    shape = UNDERLINE_SHAPES.get(number)
                    if shape is not None:
                        replace["underline"] = number != 0
                        replace["underline_style"] = shape
                continue

            if attr in COLOR_OF_A_FOREGROUND:
                replace["color"] = COLOR_OF_A_FOREGROUND[attr]
            elif attr in COLOR_OF_A_BACKGROUND:
                replace["bgcolor"] = COLOR_OF_A_BACKGROUND[attr]
            elif attr == 1:
                replace["bold"] = True
            elif attr == 2:
                replace["dim"] = True
            elif attr == 3:
                replace["italic"] = True
            elif attr == 4:
                replace["underline"] = True
                # A plain "4" draws a single line, whatever shape came
                # before it.
                replace["underline_style"] = ""
            elif attr == 5:
                replace["blink"] = True
            elif attr == 6:
                replace["blink"] = True  # Fast blink.
            elif attr == 7:
                replace["reverse"] = True
            elif attr == 8:
                replace["hidden"] = True
            elif attr == 9:
                replace["strike"] = True
            elif attr == 29:
                replace["strike"] = False
            # Where the glyph sits. A terminal draws a raised or a
            # lowered glyph smaller, and 75 puts it back on the line.
            elif attr == 73:
                replace["baseline"] = "superscript"
            elif attr == 74:
                replace["baseline"] = "subscript"
            elif attr == 75:
                replace["baseline"] = ""
            elif attr == 22:
                replace["bold"] = False
                replace["dim"] = False
            elif attr == 23:
                replace["italic"] = False
            elif attr == 21:
                replace["underline"] = True
                replace["underline_style"] = "double"
            elif attr == 24:
                # The colour of the line stays: a program that turns
                # the line on again writes no colour a second time.
                replace["underline"] = False
            elif attr == 25:
                replace["blink"] = False
            elif attr == 27:
                replace["reverse"] = False
            elif not attr:
                replace = {}
                self._rendition = PLAIN

            elif attr == 59:
                replace["underline_color"] = None
            elif attr in (38, 48):
                # The colour follows in the parameters that come next.
                parameters = [attr]
                while attrs and len(parameters) < sgr_color_parameters(parameters):
                    parameters.append(attrs.pop())
                color = sgr_color(parameters)
                if color is not None:
                    replace["color" if attr == 38 else "bgcolor"] = color

            elif attr == 58:
                parameters = [attr]
                while attrs and len(parameters) < sgr_color_parameters(parameters):
                    parameters.append(attrs.pop())
                replace["underline_color"] = sgr_color(parameters)

        self._rendition = self._rendition._replace(**replace)  # type:ignore
        self._rebuild_appearance()

    def _rebuild_appearance(self) -> None:
        """
        What a cell drawn now carries: the rendition and the hyperlink.

        A hyperlink is not a rendition. "OSC 8" opens one and "CSI m"
        says nothing about it, so the two are kept apart and joined
        here.

        This runs once per SGR sequence and once per "OSC 8", and never
        per cell. `draw` reaches for the answer.
        """
        target = self.hyperlink
        self._appearance = appearance_of[
            self._rendition,
            target,
            # An id outside a link joins nothing to nothing.
            self.hyperlink_id if target else "",
        ]

    def set_hyperlink(self, target: str, link_id: str = "") -> None:
        """
        Open a hyperlink, or close the one that is open.

        Every cell that a program draws from here on carries the target
        and the id, until the program sends an empty target.

        The id joins the pieces of one link. A program that writes a
        link across two lines gives both pieces one id, and the
        terminal of the user then highlights both when a pointer rests
        on either. So a new id opens a new link, even when the target
        does not change.
        """
        if (target, link_id) == (self.hyperlink, self.hyperlink_id):
            return
        self.hyperlink = target
        self.hyperlink_id = link_id
        self._rebuild_appearance()

    # Colour scheme that a pane is told about ("CSI ? 996 n"). pymux
    # renders a dark background, so a pane that asks gets the dark
    # answer. (One is dark, two is light.)
    color_scheme = 1

    #: What "CSI ? Ps n" answers about a part that this terminal does
    #: not have. Each one has a legal answer that says "no", and a
    #: program that asks has to read one: a query with no answer leaves
    #: the program waiting, and leaves every answer after it one place
    #: out of step.
    #:
    #: Each answer is the body of a control sequence, without the CSI
    #: in front of it. `reply_csi` spells that, because S8C1T changes
    #: how it is spelled.
    _DEVICE_STATUS_ANSWERS = {
        # DSRPrinterPort. 13 is "no printer".
        15: "?13n",
        # DSRUDKLocked. 20 is "unlocked". Nothing here defines a key,
        # so nothing can lock one either.
        25: "?20n",
        # DSRKeyboard: 27, then the language, the state and the type.
        # 1 is North American, 0 is ready and 5 is a PC keyboard.
        26: "?27;1;0;5n",
        # DSRLocatorStatus. 50 is "no locator". DECELR is not here, so
        # there is no locator to report on.
        55: "?50n",
        # DSRLocatorId: 57, then the kind of pointing device. 0 is
        # "not known".
        56: "?57;0n",
        # DECMSR: the room left for a macro, in bytes. This terminal
        # holds no macro and defines none, so there is no room. The
        # answer carries no private marker, and ends with "* {".
        62: "0*{",
        # DSRDataIntegrity. 70 is "no error since the last report".
        75: "?70n",
        # DSRMultipleSessionStatus. 83 is "not configured for more
        # than one session". A pane is a session of pymux, not of the
        # terminal.
        85: "?83n",
    }

    # ------------------------------------------------------------------
    # Reports and queries: everything a program can ask, and the answer.
    #
    # Not one of these holds state of its own. Each reads the screen and
    # writes bytes back through `reply_csi` and its neighbours.

    def report_device_status(
        self, data: int = 0, *args, private=False, **kwargs
    ) -> None:
        """
        Answer a device status report.

        "CSI 5 n" asks whether the terminal is well, "CSI 6 n" asks for
        the cursor position and "CSI ? 6 n" asks for it with the page
        number. "CSI ? 996 n" asks which colour scheme the terminal
        uses.

        The rest of "CSI ? Ps n" asks about a printer, a keyboard, a
        locator or a macro. This terminal has none of those, and each
        one has a legal answer that says so.

        Unknown reports are ignored. The private marker arrives as the
        `private` keyword; it must not raise, or one sequence would
        stop the whole pane.
        """
        if private is True and data == 996:
            self.reply_csi("?997;%in" % self.color_scheme)
            return

        if private is True and data == 63:
            # DECCKSR: the checksum of the macros, as "DCS Pid ! ~
            # xxxx ST". No macro is defined, so the sum is zero.
            pid = args[0] if args else 0
            self.reply_dcs("%i!~0000" % pid)
            return

        if private is True and data in self._DEVICE_STATUS_ANSWERS:
            self.reply_csi(self._DEVICE_STATUS_ANSWERS[data])
            return

        if data == 6:
            y, x = self.reported_position
            if private is True:
                # DECXCPR: the page number comes after the position.
                self.reply_csi("?%i;%i;1R" % (y, x))
            else:
                self.reply_csi("%i;%iR" % (y, x))
            return

        if data == 5 and private is False:
            # "The terminal is well."
            self.reply_csi("0n")

    def unscroll(self, count: int | None = None, *args, **kwargs) -> None:
        """
        Kitty's unscroll ("CSI Ps SP D").

        Move the screen down by `count` lines and bring the lines above
        it back from the scroll buffer. A shell uses it when a
        full-screen program ends: the lines that the program covered
        come back instead of leaving blank space under the prompt.

        The lines that leave the bottom of the screen are dropped, and
        the cursor keeps its position on the screen. Nothing happens
        when there is no history left to pull from.
        """
        count = count or 1
        count = min(count, self.line_offset, self.lines)
        if count <= 0:
            return

        data_buffer = self.data_buffer
        for row in range(self.max_y - count + 1, self.max_y + 1):
            data_buffer.pop(row, None)
            self.touch(row)

        self.max_y -= count
        self.graphics.prune_below(self.max_y)

        # The screen slides down over rows that a prune took away, and
        # a program may write on them again. `history_floor` says that
        # no row lives under it, so it has to follow: without this, a
        # row written at the new top of the screen sits under the floor,
        # and the next prune walks from the floor and never reaches it.
        #
        # Lowering the floor is always safe. It says where a prune
        # starts looking, and looking lower finds nothing that is not
        # there.
        self.history_floor = min(self.history_floor, self.line_offset)

        cursor_position = self.pt_cursor_position
        cursor_position.y = max(0, cursor_position.y - count)
        self.ensure_bounds()

        # The screen has slid down over rows of the history, and a
        # reflow leaves the history at the width it was written at. So
        # the rows that just arrived may be laid out at another width,
        # and this is the one path that brings such a row back onto the
        # screen. Lay them out again. Lillecarl/pymux#135.
        if self.line_offset < self.reflow_floor:
            self._reflow()

    def placeholder_runs(
        self, first_row: int, last_row: int
    ) -> List[PlaceholderRun]:
        """
        The unicode placeholder runs between two rows of the scroll
        buffer, for an embedder that draws the images.

        The runs that sit on top of each other come back as one
        rectangle, so a screen full of one image is one run and not one
        per line.

        The answer is empty while the pane holds no virtual placement,
        so a pane that shows no image pays nothing for the scan.
        """
        if not self.graphics.has_virtual_placements:
            return []

        data_buffer = self.page.data_buffer
        columns = self.columns
        runs: List[PlaceholderRun] = []
        for row in range(first_row, last_row + 1):
            line = data_buffer.get(row)
            if line:
                runs.extend(runs_in_line(line, columns, row))
        return merge_runs(runs)

    def report_version(self, *params: int, private: object = False, **kwargs) -> None:
        """
        XTVERSION ("CSI > q"): the name and the version of the terminal.

        Programs read it to decide which extensions they may use. The
        answer names ptterm, because ptterm draws the pane. A plain
        "CSI Ps q" is DECLL, which loads the keyboard lights of a real
        VT220; it is ignored.
        """
        if private != ">":
            return
        self.reply_dcs(">|%s" % TERMINAL_VERSION)

    #: The private modes that this screen acts on. DECRQM answers for
    #: these; every other mode is reported as not recognised, so that a
    #: program falls back instead of trusting an answer we invent.
    _known_private_modes = frozenset(
        [
            PrivateMode.APPLICATION_CURSOR_KEYS,
            PrivateMode.COLUMNS_132,
            PrivateMode.CURSOR_BLINK,
            PrivateMode.REVERSE_VIDEO,
            PrivateMode.ORIGIN,
            PrivateMode.AUTOWRAP,
            PrivateMode.SHOW_CURSOR,
            PrivateMode.ALLOW_80_TO_132,
            PrivateMode.MORE_FIX,
            PrivateMode.REVERSE_WRAP,
            PrivateMode.ALTERNATE_SCREEN,
            PrivateMode.LEFT_RIGHT_MARGIN,
            PrivateMode.NO_CLEAR_ON_COLUMN_CHANGE,
            PrivateMode.REVERSE_WRAP_ANYWHERE,
            PrivateMode.MOUSE_REPORTING,
            PrivateMode.SGR_MOUSE,
            PrivateMode.URXVT_MOUSE,
            PrivateMode.ALTERNATE_SCREEN_AGAIN,
            PrivateMode.SAVE_CURSOR,
            PrivateMode.ALTERNATE_SCREEN_WITH_CURSOR,
            PrivateMode.BRACKETED_PASTE,
            PrivateMode.INBAND_RESIZE,
        ]
    )

    #: The same for the modes without a private marker.
    _known_ansi_modes = frozenset(
        [AnsiMode.INSERT_REPLACE, AnsiMode.LINE_FEED_NEW_LINE]
    )

    #: The modes that a terminal knows about and never implements.
    #: DECRQM answers 4 for these, which reads as "permanently reset".
    #:
    #: That is a different answer from 0. A 0 says "I never heard of
    #: this mode", and a program then has to guess. A 4 says "the mode
    #: exists, and it can never be on", which is the truth here and
    #: what a program needs to stop asking.
    #:
    #: These twelve come from the ANSI standard. No terminal that
    #: anybody uses implements one of them, and xterm answers 4 for
    #: every one.
    _permanently_reset_ansi_modes = frozenset(
        [
            AnsiMode.GUARDED_AREA_TRANSFER,
            AnsiMode.STATUS_REPORT_TRANSFER,
            AnsiMode.VERTICAL_EDITING,
            AnsiMode.HORIZONTAL_EDITING,
            AnsiMode.POSITIONING_UNIT,
            AnsiMode.FORMAT_EFFECTOR_ACTION,
            AnsiMode.FORMAT_EFFECTOR_TRANSFER,
            AnsiMode.MULTIPLE_AREA_TRANSFER,
            AnsiMode.TRANSFER_TERMINATION,
            AnsiMode.SELECTED_AREA_TRANSFER,
            AnsiMode.TABULATION_STOP,
            AnsiMode.EDITING_BOUNDARY,
        ]
    )

    #: The same for the modes with a private marker.
    _permanently_reset_private_modes = frozenset(
        [
            PrivateMode.HORIZONTAL_CURSOR_COUPLING,
        ]
    )

    #: The modes that this screen keeps and does not act on.
    #:
    #: A mode here is remembered: a set makes DECRQM answer 1, and a
    #: reset makes it answer 2. Nothing else happens. That is a third
    #: thing, beside a mode this screen acts on and a mode that can
    #: never be on, and the three need three answers.
    #:
    #: The reason to keep one is that a program writes a mode and reads
    #: it back to learn whether the terminal took it. An answer of 0
    #: sends that program to a guess. Every mode here is one that xterm
    #: keeps as well.
    #:
    #: The comment on each line says what the mode would do. Four of
    #: them name real behaviour that ptterm does not have yet, and
    #: `tests/DEVIATIONS.md` carries them.
    _remembered_ansi_modes = frozenset(
        [
            AnsiMode.KEYBOARD_LOCKED,  # :todo: drop the input.
            AnsiMode.LOCAL_ECHO,  # :todo: echo it.
        ]
    )

    #: The same for the modes with a private marker.
    _remembered_private_modes = frozenset(
        [
            # A pane draws as fast as it can, and holds no printer.
            PrivateMode.SLOW_SCROLL,
            PrivateMode.PRINT_FORM_FEED,
            PrivateMode.PRINT_EXTENT,
            # These three name real behaviour. :todo: act on them.
            PrivateMode.HEBREW_KEYBOARD,
            PrivateMode.NATIONAL_CHARSETS,
            PrivateMode.APPLICATION_KEYPAD,
            PrivateMode.BACKARROW_IS_BACKSPACE,
        ]
    )

    def report_mode(self, *params: int, private: object = False, **kwargs) -> None:
        """
        DECRQM ("CSI ? Ps $ p" and "CSI Ps $ p"): is this mode set?

        The answer is "CSI ? Ps ; Pm $ y". Pm is 1 for set, 2 for reset,
        4 for a mode that exists and can never be on, and 0 for a mode
        that this screen never heard of.

        A mode gets 1 or 2 when this screen keeps it, whether it acts
        on the mode or not. A program writes a mode and reads it back
        to learn whether the terminal took it, and a 0 sends that
        program to a guess. `_remembered_ansi_modes` names the ones
        that are kept and not acted on.

        DECRQM arrived with the VT320. A program that asked for an
        earlier terminal with DECSCL hears nothing at all, which is
        what a real one does.
        """
        if self.conformance_level < ConformanceLevel.VT300:
            return

        number = params[0] if params else 0
        is_private = private is True

        if is_private:
            permanent = number in self._permanently_reset_private_modes
            known = (
                number in self._known_private_modes
                or number in self._remembered_private_modes
            ) and self._embedder_carries(number)
            if number == PrivateMode.CURSOR_BLINK:
                # DECSCUSR writes this one as well, and the alternate
                # screen carries a `mode` of its own. So the answer
                # comes from the shape, which is the one value that
                # both sequences write.
                enabled = self.cursor_blinks
            else:
                enabled = flag_of(number) in self.mode
        else:
            permanent = number in self._permanently_reset_ansi_modes
            known = (
                number in self._known_ansi_modes
                or number in self._remembered_ansi_modes
            )
            enabled = number in self.mode

        if permanent:
            state = ModeReport.PERMANENTLY_RESET
        elif not known:
            state = ModeReport.UNKNOWN
        else:
            state = ModeReport.SET if enabled else ModeReport.RESET

        self.reply_csi(
            "%s%i;%i$y" % ("?" if is_private else "", number, state)
        )

    def set_cursor_style(self, *params: int, **kwargs) -> None:
        """
        DECSCUSR ("CSI Ps SP q"): the shape of the cursor.

        The shape belongs to the pane. What draws the pane reads
        `cursor_style` and puts the shape on the terminal of the user,
        so a pane that asks for a bar gets one. A program that sets a
        shape also asks for it back, and it reads what it wrote.
        """
        style = params[0] if params else 0
        if style == 0:
            self.cursor_style = DEFAULT_CURSOR_STYLE
        elif style in iter(CursorShape):
            self.cursor_style = CursorShape(style)
        else:
            # A number no shape has. Nothing is asked for, so nothing
            # changes, and the ask below would be a lie.
            return
        self.cursor_style_asked = True

    def set_cursor_blink(self, blinking: bool) -> None:
        """
        Turn the blinking of the cursor on or off, and keep its shape.

        Mode 12 says only whether the cursor blinks. DECSCUSR says the
        shape and the blinking together, so this writes the same value:
        the blinking shape of a pair is the odd number, and the steady
        one is the number after it.
        """
        style = self.cursor_style
        if blinking and style % 2 == 0:
            self.cursor_style = CursorShape(style - 1)
        elif not blinking and style % 2 == 1:
            self.cursor_style = CursorShape(style + 1)
        self.cursor_style_asked = True

    @property
    def cursor_blinks(self) -> bool:
        "True when the cursor of this screen blinks."
        return self.cursor_style % 2 == 1

    def report_setting(self, name: str) -> None:
        """
        DECRQSS ("DCS $ q <name> ST"): the current value of a setting.

        The answer is "DCS 1 $ r <value> <name> ST" for a setting that
        this screen keeps, and "DCS 0 $ r ST" for one that it does not.
        """
        if name == "m":
            value = self._current_rendition()
        elif name == " q":
            value = "%i" % self.cursor_style
        elif name == "r":
            margins = self.margins or Margins(0, self.lines - 1)
            value = "%i;%i" % (margins.top + 1, margins.bottom + 1)
        elif name == "s":
            left, right = self.left_right
            value = "%i;%i" % (left + 1, right + 1)
        elif name == '"q':
            # DECSCA: does a selective erase leave the cells that come
            # next alone?
            value = "1" if self.protection & Protection.DEC else "0"
        elif name == "*x":
            value = "%i" % self.attribute_extent
        elif name == "$}":
            value = "%i" % self.active_display
        elif name == "$~":
            value = "%i" % self.status_line
        elif name == '"p':
            # 1 names seven bit controls and 2 names eight, the way
            # DECSCL reads them. 0 also means eight bit on the way in,
            # and the answer picks one of the two names.
            value = "%i;%i" % (
                self.conformance_level,
                1 if self.seven_bit_controls else 2,
            )
        elif name == "*|":
            value = "%i" % self.lines_per_screen
        elif name == "t":
            # DECSLPP: the lines of the page. A pane is its own page,
            # so the answer is how tall the pane is.
            #
            # "CSI Ps t" with Ps of 24 or more asks for a page of that
            # many lines, and xterm resizes its window. ptterm does not
            # take it: pymux owns how tall a pane is, and one pane
            # cannot move another one. So the answer is the truth about
            # this pane and not the number a program asked for.
            # `tests/DEVIATIONS.md` carries it.
            value = "%i" % self.lines
        else:
            self.reply_dcs("0$r")
            return

        self.reply_dcs("1$r%s%s" % (value, name))

    def report_capabilities(self, query: str) -> None:
        """
        XTGETTCAP ("DCS + q <names> ST"): what this terminal can do.

        The names arrive as hexadecimal, separated by semicolons, and
        each one is answered on its own. "1 + r" carries a capability
        that this terminal has and "0 + r" one that it does not.

        This is what a program asks when the database of the machine
        it runs on says nothing useful, which is every time it runs
        over ssh.
        """
        for encoded in query.split(";"):
            try:
                name = bytes.fromhex(encoded).decode("ascii")
            except ValueError:
                self.reply_dcs("0+r%s" % encoded)
                continue

            value = CAPABILITIES.get(name)
            if value is None:
                self.reply_dcs("0+r%s" % encoded)
            elif value is True:
                self.reply_dcs("1+r%s" % encoded)
            else:
                self.reply_dcs(
                    "1+r%s=%s" % (encoded, str(value).encode("utf-8").hex())
                )

    def _current_rendition(self) -> str:
        """
        The graphic rendition of this screen, as SGR parameters.

        A colour comes back the way the program named it. A number of
        the palette is a number, and a colour of its own is its three
        components. A program that probes for 24 bit colour reads its
        own colour back, which is the answer it looks for.

        One of the first sixteen comes back as the parameter that sets
        it: "31" and not "38;5;1". That is what libvterm answers, and
        its own test file says so ("t/26state_query.test", "DECRQSS on
        SGR ANSI colours"). A pane cannot tell "CSI 31 m" from
        "CSI 38;5;1 m" afterwards, because both leave the same colour,
        and either answer sets the colour back. So the shorter one, and
        the one the references write.

        "SGR 58" has no short form, so the colour of the underline is
        always a number or three components.
        """
        rendition = self._rendition
        parts = ["0"]

        for flag, parameter in (
            (rendition.bold, "1"),
            (rendition.dim, "2"),
            (rendition.italic, "3"),
            (rendition.underline, UNDERLINE_PARAMETERS[rendition.underline_style or ""]),
            (rendition.blink, "5"),
            (rendition.reverse, "7"),
            (rendition.hidden, "8"),
            (rendition.strike, "9"),
            (
                rendition.baseline,
                BASELINE_PARAMETERS.get(rendition.baseline or "", ""),
            ),
        ):
            if flag:
                parts.append(parameter)

        for color, code, background in (
            (rendition.color, 38, False),
            (rendition.bgcolor, 48, True),
        ):
            # The default colour has a single code of its own, 39 and
            # 49, and this does not write it: the answer opens with "0",
            # which already says the default.
            if color is None or color == DEFAULT_COLOR:
                continue
            if color.index is not None:
                short = sgr_code_of(color.index, background)
                if short is not None:
                    parts.append("%i" % short)
                else:
                    parts.append("%i;5;%i" % (code, color.index))
            elif color.rgb is not None:
                parts.append("%i;2;%i;%i;%i" % ((code,) + color.rgb))

        underline_color = rendition.underline_color
        if rendition.underline and underline_color is not None:
            if underline_color.index is not None:
                parts.append("58:5:%i" % underline_color.index)
            elif underline_color.rgb is not None:
                parts.append("58:2::%i:%i:%i" % underline_color.rgb)

        return ";".join(parts)

    def report_window(
        self, *params: int, private: object = False, **kwargs
    ) -> None:
        """
        Window manipulation ("CSI Ps t").

        With the private marker the same final byte is SM_Title
        ("CSI > Ps t"), which sets a title mode. xterm reads the two
        apart by the marker, and so does this: without it, "CSI > 4 t"
        would ask for a resize in pixels.

        The sizes and the titles are answered. A pane has no window of
        its own, so it cannot move, iconify or maximize one, and it
        ignores every operation that asks for that.

        Three of them ask for a size: DECSLPP ("CSI Ps t" with a Ps of
        24 or more), and the two forms of a resize, in cells and in
        pixels. Those go to `resize_func`, and the embedder decides.
        pymux asks the person first, because a pane sits in a layout
        and making one taller makes another shorter.

        A pane that draws images asks for the cell size (16) to work out
        how many cells an image covers. The answer is the size that
        `pyte.images` assumes, so both sides count alike.
        """
        if private == ">":
            self.titles.change_modes(params, True)
            return

        what = params[0] if params else 0
        which = params[1] if len(params) > 1 else 0

        if what >= FIRST_PAGE_LENGTH:
            # DECSLPP: a page of `what` lines, and the columns stay.
            self.resize_func(what, None)
        elif what == WindowOp.RESIZE_CHARS:
            self._resize_in_cells(params)
        elif what == WindowOp.RESIZE_PIXELS:
            self._resize_in_pixels(params)
        elif what == WindowOp.REPORT_ICON_LABEL:
            self.reply_osc("L%s" % self.titles.to_report(self.titles.icon))
        elif what == WindowOp.REPORT_WINDOW_TITLE:
            self.reply_osc("l%s" % self.titles.to_report(self.titles.window))
        elif what == WindowOp.PUSH_TITLE:
            self.titles.push()
        elif what == WindowOp.POP_TITLE:
            self.titles.pop(which)
        elif what == WindowOp.REPORT_CELL_SIZE_PIXELS:
            # Cell size in pixels: height first, then width.
            self.reply_csi(
                "6;%i;%it" % (ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH)
            )
        elif what == WindowOp.REPORT_TEXT_AREA_CHARS:
            # Size of the text area, in cells.
            self.reply_csi("8;%i;%it" % (self.lines, self.columns))
        elif what == WindowOp.REPORT_TEXT_AREA_PIXELS:
            # Size of the text area, in pixels.
            self.reply_csi(
                "4;%i;%it"
                % (self.lines * ASSUMED_CELL_HEIGHT, self.columns * ASSUMED_CELL_WIDTH)
            )
        elif what == WindowOp.REPORT_SCREEN_SIZE_CHARS:
            # How much room there is, in cells.
            #
            # For a window that is the display it stands on. A pane
            # stands on no display: it draws where the embedder puts
            # it and it cannot take more. So the room it has is the
            # room it already fills, and the honest answer is its own
            # size.
            #
            # A program reads this to learn how large it could become.
            # Naming a screen it cannot reach would send it asking for
            # a size that nothing can give.
            self.reply_csi("9;%i;%it" % (self.lines, self.columns))
        elif what == WindowOp.REPORT_SCREEN_SIZE_PIXELS:
            # The same room, counted in pixels.
            self.reply_csi(
                "5;%i;%it"
                % (self.lines * ASSUMED_CELL_HEIGHT, self.columns * ASSUMED_CELL_WIDTH)
            )

    def _resize_in_cells(self, params: Tuple[int, ...]) -> None:
        """
        "CSI 8 ; Ph ; Pw t": ask for Ph rows and Pw columns.

        A zero means "as much as there is", and a missing number means
        "leave this one alone". xterm reads them that way, and a
        program sends "CSI 8 ; 0 ; 80 t" to keep its height.
        """
        self.resize_func(
            self._wanted(params, 1, self.MAX_LINES),
            self._wanted(params, 2, self.MAX_COLUMNS),
        )

    def _resize_in_pixels(self, params: Tuple[int, ...]) -> None:
        """
        "CSI 4 ; Ph ; Pw t": as many cells as fit in Ph by Pw pixels.

        A pane holds no pixels, so it counts them in the cell size that
        `pyte.images` assumes. That is the same size the pane
        reports for a cell, so a program that divides gets back what it
        asked for.
        """
        lines = self._wanted(params, 1, None)
        columns = self._wanted(params, 2, None)
        self.resize_func(
            self.MAX_LINES if lines == 0 else
            None if lines is None else max(1, lines // ASSUMED_CELL_HEIGHT),
            self.MAX_COLUMNS if columns == 0 else
            None if columns is None else max(1, columns // ASSUMED_CELL_WIDTH),
        )

    @staticmethod
    def _wanted(
        params: Tuple[int, ...], index: int, whole: int | None
    ) -> int | None:
        """
        One number of a resize: how many, all of them, or leave it.

        A missing number leaves that side as it is, and None says so. A
        zero asks for the whole screen, and `whole` is what that means.
        """
        if len(params) <= index:
            return None
        value = params[index]
        return whole if value == 0 else value

    #: What "as much as there is" means. Nothing here knows how big the
    #: screen of the person is, so the embedder cuts these down to what
    #: it really has.
    MAX_LINES = 10000
    MAX_COLUMNS = 10000

    #: How many titles "CSI 22 t" remembers. xterm keeps ten, and a
    #: program that pushes and never pops must not grow the pane.
    def report_checksum(self, *params: int, **kwargs) -> None:
        """
        DECRQCRA ("CSI Pid ; Pp ; Pt ; Pl ; Pb ; Pr * y"): the checksum
        of a rectangle of the screen.

        The answer is "DCS Pid ! ~ xxxx ST", four hex digits. The value
        is the negated sum of the characters in the rectangle. DEC's own
        terminals answer that, and a conformance suite reads the screen
        back this way, one cell at a time.

        Only the character of a cell counts. A DEC terminal adds bits
        for the attributes of the cell as well, and xterm does again
        since its patch 336, but the two disagree on which bits. Nothing
        reads them here, so the simpler rule stands until something
        does.

        A cell that holds nothing counts as a space. So the sum of one
        cell is never zero, and the answer is never "0000", which a
        caller cannot tell apart from an answer that never came.
        """
        pid = params[0] if params else 0

        # Origin mode counts the corners from the margins, the same way
        # every other rectangle command counts them. A corner that is
        # not named is a margin.
        first_row, last_row = 0, self.lines - 1
        first_column, last_column = 0, self.columns - 1
        if PrivateMode.ORIGIN.flag in self.mode:
            if self.margins is not None:
                first_row, last_row = self.margins.top, self.margins.bottom
            if self.horizontal_margins is not None:
                first_column, last_column = self.horizontal_margins

        named_bottom = params[4] if len(params) > 4 else 0
        named_right = params[5] if len(params) > 5 else 0
        top, left = self._corner(
            params[2] if len(params) > 2 else 0,
            params[3] if len(params) > 3 else 0,
        )
        bottom = first_row + named_bottom - 1 if named_bottom else last_row
        right = first_column + named_right - 1 if named_right else last_column

        # A rectangle that ends before it starts is read the other way
        # round. The suite that drives this reads one cell at a time,
        # so an answer that never comes costs more than a wrong one.
        top, bottom = sorted(
            (max(0, min(top, self.lines - 1)),
             max(0, min(bottom, self.lines - 1)))
        )
        left, right = sorted(
            (max(0, min(left, self.columns - 1)),
             max(0, min(right, self.columns - 1)))
        )

        line_offset = self.line_offset
        total = 0
        for y in range(top, bottom + 1):
            row = self.data_buffer[y + line_offset]
            for x in range(left, right + 1):
                char = row[x].char
                total += ord(char[0]) if char else ord(" ")

        self.reply_dcs("%i!~%04X" % (pid, -total & 0xFFFF))

    def save_modes(self, *params: int) -> None:
        """
        XTSAVE ("CSI ? Pm s"): put private modes away.

        A program that wants to change a mode and give it back the way
        it found it saves it here first. It is the pair of XTRESTORE.
        A mode that a pane does not know is remembered as off, which is
        what a query of it answers.
        """
        for number in params:
            mode = flag_of(number)
            self.saved_modes[number] = mode in self.mode

    def restore_modes(self, *params: int) -> None:
        """
        XTRESTORE ("CSI ? Pm r"): bring back what XTSAVE put away.

        A mode that was never saved is left as it is. xterm does the
        same: a restore of nothing changes nothing.
        """
        for number in params:
            if number not in self.saved_modes:
                continue
            if self.saved_modes[number]:
                self.set_mode(number, private=True)
            else:
                self.reset_mode(number, private=True)

    def report_device_attributes(self, *params: int, **kwargs) -> None:
        """
        Answer DA ("CSI c") and DA2 ("CSI > c").

        The two are different questions and they take different
        answers. DA asks what the terminal can do, and answers with a
        level and the list of extensions. DA2 asks what the terminal
        is, and answers with a type, a firmware version and a keyboard.

        A program reads the prefix to tell one answer from the other,
        so the two may not be confused. ptterm answered the DA2 shape
        to both, and a program asking DA read it as a DA2 reply.
        """
        private = kwargs.get("private")
        if private == ">":
            # The type, the firmware and the keyboard. The firmware is
            # the patch level of xterm that a pane follows, which is
            # how a program reads it: the number says which behaviours
            # it may count on.
            self.reply_csi(">%i;%i;0c" % (XTERM_TYPE, XTERM_PATCH_LEVEL))
        elif not private and not (params and params[0]):
            self.reply_csi(
                "?%s;%sc"
                % (
                    self.conformance_level,
                    ";".join(str(one) for one in DEVICE_EXTENSIONS),
                )
            )

    def report_kitty_keyboard(self, *params, private=False) -> None:
        """
        Handle the ``CSI u`` sequences of the kitty keyboard protocol:
        push (``CSI > flags u``), pop (``CSI < number u``),
        set (``CSI = flags ; mode u``) and query (``CSI ? u``).

        Requires a ``pyte`` stream that passes the private marker (``>``,
        ``<`` or ``=``) through as the ``private`` keyword argument. With
        an unpatched ``pyte``, the sequences don't reach this method.
        """
        if private is True:
            # Query: reply with the flags that this pane really gets.
            # (Not the ones it asked for: see
            # `deliverable_kitty_keyboard_flags`.)
            self.reply_csi("?%iu" % self.deliverable_kitty_keyboard_flags)

        elif private == ">":
            # Push. The flags default to none.
            self.kitty_flags_stack = kitty_keys.pushed(
                self.kitty_flags_stack, params[0] if params else 0
            )

        elif private == "<":
            # Pop. The count defaults to one.
            self.kitty_flags_stack = kitty_keys.popped(
                self.kitty_flags_stack, params[0] if params else 1
            )

        elif private == "=":
            # Set. The mode defaults to setting the flags exactly.
            stack = kitty_keys.with_flags_set(
                self.kitty_flags_stack,
                params[0] if params else 0,
                params[1] if len(params) > 1 else kitty_keys.SET_EXACTLY,
            )
            if stack is not None:
                self.kitty_flags_stack = stack

        else:
            # A plain "CSI u" carries no private marker, so it is not
            # part of the protocol at all. It is SCORC, the restore of
            # the SCO console, and xterm reads it that way.
            self.restore_cursor()

    # ------------------------------------------------------------------
    # The OSC sequences.
    #
    # `osc.py` says what each payload holds and holds the state that
    # goes with it. Three of them only the terminal of the user can
    # serve, and those go out to `osc_func`.

    def osc(self, code: str, param: str) -> None:
        """
        An OSC sequence other than the title and the icon name.

        A pane keeps its own colours. A program sets one and reads it
        back, and the answer is what the program set; the defaults
        answer until it sets anything. What the embedder draws with is
        a separate question, and the answer to it is that a pane does
        not paint the terminal of the user.

        A hyperlink ("OSC 8") belongs to the cells that follow it, so
        the screen keeps it and every cell carries it.

        A few sequences ask the terminal of the user for something that
        a pane cannot give: the clipboard, a desktop notification, the
        shape of the pointer. Those go to `osc_func`, and the embedder
        decides what reaches the user.

        Everything else is consumed. It must not raise: one sequence
        may not stop the pane.
        """
        if code == Osc.HYPERLINK:
            link = parse_hyperlink(param)
            if link is not None:
                link_id, target = link
                self.set_hyperlink(target, link_id)
        elif code == Osc.POINTER_SHAPE:
            self._set_pointer_shape(param)
        elif code == Osc.PALETTE_COLOR:
            self._reply_each(self.colors.read_indexed(code, param, 0))
        elif code == Osc.SPECIAL_COLOR:
            self._reply_each(
                self.colors.read_indexed(code, param, FIRST_SPECIAL_COLOR)
            )
        elif code == Osc.RESET_PALETTE_COLOR:
            self.colors.reset_indexed(param, 0, len(PALETTE))
        elif code == Osc.RESET_SPECIAL_COLOR:
            self.colors.reset_indexed(
                param, FIRST_SPECIAL_COLOR, len(SPECIAL_COLOR_NAMES)
            )
        elif code in DYNAMIC_COLOR_CODES:
            self._reply_each(self.colors.read_dynamic(code, param))
        elif self._reset_code_of(code) in DYNAMIC_COLOR_CODES:
            self.colors.reset_dynamic(self._reset_code_of(code))
        elif code == Osc.KITTY_COLORS:
            answer = self.colors.answer_kitty(param)
            if answer is not None:
                self.reply_osc(answer)
        elif code in FORWARDED_OSC:
            self._forward_osc(code, param)

    def _reply_each(self, answers: Iterable[str]) -> None:
        """
        Answer a colour query with one sequence for each question.

        A program reads one answer for each question it asked, so two
        questions may not come back as one.
        """
        for answer in answers:
            self.reply_osc(answer)

    @staticmethod
    def _reset_code_of(code: str) -> str:
        """
        The code that sets what `code` puts back, or the code itself
        when it sets nothing. "OSC 110" gives "10".
        """
        if not code.isdigit():
            return code
        return str(int(code) - DYNAMIC_COLOR_RESET_OFFSET)

    def _set_pointer_shape(self, param: str) -> None:
        """
        "OSC 22": the shape of the pointer over the pane.

        `PointerShapes` keeps the stack and reads the payload. What
        belongs here is the two things only a screen can do: answer a
        question, and tell the embedder to look again.
        """
        read = self.pointer_shapes.read(param)
        if read.answer is not None:
            self.reply_osc(read.answer)
        if read.changed:
            self._forward_osc(Osc.POINTER_SHAPE, param)

    def _forward_osc(self, code: str, param: str) -> None:
        """
        Hand an OSC sequence to the embedding application.

        A clipboard query is not handed on. It reads what the user
        copied somewhere else, and a program in a pane has no claim on
        that. Writing the clipboard is handed on; reading it is not.
        """
        if code == Osc.CLIPBOARD and asks_for_the_clipboard(param):
            return
        self.osc_func(code, param)

    def set_icon_name(self, param: str) -> None:
        "\"OSC 0\" and \"OSC 1\": the label of the icon."
        self.titles.set_icon(param)

    def set_title(self, param: str) -> None:
        "\"OSC 0\" and \"OSC 2\": the title of the window."
        self.titles.set_window(param)

    # ------------------------------------------------------------------
    # APC, DCS, and what the parser hands over with nowhere else to go.

    def apc(self, data: str) -> None:
        """
        APC string sequence (``ESC _ ... ST``).

        Kitty graphics protocol commands arrive here. They are parsed
        and their images and placements are stored; the pixel data is
        not rendered (the embedding application, e.g. the pymux
        multiplexer, decides how to display images).
        """
        if not data.startswith("G"):
            return  # Not the graphics protocol.

        result = self.graphics.handle(data[1:], self)
        if result is not None:
            response, _is_ok = result
            self.reply_apc("G" + response)

    def dcs(self, data: str) -> None:
        """
        DCS string sequence (``ESC P ... ST``).

        A sixel image arrives here. It is decoded and stored in the
        graphics state, next to the images of the kitty graphics
        protocol, so that one renderer draws both.

        A DECRQSS request ("DCS $ q <name> ST") also arrives here, and
        is answered. Every other DCS sequence is consumed without
        corrupting the screen content.
        """
        if data.startswith("$q"):
            self.report_setting(data[2:])
            return

        if data.startswith("+q"):
            self.report_capabilities(data[2:])
            return

        image = decode_sixel(data)
        if image is None:
            return
        width, height, pixels = image
        self.graphics.add_sixel(width, height, pixels, self)

    def charset_default(self, *a, **kw):
        "Not implemented."

    def charset_utf8(self, *a, **kw):
        "Not implemented."

    def debug(self, *args, **kwargs):
        pass

    # ------------------------------------------------------------------
    # Laying the buffer out again at a new width.
    #
    # It lays out the screen and the lines that reach it, and leaves the
    # history where it is. A reader of the history reads lines and not
    # rows, so the width those rows were laid out at never reaches it.
    # Lillecarl/pymux#135.

    def _first_row_to_lay_out(self, last: int) -> int:
        """
        The first row a reflow has to lay out again.

        It walks up from `last` and stops at the first row of a line,
        once three things are true: it holds a line for every row of
        the screen, it has reached the top of the screen, and it has
        reached the cursor.

        **A line for every row is enough at any width.** A line takes
        at least one row however wide the screen becomes, so `lines` of
        them always fill it. Widening takes rows away from a line and
        never takes the line away.

        The other two say what a reflow may not leave behind. A row of
        the screen that keeps its old layout is a row a person sees at
        the wrong width, and the cursor has to travel with the
        character it stands on.

        It stops at the lowest row the buffer holds at the latest.
        **Not at `history_floor`**, which only says that nothing lives
        under it: the buffer can start above the floor, and a reflow
        that laid out from under the lowest row would write the rows
        out one number too low and move the whole buffer down.
        """
        data_buffer = self.page.data_buffer
        floor = min(data_buffer)
        wanted = min(self.line_offset, self.pt_cursor_position.y)
        lines = self.lines

        collected = 0
        for number in range(last, floor - 1, -1):
            row = data_buffer.get(number)

            # A row a wrap made is the middle of a line, and a line is
            # taken whole. A row the buffer does not hold is a blank
            # line, and a blank line starts one.
            if row is not None and row.wrapped:
                continue

            collected += 1
            if collected >= lines and number <= wanted:
                return number

        return floor

    def _reflow(self) -> None:
        """
        Reflow the screen using the given width.
        """
        width = self.columns

        data_buffer = self.page.data_buffer
        cursor_position = self.pt_cursor_position
        cy, cx = (cursor_position.y, cursor_position.x)

        # A screen that nobody has written on has nothing to lay out.
        if not data_buffer:
            return

        # The character the cursor stands on, for the check at the end.
        #
        # **The read goes through `.get`**: the buffer and the rows in
        # it are defaultdicts, so asking makes a cell, and asking about
        # a cursor parked past the end of a line gave that line a run
        # of blanks nobody wrote. Lillecarl/pymux#143.
        #
        # **Only a character a program wrote counts.** The trim below
        # takes the blanks an erase left off the end of a line, so a
        # cursor standing on one has nothing to keep: it ends up past
        # the end of the line, which is where it was.
        row = data_buffer.get(cursor_position.y)
        cell = None if row is None else row.get(cursor_position.x)
        cursor_character = (
            cell.char if isinstance(cell, WrittenCell) else None
        )

        # Unwrap the rows that have to be laid out again into the lines
        # a program wrote. That is the screen and the lines that reach
        # it, and never the whole history: the cost of a reflow is the
        # size of the screen and not the depth of the scrollback.
        last = max(data_buffer)

        # The cursor stands inside the range whether it stands on a
        # character or not. A cursor on a row nobody wrote is a cursor
        # the unwrapping never sees, and it would keep the numbers it
        # had while every row around it took new ones.
        if cursor_position.y > last:
            last = cursor_position.y

        offset = self._first_row_to_lay_out(last)
        all_lines, found = self.page.unwrap(offset, last, cursor=(cy, cx))
        if found is not None:
            cy, cx = found

        # Take the blanks off the end of each line, so that a line that
        # was never filled does not carry its width around. Not a blank
        # a background was painted on.
        #
        # A blank that a program wrote is content, and it stays. The
        # test is the class and not the character: a space out of
        # `draw` is a `WrittenCell`, and the blank that an erase leaves
        # is not. Reading the character instead lost the space after a
        # shell prompt on every resize. Lillecarl/pymux#56.
        #
        # Also make sure that lines consist of at lesat one character,
        # otherwise we can't calculate `max_y` correctly. (This is important
        # for the `clear` command.)
        #
        # The cursor needs nothing held back here. It travels as an
        # offset from the start of its line, and an offset past the
        # end of one is where it stands on a full row or on a row a
        # program moved onto and did not write. Lillecarl/pymux#143.
        for line in all_lines:
            cells = line.cells
            while (
                len(cells) > 1
                and not isinstance(cells[-1], WrittenCell)
                and cells[-1].appearance == PLAIN_APPEARANCE
            ):
                cells.pop()

        # The rows the lines came from go, and the lines take their
        # place. They go first: a wider screen needs fewer rows for the
        # same lines, and a row of the old layout left under the new
        # ones would come back as soon as `max_y` grew again.
        for number in range(offset, last + 1):
            data_buffer.pop(number, None)

        # Wrap lines again according to the screen width.
        new_row_index = offset
        new_column_index = 0

        #: The highest row this writes on. It is `max_y` at the end,
        #: and it is counted here because reading it back is
        #: `max(data_buffer)`, which walks the history that this method
        #: exists to leave alone.
        highest = offset - 1

        # Where the cursor lands, kept apart from where it stood.
        #
        # The loop wrote the answer back into `cy` and `cx`, so the
        # line and the offset the cursor came from and the row and the
        # column it went to were the same two numbers. A later line
        # then matched the answer and moved the cursor again. Four
        # characters, one "CSI T" and a narrowing was enough: the
        # cursor landed a row low, on the "t" of "text" instead of on
        # the blank it stood on, and the check at the end of this
        # method raised. Lillecarl/pymux#110.
        new_cursor_position = None

        for line_index, line in enumerate(all_lines):
            first_new_row = new_row_index
            for column_index, char in enumerate(line.cells):
                # Check for space on the current line.
                if new_column_index + char.width > width:
                    new_row_index += 1
                    new_column_index = 0
                    data_buffer[new_row_index].wrapped = True

                if cy == line_index and cx == column_index:
                    new_cursor_position = (new_row_index, new_column_index)

                # Add character to new buffer.
                data_buffer[new_row_index][new_column_index] = char
                new_column_index += char.width
                highest = new_row_index

            # A cursor that stands past the end of its line lands the
            # same distance past the last cell of it, wrapping the way
            # a character would. No cell in the loop above matched it,
            # because there is no cell there. Lillecarl/pymux#143.
            if cy == line_index and cx >= len(line.cells):
                cursor_row = new_row_index
                cursor_column = new_column_index + cx - len(line.cells)
                while cursor_column >= width:
                    cursor_column -= width
                    cursor_row += 1
                new_cursor_position = (cursor_row, cursor_column)

            # A DEC line attribute belongs to the whole line, so every
            # row the line now takes carries it.
            if line.attribute is not None:
                for new_row in range(first_new_row, new_row_index + 1):
                    data_buffer[new_row].attribute = line.attribute
                if new_row_index > highest:
                    highest = new_row_index

            new_row_index += 1
            new_column_index = 0

        if new_cursor_position is not None:
            cy, cx = new_cursor_position

        # A reflow puts the characters of the rows it read somewhere
        # else, so the rows a reader holds and the rows that take their
        # numbers are both new. It says so about every row rather than
        # about the ones it moved, because saying so costs one number
        # either way and a reader that draws again is never wrong.
        self.touch_everything()

        #: The lowest row that is laid out at the width the screen has
        #: now. Everything under it kept the width it was written at,
        #: which no reader of the history minds. `unscroll` is the one
        #: thing that brings such a row back onto the screen.
        self.reflow_floor = offset

        cursor_position.y, cursor_position.x = cy, cx
        self.pt_cursor_position = cursor_position

        # If everything goes well, the cursor should still be on the same
        # character. A cursor that stood on no character has none to keep,
        # and `.get` asks without making one.
        row = data_buffer.get(cursor_position.y)
        cell = None if row is None else row.get(cursor_position.x)
        if cursor_character is not None and cursor_character != (
            None if cell is None else cell.char
        ):
            # FIXME:
            raise Exception(
                "Reflow failed: {!r} {!r}".format(cursor_character, cell)
            )

        # The cursor is on the screen, so the screen reaches it. It can
        # stand past the last cell of the last line and so on a row
        # that holds none, which no longer exists now that a reflow
        # does not make one for it. Lillecarl/pymux#143.
        self.max_y = max(highest, cursor_position.y)

        self.max_y = min(self.max_y, cursor_position.y + self.lines - 1)
