"""
A screen holds cells, and something else knows how big one is.

A screen cannot measure a pixel. What draws it can: a terminal
emulator knows its font, and a client of a pane asks its outer
terminal with "CSI 16 t". `Screen.set_cell_size` is how that number
reaches the screen, and three things read it back:

* what "CSI 6/4/5/48 t" report to the program;
* how "CSI 4 ; Ph ; Pw t" turns an ask in pixels into cells;
* how many cells an image covers.

Until somebody says otherwise it is `ASSUMED_CELL_WIDTH` by
`ASSUMED_CELL_HEIGHT`, because a screen nobody draws still has to
answer those queries. Lillecarl/pymux#369.
"""

from pyte.images import ASSUMED_CELL_HEIGHT, ASSUMED_CELL_WIDTH
from pyte.screen import Screen
from pyte.sequences import Csi, csi
from pyte.streams import Stream

#: A cell that is not the assumed one, and is a real one: kitty and
#: foot draw DejaVu Sans Mono at size 12 in ten by nineteen.
REAL_CELL = (10, 19)


def _screen(lines=24, columns=80):
    replies = []
    asks = []
    screen = Screen(
        lines,
        columns,
        write_process_input=replies.append,
        resize_func=lambda rows, cols: asks.append((rows, cols)),
    )
    return screen, Stream(screen), replies, asks


def test_a_screen_nobody_measured_assumes_a_cell():
    screen, _stream, _replies, _asks = _screen()
    assert (screen.cell_width, screen.cell_height) == (
        ASSUMED_CELL_WIDTH,
        ASSUMED_CELL_HEIGHT,
    )


def test_the_cell_size_reaches_the_report():
    screen, stream, replies, _asks = _screen()
    screen.set_cell_size(*REAL_CELL)
    stream.feed(csi(Csi.XTWINOPS, 16))
    assert replies == ["\x1b[6;19;10t"]


def test_the_text_area_is_reported_in_the_cell_it_was_told():
    screen, stream, replies, _asks = _screen(lines=24, columns=80)
    screen.set_cell_size(*REAL_CELL)
    stream.feed(csi(Csi.XTWINOPS, 14))
    assert replies == ["\x1b[4;%i;%it" % (24 * 19, 80 * 10)]


def test_an_ask_in_pixels_divides_by_the_cell_it_reports():
    """
    The one place the two have to agree.

    A program asks "CSI 16 t", multiplies by the rows it wants and
    asks for that many pixels. It has to get those rows back.
    """
    screen, stream, _replies, asks = _screen()
    screen.set_cell_size(*REAL_CELL)
    stream.feed(csi(Csi.XTWINOPS, 4, 30 * 19, 100 * 10))
    assert asks == [(30, 100)]


def test_an_image_covers_the_cells_of_the_size_it_was_told():
    """
    114 pixels is six rows of a nineteen pixel cell exactly, and seven
    of the twenty pixel cell that was assumed. The count is what makes
    the difference between drawing the image and resampling it.
    """
    screen, _stream, _replies, _asks = _screen()
    screen.set_cell_size(*REAL_CELL)
    screen.graphics.add_sixel(120, 114, b"\x00" * (120 * 114 * 4), screen)
    (placement,) = screen.graphics.placements
    assert (placement.columns, placement.rows) == (12, 6)


def test_the_assumed_cell_reserves_a_row_more_for_the_same_image():
    screen, _stream, _replies, _asks = _screen()
    screen.graphics.add_sixel(120, 114, b"\x00" * (120 * 114 * 4), screen)
    (placement,) = screen.graphics.placements
    assert (placement.columns, placement.rows) == (12, 6)
    # Six rows of twenty is 120 pixels for a 114 pixel image: the same
    # count, and a box that does not fit it.
    assert placement.rows * screen.cell_height == 120


def test_a_new_cell_size_counts_the_cells_again():
    """
    A placement holds a count worked out against the cell of the moment
    it was made, and that count is only as good as the cell. 120 pixels
    is six rows of a twenty pixel cell and seven of a nineteen pixel
    one, so the two disagree and the recount has to show.
    """
    screen, _stream, _replies, _asks = _screen()
    screen.graphics.add_sixel(120, 120, b"\x00" * (120 * 120 * 4), screen)
    (placement,) = screen.graphics.placements
    assert placement.rows == 6  # ceil(120 / 20)

    screen.set_cell_size(*REAL_CELL)
    (placement,) = screen.graphics.placements
    assert placement.rows == 7  # ceil(120 / 19)


def test_the_picture_survives_the_first_report():
    """
    **The reason this counts again rather than dropping.** A pane
    starts at the assumed cell and its client answers "CSI 16 t" a
    moment later. A program that drew in between must not lose its
    picture.
    """
    screen, _stream, _replies, _asks = _screen()
    image_id = screen.graphics.add_sixel(120, 114, b"\x00" * (120 * 114 * 4), screen)

    screen.set_cell_size(*REAL_CELL)
    assert image_id in screen.graphics.images_by_id
    (placement,) = screen.graphics.placements
    assert placement.image_id == image_id


def test_a_box_the_program_asked_for_is_left_alone():
    "It asked for cells, and cells do not change when a pixel does."
    screen, stream, _replies, _asks = _screen()
    stream.feed("\x1b_Ga=T,f=24,s=2,v=2,c=6,r=3,q=2;%s\x1b\\" % ("A" * 16,))

    screen.set_cell_size(*REAL_CELL)
    (placement,) = screen.graphics.placements
    assert (placement.columns, placement.rows) == (6, 3)


def test_the_same_cell_size_again_changes_nothing():
    screen, _stream, _replies, _asks = _screen()
    screen.set_cell_size(*REAL_CELL)
    screen.graphics.add_sixel(120, 114, b"\x00" * (120 * 114 * 4), screen)
    screen.set_cell_size(*REAL_CELL)
    assert len(screen.graphics.placements) == 1


def test_a_sixel_names_no_box():
    """
    Which matters because a box the program named is a request and a
    box the terminal worked out is only the room the image needs. The
    thing that draws the pane reads this to decide whether it may draw
    the image at its own size.
    """
    screen, _stream, _replies, _asks = _screen()
    screen.graphics.add_sixel(120, 114, b"\x00" * (120 * 114 * 4), screen)
    (placement,) = screen.graphics.placements
    assert placement.asked_for_the_box is False


def test_a_kitty_placement_with_no_size_names_no_box():
    screen, stream, _replies, _asks = _screen()
    stream.feed("\x1b_Ga=T,f=24,s=2,v=2,q=2;%s\x1b\\" % ("A" * 16,))
    (placement,) = screen.graphics.placements
    assert placement.asked_for_the_box is False


def test_a_kitty_placement_that_names_a_size_asked_for_it():
    screen, stream, _replies, _asks = _screen()
    stream.feed("\x1b_Ga=T,f=24,s=2,v=2,c=6,r=3,q=2;%s\x1b\\" % ("A" * 16,))
    (placement,) = screen.graphics.placements
    assert placement.asked_for_the_box is True
    assert (placement.columns, placement.rows) == (6, 3)


def test_naming_one_of_the_two_counts_as_asking():
    "The other is worked out, and the one that was named still rules."
    screen, stream, _replies, _asks = _screen()
    stream.feed("\x1b_Ga=T,f=24,s=2,v=2,c=6,q=2;%s\x1b\\" % ("A" * 16,))
    (placement,) = screen.graphics.placements
    assert placement.asked_for_the_box is True
    assert placement.columns == 6


def test_a_cell_with_no_pixels_in_it_is_refused():
    "A terminal that answers zero has told us nothing."
    screen, _stream, _replies, _asks = _screen()
    screen.set_cell_size(0, 19)
    screen.set_cell_size(10, 0)
    assert (screen.cell_width, screen.cell_height) == (
        ASSUMED_CELL_WIDTH,
        ASSUMED_CELL_HEIGHT,
    )
