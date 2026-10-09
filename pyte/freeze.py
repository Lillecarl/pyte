"""
A screen as plain data, and back.

`freeze` walks an object's `KEEP` (`pyte.keep`) and turns every saved
field into JSON-shaped values; `thaw` writes them into a fresh object.
A hot upgrade carries a screen to a new build this way
(Lillecarl/pymux#399), so nothing here is pickled: a new build reads
the values, never the old build's classes.

**Containers are tagged, scalars are not.** A list, tuple, set and dict
all become JSON arrays, so each one says which it was. An object, a
named tuple and an enum carry the dotted name of their class, and only
`pyte` classes are named: a thaw builds nothing else.

**What two fields share stays shared.** A mutable value gets an id the
first time the walk meets it, and a reference after that. The parked
state of the alternate screen holds the first page's buffer, and a
thaw that made two buffers would let them drift apart.

**Cells are apart from the rest.** A buffer is a reference into
`Frozen.buffers`, one entry per row, and an appearance is an index
into `Frozen.appearances`. The rows are most of a screen, so an
embedder stores them as rows of its own, and their encoding is short:
`[column, char, appearance, kind]`.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from enum import Enum
from typing import Any, NamedTuple

from .cells import (
    _CHAR_CACHE,
    _PROTECTED_CHAR_CACHE,
    PLAIN_APPEARANCE,
    UNWRITTEN,
    Appearance,
    Cell,
    ErasedCell,
    ProtectedCell,
    WrittenCell,
    appearance_of,
)
from .keep import Keep
from .page import Row

__all__ = ["Frozen", "freeze", "thaw"]

#: A cell's kind in a frozen row. A protected cell adds its marks to
#: `PROTECTED`, so the marks travel in the same number.
PLAIN, WRITTEN, ERASED, PROTECTED = 0, 1, 2, 3

_KINDS: dict[type, int] = {Cell: PLAIN, WrittenCell: WRITTEN, ErasedCell: ERASED}

#: A frozen row: its number, whether a wrap made it, and its cells.
FrozenRow = list


class Frozen(NamedTuple):
    "One frozen object, and the cells and appearances it points into."

    root: Any
    #: Each buffer's rows by its id, as a string so JSON keeps it:
    #: `[number, wrapped, cells]`.
    buffers: dict[str, list[FrozenRow]]
    #: Each appearance, frozen: `[rendition, hyperlink, hyperlink_id]`.
    appearances: list[Any]


def saved_fields(cls: type) -> list[str]:
    "The fields a class saves, along its MRO, the nearest declaration winning."
    keep: dict[str, Keep] = {}
    for one in reversed(cls.__mro__):
        keep.update(one.__dict__.get("KEEP", {}))
    return [name for name, fate in keep.items() if fate == Keep.SAVED]


def _name(cls: type) -> str:
    return "%s.%s" % (cls.__module__, cls.__qualname__)


def _class(name: str) -> type:
    module, _, qualname = name.rpartition(".")
    if module != "pyte" and not module.startswith("pyte."):
        raise ValueError("a frozen screen names %s, which is not pyte's" % name)
    # Only a module the screen already loaded: a thaw imports nothing.
    return getattr(sys.modules[module], qualname)


def freeze(root: object) -> Frozen:
    "Everything `root` saves, and everything that reaches, as plain data."
    return _Freezer().run(root)


class _Freezer:
    def __init__(self) -> None:
        self.ids: dict[int, int] = {}
        # Holds every object that has an id, so no id is reused for a
        # new object while the walk runs.
        self.held: list[object] = []
        self.buffers: dict[str, list[FrozenRow]] = {}
        self.appearances: list[Any] = []
        self.appearance_index: dict[int, int] = {}

    def run(self, root: object) -> Frozen:
        return Frozen(self.value(root), self.buffers, self.appearances)

    def _id(self, value: object) -> tuple[int, bool]:
        "The id of a mutable value, and whether the walk met it before."
        known = self.ids.get(id(value))
        if known is not None:
            return known, True
        new = self.ids[id(value)] = len(self.ids)
        self.held.append(value)
        return new, False

    def value(self, value: Any) -> Any:
        kind = type(value)
        if value is None or kind in (bool, int, float, str):
            return value
        if isinstance(value, Enum):
            return {"enum": _name(kind), "value": value.value}
        if isinstance(value, tuple):
            if hasattr(kind, "_fields"):
                return {"namedtuple": _name(kind), "fields": [self.value(item) for item in value]}
            return {"tuple": [self.value(item) for item in value]}
        if kind is bytes:
            return {"bytes": value.hex()}

        number, seen = self._id(value)
        if seen:
            return {"ref": number}
        if kind is defaultdict and value.default_factory is Row:
            self.buffers[str(number)] = [self.row(index, row) for index, row in sorted(value.items())]
            return {"buffer": number}
        if kind is list:
            return {"list": [self.value(item) for item in value], "id": number}
        if kind in (set, frozenset):
            return {kind.__name__: [self.value(item) for item in sorted(value, key=repr)], "id": number}
        if kind is dict:
            return {"dict": [[self.value(key), self.value(item)] for key, item in value.items()], "id": number}
        if not any("KEEP" in cls.__dict__ for cls in kind.__mro__):
            raise TypeError("cannot freeze %s: it declares no KEEP" % _name(kind))
        fields = saved_fields(kind)
        return {
            "object": _name(kind),
            "id": number,
            "fields": {field: self.value(getattr(value, field)) for field in fields if hasattr(value, field)},
        }

    def appearance(self, appearance: Appearance) -> int:
        index = self.appearance_index.get(id(appearance))
        if index is None:
            index = self.appearance_index[id(appearance)] = len(self.appearances)
            self.held.append(appearance)
            self.appearances.append([self.value(appearance.rendition), appearance.hyperlink, appearance.hyperlink_id])
        return index

    def row(self, number: int, row: Row) -> FrozenRow:
        cells = []
        for column, cell in row.items():
            kind = _KINDS.get(type(cell))
            if kind is None:
                if type(cell) is not ProtectedCell:
                    raise TypeError("cannot freeze a cell of kind %s" % _name(type(cell)))
                kind = PROTECTED + cell.protection  # type: ignore[attr-defined]
            cells.append([column, cell.char, self.appearance(cell.appearance), kind])
        return [number, row.wrapped, cells]


def thaw(frozen: Frozen, into: object) -> None:
    """
    Write a frozen object's fields into `into`, an object of its class.

    `into` is built by its owner, so what the class does not save -- the
    callbacks, the caches, what the embedder sets -- is already there.
    What derives from saved fields, an object rebuilds in its own
    `after_thaw`, which runs once its fields are written.
    """
    _Thawer(frozen).fields(frozen.root, into)


class _Thawer:
    def __init__(self, frozen: Frozen) -> None:
        self.frozen = frozen
        self.made: dict[int, object] = {}
        self.appearances = [self.appearance(*entry) for entry in frozen.appearances]
        # One erased blank per appearance, the way a screen's erase makes one per call.
        self.erased: dict[int, ErasedCell] = {}

    def appearance(self, rendition: Any, hyperlink: str, hyperlink_id: str) -> Appearance:
        return appearance_of[self.value(rendition), hyperlink, hyperlink_id]

    def fields(self, entry: dict, into: object) -> None:
        if _name(type(into)) != entry["object"]:
            raise TypeError("a frozen %s cannot thaw into a %s" % (entry["object"], _name(type(into))))
        self.made[entry["id"]] = into
        for field, value in entry["fields"].items():
            current = getattr(into, field, None)
            if isinstance(value, dict) and "object" in value and _name(type(current)) == value["object"]:
                # The owner built this part too; fill it rather than replace it.
                self.fields(value, current)
            else:
                setattr(into, field, self.value(value))
        after_thaw = getattr(into, "after_thaw", None)
        if after_thaw is not None:
            after_thaw()

    def value(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "ref" in value:
            return self.made[value["ref"]]
        if "enum" in value:
            return _class(value["enum"])(value["value"])
        if "namedtuple" in value:
            return _class(value["namedtuple"])(*[self.value(item) for item in value["fields"]])
        if "tuple" in value:
            return tuple(self.value(item) for item in value["tuple"])
        if "bytes" in value:
            return bytes.fromhex(value["bytes"])
        if "buffer" in value:
            buffer: defaultdict[int, Row] = defaultdict(Row)
            self.made[value["buffer"]] = buffer
            for number, wrapped, cells in self.frozen.buffers[str(value["buffer"])]:
                buffer[number] = self.row(wrapped, cells)
            return buffer
        if "list" in value:
            items: list = []
            self.made[value["id"]] = items
            items.extend(self.value(item) for item in value["list"])
            return items
        if "set" in value or "frozenset" in value:
            kind = set if "set" in value else frozenset
            made = kind(self.value(item) for item in value[kind.__name__])
            self.made[value["id"]] = made
            return made
        if "dict" in value:
            mapping: dict = {}
            self.made[value["id"]] = mapping
            for key, item in value["dict"]:
                mapping[self.value(key)] = self.value(item)
            return mapping
        if "object" in value:
            made_object = _class(value["object"])()
            self.fields(value, made_object)
            return made_object
        raise ValueError("a frozen value of no known shape: %r" % (value,))

    def row(self, wrapped: bool, cells: list) -> Row:
        row = Row()
        row.wrapped = wrapped
        appearances = self.appearances
        for column, char, index, kind in cells:
            appearance = appearances[index]
            if kind == WRITTEN:
                cell = _CHAR_CACHE[char, appearance]
            elif kind == ERASED:
                cell = self.erased.get(index)
                if cell is None:
                    cell = self.erased[index] = ErasedCell(char, appearance)
                elif cell.char != char:
                    cell = ErasedCell(char, appearance)
            elif kind == PLAIN:
                cell = UNWRITTEN if char == " " and appearance is PLAIN_APPEARANCE else Cell(char, appearance)
            else:
                cell = _PROTECTED_CHAR_CACHE[char, appearance, kind - PROTECTED]
            row[column] = cell
        return row
