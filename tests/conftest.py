"""
What every run of this suite shares: the group a file belongs to, and
the examples a property test draws.

# The groups

The suite is one thing to a reader and two things to a build. Nearly
every file here needs nothing but python. One needs an X server and the
real Xlib, because `pyte/xcms.py` is a port of the colour management of
Xlib and only a comparison against the original says whether the port
is right.

Run as one derivation, a change to any test pays for all of it. So
`nix/checks.nix` runs two, and `PYTE_GROUP` says which one this is:

    unit    nothing but python, and ncurses for the terminfo entry
    xcms    Xvfb and libX11, for the colour specs

**A file is not listed anywhere.** A list would be forgotten the first
time somebody adds a test. The group comes from what the file imports:
a module that reads an oracle needs that oracle. So a new test lands in
the right group by writing the import it needs, and in `unit` when it
needs nothing.

**The decision is made on the text, not on the import.** pytest imports
every module it collects, before any mark can deselect it. In the unit
run there is no libX11 and no display, so importing `xlib_oracle` would
fail. `pytest_ignore_collect` runs before the import and reads the
source.

`ptterm/tests/conftest.py` is the same file with a third group, for the
suites that judge what a widget draws.

# The profiles

A property test with no seed is a different test every run. This one
was: `test_a_size_change_keeps_every_line` failed about one run in
eight, and a gate that is red by luck teaches everybody to run it
again instead of to look. So there are two profiles and the gate takes
the pinned one. Lillecarl/pymux#180.
"""

import os
import re
from pathlib import Path

from hypothesis import HealthCheck, settings

#: The module that reads a colour with the real Xlib.
XCMS_ORACLES = ("xlib_oracle",)

#: Which group this run is. Empty means every group, which is what a
#: run outside the build does.
GROUP = os.environ.get("PYTE_GROUP", "")

GROUPS = ("unit", "xcms")


# ----------------------------------------------------------------------
# The examples a property test draws.

# The gate. `derandomize` seeds each property test from its own source,
# so a run draws the examples the run before it drew, and a green gate
# means the same thing twice.
#
# This is hypothesis's own `ci` profile, which it loads by itself when
# it recognises the runner. A nix sandbox is not one it recognises, so
# the profile is named and loaded here.
settings.register_profile(
    "pinned",
    derandomize=True,
    print_blob=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# The hunt. Fresh examples, which is what finds the case nobody has
# written down. `checks.pyte-roaming` runs it and is not a gate.
#
# `database=None` on purpose. A sandbox throws its `.hypothesis`
# directory away, so a database there only pretends to remember. What
# this suite remembers is the `@example` decorators on the property
# tests, and those run under both profiles.
settings.register_profile(
    "roaming",
    derandomize=False,
    database=None,
    print_blob=True,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# **Here, and not in a fixture.** A `@settings(...)` decorator reads
# the profile that is loaded when the decorator runs, which is when
# pytest imports the test module. pytest imports a conftest before
# that, and calls a fixture long after it.
#
# `--hypothesis-profile=roaming` picks the other one. pytest loads it
# in `pytest_configure`, which is after this line and still before any
# test module.
settings.load_profile("pinned")


def _imports(source: str, names) -> bool:
    "True when the source imports any of these modules by name."
    for name in names:
        if re.search(r"^\s*(?:from|import)\s+%s\b" % re.escape(name), source, re.M):
            return True
    return False


def group_of(path: Path) -> str:
    "The group that this test file belongs to."
    source = path.read_text(errors="replace")
    if _imports(source, XCMS_ORACLES):
        return "xcms"
    return "unit"


def pytest_ignore_collect(collection_path, config):
    """
    Leave out the files that belong to another group.

    Returning `None` says nothing, which is what a run with no group
    set does: it collects everything, the way it always did.
    """
    if not GROUP:
        return None
    if GROUP not in GROUPS:
        raise ValueError(
            "PYTE_GROUP is %r, and the groups are %s" % (GROUP, ", ".join(GROUPS))
        )
    if collection_path.suffix != ".py":
        return None
    if not collection_path.name.startswith("test_"):
        return None
    return group_of(collection_path) != GROUP
