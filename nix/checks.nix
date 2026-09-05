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
  callPackage,
  package,
  testSources,
}:
let
  inherit (callPackage ./suite.nix { }) suite;

  pythonWithTests = python.withPackages (ps: [
    package
    pytest
  ]);

  prepare = ''
    cp -r ${testSources}/tests .
    chmod -R +w .
    export HOME="$TMPDIR"
    export LANG=C.UTF-8
    export PYTHONDONTWRITEBYTECODE=1
  '';
in
{
  tests = suite {
    name = "pyte-tests";
    inputs = [ pythonWithTests ];
    setup = prepare;
  } "python -m pytest tests -q -p no:cacheprovider";
}
