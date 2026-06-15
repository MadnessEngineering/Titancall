#!/usr/bin/env bash
# Install titancall: symlink onto PATH + seed config.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BIN="${HOME}/.local/bin"
mkdir -p "$BIN"
ln -sf "$REPO/bin/titancall" "$BIN/titancall"
echo "linked $BIN/titancall -> $REPO/bin/titancall"
"$BIN/titancall" config >/dev/null   # seeds ~/.config/titancall/config on first run
echo "config seeded. Voice library expected at ~/.local/share/titancall/sounds/<titan>/"
command -v SwitchAudioSource >/dev/null 2>&1 || echo "note: 'brew install switchaudio-osx' for output-device routing"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: add $BIN to PATH" ;; esac
