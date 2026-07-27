#!/usr/bin/env bash
# Install titancall into Claude Code hooks (idempotent, preserves existing hooks).
# Adds:  Stop -> "titancall done &"   Notification -> "titancall notify &"
# Usage: ./install-hooks.sh            # ~/.claude/settings.json (global)
#        ./install-hooks.sh PATH       # a specific settings.json
set -euo pipefail

SETTINGS="${1:-$HOME/.claude/settings.json}"
TC="$HOME/.local/bin/titancall"
[ -x "$TC" ] || TC="$(command -v titancall || echo "$TC")"

python3 - "$SETTINGS" "$TC" <<'PY'
import json, os, sys
path, tc = sys.argv[1], sys.argv[2]

if os.path.exists(path):
    with open(path) as f:
        try: d = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"refusing to touch malformed JSON: {path}\n  {e}")
else:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d = {}

hooks = d.setdefault("hooks", {})
# event -> titancall event. Curated to meaningful, lower-frequency hooks only.
# (never PreToolUse/PostToolUse — they fire on every tool call.)
EVENTS = {
    "SessionStart":       "start",    # pilot mode online
    "Stop":               "follow",   # solid copy — per-turn ack, back to you pilot
    "Notification":       "notify",   # following your lead, pilot
    "SubagentStop":       "follow",   # subagent reports back
    "PostToolUseFailure": "error",    # critical damage sustained
    "PermissionRequest":  "warn",     # warning
    "TaskCreated":        "working",  # engaging titan — work begins (bookend to TaskCompleted)
    "TaskCompleted":      "guard",    # guard mode — holding & watching results until pilot returns
    "Elicitation":        "notify",   # following your lead — MCP server requests your input
    "PostCompact":        "start",    # all systems nominal — back online after compaction
    "SessionEnd":         "exit",     # disengage
}
want = {ev: f"{tc} {te} &" for ev, te in EVENTS.items()}

added = []
for event, cmd in want.items():
    groups = hooks.setdefault(event, [])
    here = any(hk.get("command") == cmd
               for g in groups for hk in g.get("hooks", []))
    if not here:
        groups.append({"matcher": "",
                       "hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
        added.append(event)

if added:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, path)
    print(f"installed titancall hooks: {', '.join(added)}")
else:
    print("titancall hooks already present — nothing to do")

print(f"settings: {path}")
PY

echo "reload: open /hooks once (or restart) so Claude Code picks up the change"
echo "mute anytime: titancall off   |   re-enable: titancall on"
