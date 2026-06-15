# protocol2 — titancall

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
| Stop               | done    | "Enemy Titan down" |
| Notification       | notify  | "Following your lead, Pilot" |
| SubagentStop       | follow  | "Solid copy" |
| PostToolUseFailure | error   | "Critical damage sustained" |
| PermissionRequest  | warn    | "Warning" |
| TaskCompleted      | success | "Core ready" |
| SessionEnd         | exit    | "Disengage" |

`PreToolUse`/`PostToolUse` are intentionally excluded — they fire on every tool call. Edit the `EVENTS`
map in `install-hooks.sh` to add/trim. Too chatty? `titancall off`.

**Cooldown** — a burst of the same event (e.g. `SubagentStop` firing once per subagent in a workflow)
would stampede the same voice. `titancall` enforces a per-voice minimum gap (default 4s): within the
window, extra fires return silently. Distinct titans can still overlap. Tune with `titancall cooldown <secs>`
(0 = off). State lives in `~/.local/share/titancall/state/<titan>.last`.

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
```
