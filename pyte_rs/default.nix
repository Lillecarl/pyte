# The Rust kernels of pyte, as a package of its own.
#
# It is a project inside this repository and not a source of the umbrella,
# the way libpymux is inside pymux: the kernels judge themselves against the
# Python they replace, and that Python is here.
#
# **Not `mkProject`.** That cuts the source down to `.py` files, and the
# backend it resolves comes from nixpkgs' Python set, which has no maturin:
# nixpkgs ships maturin as a program. So the wheel is built with that program,
# offline, against crates vendored from `Cargo.lock`, and `pyprojectHook`
# installs it like any other. Lillecarl/pymux#566.
{
  lib,
  stdenv,
  python,
  pyprojectHook,
  mkVirtualEnv,
  callPackage,
  rustPlatform,
  cargo,
  rustc,
  maturin,
}:
let
  fs = lib.fileset;

  inherit (callPackage ../nix/suite.nix { }) suite;

  # pyte with its `test` extra, and these kernels beside it.
  testEnv = mkVirtualEnv "pyte-rs-test-env" {
    pyte = [ "test" ];
    pyte-rs = [ ];
  };

  # The kernels against the Python they replace.
  #
  #     nix build --file . checks.pyte-rs-parity
  checks.parity = suite {
    name = "pyte-rs-parity";
    inputs = [ testEnv ];
    setup = ''
      cp -r ${./tests} tests
      chmod -R +w tests
      export HOME="$TMPDIR"
      export LANG=C.UTF-8
      export PYTHONDONTWRITEBYTECODE=1
    '';
  } "python -m pytest tests -q -p no:cacheprovider";
in
stdenv.mkDerivation {
  pname = "pyte_rs";
  version = "0.1.0";

  src = fs.toSource {
    root = ./.;
    fileset = fs.unions [
      ./Cargo.toml
      ./Cargo.lock
      ./pyproject.toml
      ./src
      (fs.fileFilter (file: file.hasExt "py") ./python)
    ];
  };

  cargoDeps = rustPlatform.importCargoLock { lockFile = ./Cargo.lock; };

  nativeBuildInputs = [
    pyprojectHook
    rustPlatform.cargoSetupHook
    cargo
    rustc
    maturin
  ];

  buildPhase = ''
    runHook preBuild
    maturin build --release --offline --frozen --interpreter ${python.interpreter} --out dist
    runHook postBuild
  '';

  passthru = {
    dependencies = {
      pyte = [ ];
    };
    inherit checks;
  };

  meta = {
    description = "Rust kernels for pyte's per-cell loops";
    license = lib.licenses.lgpl3Only;
    platforms = lib.platforms.unix;
  };
}
