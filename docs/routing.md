# Routing — how one `titancall done` becomes a voice line

Every fire makes exactly three decisions: **who speaks** (titan identity), **what they say**
(event → bucket → wav), and **whether now is the time** (mute gate, cooldown). This file maps
all three, plus the two supporting acts: where a wav's bucket assignment comes from, and how a
project overrides the global config. Every name in the diagrams is a real function or config key
in `bin/titancall` — grep them.

## 1. The chain: hook → event → bucket → wav

Callers speak *dev-words* (`done success error fatal warn start notify working idle`). The sound
folders speak *titan-words* (`down core damage eject warn enter follow attack guard exit misc`).
`alias.<event>` lines in the config bridge the two, and a `group.<name>` can stand in between as
a bucket multiplexer. That indirection is the whole trick: hooks never learn Titanfall
vocabulary, and you retune what "done" sounds like without touching a single hook.

```mermaid
flowchart TD
    HK["Claude Code hook - EVENTS map in install-hooks.sh"] --> EV
    SH["shell / CI: titancall done"] --> EV
    EV(["event (dev-word): done, error, working, ..."])
    EV --> AL{"alias.EVENT set in config?"}
    AL -- "yes: use its target" --> TG
    AL -- "no: event name falls through" --> TG
    TG{"target names a group.NAME?"}
    TG -- yes --> GB["group_buckets: list members, keep only buckets this titan has wavs for, pick ONE at random"]
    TG -- no --> BK
    GB --> BK(["bucket (titan-word): down, damage, enter, ..."])
    BK --> PW["pick_wav: random wav from sounds/TITAN/BUCKET/ (dir missing? falls back to misc/)"]
```

*`resolve_bucket` is the middle of this diagram — alias lookup, fall-through, group expansion.
The fall-through arm is why raw bucket names play directly: `titancall attack` needs no alias,
and the stock `Stop` hook fires `follow` exactly this way (no `alias.follow` exists; the word
already is a bucket).*

**Worked trace #1 — the classic:**

```
$ cd ~/lab/spindle && titancall done        # or any hook wired at `done`
```

1. `resolve_titan` — no `$TITANCALL_TITAN`, no `.titan` file, but the registry has a row for
   `~/lab/spindle` → titan **ion** (via registry).
2. `resolve_bucket done ion` — config says `alias.done=down`; `down` names no group → bucket **down**.
3. `pick_wav ion down` — random draw from `sounds/ion/down/` → `enemy-titan-destroyed.wav`.
4. `play_file` detaches and returns; a beat later: *"Enemy Titan destroyed."*

**Worked trace #2 — an event pointed at a group:**

```sh
titancall group set combat attack,down,warn
titancall alias working combat
```

The `TaskCreated` hook fires `titancall working &` → `alias.working=combat` → `group_buckets
combat` = `attack down warn` → say scorch has no `warn/` folder, so members narrow to
`attack down` → `RANDOM` lands on `attack` → `pick_wav scorch attack` → *"Engaging enemy
Titan."* The next fire may draw `down` instead. That per-voice narrowing matters: a titan
missing one member bucket simply never draws it, instead of face-planting into `misc`.

## 2. Who speaks: titan identity (`resolve_titan`)

First hit wins. The winning source is exactly what `titancall whoami` reports.

```mermaid
flowchart TD
    A{"TITANCALL_TITAN env var?"} -- set --> A1(["use it - via env"])
    A -- no --> B{"read_dotfile: a .titan file, walking up from PWD?"}
    B -- found --> B1(["line 1 of .titan - via dotfile"])
    B -- no --> C{"reg_lookup: registry row for project_root?"}
    C -- hit --> C1(["registered titan - via registry"])
    C -- no --> D{"config claim=1?"}
    D -- yes --> D1(["claim_titan: first unused titan, else least-used. Writes ./.titan + registry - via claimed"])
    D -- no --> E(["config titan, default ion - via config"])
```

And `project_root` — the registry key — has its own precedence:

```mermaid
flowchart LR
    P["project_root"] --> Q1{"CLAUDE_PROJECT_DIR?"}
    Q1 -- set --> R1([use it])
    Q1 -- no --> Q2{"dir holding .titan?"}
    Q2 -- found --> R2([that dir])
    Q2 -- no --> Q3{"git toplevel?"}
    Q3 -- yes --> R3([repo root])
    Q3 -- no --> R4([PWD])
```

*This pair is why ONE global hook gives every project its own voice: Claude Code runs hooks with
`CLAUDE_PROJECT_DIR` set, each project resolves to a different root, and the first fire from an
unregistered root claims the next free titan on the spot — writing `./.titan` and a registry row
so the voice sticks.*

**Example:**

```
$ titancall whoami
titan:   ion  (via registry)
project: /Users/you/lab/spindle
```

## 3. The gauntlet: `cmd_play`

A fire has to survive two gates before anything resolves, and playback itself is built to never
make a hook wait.

```mermaid
flowchart TD
    GO["titancall done"] --> MU{"enabled=0? - mute gate"}
    MU -- muted --> S1(["return 0. Hooks always call us — muted just answers with silence"])
    MU -- no --> RT["resolve_titan → ion"]
    RT --> CO{"cooldown_ok? state/ion.last vs cooldown, default 4s. cooldown.EVENT overrides"}
    CO -- "within gap" --> S2(["return 0 - burst collapsed"])
    CO -- clear --> RB["resolve_bucket done ion → down"]
    RB --> PK["pick_wav ion down → one wav"]
    PK --> LG["reg_touch + log_play - the playback log row"]
    LG --> PL{"play_file: TITANCALL_WAIT=1?"}
    PL -- "no (default)" --> BG["backgrounded subshell, fds closed, disowned - titancall returns before sound starts"]
    PL -- yes --> FG["foreground - blocks until the clip ends"]
    BG --> SQ["_play_seq: switch output device → afplay -v VOL → restore previous device"]
    FG --> SQ
```

*The cooldown stamp is per-titan (`state/<titan>.last`), so `SubagentStop` firing nine times in
a workflow costs one line, not nine — while two different titans can still talk over each other.
Both playback paths run `_play_seq` (device switch → `afplay` → restore); `TITANCALL_WAIT=1`
just runs it in the foreground instead of a disowned subshell. Volume honors a per-event
`volume.<event>` override, then the global `volume`.*

**Example** — the only honest way to test audio, since default playback returns before sound:

```sh
TITANCALL_WAIT=1 titancall test done
```

## 4. Bucketing authority: which folder a wav lives in

`titancall normalize` decides a wav's bucket manifest-first, keywords second:

```mermaid
flowchart LR
    W["wav filename - the transcript, typos preserved"] --> MB{"manifest_bucket: row in data/buckets.tsv?"}
    MB -- hit --> B1(["curated bucket - from build_manifest.py OVERRIDES merged with data/overrides.tsv"])
    MB -- miss --> CL{"classify: first BUCKET_RULES keyword match?"}
    CL -- match --> B2([keyword bucket])
    CL -- none --> B3([misc])
```

*`data/buckets.tsv` is the single authority; the console (`titancall ui`) and `titancall review
apply` both feed it through `data/overrides.tsv` + `build_manifest.py --apply`. The keyword
fallback only catches brand-new lines that no one has curated yet. Don't hand-edit `data/*.tsv`.*

## 5. Per-project overrides: the `.titan` overlay

`./.titan` is two things in one file: **line 1 is identity** (the titan name), and any
`key=value` lines below it are a **config overlay** that beats the global config for this
project only. `cfg()` reads the overlay first, so aliases, groups, volume, and cooldown all get
per-project behavior with zero special-casing in the routing code:

```mermaid
flowchart LR
    K["cfg KEY"] --> O{"./.titan overlay has KEY?"}
    O -- hit --> V1(["project value - tagged P"])
    O -- miss --> G{"global config has KEY?"}
    G -- hit --> V2(["global value - tagged G"])
    G -- miss --> DF(["built-in default"])
```

Write it through the CLI, never by hand — `cmd_project` preserves the titan line and validates
targets the same as the global commands:

```sh
titancall project show                  # titan + current overrides
titancall project alias done core       # this project's `done` → core/
titancall project set volume 0.4        # quieter voice here only
titancall project unset alias.done      # back to the global mapping
```

(The `titan` key is identity, not overlay — `titancall project set titan x` refuses; use
`titancall titan here <name>`.) `titancall config` prints the merged view tagged `[P]`/`[G]`
when an overlay is active, so you always know which layer won.

**Worked trace #3 — overlay beats global:**

```
$ cd ~/lab/reactor && titancall project alias done core
project alias: done -> core  (/Users/you/lab/reactor/.titan)

$ cat .titan
northstar
alias.done=core

$ titancall done
```

`cfg alias.done` hits the overlay → **core** (the global `alias.done=down` never gets a vote) →
`pick_wav northstar core` → *"Flight core online."* Every other project still plays `down/`.
Commit the `.titan` and the whole team's reactor checkout sounds like this.
