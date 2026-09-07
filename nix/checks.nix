# The suites that judge pyte.
#
# It declares its own inputs, so `default.nix` holds the package and does not
# carry arguments that only a test needs.
#
# `package` and `testSources` come from `default.nix`: the first because a
# suite runs against the installed package, the second because it knows where
# the repository root is and this file does not.
#
# `nix/suite.nix` says why a check is two derivations.
{
  python,
  pytest,
  hypothesis,
  callPackage,
  ncurses,
  xorg-server,
  libx11,
  package,
  testSources,
}:
let
  inherit (callPackage ./suite.nix { }) suite;

  # hypothesis generates the sequences that `test_row_versions.py` puts
  # through a screen. A recording holds what one program happened to
  # write, and the paths that move whole ranges of rows are the ones a
  # recording is least likely to reach.
  pythonWithTests = python.withPackages (ps: [
    package
    pytest
    hypothesis
  ]);

  # Narrow a run to one file or one test while hunting:
  #
  #     PYTE_TESTS=tests/test_stream.py nix build --file . checks.pyte-unit
  selection =
    let
      value = builtins.getEnv "PYTE_TESTS";
    in
    if value == "" then "tests" else value;

  prepare = ''
    cp -r ${testSources}/tests .
    chmod -R +w .
    export HOME="$TMPDIR"
    export LANG=C.UTF-8
    export PYTHONDONTWRITEBYTECODE=1
  '';

  # `-displayfd` makes the server say which display it took, once it is
  # ready to answer. Sleeping for a while instead is a race.
  #
  # Xcms needs a display, because it reads the screen description from the
  # root window. A bare Xvfb carries none, so Xlib uses its built-in
  # description, which is the one xterm uses on such a screen too.
  display = ''
    export PYTE_LIBX11=${libx11}/lib/libX11.so
    Xvfb -displayfd 3 -screen 0 1280x1024x24 3> display.txt \
      > xvfb.log 2>&1 &
    trap 'kill %1' EXIT
    while [ ! -s display.txt ]; do sleep 0.1; done
    export DISPLAY=":$(cat display.txt)"
  '';

  runPytest = "python -m pytest $selection -q -p no:cacheprovider";
in
{
  # Everything that needs nothing but python. `tests/conftest.py` says how
  # a file lands in a group, and why the groups exist at all.
  #
  # ncurses is here for the one test that compiles the terminfo entry.
  unit = suite {
    name = "pyte-unit";
    inputs = [
      pythonWithTests
      ncurses
    ];
    env = { inherit selection; };
    setup = prepare + ''
      export PYTE_GROUP=unit
    '';
  } runPytest;

  # The colour specs, judged against the real Xlib. `pyte/xcms.py` is a
  # port of the colour management of Xlib, and only a comparison against
  # the original says whether the port is right.
  xcms = suite {
    name = "pyte-xcms";
    inputs = [
      pythonWithTests
      xorg-server
    ];
    env = { inherit selection; };
    setup = prepare + display + ''
      python -c "import sys; sys.path.insert(0, 'tests'); import xlib_oracle; assert xlib_oracle.xlib_color('rgb:f/f/f') == (255, 255, 255)"
      export PYTE_GROUP=xcms
    '';
  } runPytest;
}
