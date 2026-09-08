"""
What a program run on this screen sees in its environment.

A program that reads the name of the outer terminal picks a protocol
that this screen may not speak, so it does not inherit that name. What
it is told instead has to be true: **naming an entry that is not
installed is worse than naming xterm**, so nothing is claimed until the
compiled entry is found.
"""

import pytest

from pyte.environment import (
    DEFAULT_DATABASE,
    FALLBACK_NAME,
    TERMINAL_IDENTITY_VARIABLES,
    database,
    prepare,
    scrub_terminal_identity,
    terminal_name,
)
from pyte.terminfo import TERMINAL_NAME


@pytest.fixture
def compiled(tmp_path):
    "A database that holds the entry, the way `tic` writes one."
    directory = tmp_path / TERMINAL_NAME[0]
    directory.mkdir()
    (directory / TERMINAL_NAME).write_bytes(b"not really an entry")
    return str(tmp_path)


@pytest.fixture
def empty(tmp_path):
    "A directory with no entry in it."
    return str(tmp_path)


# ----------------------------------------------------------------------
# Finding the entry.


def test_a_database_that_is_not_there(tmp_path):
    assert database(str(tmp_path / "nowhere")) is None


def test_a_database_that_holds_no_entry(empty):
    "A directory is not enough: the entry itself has to be in it."
    assert database(empty) is None


def test_the_entry_is_found(compiled):
    assert database(compiled) == compiled


def test_the_entry_under_a_hashed_directory(tmp_path):
    "ncurses stores it under the hexadecimal of the first letter too."
    directory = tmp_path / ("%02x" % ord(TERMINAL_NAME[0]))
    directory.mkdir()
    (directory / TERMINAL_NAME).write_bytes(b"not really an entry")
    assert database(str(tmp_path)) == str(tmp_path)


def test_the_entry_of_the_package_is_the_one_that_is_used():
    """
    The build compiles it in, so a program finds it with nothing to
    configure. Lillecarl/pymux#125.

    This fails when the tests run against a source tree rather than
    against what a build made, which is what the suites do.
    """
    assert database() == DEFAULT_DATABASE


# ----------------------------------------------------------------------
# What a program is told.


def test_a_program_is_told_the_name_of_this_screen(compiled):
    environment = {}
    prepare(environment, compiled)
    assert environment["TERM"] == TERMINAL_NAME
    assert terminal_name(compiled) == TERMINAL_NAME


def test_the_name_never_carries_the_suffix(compiled):
    """
    The entry has `pyte-256color` as an alias, and a pane must never be
    given that spelling.

    A program reads "256color" out of `TERM`, decides that the palette
    is the limit, and quantises a 24 bit colour to an index before this
    screen ever sees it. Truecolour is said in the `RGB` and `Tc`
    capabilities, and never in a name.
    """
    environment = {}
    prepare(environment, compiled)
    assert "256color" not in environment["TERM"]


def test_a_program_is_told_xterm_when_the_entry_is_missing(empty):
    environment = {}
    prepare(environment, empty)
    assert environment["TERM"] == FALLBACK_NAME
    assert terminal_name(empty) == FALLBACK_NAME


def test_a_program_searches_our_database_first(compiled):
    environment = {}
    prepare(environment, compiled)
    assert environment["TERMINFO_DIRS"] == "%s:" % compiled


def test_the_database_that_was_there_stays(compiled):
    "An empty entry in the list means the place the system keeps."
    environment = {"TERMINFO_DIRS": "/somewhere/else"}
    prepare(environment, compiled)
    assert environment["TERMINFO_DIRS"] == "%s:/somewhere/else" % compiled


def test_no_database_is_named_without_an_entry(empty):
    environment = {"TERMINFO_DIRS": "/somewhere/else"}
    prepare(environment, empty)
    assert environment["TERMINFO_DIRS"] == "/somewhere/else"


def test_a_program_is_told_that_it_may_write_a_colour(compiled):
    environment = {"COLORTERM": ""}
    prepare(environment, compiled)
    assert environment["COLORTERM"] == "truecolor"


def test_preparing_scrubs_as_well(compiled):
    environment = {"KITTY_WINDOW_ID": "1"}
    prepare(environment, compiled)
    assert "KITTY_WINDOW_ID" not in environment


def test_the_rest_of_the_environment_is_left_alone(compiled):
    environment = {"HOME": "/home/someone", "SHELL": "/bin/sh"}
    prepare(environment, compiled)
    assert environment["HOME"] == "/home/someone"
    assert environment["SHELL"] == "/bin/sh"


# ----------------------------------------------------------------------
# The names of the outer terminal.


@pytest.mark.parametrize(
    "name",
    [
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "KITTY_WINDOW_ID",
        "KONSOLE_VERSION",
        "ITERM_SESSION_ID",
        "WEZTERM_EXECUTABLE",
        "GHOSTTY_RESOURCES_DIR",
        "WT_SESSION",
        "VTE_VERSION",
        "ALACRITTY_WINDOW_ID",
    ],
)
def test_a_variable_that_names_the_terminal_goes(name):
    environment = {name: "something", "HOME": "/home/someone"}
    scrub_terminal_identity(environment)
    assert name not in environment
    assert environment["HOME"] == "/home/someone"


def test_a_remote_control_socket_stays():
    "It names a service, not the terminal that this screen draws in."
    environment = {"KITTY_LISTEN_ON": "unix:/tmp/kitty", "KITTY_WINDOW_ID": "1"}
    scrub_terminal_identity(environment)
    assert environment == {"KITTY_LISTEN_ON": "unix:/tmp/kitty"}


def test_scrubbing_an_environment_without_them_changes_nothing():
    environment = {"TERM": "xterm-256color"}
    scrub_terminal_identity(environment)
    assert environment == {"TERM": "xterm-256color"}


def test_every_name_is_listed_once():
    assert len(set(TERMINAL_IDENTITY_VARIABLES)) == len(TERMINAL_IDENTITY_VARIABLES)


def test_the_names_are_upper_case():
    "An environment variable of a terminal is upper case, every time."
    for name in TERMINAL_IDENTITY_VARIABLES:
        assert name == name.upper()
