"""
Every write to a row says so, and a reader can believe it.

A front end draws every visible row of every frame, because nothing
says which rows moved. `written_at` says it: the screen counts the
writes it makes, and each row remembers the count at which it last
changed. A reader keeps the count it last drew, per row, and redraws a
row only when the two differ.

**The state lives on the reader, and not on the screen.** A set of
dirty rows on the screen needs somebody to empty it, and two front
ends draw one screen while pymux gives several clients one pane. A
screen that tracked its readers would have to register them, which a
pure layer cannot do. A count that only goes up needs no emptying:
each reader answers for itself, and a reader that attaches late
remembers nothing, so it draws everything once. Lillecarl/pymux#126.

**A missed write is not a slow screen, it is a wrong one.** A row that
changed and did not say so stays on the screen as it was, in whatever
program nobody tested. So this file does not check the writes one at a
time. It runs a reader that believes `written_at` beside one that
believes nothing, over long stretches of generated output, and says
they agree. A write path that forgets to count fails here.

The recordings of real programs live in `ptterm`, which is where the
widget that draws them is. This package has no recordings, so it
generates its own: the erase, the scroll and the rectangle families
are where whole ranges of rows move at once, and those are the paths a
recording is least likely to reach.
"""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from a_screen import a_screen
from pyte.streams import Stream
from pyte import escape
from pyte.modes import PrivateMode
from pyte.sequences import Csi, csi, reset_mode, set_mode
from pyte.sequences import Escape, Sharp, esc, sharp


def cells_of(screen, row_number: int):
    """
    One row, as a reader would draw it.

    The appearance is in the answer and not only the character. A
    program that paints a row a different colour has changed the row,
    and a reader that watched the characters alone would keep the old
    colour on the screen.
    """
    row = screen.page.data_buffer.get(row_number)
    if not row:
        return ()
    return tuple(
        (row[column].char, row[column].appearance)
        for column in range(max(row) + 1)
    )


class Believing:
    """
    A reader that trusts `written_at`, the way a front end would.

    It keeps what it drew for each row, and the count it drew it at. A
    row whose count has not moved is a row it does not read again.
    """

    def __init__(self, screen) -> None:
        self.screen = screen
        self.drawn = {}
        self.at = {}

    def read(self, rows) -> dict:
        for row_number in rows:
            version = self.screen.written_at.get(
                row_number, self.screen.everything_at
            )
            if self.at.get(row_number) != version:
                self.drawn[row_number] = cells_of(self.screen, row_number)
                self.at[row_number] = version
        return {number: self.drawn.get(number, ()) for number in rows}


def everything(screen, reader) -> range:
    """
    Every row either side has an opinion about.

    A row that a write took away is in here too: the reader has to
    learn that it went, and a range that stopped at the buffer would
    never ask.

    **A row that left the history is not in here.** It is under
    `history_floor` and no front end draws it: a pane draws the rows of
    the screen, and copy mode draws from the lowest row of the buffer.
    Asking about one would judge the screen on a promise nobody needs.
    """
    buffer = screen.page.data_buffer
    numbers = set(buffer) | set(reader.drawn)
    numbers = {number for number in numbers if number >= screen.history_floor}
    if not numbers:
        return range(0)
    return range(min(numbers), max(numbers) + 1)


def check(
    chunks, lines: int = 24, columns: int = 80, history=None
) -> None:
    """
    Feed the chunks one at a time, and after each one say that the
    believing reader holds what the screen really holds.
    """
    screen = a_screen(columns=columns, lines=lines, history=history)
    stream = Stream(screen)
    stream.attach(screen)
    reader = Believing(screen)

    # The frame before anything arrives. A reader that starts here is
    # the one a front end really is.
    reader.read(everything(screen, reader))

    for number, chunk in enumerate(chunks):
        stream.feed(chunk)
        if history is not None:
            # A screen prunes once per hundred linefeeds, which a run of
            # forty chunks never reaches. This is the prune, put where a
            # reader is watching.
            screen._remove_old_lines_from_history()
        rows = everything(screen, reader)
        believed = reader.read(rows)
        truth = {row: cells_of(screen, row) for row in rows}
        wrong = sorted(row for row in rows if believed[row] != truth[row])
        assert not wrong, (
            "after chunk %d (%r), these rows changed and did not say so: %s"
            % (number, chunk[:60], wrong)
        )


# ----------------------------------------------------------------------
# Sequences that nobody recorded.


#: The sequences that move rows about, with the numbers left open so
#: that hypothesis can fill them in.
MOVERS = [
    "\x1b[%d;%dH",      # CUP: put the cursor somewhere.
    "\x1b[%d;%dr",      # DECSTBM: a scrolling region.
    "\x1b[%dL",         # IL: insert lines.
    "\x1b[%dM",         # DL: delete lines.
    "\x1b[%dS",         # SU: scroll up.
    "\x1b[%dT",         # SD: scroll down.
    "\x1b[%d@",         # ICH: insert characters.
    "\x1b[%dP",         # DCH: delete characters.
    "\x1b[%dX",         # ECH: erase characters.
    "\x1b[%dJ",         # ED: erase in display.
    "\x1b[%dK",         # EL: erase in line.
    "\x1b[%d;%d;%d;%d$z",   # DECERA: erase a rectangle.
    "\x1b[%d;%d;%d;%d${",   # DECSERA: erase what no mark holds.
    "\x1b[%d;%d;%d;%d;%d$x",  # DECFRA: fill a rectangle.
    "\x1b[%d;%d;%d;%d;%d;%d;%d;%d$v",  # DECCRA: copy a rectangle.
    "\x1b[%d D",        # unscroll: bring lines back from the history.
    "\x1b[%d'}",        # DECIC: insert columns.
    "\x1b[%d'~",        # DECDC: delete columns.
    "\x1b[8;%d;%dt",    # XTWINOPS: resize, which reflows the buffer.
]

#: The sequences that take no number at all.
PLAIN = [
    "\n", "\r", "\x1bD", "\x1bM", "\x1bE", "\x1b7", "\x1b8",
    sharp(Sharp.DECALN),           # DECALN: fill the screen with E.
    esc(escape.RIS),            # RIS: a full reset.
    csi(Csi.DECSTR),          # DECSTR: a soft reset.
    "\x1b[?1049h", "\x1b[?1049l",   # The other page, and back.
    "\x1b[?69h", "\x1b[?69l",       # Left and right margins.
    set_mode(PrivateMode.ORIGIN), reset_mode(PrivateMode.ORIGIN),         # Origin mode.
    "\x1b[?7h", "\x1b[?7l",         # Autowrap.
    "\x1b[?3h", "\x1b[?3l",         # DECCOLM: 132 columns, and back.
    csi(escape.SGR, 0), csi(escape.SGR, 7), csi(escape.SGR, 31, 44),
    csi(Csi.DECSCA, 1), csi(Csi.DECSCA, 0),         # DECSCA: mark what an erase leaves.
    esc(Escape.SPA), esc(Escape.EPA),               # SPA and EPA, the other mark.
    "text", "wider text that wraps around the end of a short row",
]


def a_mover(draw) -> str:
    "One sequence that moves rows, with small numbers in it."
    shape = draw(st.sampled_from(MOVERS))
    count = shape.count("%d")
    numbers = draw(st.lists(st.integers(0, 12), min_size=count, max_size=count))
    return shape % tuple(numbers)


@st.composite
def a_chunk(draw) -> str:
    if draw(st.booleans()):
        return draw(st.sampled_from(PLAIN))
    return a_mover(draw)


@given(st.lists(a_chunk(), min_size=1, max_size=40))
@settings(
    # A gate runs on every build, so the number is what a gate can
    # afford. A hunt runs more:
    #
    #     PYTE_TESTS=tests/test_row_versions.py nix build ...
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_sequence_nobody_recorded(chunks):
    # A small screen, so that a scroll and a rectangle reach the edges
    # rather than land in the middle of a wide empty page.
    check(chunks, lines=6, columns=10)


@given(st.lists(a_chunk(), min_size=1, max_size=40))
@settings(
    max_examples=500,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_a_sequence_that_scrolls_out_of_the_history(chunks):
    """
    The same hunt, on a pane that keeps almost no scrollback.

    The default keeps two thousand rows, which a run of forty chunks
    never fills, so nothing above leaves the history and `_forget` is
    never reached with a reader watching. Five rows means a row leaves
    on nearly every chunk.
    """
    check(chunks, lines=6, columns=10, history=5)


# ----------------------------------------------------------------------
# The rule itself.


def test_a_row_that_nothing_wrote_keeps_its_count():
    screen = a_screen(columns=10, lines=4)
    stream = Stream(screen)
    stream.attach(screen)

    stream.feed("first\r\nsecond")
    before = dict(screen.written_at)

    stream.feed("\x1b[1;1Hagain")
    # Row 1 was not touched, so a reader leaves it alone.
    assert screen.written_at.get(1) == before.get(1)
    # Row 0 was, so a reader draws it again.
    assert screen.written_at[0] != before.get(0)


def test_the_count_only_goes_up():
    "It is never emptied, because nobody owns the emptying."
    screen = a_screen(columns=10, lines=4)
    stream = Stream(screen)
    stream.attach(screen)

    seen = []
    for _ in range(5):
        stream.feed("\x1b[1;1Hx")
        seen.append(screen.written_at[0])
    assert seen == sorted(set(seen))


def test_a_resize_says_that_every_row_changed():
    """
    A reflow puts every character somewhere else, so no reader may keep
    what it drew. The buffer is replaced rather than written into, and
    that is the one shape a write count cannot see by itself.
    """
    screen = a_screen(columns=10, lines=4)
    stream = Stream(screen)
    stream.attach(screen)
    stream.feed("a line that is longer than ten columns\r\nand another")

    reader = Believing(screen)
    reader.read(everything(screen, reader))

    screen.resize(lines=4, columns=20)

    rows = everything(screen, reader)
    believed = reader.read(rows)
    truth = {row: cells_of(screen, row) for row in rows}
    assert believed == truth


def test_the_other_page_says_that_every_row_changed():
    "And so does coming back from it."
    screen = a_screen(columns=10, lines=4)
    stream = Stream(screen)
    stream.attach(screen)
    stream.feed("the first screen")

    reader = Believing(screen)
    reader.read(everything(screen, reader))

    for chunk in ("\x1b[?1049h", "the other one", "\x1b[?1049l"):
        stream.feed(chunk)
        rows = everything(screen, reader)
        believed = reader.read(rows)
        truth = {row: cells_of(screen, row) for row in rows}
        assert believed == truth, chunk


def test_a_reader_that_attaches_late_draws_everything_once():
    """
    It remembers nothing, so every row looks new to it. That is what it
    wanted: it has drawn nothing yet.
    """
    screen = a_screen(columns=10, lines=4)
    stream = Stream(screen)
    stream.attach(screen)
    stream.feed("one\r\ntwo\r\nthree")

    reader = Believing(screen)
    rows = everything(screen, reader)
    believed = reader.read(rows)
    assert believed == {row: cells_of(screen, row) for row in rows}
