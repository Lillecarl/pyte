"""
`GraphicsState.add_png`: an image the embedder decoded and sized, placed
at the cursor. pymux puts iTerm2's inline images here. Lillecarl/pymux#789.
"""

from __future__ import annotations

from pyte.images import PNG_SIGNATURE, PixelFormat
from pyte.screen import Screen

#: Enough of a PNG for its size to read: the signature and an IHDR of 40 by 20.
PNG = (
    PNG_SIGNATURE
    + b"\x00\x00\x00\x0dIHDR"
    + (40).to_bytes(4, "big")
    + (20).to_bytes(4, "big")
    + b"\x08\x02\x00\x00\x00"
)


def test_the_image_takes_its_box_and_the_cursor_ends_beside_it():
    screen = Screen(24, 80, write_process_input=lambda data: None)
    screen.cursor_position(3, 5)
    image_id = screen.graphics.add_png(PNG, 6, 2, screen)

    (placement,) = screen.graphics.placements
    assert (placement.x, placement.y, placement.columns, placement.rows) == (4, 2, 6, 2)
    assert placement.asked_for_the_box
    image = screen.graphics.images_by_id[image_id]
    assert (image.format, image.width, image.height) == (PixelFormat.PNG, 40, 20)
    cursor = screen.pt_cursor_position
    assert (cursor.x, cursor.y) == (10, 3)


def test_an_image_that_keeps_the_cursor_leaves_it():
    screen = Screen(24, 80, write_process_input=lambda data: None)
    screen.graphics.add_png(PNG, 6, 2, screen, move_cursor=False)
    cursor = screen.pt_cursor_position
    assert (cursor.x, cursor.y) == (0, 0)
