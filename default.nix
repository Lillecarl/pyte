# The package this repository builds, and the tests that judge it. Nothing
# else belongs here: the dev shell and the collection that assembles this
# with its siblings live in pyterm.
{
  lib,
  buildPythonPackage,
  flit-core,
  wcwidth,
  python,
  pytest,
  runCommand,
}:
let
  package = buildPythonPackage {
    pname = "pyte";
    version = "0.8.3.dev";
    src = lib.cleanSource ./.;
    pyproject = true;

    build-system = [ flit-core ];
    dependencies = [ wcwidth ];

    # The suite runs as `checks.tests`, against the installed package.
    doCheck = false;
    pythonImportsCheck = [ "pyte" ];

    passthru = { inherit checks; };

    meta = {
      description = "Simple VTXXX-compatible terminal emulator";
      homepage = "https://github.com/selectel/pyte";
      license = lib.licenses.lgpl3Only;
    };
  };

  pythonWithTests = python.withPackages (ps: [
    package
    pytest
  ]);

  # Only the tests, not the whole repository. A copy of everything makes
  # the test run rebuild on every unrelated edit.
  testSources = lib.fileset.toSource {
    root = ./.;
    fileset = ./tests;
  };

  checks.tests =
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
in
package
