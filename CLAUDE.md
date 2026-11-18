# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`titancall` — a single-file bash CLI (`bin/titancall`, ~500 lines) that plays Titanfall 2 Titan
voice lines as notifications. Every project/hook that pipes into it gets its own Titan voice.
No build, no deps beyond macOS `afplay` (+ optional `SwitchAudioSource` for device routing,
`ffmpeg` only for `level`). **All playback logic lives in `bin/titancall`** — edit there.

`python3` is required only by the maintenance/UI edges — `install-hooks.sh` (JSON merge),
`scripts/build_manifest.py`, and `scripts/titancall_ui.py` (`titancall ui`). Keep it that way:
firing a notification must never need python.

## Commands

```sh
./install.sh                          # symlink bin/titancall -> ~/.local/bin, seed config
./install-hooks.sh [settings.json]    # merge Claude Code hooks (idempotent, python3 merge)
./install-hooks.sh --prune            # ...and drop titancall hooks the EVENTS map no longer wants
TITANCALL_WAIT=1 titancall test done  # play + BLOCK until clip ends — use this to verify audio
titancall config                      # dump active config
titancall whoami                      # resolved titan + why (env|dotfile|registry|claimed|config)
```

There is no test suite. To exercise a change: run the subcommand with `TITANCALL_WAIT=1` so playback
blocks (default playback is detached — the process returns before the sound plays, so a bare test
call tells you nothing). `bash -n bin/titancall` for syntax.

**Testing the curses UI headlessly.** Drive it in tmux and screenshot the pane — a hand-rolled pty
harness will lie to you (unmapped keys, wrong erase semantics):

```sh
tmux new-session -d -s ui -x 120 -y 34 "cd $PWD && python3 scripts/titancall_ui.py; sleep 30"
sleep 1.5; tmux send-keys -t ui 2; sleep 0.4      # key names: Down Tab Enter Space ...
tmux capture-pane -p -t ui; tmux kill-session -t ui
```

For anything that *writes* (moves, groups, aliases), point it at a throwaway library first —
`TITANCALL_HOME=/tmp/sbox/home XDG_CONFIG_HOME=/tmp/sbox/config` plus a copy of the repo, since
`--apply` moves real wavs and rewrites the tracked `data/*.tsv`.

## Runtime state (all outside the repo)

- `~/.config/titancall/config` — global `key=value` lines; seeded from `DEFAULT_CONFIG` on first run,
  and thereafter *merged forward* by `ensure_config` (see the schema note below).
- `<project>/.titan` — IN the project (committable). Line 1 = the titan name; any `key=value` lines
  below are a per-project config overlay that wins over the global config (see `cmd_project`).
- `~/.config/titancall/registry` — TSV `titan \t project_path \t last_fired_iso`.
- `~/.local/share/titancall/sounds/<titan>/<bucket>/*.wav` — voice library (~400M, NOT in git).
- `~/.local/share/titancall/state/<titan>.last` — epoch of last play, for cooldown.
- `~/.local/share/titancall/state/<titan>.recent` — last N clip basenames, for the anti-repeat filter.
- `~/.local/share/titancall/log` — TSV playback log.

## Architecture (the parts that span functions)

**Two-layer event model.** Callers speak *events* (dev-words: `done error start`). Config
`alias.<event>=<bucket>` maps each to a *bucket* (titan-words: `down damage enter`). Buckets are the
actual `<titan>/<bucket>/` sound folders. `resolve_bucket` does event→bucket; an event with no alias
falls through as its own name, so raw buckets play directly.

**Groups are named bucket sets** (`group.<name>=b1,b2,...`), the third alias target. `resolve_bucket
<event> [titan]` expands a group to ONE random member, and when given a titan it first narrows members
to those that actually hold wavs for that voice — otherwise a titan lacking `warn/` would silently
fall through to `misc`. Every caller (`cmd_play`, `confirm`, `cmd_random`, `cmd_lines`) passes the
titan. `target_names` = buckets + groups, and is what `cmd_alias` validates against.

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

**Three ways in, one authority.** All bucket reassignment converges on `data/buckets.tsv`:
the curated `OVERRIDES` dict (hand-edited, for STT/semantic calls), `data/overrides.tsv` (machine-written,
merged *over* the dict — so it always wins), and the two front-ends that write it: `titancall ui` (move
one/a few, with audition) and `titancall review` → `data/review.csv` → `titancall review apply` (bulk
hand-sorting in a spreadsheet). `--import-review` validates every row before touching anything: an
unknown bucket or a stale filename aborts the whole import. Prefer these over hand-editing `data/*.tsv`.

**Titan identity precedence** (`resolve_titan`, sets globals `ACTIVE_TITAN`/`ACTIVE_SRC` in the
current shell — no subshell, so callers read the source):
`$TITANCALL_TITAN` → nearest `./.titan` walking up → registry by project path → claim next free
Titan. `project_root` prefers `$CLAUDE_PROJECT_DIR`, then a `.titan` dir, then git toplevel, then
PWD — this is why one global hook gives each project its own voice. `claim_titan` grabs the first
unused Titan (least-used once all 9 are taken) and persists both `./.titan` and the registry.

**Registry removal** is `reg_forget <titan|""> <path...>` (copy → per-path awk filter → `mv`; rc 1 when
nothing matched), driven by `roster prune` (drops rows whose `$2` isn't a dir; `-n` previews) and
`roster forget [<path>|<titan>|bare=project_root]`. An empty titan arg means "every row for this path",
which is why path-mode drops all of them and titan-mode drops only that one pair — several titans can
share a path. An ambiguous titan (>1 row) exits 2 listing the candidates rather than guessing. Freed
titans need no bookkeeping — `reg_used`/`claim_titan` read the registry live.

`.titan` is deliberately NOT touched by default: identity is committable project state, so a live
project re-registers on its next fire and only the registry row is transient (after `prune` the file is
gone with its directory anyway). `forget --purge` is the opt-in that also drops the identity, and it
drops *only* the identity — a `.titan` carrying overlay `k=v` lines is rewritten without its titan line
rather than deleted, so per-project aliases/groups survive. `resolve_titan`'s `[ -n "$t" ]` guard is
what makes such an overlay-only file fall through to registry/claim instead of resolving to "".

**Coverage is uneven, so buckets degrade rather than fail.** Voices are ripped by ear, so no titan
has every bucket (only 4 of 10 have `down`, which `alias.done` targets). `BUCKET_FALLBACK` is an
ordered `bucket|next|next...` list of *nearest-meaning* substitutes (`down→core→attack`,
`eject→damage→warn`); `playable_bucket` walks it, then `misc`, then any wav the voice owns, and only
fails if the voice is empty. Every caller resolves the playable bucket *before* picking, so the log
records what actually played, not what was asked for. Adding a bucket that few voices have is
therefore cheap — give it a chain and thin voices degrade instead of dying (this is what makes
`mount`/`dismount` viable when only jarvis and legion voice them).

**`mount`/`dismount` are the subagent lifecycle.** A *friendly* second pilot boarding our hull maps
to a subagent starting; detaching maps to it finishing. Three-way split worth preserving: a
**hostile** boarder is a threat (`warn`), and an unqualified "pilot onboard, restoring manual
control" is the pilot themselves returning (`enter`). `mount` is the one signal with no dedicated
Claude Code hook — `install-hooks.sh` reaches it via `PreToolUse` scoped to the `Task` matcher, the
sole matcher-keyed entry in `EVENTS` (bare `PreToolUse` would fire on every tool call). The same two
buckets serve `WorktreeCreate`/`WorktreeRemove`, which is the same boarding gesture at repo scale.

**`EVENTS` is the only durable home for a hook, because installing is additive.** Adding a mapping
never removes the old one, so retargeting an event (`SubagentStop`: `follow` → `subagent-done`) would
leave both firing. Hence the stale pass: any hook whose command mentions `titancall` but isn't in
`wanted` — keyed on `(event, matcher, command)`, since the same command is legitimately wanted under
one event and stale under another — is reported, and removed with `--prune`. Corollary for anyone
hand-adding a titancall hook straight into settings.json: the next `--prune` deletes it. Put it in
the map. Hooks deliberately left unmapped are recorded in a comment under `EVENTS` (currently
`InstructionsLoaded`, `ElicitationResult`, `ConfigChange` — too frequent or redundant to be signal),
so the gap reads as a decision rather than an oversight.

**Anti-repeat beats bucket size.** `pick_wav` keeps a per-voice memory (`state/<titan>.recent`,
length `recent`, default 5) and drops recently-played files from the candidate set. The consulted
window is clamped to `bucket size - 1`: a flat window silently disables itself on any bucket smaller
than it — precisely the thin buckets that need it — so the clamp guarantees ≥1 fresh candidate and
an immediate repeat only when a bucket truly holds one file.

**`DEFAULT_CONFIG` reaches existing installs via `CONFIG_SCHEMA`.** Seeding used to run only for a
brand-new config, so every default added later was inert for anyone already installed. `ensure_config`
now merges in *missing* keys and stamps `schema=N`; it never overwrites a key the user already has,
so their values win. Bump `CONFIG_SCHEMA` whenever `DEFAULT_CONFIG` gains a key. Corollary: changing
a default's *value* still won't reach existing installs — that's deliberate.

**Playback is fire-and-forget.** `play_file` detaches into a backgrounded subshell with fds closed
and `disown`s it, so hooks never block. `TITANCALL_WAIT=1` switches to the blocking path
(`_play_seq`), which is also where device switch/restore happens (switch → afplay → restore prev).

**Cooldown collapses bursts.** `cooldown_ok` enforces a per-titan min gap (config `cooldown`, default
4s; `cooldown.<event>` overrides) via the `state/<titan>.last` stamp — stops e.g. `SubagentStop`
firing N times in a workflow from stampeding one voice. `confirm` chirps (device/volume/titan
changes) deliberately bypass cooldown but still respect the `enabled` mute gate.

**Config keys** are gated by `key_ok`: known scalars (`CONFIG_KEYS`) plus `alias.*`, `volume.*`,
`cooldown.*`, `group.*` namespaces. `cfg`/`cfg_set`/`cfg_unset` are grep/sed over the flat file.
`config unset` only accepts the namespaced keys — scalars have defaults worth keeping.

**Per-project overrides layer through `cfg`.** `cfg key [default]` reads the project `.titan` overlay
first (memoized `overlay_path`, the nearest `.titan` walking up), then the global config, then the
default — so `resolve_bucket`, `group_buckets`, `play_file` (volume) and `cooldown_ok` all get
per-project behavior for free, no routing-function changes. Writes go through `cmd_project`
(`titancall project alias|group|set|unset|show`) into the same `.titan` via `dotfile_set`/`dotfile_unset`,
which always preserve the titan on line 1 (as do `claim_titan`/`titan here`, now via `dotfile_write_titan`
instead of clobbering the file). The `titan` key is identity, not an overlay entry — set it with
`titan here`, and the overlay reader (`dotfile_overlay_lines`) explicitly excludes it. `titancall config`
prints the merged view tagged `[P]`/`[G]` when an overlay is active.

**The console (`titancall ui`) writes through the CLI, never around it.** `scripts/titancall_ui.py`
is a curses front-end over four layers; every mutation shells back out to bash so validation lives in
one place: `titancall alias`, `titancall group set/rm`, `titancall config unset`. It reads
`titancall buckets` / `whoami` for candidates, and previews clips via `titancall playfile <wav>`
(honors device + volume, deliberately bypasses the mute gate and cooldown — the user asked for that
exact clip). Wav→bucket moves are the one file-touching path: the UI appends to the tracked
`data/overrides.tsv` and runs `build_manifest.main(["--apply"])` *in-process* (`apply_manifest`), then
`rescan()`s only the library — not `reload()`, whose `whoami`/`buckets` spawns a move can't change. On a
loaded box each interpreter/bash spawn costs seconds; that is what made moves crawl. `overrides.tsv` is
merged *over* the curated `OVERRIDES` dict, so the console never has to rewrite python source and a UI
move always wins. A *voice* move (`v`) lists the clip's own voice first (picking it = plain rebucket, and
it cancels any pending dest), and adds an optional 4th column (dest titan) to the same row. `voice_moves` →
`apply_voice_moves` run FIRST in `--apply` (validate every row, then rename, then re-`walk()`), and the
executed row is dropped: leaving it would bounce the clip back out the next time it is moved home. Anything
that rewrites `overrides.tsv` must go through `write_user_overrides` (build_manifest) / `write_overrides`
(ui) so the dest column survives. `review.csv` still only edits buckets, not voices.
Hook→event mapping stays read-only (it lives in `~/.claude/settings.json`); the UI parses
`install-hooks.sh`'s `EVENTS` map for the recommended set and settings.json for what's actually wired,
then offers to retarget the *event* instead.

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
- **Never `producer | grep -q`** under `set -o pipefail`: `grep -q` exits on the first match and
  SIGPIPEs the producer, so the pipeline reports failure *even though the match succeeded* (this bit
  `cmd_alias` the moment its candidate list grew a second, slower producer). Use `list_has <needle>
  "$(producer)"` — herestring, no pipe.
- Feeding `while read` from `printf '%s' "$x" | tr ...` silently drops the last field (no trailing
  newline → final `read` returns non-zero). Use `printf '%s\n'`.
- A command whose last statement is a `grep` test returns that grep's rc. Wrap advisory greps in
  `if ...; then err ...; fi` so "nothing found" isn't reported as failure.
- In the curses UI, `esc` never quits (`q` does): an unmapped escape sequence arrives as a bare 27,
  and its tail is drained via `nodelay` so leftovers like `[1~` can't fire as commands.
