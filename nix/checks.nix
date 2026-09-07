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
in
{
  unit = suite {
    name = "pyte-unit";
    inputs = [ pythonWithTests ];
    env = { inherit selection; };
    setup = prepare;
  } "python -m pytest $selection -q -p no:cacheprovider";
}
