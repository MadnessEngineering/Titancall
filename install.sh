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

# ---- shell completion (idempotent, never clobbers rc files — symlinks or prints a hint) ----
COMP="$REPO/completions"
case "${SHELL##*/}" in
  zsh)
    # symlink into a writable fpath dir if one exists, else ~/.zsh/completions + rc hint
    fpath_list=$(zsh -c 'print -l $fpath' 2>/dev/null)
    dir=$(printf '%s\n' "$fpath_list" | while IFS= read -r d; do [ -w "$d" ] && { echo "$d"; break; }; done)
    [ -n "$dir" ] || { dir="$HOME/.zsh/completions"; mkdir -p "$dir"; }
    ln -sf "$COMP/_titancall" "$dir/_titancall"
    echo "zsh completion linked -> $dir/_titancall"
    case $'\n'"$fpath_list"$'\n' in
      *$'\n'"$dir"$'\n'*) echo "  run: autoload -Uz compinit && compinit   (or open a new shell)" ;;
      *) echo "  add to ~/.zshrc:  fpath=($dir \$fpath); autoload -Uz compinit; compinit" ;;
    esac ;;
  bash)
    dest=""
    for d in "${BASH_COMPLETION_USER_DIR:-$HOME/.local/share}/bash-completion/completions" \
             "$(brew --prefix 2>/dev/null)/etc/bash_completion.d" \
             /usr/local/etc/bash_completion.d /etc/bash_completion.d; do
      [ -n "$d" ] && [ -d "$d" ] && [ -w "$d" ] && { dest="$d"; break; }
    done
    if [ -n "$dest" ]; then
      ln -sf "$COMP/titancall.bash" "$dest/titancall"
      echo "bash completion linked -> $dest/titancall"
    else
      echo "bash completion: add to ~/.bashrc:  source $COMP/titancall.bash"
    fi ;;
  *)
    echo "completion: source $COMP/titancall.bash (bash) or put $COMP on \$fpath (zsh)" ;;
esac
