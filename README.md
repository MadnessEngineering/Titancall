# titancall

> *Protocol 3: Protect the Pilot.* A notification router that speaks Titanfall 2 Titan voice lines.

One CLI every project and hook pipes into. Each project registers as a specific Titan; firing an
event plays a fitting voice line from that Titan, on a selectable macOS output device.

```
titancall done &      # this project's Titan: "Enemy Titan down."
titancall error &     # "Critical damage sustained."
titancall start &     # "Pilot mode online."
```

## Install

```sh
./install.sh                  # symlinks bin/titancall -> ~/.local/bin, seeds config
./install-hooks.sh            # adds Stop/Notification hooks to ~/.claude/settings.json (idempotent)
brew install switchaudio-osx  # only needed to route to a non-default output device
```

`install-hooks.sh` merges into existing hooks — it never clobbers what's already there, and re-running
is a safe no-op. Pass a path to target a different settings file: `./install-hooks.sh ./.claude/settings.json`.
Mute without touching hooks: `titancall off` (re-enable with `titancall on`).

**Shell completion** — `install.sh` also wires up tab-completion for bash & zsh (symlinks into a
writable completions dir, or prints the line to add — never edits your rc file). Completions are
*live*: `titan <TAB>` lists installed Titans, `output <TAB>` lists your audio devices, `<TAB>` /
`play <TAB>` lists events + buckets, `alias <event> <TAB>` lists buckets — all driven by a hidden
`titancall __complete` verb, so they stay in sync as titans/devices/aliases change. New shell to load.

Voice library lives outside the repo (it's ~400M of `.wav`) at
`~/.local/share/titancall/sounds/<titan>/<event>/`. Drop new lines there and run `titancall normalize`.

## Titans (9)

`bt · ion · jarvis · legion · monarch · northstar · ronin · scorch · tone`

## Events

Hooks speak dev-words; config aliases map them to Titan voice-line **buckets**:

| event (alias) | bucket | sounds like |
|---------------|--------|-------------|
| `done`    | down   | "Enemy Titan down" |
| `success` | core   | "Laser core ready" |
| `error`   | damage | "Critical damage sustained" |
| `fatal`   | eject  | "Eject, eject!" |
| `warn`    | warn   | "Warning" |
| `start`   | enter  | "Pilot mode online" |
| `notify`  | follow | "Following your lead, Pilot" |
| `working` | attack | "Engaging Titan" |
| `idle`    | guard  | "Guard mode activated" |

Raw buckets are also playable directly: `down core damage eject warn enter follow attack guard exit misc`.

**Confirmation chirps** — some commands play an immediate sound (bypassing cooldown, respecting mute):
`titan here <name>` / `titan <name>` greet you in that voice; `output <device>` chirps **on the new device**
so you confirm routing; `volume <n>` plays at the new level; `on` proves sound is back.

## Per-project identity

Active Titan is resolved by precedence:

```
$TITANCALL_TITAN  >  nearest ./.titan (walks up)  >  registry (by project path)  >  claim next free Titan
```

- **Claim**: first time an unregistered project fires, it grabs the next unused Titan, writes `./.titan`,
  and records it in `~/.config/titancall/registry`. Unique until you exceed 9 projects (then load-balances).
- `titancall whoami` — show this project's Titan and *why*.
- `titancall titan here <name>` — pin a project deliberately.
- `titancall roster` — table of every project → Titan → last fired.

Because Claude Code runs hooks in the project's directory, a **single** global hook gives every agent its
own voice automatically — no per-project hook config.

## Claude Code wiring

Run `./install-hooks.sh` to wire these into `~/.claude/settings.json` (idempotent, preserves existing hooks):

| Claude Code hook | titancall event | sounds like |
|------------------|-----------------|-------------|
| SessionStart       | start   | "Pilot mode online" |
| Stop               | follow  | "Solid copy" (per-turn ack, back to you) |
| Notification       | notify  | "Following your lead, Pilot" |
| SubagentStop       | follow  | "Solid copy" |
| PostToolUseFailure | error   | "Critical damage sustained" |
| PermissionRequest  | warn    | "Warning" |
| TaskCreated        | working | "Engaging Titan" (work begins) |
| TaskCompleted      | guard   | "Guard mode activated" (holding results until you return) |
| Elicitation        | notify  | "Following your lead, Pilot" (MCP asks for input) |
| PostCompact        | start   | "Pilot mode online" (back online after compaction) |
| SessionEnd         | exit    | "Disengage" |

`PreToolUse`/`PostToolUse` are intentionally excluded — they fire on every tool call. Edit the `EVENTS`
map in `install-hooks.sh` to add/trim. Too chatty? `titancall off`.

**Cooldown** — a burst of the same event (e.g. `SubagentStop` firing once per subagent in a workflow)
would stampede the same voice. `titancall` enforces a per-voice minimum gap (default 4s): within the
window, extra fires return silently. Distinct titans can still overlap. Tune with `titancall cooldown <secs>`
(0 = off). State lives in `~/.local/share/titancall/state/<titan>.last`.

## Playback log

Every played line is appended to `~/.local/share/titancall/log` (tab-separated:
timestamp, event, titan, bucket, wav, project path) — so you can see which soundbyte
just fired from which project.

```
titancall log            # last 20 plays, table view
titancall log 50         # last 50
titancall log off        # disable logging (config key 'log'), if it ever causes lag
titancall log on         # re-enable
titancall log clear      # wipe the file
```

Logging is a single `printf >>` per play — effectively free — but `log off` (or
`titancall config set log 0`) turns it off entirely.

## Shell wiring

```sh
alias dn='titancall done'
long-build-command; titancall done   # speak when a long command finishes
```

## Commands

```
titancall <event>            play event for this project's Titan
titancall random <event>     play from a random Titan
titancall whoami | roster
titancall titan list | here <name> | <name>
titancall output list | <device> | default
titancall volume [0..1]
titancall lines [event]
titancall normalize          re-bucket + rename installed wavs
titancall config | test [event]
titancall log [n] | on | off | clear

```
