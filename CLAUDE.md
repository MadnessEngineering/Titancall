# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`titancall` — a single-file bash CLI (`bin/titancall`, ~425 lines) that plays Titanfall 2 Titan
voice lines as notifications. Every project/hook that pipes into it gets its own Titan voice.
No build, no deps beyond macOS `afplay` (+ optional `SwitchAudioSource` for device routing,
`ffmpeg` only for `level`). **All logic lives in `bin/titancall`** — edit there.

## Commands

```sh
./install.sh                          # symlink bin/titancall -> ~/.local/bin, seed config
./install-hooks.sh [settings.json]    # merge Claude Code hooks (idempotent, python3 merge)
TITANCALL_WAIT=1 titancall test done  # play + BLOCK until clip ends — use this to verify audio
titancall config                      # dump active config
titancall whoami                      # resolved titan + why (env|dotfile|registry|claimed|config)
```

There is no test suite. To exercise a change: run the subcommand with `TITANCALL_WAIT=1` so playback
blocks (default playback is detached — the process returns before the sound plays, so a bare test
call tells you nothing). `bash -n bin/titancall` for syntax.

## Runtime state (all outside the repo)

- `~/.config/titancall/config` — `key=value` lines; seeded from `DEFAULT_CONFIG` on first run.
- `~/.config/titancall/registry` — TSV `titan \t project_path \t last_fired_iso`.
- `~/.local/share/titancall/sounds/<titan>/<bucket>/*.wav` — voice library (~400M, NOT in git).
- `~/.local/share/titancall/state/<titan>.last` — epoch of last play, for cooldown.
- `~/.local/share/titancall/log` — TSV playback log.

## Architecture (the parts that span functions)

**Two-layer event model.** Callers speak *events* (dev-words: `done error start`). Config
`alias.<event>=<bucket>` maps each to a *bucket* (titan-words: `down damage enter`). Buckets are the
actual `<titan>/<bucket>/` sound folders. `resolve_bucket` does event→bucket; an event with no alias
falls through as its own name, so raw buckets play directly.

**Bucketing is manifest-first, keyword-fallback.** The wav filenames *are* the transcripts (named
by ear, typos preserved as ground truth). `scripts/build_manifest.py` holds an `OVERRIDES` map of
semantic bucket decisions and emits two tracked files in `data/`: `manifest.tsv` (reviewable:
titan/file/current/proposed/transcript/source) and `buckets.tsv` (authoritative `titan\tslug\tbucket`).
`normalize` calls `manifest_bucket` (greps `buckets.tsv`) first and only falls back to the keyword
`classify` (`BUCKET_RULES`, an ordered `bucket|pat1|pat2|...` list, first substring match wins) when
a file isn't in the manifest. So: to reclassify existing lines, edit `OVERRIDES` in build_manifest.py
and run `python3 scripts/build_manifest.py --apply` (moves files) — don't hand-edit `data/*.tsv`.
Adding a brand-new Titan line = drop wav in `sounds/<titan>/`, `titancall normalize` (keyword-classified),
then optionally add an OVERRIDE + rebuild if it landed wrong. `bin/titancall` resolves `REPO_DIR`
through its `~/.local/bin` symlink to find `data/buckets.tsv`.

The voice library (`$TITANCALL_HOME/sounds`, ~400M) is NOT in git — only `data/*.tsv` is. Regenerating
the manifest requires the library present; `build_manifest.py` walks it directly.

**Titan identity precedence** (`resolve_titan`, sets globals `ACTIVE_TITAN`/`ACTIVE_SRC` in the
current shell — no subshell, so callers read the source):
`$TITANCALL_TITAN` → nearest `./.titan` walking up → registry by project path → claim next free
Titan. `project_root` prefers `$CLAUDE_PROJECT_DIR`, then a `.titan` dir, then git toplevel, then
PWD — this is why one global hook gives each project its own voice. `claim_titan` grabs the first
unused Titan (least-used once all 9 are taken) and persists both `./.titan` and the registry.

**Playback is fire-and-forget.** `play_file` detaches into a backgrounded subshell with fds closed
and `disown`s it, so hooks never block. `TITANCALL_WAIT=1` switches to the blocking path
(`_play_seq`), which is also where device switch/restore happens (switch → afplay → restore prev).

**Cooldown collapses bursts.** `cooldown_ok` enforces a per-titan min gap (config `cooldown`, default
4s; `cooldown.<event>` overrides) via the `state/<titan>.last` stamp — stops e.g. `SubagentStop`
firing N times in a workflow from stampeding one voice. `confirm` chirps (device/volume/titan
changes) deliberately bypass cooldown but still respect the `enabled` mute gate.

**Config keys** are gated by `key_ok`: known scalars (`CONFIG_KEYS`) plus `alias.*`, `volume.*`,
`cooldown.*` namespaces. `cfg`/`cfg_set` are grep/sed over the flat file.

**Shell completion is data-driven.** `bin/titancall __complete <context-words>` is a hidden verb
that emits newline candidates for the slot after the given words (reusing `list_titans`,
`device_names`, `events` = config `alias.*` keys, `bucket_names`). The thin `completions/titancall.bash`
and `completions/_titancall` (zsh) call it, so completions never hardcode titans/devices/aliases.
`install.sh` symlinks them into a writable completions dir or prints an rc hint — it never edits rc files.

## Conventions

- Pure bash, `set -uo pipefail`. Small `cmd_*` functions dispatched by `main`'s case; unknown first
  arg falls through to `cmd_play` so `titancall done` == `titancall play done`.
- macOS-only (`afplay`). Guard new OS-specific calls with a `command -v ... || die`.
- Registry/config writes go through temp-file + `mv` (atomic); preserve that pattern.
- Hooks always call titancall even when muted — the `enabled=0` gate returns early inside
  `cmd_play`/`confirm`, it does not remove the hook.
