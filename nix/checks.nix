# The suites that judge pyte.
#
# It declares its own inputs, so `default.nix` holds the package and does not
# carry arguments that only a test needs.
#
# `package` and `testSources` come from `default.nix`: the first because a
# suite runs against the installed package, the second because it knows where
# the repository root is and this file does not.
{
  python,
  pytest,
  runCommand,
  package,
  testSources,
}:
let
  pythonWithTests = python.withPackages (ps: [
    package
    pytest
  ]);
in
{
  tests =
    runCommand "pyte-tests" { nativeBuildInputs = [ pythonWithTests ]; }
      ''
        cp -r ${testSources}/tests .
        chmod -R +w .
        export HOME="$TMPDIR"
        export LANG=C.UTF-8
        export PYTHONDONTWRITEBYTECODE=1
        python -m pytest tests -q -p no:cacheprovider
        touch "$out"
      '';
}
