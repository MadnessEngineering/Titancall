#!/usr/bin/env python3
"""Fill review.csv's new_bucket column with proposed reclassifications (best-guess pass)."""
import csv, os, sys

CSV = "/Users/d.edens/lab/madness_interactive/projects/common/titancall/data/review.csv"

# (titan, slug) -> proposed bucket. Only lines that should MOVE.
P = {
    # ---- bt: mission dialogue, not titan-OS chatter. Risk/consequence lines carry warn+damage,
    #      the throw itself is the "action", the briefing opens, "goodluck" closes.
    ("bt", "are-you-sure-about-this-there-is-a-58-percent-chance-of-sucess"): "warn",
    ("bt", "dismembernent-may-also-occur"): "warn",
    ("bt", "there-is-a-32-percent-chance-of-a-incomplete-transversal"): "warn",
    ("bt", "there-is-a-32-percent-chance-of-a-incomplete-transversal-resulting-in"): "warn",
    ("bt", "well-neverget-past-those-guns"): "warn",
    ("bt", "what-about-the-other-32-percent"): "warn",
    ("bt", "what-about-the-other-32-percent-incomplete-trans"): "warn",
    ("bt", "resulting-in-catostrophic-trama"): "damage",
    ("bt", "there-is-also-the-possiblity-of-eetorcution-and-dissinengration"): "damage",
    ("bt", "full-throw"): "attack",
    ("bt", "full-throw-with-other-deaths"): "attack",
    ("bt", "i-can-throw-you-across-the-gap"): "attack",
    ("bt", "my-analis-concludes-our-only-option-is-a-throw"): "attack",
    ("bt", "my-analis-concludes-our-only-option-is-a-throw-i-can-throw-you-across-the-gap"): "attack",
    ("bt", "listen-up-we-cant-take-you-directly-to-the-bridge"): "enter",
    ("bt", "good-throw-your-welcome-pilot"): "follow",
    ("bt", "goodluck"): "exit",
    ("bt", "there-is-a-58-percent-chance-of-sucess"): "core",   # `success` event, BT-style odds

    # ---- jarvis: the "friendly pilot" set is a full enter/exit lifecycle sitting in misc
    ("jarvis", "friendly-pilot-on-board"): "enter",
    ("jarvis", "friendly-pilot-on-your-titan"): "enter",
    ("jarvis", "friendly-pilot-riding-on-board"): "enter",
    ("jarvis", "friendly-pilot-has-detached-from-your-titan"): "exit",
    ("jarvis", "friendly-pilot-has-left-your-titan"): "exit",
    ("jarvis", "friendly-pilot-is-clear-of-your-titan"): "exit",
    ("jarvis", "friendly-pilot-is-now-clear-of-your-titan"): "exit",
    ("jarvis", "have-a-nice-day"): "exit",
    ("jarvis", "a-friendly-titan-is-attacking-your-target"): "follow",   # ally backup = follow
    ("jarvis", "a-pilot-is-attackig-your-target"): "follow",
    ("jarvis", "recommend-maintaining-a-safe-distance-from-allies"): "warn",
    ("jarvis", "recommend-regen"): "damage",

    # ---- legion
    ("legion", "friendly-pilot-has-left-the-hull"): "exit",
    ("legion", "friendly-pilot-on-extiorer"): "enter",
    ("legion", "pred-cannon-at-your-disposal"): "attack",
    ("legion", "multiple-titans-are-engaging-you"): "warn",      # threat, not our attack
    ("legion", "manual-targeting-restroed"): "enter",            # controls handed back

    # ---- monarch / ronin / tone / scorch: small corrections
    ("monarch", "ugrade-stage-1"): "core",
    ("ronin", "keep-your-enemies-close"): "core",                # tail of "sword core ready"
    ("ronin", "plan"): "attack",
    ("tone", "tatical-option-paritcal-wall-to-assist-evasion"): "damage",
    ("tone", "tatical-option-partical-wall"): "damage",
    ("tone", "my-systems-are-yous-paint-as-many-targets-as-you-can-with-the-40mm"): "enter",
    ("tone", "good-targeting-pilot-its-good-to-have-you-return"): "enter",
    ("scorch", "warning-core-reactor-overload-near"): "warn",    # a warning, not a core-ready cue
}

rows = list(csv.DictReader(open(CSV)))
hit, changed = set(), []
for r in rows:
    slug = r["file"][:-4] if r["file"].lower().endswith(".wav") else r["file"]
    key = (r["titan"], slug)
    if key in P and P[key] != r["bucket"]:
        r["new_bucket"] = P[key]
        changed.append((r["titan"], r["bucket"], P[key], slug))
        hit.add(key)

missing = set(P) - hit
if missing:
    sys.exit("no such wav (or already there): %s" % sorted(missing))

with open(CSV, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys(), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)

print("%d proposed moves written to review.csv\n" % len(changed))
for t, old, new, slug in sorted(changed):
    print("  %-10s %-7s -> %-7s  %s" % (t, old, new, slug.replace("-", " ")))

# projected per-titan coverage
BUCKETS = ["eject", "core", "down", "damage", "warn", "enter", "guard", "follow", "attack", "exit"]
counts = {}
for r in rows:
    counts.setdefault(r["titan"], {}).setdefault(r["new_bucket"], 0)
    counts[r["titan"]][r["new_bucket"]] += 1
print("\nprojected gaps after applying (buckets still with zero clips):")
for t in sorted(counts):
    gaps = [b for b in BUCKETS if not counts[t].get(b)]
    print("  %-10s %s" % (t, " ".join(gaps) if gaps else "(complete)"))
