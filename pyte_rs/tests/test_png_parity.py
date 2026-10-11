"""
`pyte_rs.unfilter` and `pyte_rs.rgba_of` give the bytes `pyte.png` gives.

Both take random scanlines: every filter, an unknown one and data cut
short for the first; every valid depth and colour type, with palettes and
transparency keys that match and that do not, for the second. They have
to agree on the bytes, and on the error and its message.
Lillecarl/pymux#574.
"""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyte_rs
from pyte import png

#: The references, taken before any test could have installed a kernel.
PURE_UNFILTER = png._unfilter
PURE_RGBA_OF = png._rgba_of

#: The depths each colour type takes.
DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def outcome(call, *arguments):
    try:
        return "ok", bytes(call(*arguments))
    except ValueError as error:
        return "ValueError", str(error)


@st.composite
def filtered(draw):
    height = draw(st.integers(1, 6))
    stride = draw(st.integers(1, 24))
    bytes_per_pixel = draw(st.integers(1, 8))
    rows = b"".join(
        bytes([draw(st.sampled_from([0, 1, 2, 3, 4, 4, 4, 9]))]) + draw(st.binary(min_size=stride, max_size=stride))
        for _ in range(height)
    )
    cut = draw(st.integers(0, 3))
    return rows[: len(rows) - cut] if cut else rows, height, stride, bytes_per_pixel


@given(filtered())
@settings(max_examples=2000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_unfilter_gives_the_same_samples(case):
    raw, height, stride, bytes_per_pixel = case
    assert outcome(PURE_UNFILTER, raw, height, stride, bytes_per_pixel) == outcome(
        pyte_rs.unfilter, raw, height, stride, bytes_per_pixel
    )


@st.composite
def scanlines(draw):
    colour_type = draw(st.sampled_from(sorted(DEPTHS)))
    depth = draw(st.sampled_from(DEPTHS[colour_type]))
    width = draw(st.integers(1, 9))
    height = draw(st.integers(1, 4))
    stride = (width * depth * CHANNELS[colour_type] + 7) // 8
    samples = draw(st.binary(min_size=stride * height, max_size=stride * height))
    palette = draw(st.lists(st.tuples(*[st.integers(0, 255)] * 3), max_size=20))
    # Short keys, keys that match a sample, and keys that cannot.
    transparency = draw(
        st.one_of(
            st.just(b""),
            st.binary(max_size=24),
            st.binary(min_size=1, max_size=1).map(lambda key: (b"\x00" + key) * 3),
        )
    )
    return samples, width, height, stride, depth, colour_type, palette, transparency


@given(scanlines())
@settings(max_examples=3000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rgba_of_gives_the_same_pixels(case):
    assert outcome(PURE_RGBA_OF, *case) == outcome(pyte_rs.rgba_of, *case)


def test_a_bytearray_reads_like_bytes():
    "`_unfilter` hands `_rgba_of` a bytearray in the Python path."
    case = (bytearray(b"\x10\x20\x30\x40"), 1, 1, 4, 8, 6, [], b"")
    assert outcome(PURE_RGBA_OF, *case) == outcome(pyte_rs.rgba_of, *case)
