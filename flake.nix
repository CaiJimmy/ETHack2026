{
  description = "ETHack 2026 — S&P 500 sustainability framework";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
        # manylinux wheels (numpy/pandas/scipy/pyarrow/sklearn) dlopen these at import time.
        # nix supplies the interpreter + libs on LD_LIBRARY_PATH; uv installs prebuilt wheels.
        libPath = pkgs.lib.makeLibraryPath [
          pkgs.stdenv.cc.cc.lib
          pkgs.zlib
          pkgs.zstd pkgs.bzip2 pkgs.xz pkgs.openssl pkgs.libffi pkgs.ncurses
          pkgs.glib pkgs.nss pkgs.nspr pkgs.dbus pkgs.atk pkgs.cups pkgs.libdrm
          pkgs.expat pkgs.libxkbcommon pkgs.pango pkgs.cairo pkgs.alsa-lib
          pkgs.libx11 pkgs.libxcomposite pkgs.libxdamage
          pkgs.libxext pkgs.libxfixes pkgs.libxrandr pkgs.mesa
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            pkgs.python312
            pkgs.uv
            pkgs.duckdb
            pkgs.curl
            pkgs.jq
            pkgs.git
            pkgs.ffmpeg          # website demo GIF for the deck
            pkgs.nodejs_22       # static site build
          ];
          shellHook = ''
            export LD_LIBRARY_PATH="${libPath}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            export UV_PYTHON="${pkgs.python312}/bin/python3.12"
            export UV_PYTHON_DOWNLOADS=never
            [ -d .venv ] && export PATH="$PWD/.venv/bin:$PATH"
            # API keys live in .env, which is gitignored. Sourced here so no script
            # has to know where they came from and none of them end up in a commit.
            [ -f .env ] && set -a && . ./.env && set +a
            echo "ETHack2026 — python $(python3 --version 2>&1 | cut -d' ' -f2), uv $(uv --version 2>&1 | cut -d' ' -f2), node $(node --version)"
          '';
        };
      });
}
