# The other terminals that pyte's key encoder is judged against, beside
# kitty, which carries its encoder in its python extension.
#
# Each is a program that answers one line with another;
# `tests/key-judges/ghostty_keys.c` says what a line holds, and
# `tests/key_panel.py` is the other half. They are build inputs of a test
# and reach no closure that runs.
{
  stdenv,
  rustPlatform,
  libghostty-vt,
}:
{
  # Ghostty's encoder, through libghostty-vt. C and not a binding, for the
  # reason `ptterm/tests/judges-c/ghostty_judge.c` gives.
  ghostty = stdenv.mkDerivation {
    pname = "pyte-ghostty-keys";
    version = "0.1.0";
    src = builtins.path {
      path = ../tests/key-judges;
      name = "pyte-ghostty-keys-source";
      filter = path: _type: baseNameOf path == "ghostty_keys.c";
    };
    buildInputs = [ libghostty-vt ];
    buildPhase = ''
      $CC -O2 -Wall -Wextra -Werror -I${libghostty-vt.dev}/include -o ghostty-keys ghostty_keys.c \
        -L${libghostty-vt}/lib -lghostty-vt
    '';
    installPhase = ''
      install -Dm755 ghostty-keys $out/bin/ghostty-keys
    '';
  };

  # WezTerm's two encoders, at the revision `ptterm/tests/judges` pins.
  wezterm = rustPlatform.buildRustPackage {
    pname = "pyte-wezterm-keys";
    version = "0.1.0";
    src = builtins.path {
      path = ../tests/key-judges/wezterm;
      name = "pyte-wezterm-keys-source";
    };
    cargoLock = {
      lockFile = ../tests/key-judges/wezterm/Cargo.lock;
      outputHashes = {
        "termwiz-0.24.0" = "sha256-Fe2rH9HegaUixPXHyHv4B8c0RI34GPbeX8mTzHCQwQ4=";
        "finl_unicode-1.3.0" = "sha256-38S6XH4hldbkb6NP+s7lXa/NR49PI0w3KYqd+jPHND0=";
      };
    };
    doCheck = false;
  };
}
