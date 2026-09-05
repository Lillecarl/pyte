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
