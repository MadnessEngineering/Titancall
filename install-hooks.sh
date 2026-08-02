#!/usr/bin/env bash
# Install titancall into Claude Code hooks (idempotent, preserves existing hooks).
# Usage: ./install-hooks.sh            # ~/.claude/settings.json (global)
#        ./install-hooks.sh PATH       # a specific settings.json
#        ./install-hooks.sh --prune    # also remove superseded titancall hooks
set -euo pipefail

PRUNE=0
ARGS=()
for a in "$@"; do
  case "$a" in --prune) PRUNE=1 ;; *) ARGS+=("$a") ;; esac
done

SETTINGS="${ARGS[0]:-$HOME/.claude/settings.json}"
TC="$HOME/.local/bin/titancall"
[ -x "$TC" ] || TC="$(command -v titancall || echo "$TC")"

python3 - "$SETTINGS" "$TC" "$PRUNE" <<'PY'
import json, os, sys
path, tc = sys.argv[1], sys.argv[2]
prune = sys.argv[3] == "1"

if os.path.exists(path):
    with open(path) as f:
        try: d = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"refusing to touch malformed JSON: {path}\n  {e}")
else:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d = {}

hooks = d.setdefault("hooks", {})
# "Hook" or "Hook:Matcher" -> titancall event. Curated to meaningful, lower-frequency hooks only.
# PreToolUse/PostToolUse are bare-event poison — they fire on EVERY tool call — but PreToolUse
# narrowed to the Task matcher fires only when a subagent launches, which is the one signal with
# no dedicated hook of its own. It is the sole matcher-scoped entry; keep it that way.
EVENTS = {
    "SessionStart":       "start",    # pilot mode online
    "Stop":               "follow",   # solid copy — per-turn ack, back to you pilot
    "Notification":       "notify",   # guard mode — holding, waiting on the pilot
    "PreToolUse:Task":    "subagent", # friendly pilot on board — a subagent mounts up
    "SubagentStop":       "subagent-done",  # friendly pilot is clear of the titan
    "PostToolUseFailure": "error",    # critical damage sustained
    "PermissionRequest":  "warn",     # warning
    "TaskCreated":        "working",  # engaging titan — work begins (bookend to TaskCompleted)
    "TaskCompleted":      "guard",    # guard mode — holding & watching results until pilot returns
    "Elicitation":        "notify",   # MCP server requests your input
    "PostCompact":        "start",    # all systems nominal — back online after compaction
    "SessionEnd":         "exit",     # disengage
}

# Keyed by (event, matcher, command), not command alone: the same command is legitimately wanted
# under one event and stale under another (`follow` belongs to Stop, but no longer to SubagentStop).
wanted = {(spec.partition(":")[0], spec.partition(":")[2], f"{tc} {te} &")
          for spec, te in EVENTS.items()}

added = []
for spec, te in EVENTS.items():
    event, _, matcher = spec.partition(":")
    cmd = f"{tc} {te} &"
    groups = hooks.setdefault(event, [])
    # match on command AND matcher: one hook event can carry several matcher-scoped groups
    here = any(hk.get("command") == cmd and g.get("matcher", "") == matcher
               for g in groups for hk in g.get("hooks", []))
    if not here:
        groups.append({"matcher": matcher,
                       "hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
        added.append(spec)

# Stale hooks: a titancall hook whose command isn't one this map wants. Retargeting an event (e.g.
# SubagentStop follow -> subagent-done) would otherwise leave the old one behind and fire BOTH,
# since installing is purely additive. Report by default; --prune removes.
stale = []
for event, groups in hooks.items():
    for g in groups:
        for hk in g.get("hooks", []):
            c = hk.get("command", "")
            if "titancall" in c and (event, g.get("matcher", ""), c) not in wanted:
                stale.append((event, g, hk, c))

if stale and prune:
    for event, g, hk, c in stale:
        g["hooks"].remove(hk)
    for event in list(hooks):                      # drop groups/events left empty
        hooks[event] = [g for g in hooks[event] if g.get("hooks")]
        if not hooks[event]:
            del hooks[event]

if added or (stale and prune):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, path)
    if added:
        print(f"installed titancall hooks: {', '.join(added)}")
    if stale and prune:
        print(f"pruned superseded hooks: {', '.join(f'{e} ({c.split()[-2]})' for e, _, _, c in stale)}")
else:
    print("titancall hooks already present — nothing to do")

if stale and not prune:
    print("\nsuperseded titancall hooks still installed (they will fire ALONGSIDE the new ones):")
    for event, _, _, c in stale:
        print(f"  {event:20} {c}")
    print("remove them with: ./install-hooks.sh --prune")

print(f"settings: {path}")
PY

echo "reload: open /hooks once (or restart) so Claude Code picks up the change"
echo "mute anytime: titancall off   |   re-enable: titancall on"
