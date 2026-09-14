"""
The national sets, against the source they were copied from.

A hundred and thirty odd positions typed by hand is where an error
hides, and an error here draws the wrong letter in somebody's language
and says nothing. `xterm_tables.py` says why xterm's `charsets.h` is
the list and why there is no other. Lillecarl/pymux#111.
"""

import pytest

import xterm_tables
from pyte import charsets as cs

pytestmark = pytest.mark.skipif(
    not xterm_tables.xterm_is_available(),
    reason="the xterm source is not there",
)


@pytest.mark.parametrize("name, macro", sorted(xterm_tables.MACROS.items()))
def test_a_table_is_what_xterm_has(name, macro):
    ours = cs.TECHNICAL if name == ">" else cs.NATIONAL[name]
    assert ours == xterm_tables.table_of(macro)


def test_the_british_set_is_the_pound_sign_alone():
    """
    British has no macro. `xtermCharSetIn` special-cases it, because
    one position is not worth a table: `if (code == XK_sterling) code
    = 0x23`, read the other way round.
    """
    assert cs.NATIONAL["A"] == {0x23: 0x00A3}


def test_every_set_that_pyte_names_was_checked():
    "A set added without a line in `MACROS` would be judged by nothing."
    named = set(cs.NATIONAL) | {">"}
    assert named - set(xterm_tables.MACROS) == {"A"}
