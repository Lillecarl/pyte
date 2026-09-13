# The package this repository builds. The suites that judge it live in
# `nix/checks.nix`, which declares its own inputs, so nothing that only a test
# needs is named here.
#
# Nothing else belongs in this repository: the dev shell and the collection
# that assembles this with its siblings live in pyterm.
#
# **This is a pyproject.nix builders package, not a nixpkgs one.** The one
# dependency is declared in `pyproject.toml` and the renderer reads it; an
# environment is a virtualenv rather than a PYTHONPATH. Lillecarl/pymux#319.
#
# The build system stays flit_core. Its siblings moved to hatchling because
# they had a `setup.py` to replace, and pyte has none: upstream already
# declares flit_core, and the version is `dynamic`, which flit reads out of
# `pyte/__init__.py`. Changing that would be churn with a version number to
# lose.
{
  lib,
  stdenv,
  python,
  pyprojectHook,
  resolveBuildSystem,
  mkVirtualEnv,
  mkProject,
  callPackage,
  ncurses,
}:
let
  # What the wheel is built from, and nothing else. A denylist would carry
  # `tests`, `docs`, `examples`, the `__pycache__` beside every module and
  # the `.hypothesis` directory a local property run writes, and a source
  # that a test run changes rebuilds everything above it.
  # Lillecarl/pymux#320.
  projectRoot = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      # Not only the `.py` files: `py.typed` is what tells a checker that
      # the annotations here are meant to be read.
      (lib.fileset.fileFilter (file: file.hasExt "py" || file.name == "py.typed") ./pyte)
      ./pyproject.toml
      ./README.rst
      ./LICENSE
    ];
  };

  package =
    (mkProject {
      inherit projectRoot python;
      extra = rendered: {
        # `tic` compiles the entry that describes this screen. It runs at
        # build time only, so ncurses reaches no closure that runs.
        nativeBuildInputs = rendered.nativeBuildInputs ++ [ ncurses ];

        # The compiled entry rides inside the package.
        #
        # A program built on ncurses reads the database of the machine it
        # runs on instead of asking, so without an entry of our own it reads
        # the one for xterm-256color and never writes a curly underline. The
        # entry has to be somewhere that a pane can point `TERMINFO_DIRS` at.
        #
        # Here, and not in a derivation beside the package. Every user of
        # pyte runs a program on a screen: pymux does, and so do the two
        # widgets. A separate output means a wrapper for each of them that
        # sets a variable, and a library such as ptterm has no wrapper to set
        # one in. Inside the package the entry is where `pyte.environment`
        # can always find it, from `__file__`, with nothing to configure.
        #
        # The directory is `terminfo-database` and not `terminfo`, because
        # `pyte/terminfo.py` writes the source of the entry. A directory of
        # that name beside it would be a namespace package with the name of a
        # module, which is a race nobody should have to reason about. A
        # hyphen cannot be a module name, so there is nothing to race.
        postInstall =
          let
            # `python -m pyte.terminfo` imports pyte, which imports wcwidth.
            # A builders package propagates nothing, so the interpreter needs
            # an environment that holds it -- and this is the one pyte
            # declares, read back off the renderer, so there is no second
            # dependency list here.
            deps = mkVirtualEnv "pyte-terminfo-env" rendered.passthru.dependencies;
          in
          ''
            PYTHONPATH="$out/${python.sitePackages}" \
              ${deps}/bin/python -m pyte.terminfo > pyte.ti
            tic -x -o "$out/${python.sitePackages}/pyte/terminfo-database" pyte.ti

            # An entry that does not compile leaves a pane naming a terminal
            # that is not there, which is worse than naming xterm. Both
            # spellings are checked, because `TERM` may carry either.
            export TERMINFO_DIRS="$out/${python.sitePackages}/pyte/terminfo-database:"
            infocmp -x pyte > /dev/null
            infocmp -x pyte-256color > /dev/null
          '';

        passthru = rendered.passthru // { inherit checks; };

        meta = rendered.meta // {
          description = "Simple VTXXX-compatible terminal emulator";
          homepage = "https://github.com/selectel/pyte";
          license = lib.licenses.lgpl3Only;
        };
      };
    })
      {
        inherit stdenv pyprojectHook resolveBuildSystem;
      };

  # Only the tests, not the whole repository. A copy of everything makes
  # the test run rebuild on every unrelated edit.
  #
  # It is built here and not in `nix/checks.nix`, because `./.` there is the
  # `nix` directory and this needs the root of the repository.
  # `tools` is here because a test judges one of them.
  # `tools/name_the_sequences.py` rewrites hand-typed escape sequences
  # into the builders of `pyte.sequences`, and it has changed a few
  # hundred lines across three repositories, so what it refuses to
  # touch is worth a test. Lillecarl/pymux#165.
  testSources = lib.fileset.toSource {
    root = ./.;
    fileset = lib.fileset.unions [
      ./tests
      ./tools
    ];
  };

  # What the suites run on: pyte, everything it declares, and the `test`
  # extra beside them in the same file.
  testEnv = mkVirtualEnv "pyte-test-env" { pyte = [ "test" ]; };

  checks = callPackage ./nix/checks.nix { inherit testEnv testSources; };
in
package
