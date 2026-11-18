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

Bulk hand-sorting workflow:
  python3 scripts/build_manifest.py --review          # -> data/review.csv (+ a gap report)
  # edit the new_bucket column in a spreadsheet or editor
  python3 scripts/build_manifest.py --import-review   # folds edits into overrides.tsv, moves wavs
Also reachable as `titancall review` / `titancall review apply`.

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
  mount    a FRIENDLY second pilot arrives on our hull -> a subagent starts. Note the three-way
           split: a *hostile* boarder is a threat and belongs in `warn`, and an unqualified
           "pilot onboard, restoring manual control" is the pilot themselves and belongs in `enter`.
  dismount that friendly pilot detaches / is clear of the titan -> a subagent finishes
  misc   genuine leftovers: SFX, loadout/upgrade notifications, ally chatter, flavor
"""
import os, sys, subprocess

HOME = os.environ.get("TITANCALL_HOME", os.path.expanduser("~/.local/share/titancall"))
SOUNDS = os.path.join(HOME, "sounds")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")

# (titan, slug) -> corrected bucket. Only files that MOVE.
OVERRIDES = {
    # --- subagent lifecycle: friendly boarder = mount/dismount (see bucket semantics above).
    # Pulled out of enter/exit, where they were diluting "the pilot returns" / "session over".
    # Only jarvis and legion voice these at all; every other titan degrades via BUCKET_FALLBACK.
    ("jarvis", "friendly-pilot-on-board"): "mount",
    ("jarvis", "friendly-pilot-on-your-titan"): "mount",
    ("jarvis", "friendly-pilot-riding-on-board"): "mount",
    ("jarvis", "i-am-detectig-a-friendly-pilot-onboard"): "mount",
    ("legion", "friendly-pilot-on-extiorer"): "mount",
    ("jarvis", "friendly-pilot-has-detached-from-your-titan"): "dismount",
    ("jarvis", "friendly-pilot-has-left-your-titan"): "dismount",
    ("jarvis", "friendly-pilot-is-clear-of-your-titan"): "dismount",
    ("jarvis", "friendly-pilot-is-now-clear-of-your-titan"): "dismount",
    ("legion", "friendly-pilot-has-left-the-hull"): "dismount",
    # NOT moved, deliberately: legion/pilot-onboard{,-restoring-manual-controls} and
    # scorch/pilot-onboard-restoring-manual-control are the pilot boarding their OWN titan -> enter.

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


def user_dests():
    """Optional 4th column of overrides.tsv -> {(titan, slug): dest_titan}: relocate the wav to ANOTHER
    voice (its bucket is the 3rd column). Kept beside user_overrides() rather than inside it so the
    existing (titan, slug) -> bucket consumers don't change shape."""
    dests = {}
    if not os.path.exists(USER_OVERRIDES):
        return dests
    with open(USER_OVERRIDES) as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 4 and parts[3].strip():
                dests[(parts[0], parts[1])] = parts[3].strip()
    return dests


OVERRIDES_HEADER = ("# titan\tslug\tbucket\t[dest_titan] — written by `titancall ui` / `--import-review`; merged OVER the\n"
                    "# curated OVERRIDES dict in build_manifest.py, so these always win. dest_titan relocates the wav\n"
                    "# to another voice (the ui's `v` key); that row is dropped once applied.\n"
                    "# Hand-edit freely, then run `python3 scripts/build_manifest.py --apply`.\n")


def write_user_overrides(ov, dests, header):
    """Atomic temp+rename, sorted. Always carries the dest column through — `--import-review` used to
    rewrite this file from the 3-column view alone, which would silently drop every voice move."""
    tmp = USER_OVERRIDES + ".tmp"
    with open(tmp, "w") as f:
        f.write(header)
        for (titan, slug), bucket in sorted(ov.items()):
            dest = dests.get((titan, slug))
            f.write(f"{titan}\t{slug}\t{bucket}" + (f"\t{dest}" if dest else "") + "\n")
    os.replace(tmp, USER_OVERRIDES)


def voice_moves(rows):
    """[(titan, fn, cur_bucket, dest_titan, dest_bucket)] for rows whose override names another voice."""
    dests = user_dests()
    return [(t, fn, cur, dests[(t, slug)], prop)
            for t, fn, slug, cur, prop, tr, src in rows
            if dests.get((t, slug), t) != t]


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


REVIEW_CSV = os.path.join(DATA, "review.csv")
BUCKETS = ["eject", "core", "down", "damage", "warn", "enter",
           "guard", "follow", "attack", "exit", "mount", "dismount", "misc"]


def pending_edits():
    """Rows in an existing review.csv where new_bucket differs from bucket — unapplied hand-sorting."""
    import csv
    if not os.path.exists(REVIEW_CSV):
        return 0
    try:
        with open(REVIEW_CSV, newline="") as f:
            return sum(1 for r in csv.DictReader(f)
                       if (r.get("new_bucket") or "").strip() != (r.get("bucket") or "").strip())
    except (OSError, ValueError):
        return 0


def export_review(rows, force=False):
    """Write data/review.csv — one row per wav, `new_bucket` is the column you edit."""
    import csv
    check_unique_slugs(rows)
    n = pending_edits()
    if n and not force:
        sys.exit(f"{REVIEW_CSV} has {n} unapplied edit(s) — regenerating would discard them.\n"
                 f"  apply them:   python3 scripts/build_manifest.py --import-review\n"
                 f"  or discard:   python3 scripts/build_manifest.py --review --force")
    with open(REVIEW_CSV, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")     # LF: this file is tracked in git
        w.writerow(["titan", "transcript", "bucket", "new_bucket", "file"])
        for t, fn, slug, cur, prop, tr, src in rows:
            w.writerow([t, tr, prop, prop, fn])
    counts = {}
    for t, fn, slug, cur, prop, tr, src in rows:
        counts.setdefault(t, {}).setdefault(prop, 0)
        counts[t][prop] += 1
    print(f"wrote {REVIEW_CSV}  ({len(rows)} rows)")
    print(f"edit the new_bucket column, then: python3 scripts/build_manifest.py --import-review")
    print(f"valid buckets: {' '.join(BUCKETS)}\n")
    print("gaps — buckets with no clips for that voice (these degrade down BUCKET_FALLBACK):")
    for t in sorted(counts):
        missing = [b for b in BUCKETS if b != "misc" and not counts[t].get(b)]
        print(f"  {t:<10} {' '.join(missing) if missing else '(complete)'}")


def check_unique_slugs(rows):
    """Refuse to run while a titan has the same filename in two buckets.

    Overrides are keyed (titan, slug) — one bucket per slug, by construction. A duplicate
    makes `titan/foo.wav` ambiguous: --import-review can't tell the two rows apart, and an
    override for the slug moves BOTH copies. Portal shipped 15 such twins and an import
    shuffled them, which is what taught us to check.
    """
    seen = {}
    for t, fn, slug, cur, prop, tr, src in rows:
        seen.setdefault((t, fn), []).append(cur)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    if dupes:
        lines = "\n".join(f"  {t}/{fn}  in: {', '.join(sorted(b))}" for (t, fn), b in sorted(dupes.items()))
        sys.exit(f"{len(dupes)} duplicate filename(s) across buckets — refusing to run:\n{lines}\n"
                 "Delete the redundant copies (they are usually byte-identical) and retry.")


def import_review(rows):
    """Read edited data/review.csv, fold changes into data/overrides.tsv. Returns True if anything changed."""
    import csv
    if not os.path.exists(REVIEW_CSV):
        sys.exit(f"no {REVIEW_CSV} — run --review first")
    check_unique_slugs(rows)
    by_file = {(t, fn): prop for t, fn, slug, cur, prop, tr, src in rows}
    ov, changed, bad = user_overrides(), [], []
    with open(REVIEW_CSV, newline="") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            titan, fn = (r.get("titan") or "").strip(), (r.get("file") or "").strip()
            new = (r.get("new_bucket") or "").strip().lower()
            if not titan or not fn:
                continue
            if new not in BUCKETS:
                bad.append(f"  line {i}: {titan}/{fn} -> '{new}'")
                continue
            if (titan, fn) not in by_file:
                bad.append(f"  line {i}: no such wav {titan}/{fn}")
                continue
            if new != by_file[(titan, fn)]:
                slug = fn[:-4] if fn.lower().endswith(".wav") else fn
                ov[(titan, slug)] = new
                changed.append((titan, by_file[(titan, fn)], new, fn))
    if bad:
        sys.exit("review.csv has %d bad row(s) — nothing applied:\n%s\nvalid buckets: %s"
                 % (len(bad), "\n".join(bad), " ".join(BUCKETS)))
    if not changed:
        print("review.csv matches the library — nothing to change")
        return False
    write_user_overrides(ov, user_dests(), OVERRIDES_HEADER)
    print(f"{len(changed)} reclassification(s) from review.csv:")
    for titan, old, new, fn in changed:
        print(f"  {titan}: {old} -> {new}  {fn}")
    return True


def apply_voice_moves(vmoves):
    """Relocate wavs to another voice. Validates every row before touching a file, like --import-review:
    one bad destination aborts the whole batch. A name clash in the destination gets -1/-2 like bucket moves."""
    bad = []
    for t, fn, cur, dest, dbk in vmoves:
        if dest != os.path.basename(dest) or dest in ("", ".", ".."):
            bad.append(f"  {t}/{fn}: bad destination voice '{dest}'")
        elif dbk not in BUCKETS:
            bad.append(f"  {t}/{fn}: unknown bucket '{dbk}'")
        elif not os.path.isfile(os.path.join(SOUNDS, t, cur, fn)):
            bad.append(f"  {t}/{cur}/{fn}: no such wav")
    if bad:
        sys.exit("voice moves invalid — nothing moved:\n" + "\n".join(bad))
    moved = 0
    for t, fn, cur, dest, dbk in vmoves:
        dstdir = os.path.join(SOUNDS, dest, dbk)
        os.makedirs(dstdir, exist_ok=True)
        dst = os.path.join(dstdir, fn)
        base, ext = os.path.splitext(fn)
        n = 1
        while os.path.exists(dst):
            dst = os.path.join(dstdir, f"{base}-{n}{ext}")
            n += 1
        os.rename(os.path.join(SOUNDS, t, cur, fn), dst)
        moved += 1
    # A voice move is one-shot: the file now lives at its destination and buckets.tsv records it there.
    # Leaving the (old voice, slug) -> dest row behind would yank the clip back out the next time it is
    # moved home again, so drop executed rows.
    ov, dests = user_overrides(), user_dests()
    for t, fn, *_ in vmoves:
        k = (t, fn[:-4] if fn.lower().endswith(".wav") else fn)
        ov.pop(k, None)
        dests.pop(k, None)
    write_user_overrides(ov, dests, OVERRIDES_HEADER)
    return moved


def main(argv=None):
    """`argv` lets `titancall ui` call this in-process — a fresh interpreter per move was most of its lag."""
    argv = sys.argv[1:] if argv is None else argv
    apply = "--apply" in argv
    review = "--review" in argv
    imp = "--import-review" in argv
    if not os.path.isdir(SOUNDS):
        sys.exit(f"no sounds dir at {SOUNDS}")
    os.makedirs(DATA, exist_ok=True)
    rows = walk()

    if review:
        export_review(rows, force="--force" in argv)
        return
    if imp:
        if not import_review(rows):
            return
        rows = walk()        # re-read: overrides.tsv just changed
        apply = True         # importing your edits means you want them applied

    vmoves = voice_moves(rows)
    vdone = 0
    if vmoves and apply:
        vdone = apply_voice_moves(vmoves)
        rows = walk()        # files now live under their new voice; manifest/buckets must reflect that
        vmoves = []
    vkeys = {(t, fn) for t, fn, *_ in vmoves}      # dry run only: report these as voice moves, not bucket moves

    with open(os.path.join(DATA, "manifest.tsv"), "w") as f:
        f.write("titan\tfile\tcurrent_bucket\tproposed_bucket\ttranscript\tsource\n")
        for t, fn, slug, cur, prop, tr, src in rows:
            f.write(f"{t}\t{fn}\t{cur}\t{prop}\t{tr}\t{src}\n")

    with open(os.path.join(DATA, "buckets.tsv"), "w") as f:
        f.write("# titan\tslug\tbucket  — authoritative bucket map (consumed by `titancall normalize`)\n")
        for t, fn, slug, cur, prop, tr, src in rows:
            f.write(f"{t}\t{slug}\t{prop}\n")

    moves = [(t, fn, cur, prop) for t, fn, slug, cur, prop, tr, src in rows
             if cur != prop and (t, fn) not in vkeys]
    nuser = len(user_overrides())
    print(f"{len(rows)} wavs, {len(moves)} reclassified"
          + (f", {len(vmoves)} to another voice" if vmoves else "")
          + (f" ({nuser} ui override rows)" if nuser else ""))
    for t, fn, cur, prop in moves:
        print(f"  {t}: {cur} -> {prop}  {fn}")
    for t, fn, cur, dest, dbk in vmoves:
        print(f"  {t}/{cur} -> {dest}/{dbk}  {fn}")
    if vdone:
        print(f"applied: moved {vdone} files to another voice")

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
        print(f"applied: moved {moved + vdone} files")     # total — the ui shows this last line as its status
        if imp:
            export_review(walk(), force=True)   # edits are applied now; safe to regenerate
    else:
        print("dry run — pass --apply to move files")


if __name__ == "__main__":
    main()
