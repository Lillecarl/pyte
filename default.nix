# The package this repository builds. The suites that judge it live in
# `nix/checks.nix`, which declares its own inputs, so nothing that only a test
# needs is named here.
#
# Nothing else belongs in this repository: the dev shell and the collection
# that assembles this with its siblings live in pyterm.
{
  lib,
  buildPythonPackage,
  flit-core,
  wcwidth,
  callPackage,
  ncurses,
  python,
}:
let
  package = buildPythonPackage {
    pname = "pyte";
    version = "0.8.3.dev";
    src = lib.cleanSource ./.;
    pyproject = true;

    build-system = [ flit-core ];
    dependencies = [ wcwidth ];

    # `tic` compiles the entry that describes this screen. It runs at build
    # time only, so ncurses reaches no closure that runs.
    nativeBuildInputs = [ ncurses ];

    # The compiled entry rides inside the package.
    #
    # A program built on ncurses reads the database of the machine it runs
    # on instead of asking, so without an entry of our own it reads the one
    # for xterm-256color and never writes a curly underline. The entry has
    # to be somewhere that a pane can point `TERMINFO_DIRS` at.
    #
    # Here, and not in a derivation beside the package. Every user of pyte
    # runs a program on a screen: pymux does, and so do the two widgets. A
    # separate output means a wrapper for each of them that sets a variable,
    # and a library such as ptterm has no wrapper to set one in. Inside the
    # package the entry is where `pyte.environment` can always find it, from
    # `__file__`, with nothing to configure.
    #
    # The directory is `terminfo-database` and not `terminfo`, because
    # `pyte/terminfo.py` writes the source of the entry. A directory of that
    # name beside it would be a namespace package with the name of a module,
    # which is a race nobody should have to reason about. A hyphen cannot be
    # a module name, so there is nothing to race.
    postInstall = ''
      export PYTHONPATH=$out/${python.sitePackages}''${PYTHONPATH:+:}$PYTHONPATH
      python -m pyte.terminfo > pyte.ti
      tic -x -o $out/${python.sitePackages}/pyte/terminfo-database pyte.ti

      # An entry that does not compile leaves a pane naming a terminal that
      # is not there, which is worse than naming xterm. Both spellings are
      # checked, because `TERM` may carry either.
      export TERMINFO_DIRS=$out/${python.sitePackages}/pyte/terminfo-database:
      infocmp -x pyte > /dev/null
      infocmp -x pyte-256color > /dev/null
    '';

    # The suite runs as `checks.unit`, against the installed package.
    doCheck = false;
    pythonImportsCheck = [ "pyte" ];

    passthru = { inherit checks; };

    meta = {
      description = "Simple VTXXX-compatible terminal emulator";
      homepage = "https://github.com/selectel/pyte";
      license = lib.licenses.lgpl3Only;
    };
  };

  # Only the tests, not the whole repository. A copy of everything makes
  # the test run rebuild on every unrelated edit.
  #
  # It is built here and not in `nix/checks.nix`, because `./.` there is the
  # `nix` directory and this needs the root of the repository.
  testSources = lib.fileset.toSource {
    root = ./.;
    fileset = ./tests;
  };

  checks = callPackage ./nix/checks.nix { inherit package testSources; };
in
package
