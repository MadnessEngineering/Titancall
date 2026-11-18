#!/usr/bin/env python3
"""titancall_ui.py — curses console for wiring the Titan voice library.

Launched by `titancall ui`. This is the ONLY python3 path in titancall's runtime; playing
sounds stays pure bash, so a machine without python3 still gets notifications.

The four layers it manages (bash CLI stays authoritative for every write):

    wav   -> bucket    data/overrides.tsv  +  build_manifest.py --apply  (actually moves the wav)
    wav   -> voice     same file, optional 4th column (dest voice); `v` key — relocates across titans
    group -> buckets   `titancall group set <name> <b1,b2,...>`          (config group.*)
    event -> target    `titancall alias <event> <bucket|group>`          (config alias.*)
    hook  -> event     READ-ONLY (install-hooks.sh + ~/.claude/settings.json)

Hook rows are deliberately read-only: remapping a Claude Code hook means editing your
settings.json, so instead you retarget the event it fires (the alias layer), which is
titancall's own config. Run ./install-hooks.sh to add/remove hooks themselves.
"""

import curses
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TC = os.path.join(REPO, "bin", "titancall")
DATA = os.path.join(REPO, "data")
OVERRIDES_TSV = os.path.join(DATA, "overrides.tsv")
BUILD_MANIFEST = os.path.join(REPO, "scripts", "build_manifest.py")
INSTALL_HOOKS = os.path.join(REPO, "install-hooks.sh")

HOME = os.environ.get("TITANCALL_HOME", os.path.expanduser("~/.local/share/titancall"))
SOUNDS = os.path.join(HOME, "sounds")
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "titancall")
CONFIG = os.path.join(CONFIG_DIR, "config")
SETTINGS = os.path.expanduser("~/.claude/settings.json")

BROWSE, EVENTS, GROUPS, HOOKS = range(4)
SCREENS = ["browse", "events", "groups", "hooks"]
ALL_BUCKETS = "* all"          # synthetic bucket row: every wav of the titan, bucket-prefixed


# ---------------------------------------------------------------- shell plumbing

def run(args):
    """Run a command, return (rc, stdout+stderr). Blocking — only on user actions."""
    try:
        p = subprocess.run(args, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()
    except OSError as e:
        return 1, str(e)


def tc(*args):
    return run([TC] + list(args))


def apply_manifest():
    """`build_manifest.py --apply`, in-process. Same code path as the CLI, minus a fresh interpreter per
    move — on a loaded box that spawn was ~2s of the ~10s a move took. Returns (rc, output)."""
    import contextlib
    import io
    sys.path.insert(0, os.path.dirname(BUILD_MANIFEST))
    try:
        import build_manifest
    finally:
        sys.path.pop(0)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            build_manifest.main(["--apply"])
        return 0, buf.getvalue().strip()
    except SystemExit as e:
        return (e.code if isinstance(e.code, int) else 1), (buf.getvalue() + str(e.code or "")).strip()
    except Exception as e:      # a bad override row must not kill the console mid-sort
        return 1, (buf.getvalue() + "%s: %s" % (type(e).__name__, e)).strip()


def play(path):
    """Fire-and-forget preview through the CLI, so device switching + volume are honored."""
    try:
        subprocess.Popen([TC, "playfile", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# ---------------------------------------------------------------- config + library

def read_config():
    """Flat key=value config -> dict. Comments/blank lines dropped (we never rewrite it here)."""
    cfg = {}
    try:
        with open(CONFIG) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    except OSError:
        pass
    return cfg


def canonical_buckets():
    rc, out = tc("buckets")
    return [b for b in out.splitlines() if b] if rc == 0 else ["misc"]


def scan_library():
    """{titan: {bucket: [filenames]}} — the on-disk truth."""
    lib = {}
    if not os.path.isdir(SOUNDS):
        return lib
    for titan in sorted(os.listdir(SOUNDS)):
        tdir = os.path.join(SOUNDS, titan)
        if not os.path.isdir(tdir):
            continue
        buckets = {}
        for bucket in sorted(os.listdir(tdir)):
            bdir = os.path.join(tdir, bucket)
            if not os.path.isdir(bdir):
                continue
            buckets[bucket] = sorted(fn for fn in os.listdir(bdir) if fn.lower().endswith(".wav"))
        lib[titan] = buckets
    return lib


def read_overrides():
    """data/overrides.tsv -> {(titan, slug): bucket}. UI-written, merged over the curated dict."""
    ov = {}
    try:
        with open(OVERRIDES_TSV) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    ov[(parts[0], parts[1])] = parts[2]
    except OSError:
        pass
    return ov


def read_dests():
    """Optional 4th column of overrides.tsv -> {(titan, slug): dest_titan} (a pending move to another voice)."""
    dests = {}
    try:
        with open(OVERRIDES_TSV) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 4 and parts[3].strip():
                    dests[(parts[0], parts[1])] = parts[3].strip()
    except OSError:
        pass
    return dests


def write_overrides(ov, dests=None):
    """Atomic temp+rename, sorted — this file is tracked in git, keep the diffs readable.
    `dests` defaults to whatever the file already holds, so a plain bucket move never drops a pending voice move."""
    if dests is None:
        dests = read_dests()
    os.makedirs(DATA, exist_ok=True)
    tmp = OVERRIDES_TSV + ".tmp"
    with open(tmp, "w") as f:
        f.write("# titan\tslug\tbucket\t[dest_titan] — written by `titancall ui` / `--import-review`; merged OVER the\n"
                "# curated OVERRIDES dict in build_manifest.py, so these always win. dest_titan relocates the wav\n"
                "# to another voice (the ui's `v` key); that row is dropped once applied.\n"
                "# Hand-edit freely, then run `python3 scripts/build_manifest.py --apply`.\n")
        for (titan, slug), bucket in sorted(ov.items()):
            dest = dests.get((titan, slug))
            f.write("%s\t%s\t%s%s\n" % (titan, slug, bucket, ("\t" + dest) if dest else ""))
    os.replace(tmp, OVERRIDES_TSV)


# ---------------------------------------------------------------- hook layer (read-only)

def recommended_hooks():
    """Claude event -> titancall event, parsed out of install-hooks.sh's EVENTS map."""
    out = {}
    try:
        with open(INSTALL_HOOKS) as f:
            body = f.read()
        block = re.search(r"EVENTS\s*=\s*\{(.*?)\}", body, re.S)
        if block:
            for ev, te in re.findall(r'"(\w+)":\s*"(\w+)"', block.group(1)):
                out[ev] = te
    except OSError:
        pass
    return out


def installed_hooks():
    """Claude event -> titancall event actually wired in ~/.claude/settings.json."""
    out = {}
    try:
        with open(SETTINGS) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return out
    for event, groups in (d.get("hooks") or {}).items():
        for g in groups if isinstance(groups, list) else []:
            for hk in g.get("hooks", []) if isinstance(g, dict) else []:
                cmd = hk.get("command", "") if isinstance(hk, dict) else ""
                if "titancall" not in cmd:
                    continue
                words = [w for w in cmd.replace("&", " ").split() if w]
                for i, w in enumerate(words):
                    if w.endswith("titancall") and i + 1 < len(words):
                        out[event] = words[i + 1]
                        break
                else:
                    out.setdefault(event, "?")
    return out


# ---------------------------------------------------------------- the app

class UI:
    def __init__(self, stdscr):
        self.s = stdscr
        self.screen = BROWSE
        self.msg = ""      # transient: set by an action, shown until the next keypress
        self.ctx = "wire soundbytes -> buckets -> groups -> events.  ? for keys"
        self.reload()

        self.pane = 0                      # 0 titans, 1 buckets, 2 files
        self.sel = [0, 0, 0]               # per-pane cursor
        if self.active in self.titans:     # open on the voice this project actually uses
            self.sel[0] = self.titans.index(self.active)
        self.off = [0, 0, 0]               # per-pane scroll offset
        self.marks = set()                 # (titan, bucket, filename) queued for a batch move
        self.filter = ""
        self.row = {EVENTS: 0, GROUPS: 0, HOOKS: 0}
        self.roff = {EVENTS: 0, GROUPS: 0, HOOKS: 0}

    # ---- state

    def reload(self):
        self.lib = scan_library()
        self.cfg = read_config()
        self.buckets_all = canonical_buckets()
        self.titans = sorted(self.lib)
        # the titan this project actually speaks with — what events/groups/hooks counts are about
        rc, out = tc("whoami")
        m = re.search(r"titan:\s+(\S+)\s+\(via (\w+)\)", out) if rc == 0 else None
        self.active = m.group(1) if m else (self.titans[0] if self.titans else "")
        self.who = "%s (via %s)" % (self.active, m.group(2)) if m else self.active or "?"

    def rescan(self):
        """After a wav move: only the library changed. reload() would also re-run `titancall whoami`
        and `titancall buckets` — two bash spawns for data a move can't touch."""
        cur = self.titan()
        self.lib = scan_library()
        self.titans = sorted(self.lib)
        if cur in self.titans:
            self.sel[0] = self.titans.index(cur)

    def aliases(self):
        return sorted((k[len("alias."):], v) for k, v in self.cfg.items() if k.startswith("alias."))

    def groups(self):
        return sorted((k[len("group."):], v) for k, v in self.cfg.items() if k.startswith("group."))

    def group_map(self):
        return {n: [b for b in v.split(",") if b] for n, v in self.groups()}

    def titan(self):
        return self.titans[self.sel[0]] if self.titans else ""

    def bucket_rows(self):
        """Buckets for the browse titan: on-disk first, then canonical-but-empty, plus '* all'."""
        have = self.lib.get(self.titan(), {})
        rows = [ALL_BUCKETS] + sorted(have)
        rows += [b for b in self.buckets_all if b not in have]
        return rows

    def bucket(self):
        rows = self.bucket_rows()
        return rows[self.sel[1]] if rows else ""

    def file_rows(self):
        """[(bucket, filename)] for the current selection, filtered by self.filter."""
        have = self.lib.get(self.titan(), {})
        b = self.bucket()
        if b == ALL_BUCKETS:
            rows = [(bk, fn) for bk in sorted(have) for fn in have[bk]]
        else:
            rows = [(b, fn) for fn in have.get(b, [])]
        if self.filter:
            q = self.filter.lower()
            # match the transcript (slug), not the filename — every name ends in ".wav"
            rows = [(bk, fn) for bk, fn in rows
                    if q in fn[:-4].lower().replace("-", " ") or q in bk.lower()]
        return rows

    def count(self, titan, target):
        """wavs available for titan behind a bucket-or-group target (what an event would draw from)."""
        have = self.lib.get(titan, {})
        members = self.group_map().get(target, [target])
        return sum(len(have.get(m, [])) for m in members)

    # ---- drawing

    def put(self, y, x, text, attr=0):
        h, w = self.s.getmaxyx()
        if "\n" in text:            # CLI output is multi-line; footers are one line
            text = " | ".join(l.strip() for l in text.splitlines() if l.strip())
        if 0 <= y < h and x < w:
            try:
                self.s.addnstr(y, x, text, max(0, w - x - 1), attr)
            except curses.error:
                pass

    def draw(self):
        self.s.erase()
        h, w = self.s.getmaxyx()
        if h < 12 or w < 60:
            self.put(0, 0, "terminal too small (need 60x12)")
            self.s.refresh()
            return

        muted = self.cfg.get("enabled", "1") == "0"
        tabs = "  ".join("%d %s" % (i + 1, n) for i, n in enumerate(SCREENS))
        self.put(0, 0, " titancall console ", curses.A_REVERSE | curses.A_BOLD)
        self.put(0, 20, tabs)
        state = "MUTED" if muted else "live"
        novoice = self.active not in self.lib
        right = "%s%s | vol %s | %s" % (self.who, " NO VOICE DIR" if novoice else "",
                                        self.cfg.get("volume", "0.7"), state)
        self.put(0, max(20, w - len(right) - 2), right,
                 self.c(3) if (muted or novoice) else self.c(2))
        self.put(1, 0, "-" * (w - 1), curses.A_DIM)

        body_top, body_bot = 2, h - 3
        if self.screen == BROWSE:
            self.draw_browse(body_top, body_bot, w)
        elif self.screen == EVENTS:
            self.draw_events(body_top, body_bot, w)
        elif self.screen == GROUPS:
            self.draw_groups(body_top, body_bot, w)
        else:
            self.draw_hooks(body_top, body_bot, w)

        self.put(h - 2, 0, (self.msg or self.ctx)[:w - 2],
                 curses.A_BOLD if self.msg else curses.A_DIM)
        self.put(h - 1, 0, self.keyline()[:w - 2], curses.A_REVERSE)
        self.s.refresh()

    def c(self, pair, extra=0):
        return (curses.color_pair(pair) if curses.has_colors() else 0) | extra

    def keyline(self):
        if self.screen == BROWSE:
            base = " tab pane  enter/p play  space mark  m move  v voice  x clear  / filter  r reload  1-4 screens  q quit "
            return base if not self.marks else " %d marked | m move them  x clear  space unmark " % len(self.marks)
        if self.screen == EVENTS:
            return " enter retarget  n new event  d delete  p test event  1-4 screens  q quit "
        if self.screen == GROUPS:
            return " enter edit members  n new group  d delete  p preview  1-4 screens  q quit "
        return " read-only: hooks live in settings.json | enter retarget the event  i install cmd  q quit "

    def scroll(self, sels, offs, key, total, view):
        """Clamp cursor `sels[key]` and slide `offs[key]` so it stays visible. Returns the offset."""
        sel = max(0, min(sels[key], max(0, total - 1)))
        off = min(offs[key], sel)
        if sel >= off + view:
            off = sel - view + 1
        off = max(0, min(off, max(0, total - view)))
        sels[key], offs[key] = sel, off
        return off

    def draw_browse(self, top, bot, w):
        view = bot - top
        tw, bw = 13, 15
        fx = tw + bw + 2
        have = self.lib.get(self.titan(), {})
        gmap = self.group_map()

        self.put(top - 1 + 0, 0, "", 0)
        self.put(top, 0, "TITAN", curses.A_BOLD | curses.A_UNDERLINE)
        self.put(top, tw + 1, "BUCKET", curses.A_BOLD | curses.A_UNDERLINE)
        label = "%s/%s" % (self.titan(), self.bucket()) if self.titans else "(no library)"
        if self.filter:
            label += "   /%s" % self.filter
        self.put(top, fx, "WAV  [%s]" % label, curses.A_BOLD | curses.A_UNDERLINE)

        # titans
        toff = self.scroll(self.sel, self.off, 0, len(self.titans), view - 1)
        for i, t in enumerate(self.titans[toff:toff + view - 1]):
            n = sum(len(v) for v in self.lib[t].values())
            attr = curses.A_REVERSE if (toff + i == self.sel[0] and self.pane == 0) else 0
            if toff + i == self.sel[0] and self.pane != 0:
                attr = curses.A_BOLD
            self.put(top + 1 + i, 0, "%-9s %3d" % (t[:9], n), attr)

        # buckets
        brows = self.bucket_rows()
        boff = self.scroll(self.sel, self.off, 1, len(brows), view - 1)
        for i, b in enumerate(brows[boff:boff + view - 1]):
            if b == ALL_BUCKETS:
                n = sum(len(v) for v in have.values())
            else:
                n = len(have.get(b, []))
            attr = curses.A_REVERSE if (boff + i == self.sel[1] and self.pane == 1) else 0
            if boff + i == self.sel[1] and self.pane != 1:
                attr = curses.A_BOLD
            if not n and b != ALL_BUCKETS:
                attr |= curses.A_DIM
            self.put(top + 1 + i, tw + 1, "%-9s %3d" % (b[:9], n), attr)

        # files
        frows = self.file_rows()
        foff = self.scroll(self.sel, self.off, 2, len(frows), view - 1)
        for i, (bk, fn) in enumerate(frows[foff:foff + view - 1]):
            marked = (self.titan(), bk, fn) in self.marks
            cur = foff + i == self.sel[2]
            attr = curses.A_REVERSE if (cur and self.pane == 2) else (curses.A_BOLD if cur else 0)
            slug = fn[:-4] if fn.lower().endswith(".wav") else fn
            prefix = "*" if marked else " "
            text = "%s %s" % (prefix, slug.replace("-", " "))
            if self.bucket() == ALL_BUCKETS:
                text = "%s [%-6s] %s" % (prefix, bk[:6], slug.replace("-", " "))
            self.put(top + 1 + i, fx, text, attr | (self.c(4) if marked else 0))
        if not frows:
            note = ("no wav matches /%s (esc clears)" % self.filter) if self.filter \
                else "(empty bucket — mark wavs elsewhere and press m to fill it)"
            self.put(top + 1, fx, note, curses.A_DIM)

        # which events point here
        if self.bucket() not in ("", ALL_BUCKETS):
            hits = [ev for ev, tgt in self.aliases()
                    if tgt == self.bucket() or self.bucket() in gmap.get(tgt, [])]
            if hits:
                self.ctx = "%s <- events: %s" % (self.bucket(), " ".join(hits))
            else:
                self.ctx = "%s <- no event points here (screen 2 to wire one)" % self.bucket()

    def draw_events(self, top, bot, w):
        rows = self.aliases()
        gmap = self.group_map()
        self.put(top, 0, "%-12s %-14s %-7s %-6s %s"
                 % ("EVENT", "TARGET", "KIND", "WAVS", "MEMBERS"),
                 curses.A_BOLD | curses.A_UNDERLINE)
        view = bot - top - 1
        off = self.scroll(self.row, self.roff, EVENTS, len(rows), view)
        for i, (ev, tgt) in enumerate(rows[off:off + view]):
            kind = "group" if tgt in gmap else ("bucket" if tgt in self.buckets_all else "?")
            n = self.count(self.active, tgt)
            members = ",".join(gmap.get(tgt, []))
            attr = curses.A_REVERSE if off + i == self.row[EVENTS] else 0
            if kind == "?":
                attr |= self.c(3)
            elif not n:
                attr |= curses.A_DIM
            self.put(top + 1 + i, 0, "%-12s %-14s %-7s %-6s %s" % (ev, tgt, kind, n, members), attr)
        if not rows:
            self.put(top + 1, 0, "(no aliases — n to add one)", curses.A_DIM)
        self.ctx = "WAVS = clips this project's titan (%s) can draw.  0 falls back to misc." % self.active

    def draw_groups(self, top, bot, w):
        rows = self.groups()
        aliases = self.aliases()
        self.put(top, 0, "%-14s %-34s %-6s %s" % ("GROUP", "BUCKETS", "WAVS", "USED BY"),
                 curses.A_BOLD | curses.A_UNDERLINE)
        view = bot - top - 1
        off = self.scroll(self.row, self.roff, GROUPS, len(rows), view)
        for i, (name, members) in enumerate(rows[off:off + view]):
            used = " ".join(ev for ev, tgt in aliases if tgt == name)
            n = self.count(self.active, name)
            attr = curses.A_REVERSE if off + i == self.row[GROUPS] else 0
            self.put(top + 1 + i, 0, "%-14s %-34s %-6s %s" % (name, members[:34], n, used), attr)
        if not rows:
            self.put(top + 1, 0, "(no groups yet — n to make one, e.g. combat = attack,down,warn)",
                     curses.A_DIM)
        self.ctx = "a group is a named bucket set; an event aimed at it draws from any member that has wavs"

    def hook_rows(self):
        """[(claude_hook, event, target, kind, wavs, wired)] — settings.json wins, install-hooks.sh fills in."""
        rec, inst = recommended_hooks(), installed_hooks()
        aliases = dict(self.aliases())
        gmap = self.group_map()
        rows = []
        for hook in sorted(set(rec) | set(inst)):
            ev = inst.get(hook, rec.get(hook, "?"))
            tgt = aliases.get(ev, ev)
            kind = "group" if tgt in gmap else "bucket"
            rows.append((hook, ev, tgt, kind, self.count(self.active, tgt), hook in inst))
        return rows

    def draw_hooks(self, top, bot, w):
        rows = self.hook_rows()
        self.put(top, 0, "%-20s %-10s %-14s %-7s %-6s %s"
                 % ("CLAUDE HOOK", "EVENT", "TARGET", "KIND", "WAVS", "WIRED"),
                 curses.A_BOLD | curses.A_UNDERLINE)
        view = bot - top - 1
        off = self.scroll(self.row, self.roff, HOOKS, len(rows), view)
        for i, (hook, ev, tgt, kind, n, wired) in enumerate(rows[off:off + view]):
            attr = curses.A_REVERSE if off + i == self.row[HOOKS] else 0
            mark = "yes" if wired else "no"
            self.put(top + 1 + i, 0, "%-20s %-10s %-14s %-7s %-6s %s"
                     % (hook, ev, tgt, kind, n, mark),
                     attr | (0 if wired else curses.A_DIM))
        self.ctx = "hook->event lives in settings.json (./install-hooks.sh). enter retargets the event instead."

    # ---- overlays

    def overlay(self, title, items, multi=False, preselect=None):
        """Modal list picker. Returns a str (single), list (multi), or None on cancel."""
        if not items:
            self.msg = "nothing to pick"
            return None
        chosen = set(preselect or [])
        sel, off = 0, 0
        h, w = self.s.getmaxyx()
        width = max(len(title) + 4, max(len(str(i)) for i in items) + 8, 34)
        width = min(width, w - 4)
        view = min(len(items), max(3, h - 10))
        win = curses.newwin(view + 4, width, max(1, (h - view - 4) // 2), max(1, (w - width) // 2))
        win.keypad(True)
        while True:
            win.erase()
            win.box()
            win.addnstr(0, 2, " %s " % title, width - 4, curses.A_BOLD)
            off = min(off, sel)
            if sel >= off + view:
                off = sel - view + 1
            for i, it in enumerate(items[off:off + view]):
                flag = "[x] " if it in chosen else ("[ ] " if multi else "    ")
                attr = curses.A_REVERSE if off + i == sel else 0
                win.addnstr(1 + i, 2, "%s%s" % (flag if multi else "", it), width - 4, attr)
            foot = " space toggle  enter ok  esc cancel " if multi else " enter pick  esc cancel "
            win.addnstr(view + 2, 2, foot, width - 4, curses.A_DIM)
            win.refresh()
            k = win.getch()
            if k in (27, ord("q")):
                return None
            if k in (curses.KEY_UP, ord("k")):
                sel = max(0, sel - 1)
            elif k in (curses.KEY_DOWN, ord("j")):
                sel = min(len(items) - 1, sel + 1)
            elif k == curses.KEY_HOME:
                sel = 0
            elif k == curses.KEY_END:
                sel = len(items) - 1
            elif multi and k == ord(" "):
                if items[sel] in chosen:
                    chosen.discard(items[sel])
                else:
                    chosen.add(items[sel])
            elif k in (curses.KEY_ENTER, 10, 13):
                return [i for i in items if i in chosen] if multi else items[sel]

    def prompt(self, label, initial=""):
        """One-line text input at the bottom. Returns str or None on cancel."""
        buf = list(initial)
        h, w = self.s.getmaxyx()
        curses.curs_set(1)
        try:
            while True:
                line = "%s%s" % (label, "".join(buf))
                self.put(h - 2, 0, line + " " * max(0, w - len(line) - 2), curses.A_BOLD)
                self.s.move(h - 2, min(len(line), w - 2))
                self.s.refresh()
                k = self.s.getch()
                if k == 27:
                    return None
                if k in (curses.KEY_ENTER, 10, 13):
                    return "".join(buf).strip()
                if k in (curses.KEY_BACKSPACE, 127, 8):
                    buf and buf.pop()
                elif 32 <= k < 127:
                    buf.append(chr(k))
        finally:
            curses.curs_set(0)

    def help(self):
        lines = [
            "browse   tab/left/right pane   up/down move   enter or p play",
            "         space mark wav   m move marked (or current) -> bucket   x clear marks",
            "         v move marked (or current) -> a VOICE (own voice listed first), then its bucket",
            "         / filter (esc clears)   r rescan library",
            "events   enter retarget event -> bucket|group   n new   d delete   p test through CLI",
            "groups   n new group   enter edit members   d delete   p preview a member",
            "hooks    read-only chain; enter jumps to that event's alias   i show install command",
            "",
            "moves write data/overrides.tsv then run build_manifest.py --apply (git-tracked, reviewable)",
            "everything else goes through `titancall alias` / `titancall group`",
        ]
        self.overlay("keys", lines)

    # ---- actions

    def cur_file(self):
        rows = self.file_rows()
        if not rows:
            return None
        bk, fn = rows[min(self.sel[2], len(rows) - 1)]
        return self.titan(), bk, fn

    def do_play(self):
        item = self.cur_file()
        if not item:
            self.msg = "no wav selected"
            return
        titan, bk, fn = item
        play(os.path.join(SOUNDS, titan, bk, fn))
        self.msg = "playing %s/%s/%s" % (titan, bk, fn)

    def do_mark(self):
        item = self.cur_file()
        if not item:
            return
        if item in self.marks:
            self.marks.discard(item)
        else:
            self.marks.add(item)
        self.sel[2] += 1

    def do_move(self):
        items = sorted(self.marks) if self.marks else ([self.cur_file()] if self.cur_file() else [])
        if not items:
            self.msg = "nothing to move"
            return
        dest = self.overlay("move %d wav(s) to bucket" % len(items), self.buckets_all)
        if not dest:
            return
        ov = read_overrides()
        for titan, bk, fn in items:
            ov[(titan, fn[:-4] if fn.lower().endswith(".wav") else fn)] = dest
        write_overrides(ov)
        rc, out = apply_manifest()
        self.marks.clear()
        self.rescan()
        tail = out.splitlines()[-1] if out else ""
        self.msg = ("moved %d -> %s (%s)" % (len(items), dest, tail)) if rc == 0 \
            else "build_manifest failed: %s" % tail

    def do_move_voice(self):
        """Marked (or current) wavs -> a voice, then a bucket there. Same override file as `m`; the
        4th column (dest voice) is what build_manifest.py --apply acts on. The clips' own voice is
        offered first, so `v` alone covers a plain rebucket too — no need to back out and press `m`."""
        items = sorted(self.marks) if self.marks else ([self.cur_file()] if self.cur_file() else [])
        if not items:
            self.msg = "nothing to move"
            return
        origins = sorted({t for t, _, _ in items})
        label = {("%s  (same voice)" % t if t in origins else t): t
                 for t in origins + [t for t in self.titans if t not in origins]}
        picked = self.overlay("move %d wav(s) to voice" % len(items), list(label))
        if not picked:
            return
        dest = label[picked]
        # offer the clips' own bucket first when they share one — most cross-voice moves keep the bucket
        shared = {bk for _, bk, _ in items}
        buckets = self.buckets_all
        if len(shared) == 1:
            buckets = sorted(buckets, key=lambda b: b not in shared)
        bucket = self.overlay("bucket in %s" % dest, buckets)
        if not bucket:
            return
        ov, dests = read_overrides(), read_dests()
        for titan, bk, fn in items:
            key = (titan, fn[:-4] if fn.lower().endswith(".wav") else fn)
            ov[key] = bucket
            if titan == dest:
                dests.pop(key, None)     # same voice: a plain rebucket, and it cancels any pending voice move
            else:
                dests[key] = dest
        write_overrides(ov, dests)
        rc, out = apply_manifest()
        self.marks.clear()
        self.rescan()
        tail = out.splitlines()[-1] if out else ""
        self.msg = ("moved %d -> %s/%s (%s)" % (len(items), dest, bucket, tail)) if rc == 0 \
            else "build_manifest failed: %s" % tail

    def targets(self):
        return self.buckets_all + [n for n, _ in self.groups()]

    def do_retarget(self, event):
        tgt = self.overlay("alias.%s ->" % event, self.targets())
        if not tgt:
            return
        rc, out = tc("alias", event, tgt)
        self.reload()
        self.msg = out if out else "alias: %s -> %s" % (event, tgt)

    def do_new_event(self):
        name = self.prompt("new event name: ")
        if not name:
            return
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            self.msg = "event names: letters/digits/-/_ only"
            return
        self.do_retarget(name)

    def do_delete_alias(self, event):
        if self.overlay("delete alias.%s ?" % event, ["no, keep it", "yes, delete"]) != "yes, delete":
            return
        rc, out = tc("config", "unset", "alias.%s" % event)
        self.reload()
        self.msg = out or "removed alias.%s" % event

    def do_group_members(self, name, existing=None):
        picked = self.overlay("buckets in group '%s'" % name, self.buckets_all,
                              multi=True, preselect=existing or [])
        if picked is None:
            return
        if not picked:
            self.msg = "a group needs at least one bucket"
            return
        rc, out = tc("group", "set", name, ",".join(picked))
        self.reload()
        self.msg = out

    def do_new_group(self):
        name = self.prompt("new group name: ")
        if not name:
            return
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            self.msg = "group names: letters/digits/-/_ only"
            return
        self.do_group_members(name)

    def do_delete_group(self, name):
        if self.overlay("delete group '%s' ?" % name, ["no, keep it", "yes, delete"]) != "yes, delete":
            return
        rc, out = tc("group", "rm", name)
        self.reload()
        self.msg = out

    # ---- input

    NAV = {curses.KEY_UP: -1, ord("k"): -1, curses.KEY_DOWN: 1, ord("j"): 1,
           curses.KEY_PPAGE: -10, curses.KEY_NPAGE: 10,
           curses.KEY_HOME: -10 ** 6, curses.KEY_END: 10 ** 6}

    def nav(self, k, store, key, total):
        """Move cursor store[key]. Returns True if the key was a navigation key."""
        if k not in self.NAV:
            return False
        store[key] = max(0, min(total - 1, store[key] + self.NAV[k]))
        return True

    def key_browse(self, k):
        panes = [len(self.titans), len(self.bucket_rows()), len(self.file_rows())]
        if self.nav(k, self.sel, self.pane, max(1, panes[self.pane])):
            if self.pane == 0:
                self.sel[1] = self.sel[2] = 0
            elif self.pane == 1:
                self.sel[2] = 0
            return
        if k in (9, curses.KEY_RIGHT, ord("l")):
            self.pane = min(2, self.pane + 1)
        elif k in (curses.KEY_BTAB, 353, curses.KEY_LEFT, ord("h")):
            self.pane = max(0, self.pane - 1)
        elif k in (curses.KEY_ENTER, 10, 13):
            if self.pane < 2:
                self.pane += 1
            else:
                self.do_play()
        elif k == ord("p"):
            self.do_play()
        elif k == ord(" "):
            self.do_mark()
        elif k == ord("m"):
            self.do_move()
        elif k == ord("v"):
            self.do_move_voice()
        elif k == ord("x"):
            self.marks.clear()
            self.msg = "marks cleared"
        elif k == ord("/"):
            f = self.prompt("filter: ", self.filter)
            self.filter = f or ""
            self.sel[2] = 0

    def key_events(self, k):
        rows = self.aliases()
        if self.nav(k, self.row, EVENTS, max(1, len(rows))):
            return
        cur = rows[self.row[EVENTS]][0] if rows else None
        if k in (curses.KEY_ENTER, 10, 13) and cur:
            self.do_retarget(cur)
        elif k == ord("n"):
            self.do_new_event()
        elif k == ord("d") and cur:
            self.do_delete_alias(cur)
        elif k == ord("p") and cur:
            rc, out = tc("test", cur)
            self.msg = out or ("fired %s (cooldown/mute apply)" % cur)

    def key_groups(self, k):
        rows = self.groups()
        if self.nav(k, self.row, GROUPS, max(1, len(rows))):
            return
        cur = rows[self.row[GROUPS]] if rows else None
        if k in (curses.KEY_ENTER, 10, 13) and cur:
            self.do_group_members(cur[0], [b for b in cur[1].split(",") if b])
        elif k == ord("n"):
            self.do_new_group()
        elif k == ord("d") and cur:
            self.do_delete_group(cur[0])
        elif k == ord("p") and cur:
            rc, out = tc("play", cur[0])
            self.msg = out or "played from group %s" % cur[0]

    def key_hooks(self, k):
        rows = self.hook_rows()
        if self.nav(k, self.row, HOOKS, max(1, len(rows))):
            return
        cur = rows[self.row[HOOKS]] if rows else None
        if k in (curses.KEY_ENTER, 10, 13) and cur:
            self.do_retarget(cur[1])
        elif k == ord("i") and cur:
            self.msg = "install/refresh all hooks: ./install-hooks.sh   (adds %s -> titancall %s)" % (cur[0], cur[1])

    def loop(self):
        while True:
            self.draw()
            k = self.s.getch()
            self.msg = ""                    # action messages live exactly one draw
            if k == curses.KEY_RESIZE:
                continue
            if k in (ord("q"), ord("Q")):
                return
            if k == 27:
                # ESC only backs out of things. It never quits: an unmapped escape sequence
                # (odd Home key, mouse report, bracketed paste) arrives here as a bare 27,
                # and killing the console on that would be a nasty surprise. Swallow the rest
                # of the sequence too, or its tail ("[1~") lands as real commands.
                self.s.nodelay(True)
                try:
                    while self.s.getch() != -1:
                        pass
                finally:
                    self.s.nodelay(False)
                if self.screen == BROWSE and self.filter:
                    self.filter = ""
                    self.msg = "filter cleared"
                else:
                    self.msg = "q quits (esc only clears a filter)"
                continue
            if k == ord("?"):
                self.help()
                continue
            if k in (ord("1"), ord("2"), ord("3"), ord("4")):
                self.screen = k - ord("1")
                continue
            if k == ord("r"):
                self.reload()
                self.msg = "rescanned library + config"
                continue
            if self.screen == BROWSE:
                self.key_browse(k)
            elif self.screen == EVENTS:
                self.key_events(k)
            elif self.screen == GROUPS:
                self.key_groups(k)
            else:
                self.key_hooks(k)


def main(stdscr):
    curses.curs_set(0)
    if hasattr(curses, "set_escdelay"):
        curses.set_escdelay(25)     # default 1000ms: every esc-cancel in an overlay sat for a full second
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
        curses.init_pair(4, curses.COLOR_MAGENTA, -1)
    stdscr.keypad(True)
    UI(stdscr).loop()


if __name__ == "__main__":
    if not os.path.isdir(SOUNDS):
        sys.exit("no voice library at %s — install sounds first" % SOUNDS)
    if not os.access(TC, os.X_OK):
        sys.exit("cannot execute %s" % TC)
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
