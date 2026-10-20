# pyte

> This repository is a copy. Work on pyte happens in
> [pyterm](https://github.com/Lillecarl/pyterm), which exports its `pyte/`
> directory here on every push. Send changes there, and issues to
> [Lillecarl/pymux](https://github.com/Lillecarl/pymux/issues).
> The docs are at <https://lillecarl.github.io/pyte/>.

<!-- The lines above are pyterm's nix/shared/readme-head.md, written by sync-sources. -->

```
                   _
                  | |
     _ __   _   _ | |_  ___
    | '_ \ | | | || __|/ _ \
    | |_) || |_| || |_|  __/
    | .__/  \__, | \__|\___|
    | |      __/ |
    |_|     |___/
```

A terminal emulator without a terminal. It parses what a program writes
and holds the screen that results: the cells, the cursor, the modes and
the history. It opens nothing and draws nothing. `ptyhost` feeds it, and
`ptterm` and `txterm` draw it.

```python
from pyte import Screen, Stream

replies = []
screen = Screen(24, 80, write_process_input=replies.append)
Stream(screen).feed("Hello \x1b[1mworld\x1b[0m!\x1b[6n")

row = screen.page.data_buffer[0]
print("".join(row[x].char for x in range(screen.columns)).rstrip())  # Hello world!
print(replies)  # ['\x1b[1;13R'], the answer to the cursor report
```

`Screen` takes the lines first, the order in which a terminal reports
its size. `write_process_input` takes what the screen answers to the
program: a cursor report, a device attribute, a colour query.

## What it answers as

A VT520, and it honours DECSCL down to a VT100. On top of that it holds
what no DEC terminal had: 256 colours, truecolour, the kitty keyboard
and graphics protocols, sixels, hyperlinks and the underline shapes.
The docstring of `pyte/__init__.py` lists the exceptions.

## Where it comes from

It began as [selectel/pyte](https://github.com/selectel/pyte), which
began as a fork of [vt102](https://github.com/samfoo/vt102). It is not
upstream pyte any more, and it cannot be: the screen moved here out of
`ptterm`, and the API changed with it. `AUTHORS` names the people who
wrote the original, and the licence is still the LGPL.

<!-- The lines below are pyterm's nix/shared/readme-tail.md, written by sync-sources. -->

## Building

    nix build github:Lillecarl/pyte    # from this repository alone
    nix build --file . pyte            # in a checkout of pyterm

The suites that judge it run in pyterm, as `checks.pyte-*`.

## The collection

pyte is one source of [pyterm](https://github.com/Lillecarl/pyterm), and
each source claims one job:

| source | job |
| --- | --- |
| [pyte](https://lillecarl.github.io/pyte/) | parse, and hold a screen |
| [ptyhost](https://lillecarl.github.io/ptyhost/) | run a program on a pty, and carry its bytes |
| [ptterm](https://lillecarl.github.io/ptterm/) | draw one terminal, with prompt-toolkit |
| [txterm](https://lillecarl.github.io/txterm/) | draw one terminal, with Textual |
| [pymux](https://lillecarl.github.io/pymux/) | arrange several of them |
| [pysmithay](https://lillecarl.github.io/pysmithay/) | a headless Wayland compositor, for a GUI program in a pane |
| [pyterm-pytest](https://lillecarl.github.io/pyterm-pytest/) | the test equipment the suites share |
| [deferimport](https://lillecarl.github.io/deferimport/) | make imports lazy, without a keyword |

[pyterm's site](https://lillecarl.github.io/pyterm/) holds every source's
docs.
