"""
Ask xterm itself what a key sends, by pressing it.

xterm is a program and has no encoder to call, so this runs it on an X
display, gives it the focus, and presses keys with XTest. What xterm
writes to its pty is what a key sends. `ptterm/tests/xterm_oracle.py`
runs xterm the same way to read a screen.

xterm defines modifyOtherKeys, so it is the judge that settles the
extended mode (Lillecarl/pymux#698). It speaks no kitty protocol, so it
answers for a pane that pushed no flag, and abstains for every other.

**Every answer ends at a key that says it is done.** After the key
under test, F5 goes down and up, and its "CSI 15 ~" is the same in every
mode a request can ask for. What came before it is the answer. F5 under
test ends with F6.

Settings that are not xterm's defaults, and why:

- `metaSendsEscape`: alt sends ESC before the key, as every other judge
  does. Out of the box xterm sets the eighth bit, which no program in
  use reads; Lillecarl/pymux#186 is about letting a pane choose.
- `backarrowKey: false`, `deleteIsDEL: false`: Backspace sends DEL and
  Delete sends "CSI 3 ~", the pair a pty reports and every judge sends.
- `omitTranslation`: the keys xterm keeps for itself reach the program.

**Alt below modifyOtherKeys level 2 gets no answer.** There it is
`metaSendsEscape` that decides, a setting and not a mode. From level 2
up the mode decides, as xterm's own answers show.

`PYTE_XTERM` names the program, `PYTE_LIBX11` and `PYTE_LIBXTST` the
two libraries, and `DISPLAY` the server.
"""

from __future__ import annotations

import ctypes
import os
import re
import select
import subprocess
import time
import tty

from pyte.keys.events import Modifier

__all__ = ["XtermKeys", "xterm_keys"]

#: How long one answer may take. A build machine under load runs an X
#: client slowly, and a wait that is too short reads as a fault.
PATIENCE = 30.0

#: The keysym of each key kitty names, on the evdev US layout Xvfb has.
#: A key that is missing, or has no keycode there, gets no answer.
_KEYSYMS = {
    "ESCAPE": "Escape",
    "ENTER": "Return",
    "TAB": "Tab",
    "BACKSPACE": "BackSpace",
    "INSERT": "Insert",
    "DELETE": "Delete",
    "LEFT": "Left",
    "RIGHT": "Right",
    "UP": "Up",
    "DOWN": "Down",
    "PAGE_UP": "Prior",
    "PAGE_DOWN": "Next",
    "HOME": "Home",
    "END": "End",
    "PRINT_SCREEN": "Print",
    "PAUSE": "Pause",
    "MENU": "Menu",
    **{"F%d" % n: "F%d" % n for n in range(1, 13)},
    **{"KP_%d" % n: "KP_%d" % n for n in range(10)},
    "KP_DECIMAL": "KP_Decimal",
    "KP_DIVIDE": "KP_Divide",
    "KP_MULTIPLY": "KP_Multiply",
    "KP_SUBTRACT": "KP_Subtract",
    "KP_ADD": "KP_Add",
    "KP_ENTER": "KP_Enter",
    "KP_LEFT": "KP_Left",
    "KP_RIGHT": "KP_Right",
    "KP_UP": "KP_Up",
    "KP_DOWN": "KP_Down",
    "KP_PAGE_UP": "KP_Prior",
    "KP_PAGE_DOWN": "KP_Next",
    "KP_HOME": "KP_Home",
    "KP_END": "KP_End",
    "KP_INSERT": "KP_Insert",
    "KP_DELETE": "KP_Delete",
    "KP_BEGIN": "KP_Begin",
    "LEFT_SHIFT": "Shift_L",
    "LEFT_CONTROL": "Control_L",
    "LEFT_ALT": "Alt_L",
    "LEFT_SUPER": "Super_L",
    "RIGHT_SHIFT": "Shift_R",
    "RIGHT_CONTROL": "Control_R",
    "RIGHT_ALT": "Alt_R",
    "RIGHT_SUPER": "Super_R",
}

#: The keysym of each character a request may type, by its key.
_CHARACTERS = {" ": "space", "[": "bracketleft", "/": "slash", "-": "minus"}

#: The keys held for each modifier. Hyper and meta have no key of their
#: own on this layout, so a request with either gets no answer.
_HELD = {Modifier.SHIFT: "Shift_L", Modifier.CTRL: "Control_L", Modifier.ALT: "Alt_L", Modifier.SUPER: "Super_L"}

#: The X modifier masks of the two locks.
_LOCK_MASK = 1 << 1
_MOD2_MASK = 1 << 4
_XKB_USE_CORE_KBD = 0x0100

#: The keys that ctrl+alt gives to the X server on the evdev layout.
_TO_THE_SERVER = frozenset(
    ("BACKSPACE", "KP_ADD", "KP_SUBTRACT", "KP_MULTIPLY", "KP_DIVIDE", *("F%d" % n for n in range(1, 13)))
)

_SENTINEL = {"F5": "\x1b[15~", "F6": "\x1b[17~"}

_READY = re.compile(r"([0-9a-f]+)\r?\n")


def _argv(path: str, slave: str, fd: int) -> list[str]:
    "xterm in slave mode, on a pty this side made. `xterm_oracle._argv` says why."
    return [
        path,
        "-S%s/%d" % (slave, fd),
        "-geometry",
        "20x4",
        "-fn",
        "fixed",
        "-u8",
        "-xrm",
        "XTerm*metaSendsEscape: true",
        "-xrm",
        "XTerm*backarrowKey: false",
        "-xrm",
        "XTerm*deleteIsDEL: false",
        "-xrm",
        "XTerm*cursorBlink: false",
        # xterm keeps some keys for itself: shift+keypad plus is a
        # bigger font, alt+Enter is the full screen, shift+Insert is a
        # paste. None of that reaches a program, so all of it goes.
        "-xrm",
        "XTerm*omitTranslation: fullscreen,scroll-back,scroll-forw,scroll-lock,shift-fonts,paste,popup-menu,reset,select,wheel-mouse",
    ]


class XtermKeys:
    "One xterm on one display, and the keys pressed into it."

    def __init__(self, path: str, libx11: str, libxtst: str) -> None:
        self._x = ctypes.CDLL(libx11)
        self._xtst = ctypes.CDLL(libxtst)
        self._x.XOpenDisplay.restype = ctypes.c_void_p
        self._x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self._x.XStringToKeysym.restype = ctypes.c_ulong
        self._x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        self._x.XKeysymToKeycode.restype = ctypes.c_ubyte
        self._x.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._x.XSetInputFocus.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        self._x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._x.XkbLockModifiers.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self._xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self._display = self._x.XOpenDisplay(None)
        if not self._display:
            raise RuntimeError("no X display at %r" % os.environ.get("DISPLAY"))

        master, slave = os.openpty()
        tty.setraw(slave)
        try:
            self._process = subprocess.Popen(
                _argv(path, os.ttyname(slave), master),
                pass_fds=(master,),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            os.close(master)
        self._fd = slave
        window = int(_READY.search(self._read_until(lambda said: _READY.search(said))).group(1), 16)
        tty.setraw(slave)
        self._focus(window)
        self._mode: tuple | None = None

    def _focus(self, window: int) -> None:
        """
        Give the focus to xterm's window, once it can take it.

        xterm writes the id of its window before it maps it, and the
        focus of a window that is not mapped yet is a BadMatch, which
        Xlib's own handler answers by ending the process. So errors are
        ignored here, and the focus is set until it holds.
        """
        handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        # Kept on the object: the server calls it back for as long as
        # the display is open.
        self._ignore = handler(lambda display, event: 0)
        self._x.XSetErrorHandler.argtypes = [handler]
        self._x.XSetErrorHandler(self._ignore)
        self._x.XGetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
        ]
        focused, revert = ctypes.c_ulong(), ctypes.c_int()
        deadline = time.monotonic() + PATIENCE
        while True:
            # RevertToParent, CurrentTime. With no window manager the
            # focus stays where it is put.
            self._x.XSetInputFocus(self._display, window, 2, 0)
            self._x.XSync(self._display, 0)
            self._x.XGetInputFocus(self._display, ctypes.byref(focused), ctypes.byref(revert))
            if focused.value == window:
                return
            if time.monotonic() > deadline:
                raise RuntimeError("xterm's window %#x never took the focus" % window)
            time.sleep(0.01)

    def _read_until(self, done) -> str:
        said = ""
        deadline = time.monotonic() + PATIENCE
        while not done(said):
            left = deadline - time.monotonic()
            if left <= 0:
                raise RuntimeError("xterm said %r and no more" % said[-200:])
            readable, _, _ = select.select([self._fd], [], [], min(left, 0.5))
            if readable:
                piece = os.read(self._fd, 1 << 16)
                if not piece:
                    raise RuntimeError("xterm let go of the pty")
                said += piece.decode("utf-8", "surrogateescape")
        return said

    def _keycode(self, keysym: str) -> int:
        return self._x.XKeysymToKeycode(self._display, self._x.XStringToKeysym(keysym.encode()))

    def _tap(self, keycode: int) -> None:
        self._xtst.XTestFakeKeyEvent(self._display, keycode, 1, 0)
        self._xtst.XTestFakeKeyEvent(self._display, keycode, 0, 0)

    def _set_mode(self, cursor_keys: bool, keypad: bool, other_keys: int) -> None:
        mode = (cursor_keys, keypad, other_keys)
        if mode == self._mode:
            return
        settings = (
            ("\x1b[?1h" if cursor_keys else "\x1b[?1l") + ("\x1b=" if keypad else "\x1b>") + "\x1b[>4;%dm" % other_keys
        )
        os.write(self._fd, settings.encode())
        # xterm reads the pty and the X server in one loop, so a reply
        # to a query says the settings above are in.
        os.write(self._fd, b"\x1b[c")
        self._read_until(lambda said: said.endswith("c") and "\x1b[?" in said)
        self._mode = mode

    def press(
        self, key: str, character: str, mods: int, cursor_keys: bool, other_keys: int, keypad: bool
    ) -> str | None:
        """
        What xterm sends for this key, or None when it cannot be pressed.

        `key` is kitty's name, or "CHAR" with `character` the key's own
        character, before shift.
        """
        keysym = _CHARACTERS.get(character, character) if key == "CHAR" else _KEYSYMS.get(key)
        if keysym is None or mods & (Modifier.HYPER | Modifier.META):
            return None
        if mods & Modifier.ALT and other_keys < 2:
            # Below level 2 alt is `metaSendsEscape`, a setting no
            # program can ask for, and not the mode under test.
            return None
        if key in ("PAGE_UP", "PAGE_DOWN") and mods & Modifier.SHIFT:
            # xterm's own translations scroll its scrollback on these, and
            # nothing reaches the pty.
            return None
        if key in _TO_THE_SERVER and mods & Modifier.CTRL and mods & Modifier.ALT:
            # The evdev keymap gives ctrl+alt on these to the X server:
            # XF86Switch_VT_3, XF86Next_VMode, Terminate_Server. No key
            # reaches xterm.
            return None
        keycode = self._keycode(keysym)
        if not keycode:
            return None
        held = [self._keycode(name) for bit, name in _HELD.items() if mods & bit]
        sentinel_key = "F6" if key == "F5" else "F5"
        sentinel = _SENTINEL[sentinel_key]

        self._set_mode(cursor_keys, keypad, other_keys)
        locks = (_LOCK_MASK if mods & Modifier.CAPS_LOCK else 0) | (_MOD2_MASK if mods & Modifier.NUM_LOCK else 0)
        self._x.XkbLockModifiers(self._display, _XKB_USE_CORE_KBD, _LOCK_MASK | _MOD2_MASK, locks)
        for code in held:
            self._xtst.XTestFakeKeyEvent(self._display, code, 1, 0)
        self._tap(keycode)
        for code in reversed(held):
            self._xtst.XTestFakeKeyEvent(self._display, code, 0, 0)
        self._x.XkbLockModifiers(self._display, _XKB_USE_CORE_KBD, _LOCK_MASK | _MOD2_MASK, 0)
        self._tap(self._keycode(sentinel_key))
        self._x.XSync(self._display, 0)
        said = self._read_until(lambda said: said.endswith(sentinel))
        return said[: -len(sentinel)]

    def stop(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        os.close(self._fd)


_xterm: XtermKeys | None = None


def xterm_keys() -> XtermKeys | None:
    "The one xterm every request is pressed into, or None without one."
    global _xterm
    if _xterm is None:
        path, libx11, libxtst = (os.environ.get(name) for name in ("PYTE_XTERM", "PYTE_LIBX11", "PYTE_LIBXTST"))
        if not (path and libx11 and libxtst and os.environ.get("DISPLAY")):
            return None
        _xterm = XtermKeys(path, libx11, libxtst)
    return _xterm
