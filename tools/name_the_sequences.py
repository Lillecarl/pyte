"""
Rewrite hand-typed escape sequences into calls that say what they mean.

Escape sequences reach this codebase as raw strings in a few thousand
places. `"\\x1b[?1049h"` is a mode number in a positional slot of a
plain string, and a wrong digit passes review as easily as a right
one. `pyte.sequences` names them instead. This is the tool that moves
the calls over, because there are too many to move by hand and a hand
that moves three thousand of them makes mistakes of its own.
Lillecarl/pymux#165.

    python pyte/tools/name_the_sequences.py pyte/tests        # look
    python pyte/tools/name_the_sequences.py --apply pyte/tests  # do it

**It looks by default and changes nothing.** A run prints a unified
diff of every file it would touch and a count of what it left alone.
`--apply` is the flag that writes.

**Every rewrite proves itself before the file is written.** The new
expression is evaluated and compared with the string it replaces, and
a run stops on the first one that differs. The diff is for a person to
read; this is what makes the result trustworthy, because a mechanical
change that nobody can check is worth less than no change at all.

**What it does not touch**, and each for a reason:

- The files in `KEEPS_ITS_LITERALS`. A test that judges a writer has
  to hold the bytes it expects as a literal, or it proves nothing:
  `encode_key("\\x01") == kitty_key("a", CTRL)` passes whatever both
  of them do. Those suites are named, not guessed.
- A string with more than one ESC in it. One call per sequence is the
  point, and splitting a blob into several calls is a judgement about
  where the sequence ends that this tool has no business making.
- A byte string. `drive_with_pty.py` writes `b"\\x1b[6;20;10t"`, and
  giving it a builder means deciding whether `Terminal.write` takes
  text. That is a change to the harness, not a rename.
- Anything that is not a plain string constant: an f-string part, a
  docstring, a string that is already an argument to a builder.
- A sequence with no rule. OSC, DCS and APC carry payloads that are
  not parameters, and SGR carries attributes that nothing names yet.
  They are counted and printed, so the next builder is chosen from
  what is actually there rather than from a guess.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator, List, NamedTuple, Tuple

REPOSITORY = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPOSITORY / "pyte"))

from pyte import escape  # noqa: E402
from pyte.control import CSI  # noqa: E402
from pyte.modes import AnsiMode, PrivateMode  # noqa: E402
from pyte.sequences import MARKERS, Csi  # noqa: E402

#: The suites that judge a writer. Their literals are the answer, so
#: writing them through a builder would ask the writer to mark its own
#: work. `pyte/tests/test_writing_a_sequence.py` is the third case: it
#: is what proves the builder itself.
KEEPS_ITS_LITERALS = frozenset(
    {
        "pyte/tests/test_keys.py",
        "pyte/tests/test_kitty_keyboard.py",
        "pyte/tests/test_modify_other_keys.py",
        "pyte/tests/test_application_keypad.py",
        "pyte/tests/test_queries.py",
        "pyte/tests/test_terminfo.py",
        "pyte/tests/test_writing_a_sequence.py",
        # This tool's own tests. Their literals are the input it is
        # asked to name, so writing them through the builder makes
        # every case circular: `rewritten(csi(Csi.SD, 2))` asks the
        # tool about a string the builder wrote, which is not the
        # question. It rewrote this file once, before the name was
        # here.
        "pyte/tests/test_naming_the_sequences.py",
        "pymux/tests/test_keys.py",
        # An example a reader learns the bytes from. The strings are
        # the subject, not a way of reaching one.
        "pyte/examples/debug.py",
    }
)

#: One CSI sequence, whole. The parameters, then the intermediate
#: bytes, then the final byte: the same three parts `streams.py` reads.
#:
#: **It ends with `\Z` and not `$`.** In Python `$` also matches
#: before a trailing newline, so `"\x1b[4;1H\n"` read as a bare
#: sequence and the rewrite dropped the newline. The check that every
#: expression writes back the string it replaced is what found it.
A_CSI_SEQUENCE = re.compile(
    r"\A\x1b\["
    r"(?P<private>[?<>=]?)"
    r"(?P<params>[0-9;:]*)"
    r"(?P<final>[ -/]*[@-~])\Z"
)

#: The names in `escape.py` that are CSI final bytes, and only those.
#:
#: **The list is written out because the module mixes two kinds.**
#: `escape.py` names the ESC sequences and the CSI ones in one file,
#: and the same byte means different things in the two: "D" is IND
#: after ESC and CUB after CSI, "c" is RIS after ESC and DA after CSI.
#: Reading the module with `dir` gives whichever name comes last in
#: the alphabet, so "CSI 3 D" came out as `csi(escape.IND, 3)`, which
#: writes the right bytes under a name that means something else.
CSI_NAMES = (
    "ICH", "CUU", "CUD", "CUF", "CUB", "CNL", "CPL", "CHA", "CUP",
    "ED", "EL", "IL", "DL", "DCH", "ECH", "HPR", "DA", "VPA", "VPR",
    "HVP", "TBC", "SM", "RM", "SGR", "DSR", "DECSTBM", "HPA",
)

#: What each final byte is called, so that a rewrite names it.
_ESCAPE_NAMES = {getattr(escape, name): name for name in CSI_NAMES}


class Rewrite(NamedTuple):
    "One string, and the expression that writes it instead."

    text: str
    expression: str


class Skipped(NamedTuple):
    "One string this tool left alone, and why."

    text: str
    reason: str


def an_expression_for(text: str) -> Rewrite | Skipped:
    """
    The call that writes `text`, or the reason there is none.

    The rules run from the most specific to the least, so a mode is a
    mode before it is a CSI sequence with an "h" on the end.
    """
    if text.count("\x1b") != 1:
        return Skipped(text, "not one sequence")
    if not text.startswith(CSI):
        return Skipped(text, "not CSI")

    match = A_CSI_SEQUENCE.match(text)
    if match is None:
        return Skipped(text, "no whole CSI sequence")

    private = match.group("private")
    final = match.group("final")
    params = match.group("params")

    if ":" in params:
        # A subparameter is a tuple, and reading one back means
        # deciding which parameter it belongs to. `csi` writes them;
        # nothing here has to guess where they go.
        return Skipped(text, "subparameters")

    values = _values_of(params)

    mode = _a_mode_call(final, private, values)
    if mode is not None:
        return Rewrite(text, mode)

    name = _a_name_for(final)
    if name is None:
        return Skipped(text, "no name for %r" % (final,))

    arguments = [name] + [_written(value) for value in values]
    if private:
        arguments.append("private=%r" % (private,))
    return Rewrite(text, "csi(%s)" % ", ".join(arguments))


def _values_of(params: str) -> List[int | None]:
    """
    The parameters, with `None` for one that was left out.

    An empty string carries no parameters at all, which is not the
    same as one empty parameter: "CSI H" and "CSI ; H" are different
    sequences, and only the second has two of them.
    """
    if params == "":
        return []
    return [int(one) if one else None for one in params.split(";")]


def _a_mode_call(
    final: str, private: str, values: List[int | None]
) -> str | None:
    "SM or RM, when `modes.py` names every mode in it."
    if final not in (escape.SM, escape.RM):
        return None
    if private not in ("", "?"):
        return None
    if not values or any(value is None for value in values):
        return None

    kind = PrivateMode if private == "?" else AnsiMode
    try:
        modes = [kind(value) for value in values]
    except ValueError:
        # A number that nothing names. The long form says the marker
        # out loud, which the short form cannot.
        return None

    call = "set_mode" if final == escape.SM else "reset_mode"
    return "%s(%s)" % (
        call,
        ", ".join("%s.%s" % (kind.__name__, mode.name) for mode in modes),
    )


def _a_name_for(final: str) -> str | None:
    "What to call this final byte, with the module it comes from."
    if final in _ESCAPE_NAMES:
        return "escape.%s" % _ESCAPE_NAMES[final]
    for member in Csi:
        if member.value == final:
            return "Csi.%s" % member.name
    return None


def _written(value: int | None) -> str:
    return "None" if value is None else str(value)


class Change(NamedTuple):
    "Where a string sits in a file, and what replaces it."

    start: Tuple[int, int]
    end: Tuple[int, int]
    rewrite: Rewrite


#: The string methods that take an expectation and not input.
#:
#: `line.endswith("\x1b[0m")` asks a question about an answer, the
#: same way `line == "\x1b[0m"` does, and the argument is the subject
#: of the test either way. Writing it through a builder that the code
#: under test also uses makes the assertion true whatever both of them
#: do: `blocks.py` writes `csi(escape.SGR, 0)`, so a test that expects
#: `csi(escape.SGR, 0)` has stopped asking anything.
READS_A_STRING = frozenset(
    {
        "startswith",
        "endswith",
        "count",
        "find",
        "index",
        "rfind",
        "rindex",
        "removeprefix",
        "removesuffix",
        "split",
        "rsplit",
        "partition",
        "rpartition",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
    }
)


def _expectations(tree: ast.AST) -> set:
    """
    The strings a test expects, which stay as they are.

    A test that reads a screen's answer back holds that answer as a
    literal, and it has to: `answers == [csi(Csi.XTWINOPS, 9, 25, 80)]`
    asks the writer to mark its own work, and passes whatever the
    writer does. The bytes on that side of a comparison are the
    subject of the test.

    **The rule is where the string sits, not which file it is in.** A
    string inside a call is an argument to something the test runs, so
    it is input even when the call is one side of a comparison:
    `feed(csi(...)) == [...]` is a sequence going in and an answer
    coming back, and only the answer is an expectation.

    A call to one of `READS_A_STRING` is the exception to that: those
    ask a question about a string rather than doing something with it,
    so what they are given is an expectation wherever it appears.
    """
    expected = set()

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Call) and not _reads_a_string(child):
                # What a call is given is input to it. The comparison
                # is about what comes out.
                continue
            if isinstance(child, ast.Constant):
                expected.add(id(child))
            walk(child)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            walk(node)
        elif isinstance(node, ast.Call) and _reads_a_string(node):
            for argument in node.args:
                for part in ast.walk(argument):
                    if isinstance(part, ast.Constant):
                        expected.add(id(part))

    return expected


def _reads_a_string(node: ast.Call) -> bool:
    "Whether this call asks a question about a string."
    return (
        isinstance(node.func, ast.Attribute)
        and node.func.attr in READS_A_STRING
    )


def _strings_of(tree: ast.AST) -> Iterator[ast.Constant]:
    """
    Every plain string constant that is a sequence going somewhere.

    A part of an f-string is not one: it has no position of its own
    that a splice can use, and a builder call inside one would have to
    be written differently anyway. A docstring is not one either: it
    is prose about the sequences and not a sequence. What a comparison
    expects is not one, and `_expectations` says why.
    """
    inside_a_format = set()
    docstrings = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                inside_a_format.add(id(part))
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(
                first.value, ast.Constant
            ):
                docstrings.add(id(first.value))

    leave_alone = inside_a_format | docstrings | _expectations(tree)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str):
            continue
        if id(node) in leave_alone:
            continue
        yield node


def changes_in(source: str) -> Tuple[List[Change], List[Skipped]]:
    "What this tool would do to one module, and what it would not."
    tree = ast.parse(source)
    changes: List[Change] = []
    skipped: List[Skipped] = []

    for node in _strings_of(tree):
        if "\x1b" not in node.value:
            continue
        answer = an_expression_for(node.value)
        if isinstance(answer, Skipped):
            skipped.append(answer)
            continue
        if node.end_lineno is None or node.end_col_offset is None:
            skipped.append(Skipped(node.value, "no end position"))
            continue
        changes.append(
            Change(
                start=(node.lineno, node.col_offset),
                end=(node.end_lineno, node.end_col_offset),
                rewrite=answer,
            )
        )

    return _that_fit(source, changes, skipped)


#: How long a line this tool will write. The longest line in the tests
#: today is ninety three, so a rewrite that goes past this is making
#: the file harder to read and not easier.
ROOM_ON_A_LINE = 88


def _that_fit(
    source: str, changes: List[Change], skipped: List[Skipped]
) -> Tuple[List[Change], List[Skipped]]:
    """
    The changes that leave a line somebody can read.

    A name is longer than the bytes it names, and on a line that was
    already nearly full the rewrite runs off the end. Wrapping it is a
    decision about how the line should read, which is a person's and
    not this tool's. So the line stays as it was and the count says
    how many are waiting.

    A line is judged whole, because two rewrites on one line are one
    line. A rewrite that makes an over-long line shorter is kept: the
    limit is on what this tool adds, not on what it found.
    """
    lines = source.splitlines()
    kept: List[Change] = []

    by_line: dict = {}
    for change in changes:
        by_line.setdefault(change.start[0], []).append(change)

    for number, on_this_line in sorted(by_line.items()):
        was = lines[number - 1]
        now = was
        for change in sorted(on_this_line, key=lambda one: one.start,
                             reverse=True):
            now = (
                now[: change.start[1]]
                + change.rewrite.expression
                + now[change.end[1]:]
            )
        if len(now) <= max(ROOM_ON_A_LINE, len(was)):
            kept.extend(on_this_line)
        else:
            skipped.extend(
                Skipped(change.rewrite.text, "no room on the line")
                for change in on_this_line
            )

    return kept, skipped


#: Where each name a rewrite can reach for comes from. Only the names
#: a file actually uses are imported, and the ones that share a module
#: share a line.
_IMPORTS = {
    "csi": "pyte.sequences",
    "Csi": "pyte.sequences",
    "set_mode": "pyte.sequences",
    "reset_mode": "pyte.sequences",
    "escape": "pyte",
    "AnsiMode": "pyte.modes",
    "PrivateMode": "pyte.modes",
}


def applied(source: str, changes: List[Change]) -> str:
    """
    The module with every change spliced in.

    The splice runs backwards, so a change never moves the position of
    the one before it.
    """
    lines = source.splitlines(keepends=True)

    for change in sorted(changes, key=lambda one: one.start, reverse=True):
        (first_line, first_column) = change.start
        (last_line, last_column) = change.end
        if first_line != last_line:
            # An implicitly joined string over several lines. The
            # splice would have to decide what to do with the join.
            continue
        line = lines[first_line - 1]
        lines[first_line - 1] = (
            line[:first_column]
            + change.rewrite.expression
            + line[last_column:]
        )

    return "".join(lines) if lines else source


def with_the_imports(source: str, changes: List[Change]) -> str:
    """
    The module, with an import for every name the changes reach for.

    They go under the imports the file already has, which is where a
    reader looks for one and where isort would keep them. A file with
    none gets them under the docstring.

    Names that come from one module share a line. Nothing is added
    twice: a file that already imports `escape` keeps the import it
    has.
    """
    used = {
        name: module
        for name, module in _IMPORTS.items()
        if any(
            re.search(r"\b%s\b" % re.escape(name), change.rewrite.expression)
            for change in changes
        )
    }

    modules: dict = {}
    for name, module in used.items():
        modules.setdefault(module, []).append(name)

    tree = ast.parse(source)
    already = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    wanted = []
    for module, names in modules.items():
        missing = sorted(name for name in names if name not in already)
        if missing:
            wanted.append("from %s import %s" % (module, ", ".join(missing)))
    if not wanted:
        return source

    lines = source.splitlines(keepends=True)
    return "".join(
        lines[: _after_the_imports(tree)]
        + [line + "\n" for line in sorted(wanted)]
        + lines[_after_the_imports(tree) :]
    )


def _after_the_imports(tree: ast.Module) -> int:
    "The line to put a new import on, counting from one."
    after = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            after = node.end_lineno or after
        elif (
            after == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            # The docstring, for a file that imports nothing yet.
            after = node.end_lineno or 0
    return after


def _proven(changes: List[Change], where: Path) -> None:
    """
    Every new expression writes exactly the string it replaces.

    A tool that rewrites three thousand strings is only worth having
    if it cannot get one of them wrong quietly. This is what says so,
    and a run stops here rather than writing a file it cannot vouch
    for.
    """
    scope = {
        "csi": __import__("pyte.sequences", fromlist=["csi"]).csi,
        "Csi": Csi,
        "set_mode": __import__(
            "pyte.sequences", fromlist=["set_mode"]
        ).set_mode,
        "reset_mode": __import__(
            "pyte.sequences", fromlist=["reset_mode"]
        ).reset_mode,
        "escape": escape,
        "AnsiMode": AnsiMode,
        "PrivateMode": PrivateMode,
    }
    for change in changes:
        written = eval(change.rewrite.expression, dict(scope))  # noqa: S307
        if written != change.rewrite.text:
            raise SystemExit(
                "%s: %s writes %r and not %r"
                % (
                    where,
                    change.rewrite.expression,
                    written,
                    change.rewrite.text,
                )
            )


def files_under(paths: List[str]) -> Iterator[Path]:
    for one in paths:
        path = Path(one)
        if path.is_dir():
            yield from sorted(path.rglob("*.py"))
        elif path.suffix == ".py":
            yield path


def _named_by(path: Path) -> str:
    "The path as `KEEPS_ITS_LITERALS` spells one."
    try:
        return path.resolve().relative_to(REPOSITORY).as_posix()
    except ValueError:
        return path.as_posix()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="files or directories")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the files. Without it, nothing changes.",
    )
    parser.add_argument(
        "--skipped",
        action="store_true",
        help="list the sequences that no rule matched, with their counts.",
    )
    arguments = parser.parse_args(argv)

    rewritten = 0
    left = Counter()
    #: Every string no rule matched, with how often it appears.
    #: `--skipped` prints it, and it is how the next builder gets
    #: chosen from what is there rather than from a guess.
    waiting = Counter()

    # **Every file is read and proven before any file is written.**
    # A run that stopped halfway would leave the tree half rewritten,
    # and the thing that stops it is exactly the case where nobody
    # should trust what it already did.
    planned: List[Tuple[Path, str, str]] = []

    for path in files_under(arguments.paths):
        if _named_by(path) in KEEPS_ITS_LITERALS:
            continue

        source = path.read_text()
        # No fast path on the text. A file writes ESC as "\x1b", four
        # characters and not the byte, and the byte only exists after
        # the parser has read the constant. A gate on the text would
        # have to guess which of the spellings a file used.
        try:
            changes, skipped = changes_in(source)
        except SyntaxError as problem:
            print("%s: %s" % (path, problem), file=sys.stderr)
            continue
        for one in skipped:
            left[one.reason] += 1
            waiting[(one.reason, one.text)] += 1
        if not changes:
            continue

        _proven(changes, path)
        new = with_the_imports(applied(source, changes), changes)
        if new == source:
            continue

        rewritten += len(changes)
        planned.append((path, source, new))

    for path, source, new in planned:
        sys.stdout.writelines(
            difflib.unified_diff(
                source.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        )
        if arguments.apply:
            path.write_text(new)

    touched = len(planned)
    print(
        "\n%s %d sequences in %d files."
        % ("Wrote" if arguments.apply else "Would write", rewritten, touched)
    )
    if left:
        print("Left alone:")
        for reason, count in left.most_common():
            print("  %5d  %s" % (count, reason))
    if arguments.skipped:
        print("\nWhat is waiting, most common first:")
        for (reason, text), count in waiting.most_common():
            print("  %5d  %-24s %r" % (count, reason, text))
    if not arguments.apply and touched:
        print("Nothing was written. Pass --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
