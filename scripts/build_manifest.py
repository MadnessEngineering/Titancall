#!/usr/bin/env python3
"""build_manifest.py — transcript-driven bucket manifest for the titancall voice library.

The wav filenames ARE the transcripts (named by ear; typos preserved as ground truth).
This script:
  1. walks $TITANCALL_HOME/sounds/<titan>/<bucket>/*.wav
  2. derives a transcript from each filename
  3. applies semantic OVERRIDES (below), then data/overrides.tsv on top (see USER_OVERRIDES)
  4. writes:
       data/manifest.tsv  — reviewable: titan file current proposed transcript source
       data/buckets.tsv   — authoritative titan\tslug\tbucket  (consumed by `titancall normalize`)
  5. with --apply, moves each wav into its proposed bucket dir

OVERRIDES key = (titan, slug) where slug is the filename without .wav.
Only list files whose bucket should CHANGE — everything else keeps its current bucket.

data/overrides.tsv (`titan \t slug \t bucket`) is the machine-writable twin, produced by
`titancall ui` when you move a wav. It is applied AFTER the dict below, so a UI move always
wins over a curated guess — that way the console never has to rewrite this source file.

Bucket semantics (target of Claude hooks via alias map):
  down   enemy killed/eliminated/destroyed
  core   titan core ability ready/active/offline
  damage OUR titan hurt: critical/heavy/major/severe damage, reactor exposed, casing compromised
  eject  eject
  warn   external threat: enemy attacking, hostile on hull, outnumbered, position compromised
  enter  pilot returns: controls/systems handed to pilot, welcome back, pilot mode online, manual restored
  follow follow mode, following your lead, solid copy, understood, providing backup
  attack engaging enemy, targeting, weapons armed/energized, powering up, scanning for hostiles
  guard  guard mode
  exit   disengage, shutdown, logoff, offline
  misc   genuine leftovers: SFX, loadout/upgrade notifications, ally chatter, flavor
"""
import os, sys, subprocess

HOME = os.environ.get("TITANCALL_HOME", os.path.expanduser("~/.local/share/titancall"))
SOUNDS = os.path.join(HOME, "sounds")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")

# (titan, slug) -> corrected bucket. Only files that MOVE.
OVERRIDES = {
    ("ion", "advice-defensive-system"): "damage",
    ("ion", "asfa"): "damage",  # STT: "severe damage..." — see TRANSCRIBED
    ("ion", "enemy-pilot-attacking"): "warn",
    ("ion", "trasnfering-controls-to-pilot"): "enter",

    ("jarvis", "caution"): "warn",

    ("legion", "advise-aggressive-sustained-counterfire"): "attack",
    ("legion", "conentrate-fire-on-the-weakest-target"): "attack",
    ("legion", "providing-backup"): "follow",
    ("legion", "providing-backup2"): "follow",
    ("legion", "scanning-for-enemy-hostiles"): "attack",
    ("legion", "we-are-better-together"): "enter",
    ("legion", "welcome-back"): "enter",
    ("legion", "warning-major-damage-sustained"): "damage",

    ("monarch", "followingyourleadpilot"): "follow",
    ("monarch", "monarch-pilotsystemtrasnfer"): "enter",
    ("monarch", "moving-in-to-kill"): "attack",
    ("monarch", "pilot-detected-validating-proticals"): "enter",
    ("monarch", "protocal3"): "guard",
    ("monarch", "takeevasive-action"): "damage",
    ("monarch", "understood"): "follow",
    ("monarch", "welcome-back-pilot"): "enter",
    ("monarch", "welcome-back-pilot2"): "enter",
    ("monarch", "your-skills-are-impressive-pilot-it-is-good-to-have-you-return"): "enter",

    ("northstar", "systems-are-yours-we-are-a-strong-force-together"): "enter",
    ("northstar", "trasnfering-systems-to-pilot"): "enter",
    ("northstar", "our-postion-is-compromised"): "warn",

    ("ronin", "engaging-gaurd-mdoe"): "guard",
    ("ronin", "the-sword-is-yours-pilot"): "enter",
    ("ronin", "the-systems-are-yours-we-are-stronger-united"): "enter",
    ("ronin", "the-systems-are-yours"): "enter",
    ("ronin", "trasnfering-controls"): "enter",
    ("ronin", "we-are-stronger-united"): "enter",
    ("ronin", "welcome-back-pilot"): "enter",
    ("ronin", "welcome-back"): "enter",

    ("scorch", "enemy-titan-detected-attempting-situation-control"): "warn",
    ("scorch", "flame-croe-is-ready"): "core",
    ("scorch", "pilol-control-online-thermal-systems-functional"): "enter",
    ("scorch", "priming-offensive-thermal-systems"): "attack",
    ("scorch", "scanning-for-enemy-hostiles"): "attack",
    ("scorch", "scortch-ai-tranfering-controls-to-pilot"): "enter",
    ("scorch", "scortch-ai-tranfering-controls-to-pilot2"): "enter",
    ("scorch", "welcome-back-cockpit-cooling-reactivated"): "enter",
    ("scorch", "welcome-back-cockpit-cooling-reactivated2"): "enter",

    ("tone", "it-is-good-to-have-you-return"): "enter",
    ("tone", "major-damage-sustained"): "damage",
    ("tone", "my-systems-are-yours"): "enter",
    ("tone", "my-systems-are-yours2"): "enter",
    ("tone", "rocket-systems-are-in-your-control-pilot"): "enter",
    ("tone", "seak-out-target-locks-and-track-them"): "attack",
    ("tone", "sev-damage-incured"): "damage",
    ("tone", "switching-to-manual"): "enter",
    ("tone", "systems-are-in-your-control-pilot"): "enter",
    ("tone", "tone-systems-trasnfered-to-pilot"): "enter",
    ("tone", "tracking-hostiles"): "attack",
    ("tone", "understood"): "follow",
    ("tone", "welcome-back-pilot"): "enter",
    ("tone", "warning-major-damage-sustained"): "damage",
}

# Files whose filename is NOT the transcript — resolved by whisper-cpp (ggml-base.en/small.en).
# (titan, slug) -> (source, real_transcript). source: "sfx" = non-speech, stays in misc;
# "stt" = real speech, transcript below is ground truth (bucket set via OVERRIDES above).
TRANSCRIBED = {
    ("bt", "mechsounds1"): ("sfx", "(dramatic music / mech SFX)"),
    ("bt", "mechsounds2"): ("sfx", "(dramatic music / mech SFX)"),
    ("bt", "mechsounds3"): ("sfx", "(dramatic music / mech SFX)"),
    ("bt", "mechsounds4"): ("sfx", "(dramatic music / mech SFX)"),
    ("portal", "asterisk"): ("sfx", "(macOS asterisk alert tone)"),
    ("ion", "asfa"): ("stt", "severe damage"),
    ("jarvis", "electicsmokedur"): ("stt", "electric smoke duration extended"),
    ("monarch", "x016armedtokill"): ("stt", "XO-16 armed to kill"),
}


def transcript(slug):
    return slug.replace("-", " ").strip()


USER_OVERRIDES = os.path.join(DATA, "overrides.tsv")


def user_overrides():
    """data/overrides.tsv -> {(titan, slug): bucket}. Written by `titancall ui`; wins over OVERRIDES."""
    ov = {}
    if not os.path.exists(USER_OVERRIDES):
        return ov
    with open(USER_OVERRIDES) as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                ov[(parts[0], parts[1])] = parts[2]
    return ov


def walk():
    user = user_overrides()
    rows = []
    for titan in sorted(os.listdir(SOUNDS)):
        tdir = os.path.join(SOUNDS, titan)
        if not os.path.isdir(tdir):
            continue
        for bucket in sorted(os.listdir(tdir)):
            bdir = os.path.join(tdir, bucket)
            if not os.path.isdir(bdir):
                continue
            for fn in sorted(os.listdir(bdir)):
                if not fn.lower().endswith(".wav"):
                    continue
                slug = fn[:-4]
                cur = bucket
                prop = user.get((titan, slug), OVERRIDES.get((titan, slug), cur))
                if (titan, slug) in TRANSCRIBED:
                    src, tr = TRANSCRIBED[(titan, slug)]
                else:
                    src, tr = "filename", transcript(slug)
                rows.append((titan, fn, slug, cur, prop, tr, src))
    return rows


def main():
    apply = "--apply" in sys.argv
    if not os.path.isdir(SOUNDS):
        sys.exit(f"no sounds dir at {SOUNDS}")
    os.makedirs(DATA, exist_ok=True)
    rows = walk()

    with open(os.path.join(DATA, "manifest.tsv"), "w") as f:
        f.write("titan\tfile\tcurrent_bucket\tproposed_bucket\ttranscript\tsource\n")
        for t, fn, slug, cur, prop, tr, src in rows:
            f.write(f"{t}\t{fn}\t{cur}\t{prop}\t{tr}\t{src}\n")

    with open(os.path.join(DATA, "buckets.tsv"), "w") as f:
        f.write("# titan\tslug\tbucket  — authoritative bucket map (consumed by `titancall normalize`)\n")
        for t, fn, slug, cur, prop, tr, src in rows:
            f.write(f"{t}\t{slug}\t{prop}\n")

    moves = [(t, fn, cur, prop) for t, fn, slug, cur, prop, tr, src in rows if cur != prop]
    nuser = len(user_overrides())
    print(f"{len(rows)} wavs, {len(moves)} reclassified"
          + (f" ({nuser} ui override rows)" if nuser else ""))
    for t, fn, cur, prop in moves:
        print(f"  {t}: {cur} -> {prop}  {fn}")

    if apply:
        moved = 0
        for t, fn, cur, prop in moves:
            src = os.path.join(SOUNDS, t, cur, fn)
            dstdir = os.path.join(SOUNDS, t, prop)
            os.makedirs(dstdir, exist_ok=True)
            dst = os.path.join(dstdir, fn)
            base, ext = os.path.splitext(fn)
            n = 1
            while os.path.exists(dst):
                dst = os.path.join(dstdir, f"{base}-{n}{ext}")
                n += 1
            os.rename(src, dst)
            moved += 1
        print(f"applied: moved {moved} files")
    else:
        print("dry run — pass --apply to move files")


if __name__ == "__main__":
    main()
