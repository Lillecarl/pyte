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
  clippy,
  rustfmt,
  ncurses,
}:
let
  fs = lib.fileset;

  inherit (callPackage ../nix/suite.nix { }) suite;

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

  # The Rust's style, held by the formatter and by clippy with every
  # warning an error, the way `ruff` holds the Python's.
  #
  #     nix build --file . checks.pyte-rs-lint
  checks.lint = suite {
    name = "pyte-rs-lint";
    # A compiler, for the build scripts of the crates: a `runCommand`
    # has none of its own.
    inputs = [
      cargo
      rustc
      clippy
      rustfmt
      stdenv.cc
    ];
    setup = ''
      cp -r ${src}/. crate
      chmod -R +w crate
      cd crate
      export HOME="$TMPDIR"
      export PYO3_PYTHON=${python.interpreter}
      export CARGO_TARGET_DIR="$TMPDIR/target"
      # What `cargoSetupHook` writes, which a `runCommand` never runs.
      mkdir -p .cargo
      printf '[source.crates-io]\nreplace-with = "vendored"\n[source.vendored]\ndirectory = "%s"\n' ${cargoDeps} > .cargo/config.toml
    '';
  } ''
    cargo fmt --check
    cargo clippy --offline --frozen -- -D warnings
  '';

  # pyte with its `test` extra, and these kernels beside it.
  testEnv = mkVirtualEnv "pyte-rs-test-env" {
    pyte = [ "test" ];
    pyte-rs = [ ];
  };

  # pyte's whole unit suite, with the Rust row and kernels installed by
  # `tests/conftest.py`. Every behaviour pyte has tests for, through
  # the storage that replaces the dict. Lillecarl/pymux#570.
  #
  #     nix build --file . checks.pyte-rs-unit
  checks.unit = suite {
    name = "pyte-rs-unit";
    inputs = [
      testEnv
      ncurses
    ];
    setup = ''
      cp -r ${../tests} tests
      cp -r ${../tools} tools
      chmod -R +w .
      export HOME="$TMPDIR"
      export LANG=C.UTF-8
      export PYTHONDONTWRITEBYTECODE=1
      export PYTE_GROUP=unit
      export PYTE_RS=1
    '';
  } "python -m pytest tests -q -p no:cacheprovider";

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

  inherit src cargoDeps;

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
