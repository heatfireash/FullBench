"""
Full Bench -- desktop GUI.

Tabs:
  Dashboard  record and splits, filterable by which deck you played
  Matches    every match, click one to see both decklists as seen
  Decks      your decks and matchup breakdown
  Activity   live status of the two watchers

Both decks are detected from the battle log -- nothing to type in.
"""

import json
import queue
import sqlite3
import sys
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

APP_NAME = "Full Bench"
try:
    from version import VERSION, CHANGELOG, DONATE_URL, DONATE_LABEL
except ImportError:
    VERSION, CHANGELOG, DONATE_URL, DONATE_LABEL = "0.0.0", [], "", ""
DB_PATH = Path.home() / "ptcgl_matches.db"

# Light theme. Blue and gold are kept for the header and for selection;
# everything else is white so the app doesn't drown in colour.
SURFACE = "#ffffff"       # window background
PANEL = "#f1f4fa"         # cards, fields, table rows
LINE = "#dbe2ee"          # borders and dividers
TEXT = "#12193a"          # body text: the deep blue, near-black
MUTED = "#5b6683"         # secondary text (passes on white and on panel)
HEADER = "#1a2d68"        # the blue bar across the top
HEADER_FG = "#f7f8fc"     # text on that bar
ACCENT = "#f5c518"        # gold -- selected tab, primary button
ACCENT_DK = "#d9ab0f"
WIN = "#14752f"           # dark enough to stay readable on white
LOSS = "#c5221f"
RED = LOSS                # warnings and problems
CONSOLE = "#f7f8fb"       # Activity log
CONSOLE_FG = "#3a445f"


def _asset(name):
    """Asset path that works from source and inside a PyInstaller exe."""
    base = Path(getattr(sys, "_MEIPASS", HERE))
    p = base / name
    return p if p.exists() else HERE / name


# ----------------------------------------------------------------- data

_migrated = False


def _ensure_migrated():
    """Upgrade an older database the first time the GUI touches it."""
    global _migrated
    if _migrated or not DB_PATH.exists():
        return
    _migrated = True
    try:
        import ptcgl_tracker
        c = sqlite3.connect(DB_PATH)
        ptcgl_tracker.migrate(c, verbose=False)
        c.close()
    except Exception:
        pass


def q(sql, args=()):
    if not DB_PATH.exists():
        return []
    _ensure_migrated()
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()


def _col(row, name):
    """Read a column that may not exist yet in an older database file."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None


def execute(sql, args=()):
    if not DB_PATH.exists():
        return 0
    _ensure_migrated()
    c = sqlite3.connect(DB_PATH)
    try:
        cur = c.execute(sql, args)
        c.commit()
        return cur.rowcount
    finally:
        c.close()


def rename_deck(old, new, which="all", match_id=None):
    """
    Rename a deck. deck_edited=1 marks it as set by hand so --reparse
    leaves it alone.
    """
    if which == "match" and match_id is not None:
        return execute("UPDATE matches SET deck_label=?, deck_edited=1 "
                       "WHERE id=?", (new, match_id))
    return execute("UPDATE matches SET deck_label=?, deck_edited=1 "
                   "WHERE deck_label IS ?", (new, old))


def rename_opponent_archetype(old, new):
    return execute("UPDATE matches SET opponent_archetype=? "
                   "WHERE opponent_archetype IS ?", (new, old))


def decks_used():
    rows = q(f"SELECT DISTINCT deck_label FROM matches "
             f"WHERE {NOT_EXCLUDED} AND deck_label IS NOT NULL "
             f"ORDER BY deck_label")
    return [r["deck_label"] for r in rows]


# Matches flagged as not-a-game are kept but never counted. COALESCE
# because older rows predate the column.
NOT_EXCLUDED = "COALESCE(excluded,'') = ''"


def match_rows(deck=None, version=None, include_excluded=False):
    """
    Matches, optionally narrowed to one deck and one list version.

    Excluded matches are left out of every statistic but still listed in
    the Matches tab, so an ignored game is visible rather than vanished.
    """
    where = "1=1" if include_excluded else NOT_EXCLUDED
    if deck and deck != "All decks":
        if version not in (None, "All versions"):
            v = int(str(version).lstrip("v"))
            return q(f"SELECT * FROM matches WHERE {where} AND "
                     f"deck_label=? AND deck_version=?", (deck, v))
        return q(f"SELECT * FROM matches WHERE {where} AND deck_label = ?",
                 (deck,))
    return q(f"SELECT * FROM matches WHERE {where}")


def versions_for(deck):
    if not deck or deck == "All decks":
        return []
    return [r["version"] for r in
            q("SELECT version FROM deck_versions WHERE deck_label=? "
              "ORDER BY version", (deck,))]


def stats(deck=None, version=None):
    """Aggregate stats, optionally restricted to a deck and list version."""
    rows = match_rows(deck, version)

    d = {"n": len(rows), "w": 0, "l": 0, "first": [0, 0], "second": [0, 0],
         "turns": [], "prizediff": [], "recent": [],
         "my_mull": [], "opp_mull": [], "my_mdraw": [], "opp_mdraw": []}
    for r in rows:
        if r["result"] == "win":
            d["w"] += 1
        elif r["result"] == "loss":
            d["l"] += 1
        if r["result"] in ("win", "loss"):
            k = "first" if r["went_first"] == 1 else (
                "second" if r["went_first"] == 0 else None)
            if k:
                d[k][0] += 1
                d[k][1] += (r["result"] == "win")
        if r["turns"]:
            d["turns"].append(r["turns"])
        if (r["player_prizes_taken"] is not None
                and r["opponent_prizes_taken"] is not None):
            d["prizediff"].append(
                r["player_prizes_taken"] - r["opponent_prizes_taken"])
        for key, col in (("my_mull", "player_mulligans"),
                         ("opp_mull", "opponent_mulligans"),
                         ("my_mdraw", "player_mulligan_draws"),
                         ("opp_mdraw", "opponent_mulligan_draws")):
            v = _col(r, col)
            if v is not None:
                d[key].append(v)
    d["recent"] = [r["result"] for r in rows[-12:]]
    return d


def pct(w, n):
    return f"{100.0*w/n:.1f}%" if n else "--"


def avg(xs):
    return sum(xs) / len(xs) if xs else None


# ----------------------------------------------------------------- app

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} {VERSION}")
        self.geometry("1120x730")
        self.minsize(960, 620)
        self.configure(bg=SURFACE)

        try:
            ico = _asset("icon.ico")
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

        self.log_q = queue.Queue()
        self.stop_evt = None
        self.logo_img = None
        self.missed = 0
        self._detail_id = None
        self._game_up = False

        import settings as settings_mod
        self.settings_mod = settings_mod
        self.cfg = settings_mod.load()

        try:
            # Only the shield over Continue. The full-width banner used to
            # sit across the top of the screen, which is exactly where the
            # battle log's copy icon is -- it was covering the button the
            # capture needs to click.
            from overlay import ClickShield
            self.shield = ClickShield(self)
        except Exception:
            self.shield = None

        self._style()
        self._build()
        self.refresh()
        self.after(300, self._drain_log)
        self._start_game_watch()
        if self.cfg.get("start_minimised"):
            self.iconify()
        self._update_info = None       # set when a newer build exists
        self._update_prompted = None   # version already shown this run
        self.after(4000, self._check_for_update)

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=SURFACE, foreground=TEXT,
                    fieldbackground="#ffffff", bordercolor=LINE)
        s.configure("TNotebook", background=SURFACE, borderwidth=0)
        s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED,
                    padding=(18, 9), borderwidth=0)
        s.configure("Treeview", borderwidth=1, relief="flat")
        # dark text on the gold tab -- white on yellow is unreadable
        s.map("TNotebook.Tab", background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])
        s.configure("Treeview", background="#ffffff",
                    fieldbackground="#ffffff", foreground=TEXT,
                    rowheight=27, borderwidth=0)
        s.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                    borderwidth=0, relief="flat")
        # gold selection, dark text -- the accent doing real work
        s.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", TEXT)])
        s.configure("TButton", background=PANEL, foreground=TEXT,
                    borderwidth=0, padding=(14, 7), focuscolor=PANEL)
        s.map("TButton", background=[("active", LINE)])
        # primary action in gold, with dark text for contrast
        s.configure("Go.TButton", background=ACCENT, foreground=SURFACE)
        s.map("Go.TButton", background=[("active", ACCENT_DK)])
        s.configure("TCombobox", fieldbackground="#ffffff",
                    background=PANEL, foreground=TEXT, arrowcolor=TEXT,
                    borderwidth=0, padding=(8, 6))
        # the deck picker drives the whole dashboard, so it gets a size
        # that reads at a glance rather than the default control text
        s.configure("Big.TCombobox", fieldbackground="#ffffff",
                    background=PANEL, foreground=TEXT, arrowcolor=TEXT,
                    borderwidth=0, padding=(10, 8))
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 12))
        self.option_add("*TCombobox*Listbox.background", "#ffffff")
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT)

    def _build(self):
        # blue header bar, full width, with the gold rule beneath it
        bar = tk.Frame(self, bg=HEADER)
        bar.pack(fill="x")
        inner_bar = tk.Frame(bar, bg=HEADER)
        inner_bar.pack(fill="x", padx=16, pady=10)
        bar = inner_bar

        logo = _asset("logo_small.png")
        if logo.exists():
            try:
                self.logo_img = tk.PhotoImage(file=str(logo))
                tk.Label(bar, image=self.logo_img, bg=HEADER,
                         fg=HEADER_FG).pack(side="left")
            except Exception:
                pass

        title = tk.Frame(bar, bg=HEADER)
        title.pack(side="left", padx=10)
        tk.Label(title, text=APP_NAME, bg=HEADER, fg=HEADER_FG,
                 font=("Segoe UI Semibold", 16)).pack(anchor="w")
        self.status = tk.Label(title, text="\u25cf not tracking", bg=HEADER,
                               fg="#a9b6da", font=("Segoe UI", 9))
        self.status.pack(anchor="w")

        # Right side of the header: account state, and the tracking
        # controls only when they are actually useful. Tracking starts and
        # stops with the game, so a Stop button is clutter; it stays in
        # developer mode for when something needs poking.
        self.btn_refresh = ttk.Button(bar, text="Refresh",
                                      command=self.refresh)
        self.btn = ttk.Button(bar, text="Start tracking", style="Go.TButton",
                              command=self.toggle)

        self.acct = tk.Frame(bar, bg=HEADER)
        self.acct.pack(side="right")
        self.acct_label = tk.Label(self.acct, text="", bg=HEADER,
                                   fg="#a9b6da", font=("Segoe UI", 10))
        self.btn_account = ttk.Button(self.acct, text="Sign in",
                                      command=self._cloud_browser_login)
        self.btn_cloud_sync = ttk.Button(self.acct, text="Sync",
                                         command=self._cloud_sync)
        # Shown only when a newer build is out; stays until updated, so
        # closing the popup with "Later" doesn't lose the way back to it.
        self.btn_update = ttk.Button(self.acct, text="Update available",
                                     style="Go.TButton",
                                     command=lambda: self._show_update(
                                         force=True))

        tk.Frame(self, bg=ACCENT, height=4).pack(fill="x")

        nb = ttk.Notebook(self)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=16, pady=(10, 16))
        self.tab_dash = tk.Frame(nb, bg=SURFACE)
        self.tab_matches = tk.Frame(nb, bg=SURFACE)
        self.tab_act = tk.Frame(nb, bg=SURFACE)
        self.tab_set = tk.Frame(nb, bg=SURFACE)
        self.tab_about = tk.Frame(nb, bg=SURFACE)
        for t, n in ((self.tab_dash, "Dashboard"), (self.tab_matches, "Matches"),
                     (self.tab_act, "Activity"),
                     (self.tab_set, "Settings"), (self.tab_about, "About")):
            nb.add(t, text=n)

        self._build_dash()
        self._build_matches()
        self._build_activity()
        self._build_settings()
        self._build_about()
        self._apply_dev_mode()
        self._header_state()

    # ---- dashboard
    def _build_dash(self):
        head = tk.Frame(self.tab_dash, bg=SURFACE)
        head.pack(fill="x", pady=(14, 4))
        tk.Label(head, text="Deck", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 11)).pack(side="left", padx=(6, 8))
        self.deck_filter = ttk.Combobox(head, state="readonly", width=30,
                                        style="Big.TCombobox",
                                        font=("Segoe UI", 13),
                                        values=["All decks"])
        self.deck_filter.set("All decks")
        self.deck_filter.pack(side="left")
        self.deck_filter.bind("<<ComboboxSelected>>",
                              lambda e: self.refresh(keep=True))
        tk.Label(head, text="List", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 11)).pack(side="left", padx=(16, 8))
        self.ver_filter = ttk.Combobox(head, state="readonly", width=13,
                                       style="Big.TCombobox",
                                       font=("Segoe UI", 13),
                                       values=["All versions"])
        self.ver_filter.set("All versions")
        self.ver_filter.pack(side="left")
        self.ver_filter.bind("<<ComboboxSelected>>",
                             lambda e: self.refresh(keep=True))

        ttk.Button(head, text="Paste decklist",
                   command=self._paste_decklist).pack(side="right")
        ttk.Button(head, text="View list",
                   command=self._view_decklist).pack(side="right", padx=8)

        self.filter_note = tk.Label(head, text="", bg=SURFACE, fg=MUTED,
                                    font=("Segoe UI", 9))
        self.filter_note.pack(side="left", padx=12)

        self.cards = tk.Frame(self.tab_dash, bg=SURFACE)
        self.cards.pack(fill="x", pady=(10, 8))
        self.card_widgets = {}
        for i, (key, label) in enumerate([
                ("record", "Record"), ("wr", "Win rate"),
                ("first", "Going first"), ("second", "Going second")]):
            f = tk.Frame(self.cards, bg=PANEL, highlightbackground=LINE,
                         highlightthickness=1)
            f.grid(row=0, column=i, padx=6, sticky="nsew", ipady=14)
            self.cards.grid_columnconfigure(i, weight=1)
            tk.Label(f, text=label.upper(), bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=16)
            v = tk.Label(f, text="--", bg=PANEL, fg=TEXT,
                         font=("Segoe UI Semibold", 24))
            v.pack(anchor="w", padx=16)
            sub = tk.Label(f, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 9))
            sub.pack(anchor="w", padx=16)
            self.card_widgets[key] = (v, sub)

        mid = tk.Frame(self.tab_dash, bg=SURFACE)
        mid.pack(fill="both", expand=True, pady=6)

        tk.Label(mid, text="RECENT FORM", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=6)
        self.form = tk.Frame(mid, bg=SURFACE)
        self.form.pack(anchor="w", padx=6, pady=(4, 14))

        grid = tk.Frame(mid, bg=SURFACE)
        grid.pack(fill="x", padx=6)
        self.stat_rows = {}
        for i, (key, label) in enumerate([
                ("turns", "Median game length"),
                ("pd", "Average prize differential"),
                ("mymull", "Your mulligans (avg)"),
                ("oppmull", "Opponent mulligans (avg)"),
                ("mymdraw", "Cards you drew off their mulligans"),
                ("oppmdraw", "Cards they drew off your mulligans")]):
            r = tk.Frame(grid, bg=SURFACE)
            r.grid(row=i % 3, column=i // 3, sticky="w", padx=(0, 52), pady=5)
            tk.Label(r, text=label, bg=SURFACE, fg=MUTED, width=36,
                     anchor="w", font=("Segoe UI", 10)).pack(side="left")
            v = tk.Label(r, text="--", bg=SURFACE, fg=TEXT,
                         font=("Segoe UI Semibold", 11))
            v.pack(side="left")
            self.stat_rows[key] = v

        # --- matchups for whichever deck is selected above
        head2 = tk.Frame(mid, bg=SURFACE)
        head2.pack(fill="x", padx=6, pady=(18, 4))
        self.mu_title = tk.Label(head2, text="MATCHUPS", bg=SURFACE, fg=MUTED,
                                 font=("Segoe UI", 8, "bold"))
        self.mu_title.pack(side="left")
        ttk.Button(head2, text="Rename archetype",
                   command=self._rename_arch_row).pack(side="right")

        self.mu_tree = ttk.Treeview(
            mid, columns=("name", "rec", "wr", "n"), show="headings",
            height=9)
        for c, h, w, anchor in (("name", "Opponent deck", 300, "w"),
                                ("rec", "W-L", 90, "w"),
                                ("wr", "Win rate", 100, "w"),
                                ("n", "Games", 70, "w")):
            self.mu_tree.heading(c, text=h)
            self.mu_tree.column(c, width=w, anchor=anchor)
        self.mu_tree.tag_configure("good", foreground=WIN)
        self.mu_tree.tag_configure("bad", foreground=RED)
        self.mu_tree.pack(fill="both", expand=True, padx=6, pady=(0, 6))

    # ---- matches
    def _build_matches(self):
        pane = tk.PanedWindow(self.tab_matches, orient="horizontal", bg=SURFACE,
                              sashwidth=6, borderwidth=0)
        pane.pack(fill="both", expand=True, pady=10)

        left = tk.Frame(pane, bg=SURFACE)
        cols = ("when", "result", "mydeck", "opp", "arch", "order", "turns",
                "prizes", "mull")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for c, t, w in [("when", "When", 108), ("result", "Result", 60),
                        ("mydeck", "Your deck", 136), ("opp", "Opponent", 108),
                        ("arch", "Their deck", 136), ("order", "Order", 60),
                        ("turns", "Turns", 52), ("prizes", "Prizes", 58),
                        ("mull", "Mull", 52)]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.tag_configure("win", foreground=WIN)
        self.tree.tag_configure("loss", foreground=LOSS)
        self.tree.tag_configure("ignored", foreground=MUTED)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._show_detail)
        self.tree.bind("<Double-1>", self._edit_from_tree)

        btns = tk.Frame(left, bg=SURFACE)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="View battle log", style="Go.TButton",
                   command=self._view_log).pack(side="left", padx=(0, 8))
        ttk.Button(btns, text="Rename deck for this match",
                   command=lambda: self._edit_deck(scope="match")).pack(
            side="left")
        ttk.Button(btns, text="Rename everywhere",
                   command=lambda: self._edit_deck(scope="all")).pack(
            side="left", padx=8)
        tk.Label(btns, text="double-click a row to rename",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 9)).pack(side="left",
                                                                padx=8)
        self._toast_lbl = tk.Label(left, text="", bg=SURFACE, fg=MUTED,
                                   font=("Segoe UI", 9), anchor="w")
        self._toast_lbl.pack(fill="x", pady=(4, 0))
        pane.add(left, stretch="always")

        right = tk.Frame(pane, bg=SURFACE, width=380)
        tk.Label(right, text="CARDS SEEN", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10,
                                                    pady=(0, 4))
        self.detail = tk.Text(right, bg=PANEL, fg=TEXT, relief="flat",
                              font=("Consolas", 9), wrap="word", width=44,
                              insertbackground=TEXT)
        self.detail.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.detail.tag_configure("hdr", foreground=ACCENT,
                                  font=("Consolas", 9, "bold"))
        self.detail.configure(state="disabled")

        pane.add(right)

    # ---- activity
    def _build_activity(self):
        self.act = tk.Text(self.tab_act, bg=CONSOLE, fg=CONSOLE_FG,
                           relief="flat", font=("Consolas", 9), wrap="word")
        self.act.pack(fill="both", expand=True, pady=10)
        self.act.insert("end",
                        "Press 'Start tracking', then play a match.\n"
                        "Both decks are detected from the battle log "
                        "automatically.\n")
        self.act.configure(state="disabled")

    def _scrollable(self, parent):
        """
        A frame that scrolls when its contents outgrow the window.

        Settings is taller than a windowed app, so without this the
        bottom of the tab is simply unreachable. The scrollbar only
        appears when it is needed, and the wheel is bound on enter and
        unbound on leave so it does not hijack scrolling elsewhere.
        """
        outer = tk.Frame(parent, bg=SURFACE)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=SURFACE, highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=SURFACE)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)

        def on_inner(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            need = inner.winfo_reqheight() > canvas.winfo_height()
            if need and not bar.winfo_ismapped():
                bar.pack(side="right", fill="y")
            elif not need and bar.winfo_ismapped():
                bar.pack_forget()

        def on_canvas(e):
            # keep the content the full width of the viewport, so text
            # wrapping and right-aligned widgets behave
            canvas.itemconfigure(window, width=e.width)
            on_inner()

        inner.bind("<Configure>", on_inner)
        canvas.bind("<Configure>", on_canvas)

        def wheel(e):
            if inner.winfo_reqheight() <= canvas.winfo_height():
                return
            # Windows and macOS report delta differently; Linux sends
            # Button-4/5 instead
            step = -1 if getattr(e, "num", None) == 4 else (
                1 if getattr(e, "num", None) == 5 else
                int(-e.delta / (120 if abs(e.delta) >= 120 else 1)))
            canvas.yview_scroll(step, "units")

        def bind_wheel(_e=None):
            canvas.bind_all("<MouseWheel>", wheel)
            canvas.bind_all("<Button-4>", wheel)
            canvas.bind_all("<Button-5>", wheel)

        def unbind_wheel(_e=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        outer.bind("<Enter>", bind_wheel)
        outer.bind("<Leave>", unbind_wheel)
        return inner

    # ---- settings
    def _build_settings(self):
        wrap = self._scrollable(self.tab_set)
        wrap.configure(padx=8, pady=16)

        self.set_vars = {}
        opts = [
            ("start_with_windows", "Start Full Bench when Windows starts",
             "Adds a per-user entry under Run in the registry. No admin "
             "rights needed, and you can also turn it off from Task "
             "Manager's Startup tab."),
            ("auto_track_on_game_launch",
             "Start tracking automatically when PTCGL launches",
             "Detects the game window or process and begins watching, so "
             "you never have to remember to press Start."),
            ("stop_tracking_on_game_exit",
             "Stop tracking when PTCGL closes",
             "Releases the screen watcher when you're done playing."),
            ("start_minimised", "Start minimised",
             "Useful together with the option above."),
            ("block_continue",
             "Block the Continue button while the log is being saved",
             "Puts a small cover over the Continue button for the "
             "half-second the copy takes, so a fast click can't throw the "
             "match away. Click it or press Escape to dismiss it early; "
             "it also clears itself after four seconds no matter what."),
            ("ignore_no_attack",
             "Ignore matches where neither player attacked",
             "An instant concede is not a game, and counting it moves "
             "your win rate without saying anything about how the decks "
             "play. These matches are still recorded and still visible "
             "in the Matches tab, they just don't count."),
            ("developer_mode", "Developer mode",
             "Shows the Activity tab: a live log of what the watchers are "
             "doing. Useful when something isn't being captured, noise "
             "otherwise. Problems are reported next to the app title "
             "whether this is on or not."),
        ]
        for key, label, blurb in opts:
            row = tk.Frame(wrap, bg=SURFACE)
            row.pack(fill="x", pady=(6, 2), anchor="w")
            v = tk.BooleanVar(value=bool(self.cfg.get(key)))
            self.set_vars[key] = v
            tk.Checkbutton(
                row, text=label, variable=v,
                command=lambda k=key: self._on_setting(k),
                bg=SURFACE, fg=TEXT, selectcolor=PANEL,
                activebackground=SURFACE, activeforeground=TEXT,
                borderwidth=0, highlightthickness=0,
                font=("Segoe UI", 10)).pack(anchor="w")
            tk.Label(wrap, text=blurb, bg=SURFACE, fg=MUTED,
                     font=("Segoe UI", 9), wraplength=680,
                     justify="left").pack(anchor="w", padx=26, pady=(0, 8))

        self.set_note = tk.Label(wrap, text="", bg=SURFACE, fg=MUTED,
                                 font=("Segoe UI", 9))
        self.set_note.pack(anchor="w", pady=(10, 0))

        # --- cloud sync
        tk.Label(wrap, text="CLOUD SYNC", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(22, 4))
        tk.Label(wrap,
                 text="Optional. Sign in and your history is kept in your "
                      "account, so two PCs share one record and nothing is "
                      "lost if this machine dies. Your matches also count "
                      "towards the deck statistics on fullbench.gg \u2014 "
                      "counts by deck only, never player names, yours or "
                      "your opponents'.",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 9), wraplength=700,
                 justify="left").pack(anchor="w", pady=(0, 10))

        self.cloud_btns = tk.Frame(wrap, bg=SURFACE)
        self.cloud_btns.pack(anchor="w")

        # One button. Signing in happens in the browser, where the
        # address bar and the certificate are visible -- which is the
        # whole point, and is undone by also offering to take a password
        # here.
        self.btn_browser = ttk.Button(self.cloud_btns,
                                      text="Sign in at fullbench.gg",
                                      style="Go.TButton",
                                      command=self._cloud_browser_login)
        self.btn_sync = ttk.Button(self.cloud_btns, text="Sync now",
                                   style="Go.TButton",
                                   command=self._cloud_sync)
        self.btn_signout = ttk.Button(self.cloud_btns, text="Sign out",
                                      command=self._cloud_signout)

        v = tk.BooleanVar(value=bool(self.cfg.get("cloud_auto_sync", True)))
        self.set_vars["cloud_auto_sync"] = v
        self.chk_auto = tk.Checkbutton(
            wrap, text="Sync automatically after each match", variable=v,
            command=lambda: self._on_setting("cloud_auto_sync"),
            bg=SURFACE, fg=TEXT, selectcolor=PANEL, activebackground=SURFACE,
            activeforeground=TEXT, borderwidth=0, highlightthickness=0,
            font=("Segoe UI", 10))
        self.chk_auto.pack(anchor="w", pady=(10, 0))

        self.cloud_note = tk.Label(wrap, text="", bg=SURFACE, fg=MUTED,
                                   font=("Segoe UI", 9), wraplength=700,
                                   justify="left")
        self.cloud_note.pack(anchor="w", pady=(8, 0))
        self._cloud_state()
        if self.cfg.get("cloud_token"):
            self.cloud_note.configure(
                text=f"signed in as {self.cfg.get('cloud_email', '')}",
                fg=MUTED)

        tk.Label(wrap, text="GAME", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(18, 4))
        self.game_lbl = tk.Label(wrap, text="checking...", bg=SURFACE,
                                 fg=MUTED, font=("Segoe UI", 10))
        self.game_lbl.pack(anchor="w")

        # keep the checkbox honest if the registry says otherwise
        try:
            actual = self.settings_mod.startup_enabled()
            self.set_vars["start_with_windows"].set(actual)
            self.cfg["start_with_windows"] = actual
        except Exception:
            pass

    def _on_setting(self, key):
        val = self.set_vars[key].get()
        self.cfg[key] = val
        self.settings_mod.save(self.cfg)

        if key == "start_with_windows":
            ok, msg = self.settings_mod.set_startup(val)
            self.set_note.configure(text=msg, fg=TEXT if ok else RED)
            if not ok:
                self.set_vars[key].set(not val)
                self.cfg[key] = not val
                self.settings_mod.save(self.cfg)
        elif key == "developer_mode":
            self._apply_dev_mode()
            self._header_state()
            self.set_note.configure(
                text="Activity tab shown" if val else "Activity tab hidden",
                fg=MUTED)
        else:
            self.set_note.configure(text="saved", fg=MUTED)

    def _ask_name(self, title, prompt, initial):
        """Small modal text prompt, themed to match the app."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=SURFACE)
        dlg.transient(self)
        dlg.resizable(False, False)
        tk.Label(dlg, text=prompt, bg=SURFACE, fg=TEXT,
                 font=("Segoe UI", 10), wraplength=420,
                 justify="left").pack(anchor="w", padx=16, pady=(16, 6))
        var = tk.StringVar(value=initial or "")
        ent = tk.Entry(dlg, textvariable=var, width=46, bg=PANEL, fg=TEXT,
                       insertbackground=TEXT, relief="flat",
                       font=("Segoe UI", 11))
        ent.pack(padx=16, ipady=5)
        ent.focus_set()
        ent.select_range(0, "end")

        out = {"v": None}

        def close():
            # release the grab before destroying: leaving it held means
            # the NEXT modal never receives events and wait_window()
            # blocks forever.
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            dlg.destroy()

        def ok(_e=None):
            out["v"] = var.get().strip()
            close()

        row = tk.Frame(dlg, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=14)
        ttk.Button(row, text="Save", style="Go.TButton",
                   command=ok).pack(side="right")
        ttk.Button(row, text="Cancel",
                   command=close).pack(side="right", padx=8)
        ent.bind("<Return>", ok)
        dlg.bind("<Escape>", lambda e: close())
        dlg.protocol("WM_DELETE_WINDOW", close)

        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + 160
        dlg.geometry(f"+{x}+{y}")
        dlg.grab_set()
        self.wait_window(dlg)
        return out["v"]

    def _edit_from_tree(self, _evt):
        self._edit_deck(scope="match")

    def _edit_deck(self, scope="match"):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select a match first.")
            return
        mid = int(sel[0])
        rows = q("SELECT deck_label FROM matches WHERE id=?", (mid,))
        cur = rows[0]["deck_label"] if rows else ""
        prompt = ("New name for the deck you played in this match:"
                  if scope == "match" else
                  f"Rename every match currently labelled "
                  f"\"{cur or 'unknown'}\":")
        new = self._ask_name("Rename deck", prompt, cur)
        if not new or new == cur:
            return
        n = rename_deck(cur, new, which=scope, match_id=mid)
        self.refresh(keep=True)
        self.log(f"renamed deck -> {new} ({n} match{'es' if n != 1 else ''})")

    def _rename_arch_row(self):
        sel = self.mu_tree.selection()
        if not sel:
            messagebox.showinfo(APP_NAME, "Select an archetype first.")
            return
        cur = self.mu_tree.item(sel[0], "values")[0]
        cur = None if cur == "unknown" else cur
        new = self._ask_name("Rename archetype",
                             f"Rename every opponent deck labelled "
                             f"\"{cur or 'unknown'}\":", cur)
        if new and new != cur:
            n = rename_opponent_archetype(cur, new)
            self.refresh(keep=True)
            self.log(f"renamed archetype -> {new} ({n} matches)")

    def _paste_decklist(self):
        """
        Read the decklist straight off the clipboard.

        You already copied it in PTCGL, so asking you to paste it into
        another box is a wasted step. Result is reported inline rather
        than in a popup.
        """
        sel = self.deck_filter.get()
        decks = decks_used()
        if sel == "All decks":
            if len(decks) == 1:
                sel = decks[0]
                self.deck_filter.set(sel)
            elif not decks:
                self._paste_note("No decks recorded yet - play a match "
                                 "first.", RED)
                return
            else:
                self._paste_note("Pick which deck this list belongs to "
                                 "in the Deck box first.", RED)
                return

        try:
            text = self.clipboard_get()
        except tk.TclError:
            text = ""
        if not text.strip():
            self._paste_note("Clipboard is empty - copy the list in PTCGL "
                             "first.", RED)
            return

        import decklist as dl
        if not dl.looks_like_decklist(text):
            d = dl.parse_decklist(text)
            if d["ok"]:
                # it parsed, just short -- say so rather than claiming it
                # isn't a decklist at all
                self._paste_note(
                    f"Only {d['total']} cards found - looks like a partial "
                    f"list. Copy the whole deck in PTCGL.", RED)
            else:
                self._paste_note("That's not a decklist. In PTCGL open the "
                                 "deck and choose Copy.", RED)
            return

        import sqlite3 as sq
        import ptcgl_tracker
        c = sq.connect(DB_PATH)
        try:
            ver, parsed, msg = ptcgl_tracker.add_deck_version(c, sel, text)
        finally:
            c.close()

        if ver is None:
            self._paste_note(msg, RED)
            return
        self.log(f"decklist for {sel}: {msg}")
        self.refresh(keep=True)
        if ver:
            self.ver_filter.set(f"v{ver}")
            self.refresh(keep=True)
        # note last: refresh() rewrites this label, so setting it first
        # would just be overwritten
        extra = ""
        if parsed["problems"]:
            extra = "  (" + "; ".join(parsed["problems"][:2]) + ")"
        self._paste_note(f"{sel}: {msg}, {parsed['total']} cards{extra}",
                         RED if parsed["problems"] else WIN)

    def _paste_note(self, text, colour=MUTED):
        self.filter_note.configure(text=text, fg=colour)
        # let the normal note come back after a few seconds
        self.after(6000, lambda: self.refresh(keep=True))

    def _view_decklist(self):
        """Show the stored list, with a button to copy it back out."""
        sel = self.deck_filter.get()
        if sel == "All decks":
            self._paste_note("Pick a deck first.", RED)
            return
        vers = versions_for(sel)
        if not vers:
            self._paste_note(f"No decklist saved for {sel} yet - "
                             f"use Paste decklist.", RED)
            return
        selv = self.ver_filter.get()
        v = vers[-1] if selv == "All versions" else int(selv.lstrip("v"))

        import sqlite3 as sq
        import ptcgl_tracker
        import decklist as dl
        c = sq.connect(DB_PATH)
        try:
            rec = ptcgl_tracker.deck_version_list(c, sel, v)
        finally:
            c.close()
        if not rec:
            self._paste_note("That version isn't stored.", RED)
            return
        list_text, cards_json, total, created = rec
        parsed = dl.parse_decklist(list_text)

        dlg = tk.Toplevel(self)
        dlg.title(f"{sel} - v{v}")
        dlg.configure(bg=SURFACE)

        head = tk.Frame(dlg, bg=HEADER)
        head.pack(fill="x")
        tk.Label(head, text=f"{sel}   v{v}", bg=HEADER, fg=HEADER_FG,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=16,
                                                      pady=(12, 0))
        tk.Label(head,
                 text=f"{total} cards \u2014 saved "
                      f"{created[:16].replace('T', ' ')}",
                 bg=HEADER, fg="#a9b6da",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 12))
        tk.Frame(dlg, bg=ACCENT, height=4).pack(fill="x")

        body = tk.Text(dlg, width=46, height=30, bg="#ffffff", fg=TEXT,
                       relief="flat", font=("Consolas", 10),
                       padx=14, pady=12)
        body.pack(fill="both", expand=True, padx=16, pady=(12, 4))
        body.insert("1.0", dl.format_list(parsed))
        body.configure(state="disabled")

        note = tk.Label(dlg, text="", bg=SURFACE, fg=MUTED,
                        font=("Segoe UI", 9))
        note.pack(anchor="w", padx=16)

        def copy_list():
            """Put the original text back on the clipboard, exactly as
            PTCGL produced it, so it can be pasted straight back in."""
            self.clipboard_clear()
            self.clipboard_append(list_text)
            self.update()
            note.configure(text="copied - paste it into PTCGL's deck "
                                "import", fg=WIN)

        row = tk.Frame(dlg, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=12)
        ttk.Button(row, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="Copy list", style="Go.TButton",
                   command=copy_list).pack(side="right", padx=8)

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Control-c>", lambda e: copy_list())
        dlg.geometry(f"+{self.winfo_rootx()+160}+{self.winfo_rooty()+40}")

    def _build_about(self):
        wrap = self._scrollable(self.tab_about)
        wrap.configure(padx=8, pady=14)

        head = tk.Frame(wrap, bg=SURFACE)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, bg=SURFACE, fg=TEXT,
                 font=("Segoe UI Semibold", 15)).pack(side="left")
        tk.Label(head, text=f"version {VERSION}", bg=SURFACE, fg=HEADER,
                 font=("Segoe UI", 10)).pack(side="left", padx=10)

        tk.Label(wrap, text="Stat tracker for Pokemon TCG Live, built from "
                            "the post-match battle log.",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 10),
                 wraplength=760, justify="left").pack(anchor="w", pady=(4, 8))

        if DONATE_URL:
            sup = tk.Frame(wrap, bg=PANEL, highlightbackground=LINE,
                           highlightthickness=1)
            sup.pack(anchor="w", fill="x", pady=(0, 12))
            tk.Label(sup, text="Full Bench is free and will stay free. If "
                               "it's useful, a small tip covers the server.",
                     bg=PANEL, fg=TEXT, font=("Segoe UI", 10),
                     wraplength=560, justify="left").pack(side="left",
                                                         padx=14, pady=10)
            ttk.Button(sup, text=DONATE_LABEL, style="Go.TButton",
                       command=lambda: __import__("webbrowser").open(
                           DONATE_URL)).pack(side="right", padx=14, pady=8)

        tk.Label(wrap, text="CHANGELOG", bg=SURFACE, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w")

        inner = tk.Frame(wrap, bg=SURFACE)
        inner.pack(fill="both", expand=True, pady=(6, 0))

        for ver, date, notes in CHANGELOG:
            row = tk.Frame(inner, bg=SURFACE)
            row.pack(fill="x", anchor="w", pady=(10, 2))
            tk.Label(row, text=ver, bg=SURFACE, fg=HEADER,
                     font=("Segoe UI Semibold", 11)).pack(side="left")
            tk.Label(row, text=date, bg=SURFACE, fg=MUTED,
                     font=("Segoe UI", 9)).pack(side="left", padx=8)
            for n in notes:
                tk.Label(inner, text="\u2022  " + n, bg=SURFACE, fg=MUTED,
                         font=("Segoe UI", 9), wraplength=740,
                         justify="left").pack(anchor="w", padx=10, pady=1)

        tk.Label(wrap, text="Not produced by, endorsed by, or affiliated "
                            "with Pokemon, Nintendo, Game Freak or Creatures.",
                 bg=SURFACE, fg=MUTED, font=("Segoe UI", 8),
                 wraplength=760, justify="left").pack(anchor="w", pady=(12, 0))

    def _set_status_line(self):
        if self.stop_evt:
            self.status.configure(text="\u25cf tracking", fg="#8fe3a8")
        else:
            self.status.configure(text="\u25cf not tracking", fg="#a9b6da")

    def _header_state(self):
        """
        Show only what is worth showing.

        Signed in -> the account and a Sync button. Not signed in -> a
        Sign in button. Tracking controls appear when tracking is off (so
        it can be started by hand) or whenever developer mode is on.
        """
        dev = bool(self.cfg.get("developer_mode"))
        email = self.cfg.get("cloud_email") if self.cfg.get("cloud_token") else None

        for w in (self.acct_label, self.btn_account, self.btn_cloud_sync,
                  self.btn_update):
            w.pack_forget()
        info = getattr(self, "_update_info", None)
        if info:
            self.btn_update.configure(
                text="Update to sync" if info.get("must")
                else "Update available")
            self.btn_update.pack(side="left", padx=(0, 10))
        if email:
            self.acct_label.configure(text=f"signed in as {email}")
            self.acct_label.pack(side="left", padx=(0, 10))
            self.btn_cloud_sync.pack(side="left")
        else:
            self.btn_account.pack(side="left")

        self.btn.pack_forget()
        self.btn_refresh.pack_forget()
        if dev:
            self.btn_refresh.pack(side="right", padx=(8, 10))
            self.btn.pack(side="right")
        elif not self.stop_evt:
            self.btn.pack(side="right", padx=(0, 10))

    def _apply_dev_mode(self):
        """
        Show or hide the Activity tab.

        The tab is only detached from the notebook -- the widget and its
        text buffer stay alive, so turning developer mode back on shows
        the full history rather than starting blank.
        """
        on = bool(self.cfg.get("developer_mode"))
        try:
            # setting the tab's state keeps it in place; notebook.hide()
            # followed by insert() does not clear the hidden state, so the
            # tab would never come back.
            self.nb.tab(self.tab_act, state="normal" if on else "hidden")
        except tk.TclError:
            pass

    # ---- cloud sync
    def _server(self):
        import cloud
        return cloud.DEFAULT_SERVER

    def _cloud_state(self):
        """Show either the sign-in button or the signed-in controls."""
        signed_in = bool(self.cfg.get("cloud_token"))
        for b in (self.btn_browser, self.btn_sync, self.btn_signout):
            b.pack_forget()
        if signed_in:
            self.btn_sync.pack(side="left")
            self.btn_signout.pack(side="left", padx=8)
        else:
            self.btn_browser.pack(side="left")

    def _cloud_browser_login(self):
        """
        Sign in through the browser.

        The app never sees a password. It asks the server for a short
        code, opens the site, and waits for you to approve this computer
        there -- where you can see the address bar and the certificate.
        """
        import cloud
        url = self._server()
        self.cloud_note.configure(text="opening your browser\u2026", fg=MUTED)

        def run():
            ok, info, msg = cloud.start_browser_login(url)
            if not ok:
                self.after(0, lambda: self.cloud_note.configure(text=msg,
                                                                fg=RED))
                return
            import webbrowser
            try:
                webbrowser.open(info["verify_url"])
            except Exception:
                pass
            self.after(0, lambda: self.cloud_note.configure(
                text=f"approve this computer in your browser. "
                     f"Code: {info['user_code']}", fg=MUTED))

            deadline = time.time() + info.get("expires_in", 600)
            interval = max(1, int(info.get("interval", 2)))
            while time.time() < deadline:
                time.sleep(interval)
                state, token, m = cloud.poll_browser_login(
                    url, info["device_code"])
                if state == "approved":
                    def done():
                        self.cfg["cloud_token"] = token
                        self.cfg["cloud_email"] = m.replace(
                            "signed in as ", "").strip()
                        self.settings_mod.save(self.cfg)
                        self._cloud_state()
                        self._header_state()
                        self.cloud_note.configure(text=m, fg=WIN)
                        self._cloud_sync(quiet=True)
                    self.after(0, done)
                    return
                if state == "failed":
                    self.after(0, lambda mm=m: self.cloud_note.configure(
                        text=mm, fg=RED))
                    return
            self.after(0, lambda: self.cloud_note.configure(
                text="the code expired - try again", fg=RED))

        threading.Thread(target=run, daemon=True).start()

    def _cloud_signout(self):
        import cloud
        url, token = self._server(), self.cfg.get("cloud_token")

        def run():
            cloud.sign_out(url, token)
        threading.Thread(target=run, daemon=True).start()

        self.cfg["cloud_token"] = ""
        self.cfg["cloud_email"] = ""
        self.settings_mod.save(self.cfg)
        self._cloud_state()
        self._header_state()
        self.cloud_note.configure(
            text="signed out on this computer - your matches stay here and "
                 "in your account", fg=MUTED)

    def _cloud_sync(self, quiet=False):
        import cloud
        token = self.cfg.get("cloud_token")
        if not token:
            if not quiet:
                self.cloud_note.configure(text="sign in first", fg=RED)
            return
        if not quiet:
            self.cloud_note.configure(text="syncing\u2026", fg=MUTED)

        def run():
            ok, msg = cloud.sync(self._server(), token, DB_PATH)
            self.log(f"cloud sync: {msg}")
            blocked = cloud.update_required

            def done():
                if hasattr(self, "cloud_note"):
                    self.cloud_note.configure(text=msg, fg=WIN if ok else RED)
                if blocked:
                    # the server is refusing this build: find out what's
                    # current and put the prompt up
                    self._check_for_update(reschedule=False)
                if not ok and "sign in again" in msg:
                    self.cfg["cloud_token"] = ""
                    self.settings_mod.save(self.cfg)
                    self._cloud_state()
                    self._header_state()
                if ok:
                    self.refresh(keep=True)
            self.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    # ---- updates
    UPDATE_RECHECK_MS = 6 * 60 * 60 * 1000   # the app is often left open

    def _check_for_update(self, reschedule=True):
        """Ask the server for the current release, off the UI thread."""
        import cloud

        def run():
            info = cloud.check_version(self._server())

            def done():
                if info and (info["newer"] or info["must"]):
                    self._update_info = info
                    self.log(f"update available: {info['latest']} "
                             f"(this is {VERSION})"
                             + (" - syncing paused until updated"
                                if info["must"] else ""))
                    self._header_state()
                    self._show_update()
                elif info:
                    self._update_info = None
                    self._header_state()
            self.after(0, done)

        threading.Thread(target=run, daemon=True).start()
        if reschedule:
            self.after(self.UPDATE_RECHECK_MS, self._check_for_update)

    def _show_update(self, force=False):
        """
        The update prompt. Shown once per new version per run unless asked
        for from the header button, so "Later" means later.
        """
        info = self._update_info
        if not info:
            return
        if not force and self._update_prompted == info["latest"]:
            return
        self._update_prompted = info["latest"]
        if getattr(self, "_update_dlg", None):
            try:
                self._update_dlg.destroy()
            except tk.TclError:
                pass

        dlg = tk.Toplevel(self)
        self._update_dlg = dlg
        dlg.title("Full Bench update")
        dlg.configure(bg=SURFACE)
        dlg.resizable(False, False)
        # A transient window hides along with a minimised parent, and the
        # app is often minimised -- the prompt would never be seen.
        if self.state() != "iconic":
            dlg.transient(self)

        head = tk.Frame(dlg, bg=HEADER)
        head.pack(fill="x")
        tk.Label(head, text=f"Full Bench {info['latest']} is out",
                 bg=HEADER, fg=HEADER_FG,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=18,
                                                      pady=(14, 0))
        tk.Label(head, text=f"You have {VERSION}", bg=HEADER, fg="#a9b6da",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=18,
                                            pady=(0, 12))
        tk.Frame(dlg, bg=ACCENT, height=4).pack(fill="x")

        if info["must"]:
            text = ("Syncing is paused until you update. Your matches are "
                    "safe on this PC - they'll all upload once the new "
                    "version is running.\n\nTracking keeps working in the "
                    "meantime.")
        else:
            text = ("A newer version is on the download page. Tracking and "
                    "syncing keep working either way.")
        text += ("\n\nTo update: download it, close Full Bench, and "
                 "replace your old FullBench.exe with the new one. Your "
                 "matches and settings are kept.")
        tk.Label(dlg, text=text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10),
                 wraplength=400, justify="left").pack(anchor="w", padx=18,
                                                      pady=(14, 6))

        def download():
            import webbrowser
            webbrowser.open(info["page"])
            dlg.destroy()

        row = tk.Frame(dlg, bg=SURFACE)
        row.pack(fill="x", padx=18, pady=(8, 16))
        ttk.Button(row, text="Later", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="Open download page", style="Go.TButton",
                   command=download).pack(side="right", padx=8)

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.bind("<Return>", lambda e: download())
        if self.state() != "iconic":
            dlg.geometry(f"+{self.winfo_rootx()+120}+{self.winfo_rooty()+80}")
        dlg.lift()
        dlg.focus_force()

    # ---- game detection
    def _start_game_watch(self):
        try:
            import game_watch
        except ImportError:
            return

        def on_start():
            self.after(0, self._game_started)

        def on_stop():
            self.after(0, self._game_stopped)

        threading.Thread(
            target=lambda: game_watch.watch(on_start=on_start,
                                            on_stop=on_stop),
            daemon=True).start()

    def _game_started(self):
        self._game_up = True
        if hasattr(self, "game_lbl"):
            self.game_lbl.configure(text="\u25cf PTCGL is running", fg=WIN)
        try:
            import game_watch
            seen = game_watch.last_match
        except ImportError:
            seen = ""
        # Naming the window makes a false detection easy to track down.
        self.log(f"PTCGL detected: {seen}." if seen else "PTCGL detected.")
        if self.cfg.get("auto_track_on_game_launch") and not self.stop_evt:
            self.log("auto-starting tracking.")
            self.toggle()

    def _game_stopped(self):
        self._game_up = False
        if hasattr(self, "game_lbl"):
            self.game_lbl.configure(text="\u25cb PTCGL not running", fg=MUTED)
        self.log("PTCGL closed.")
        if self.cfg.get("stop_tracking_on_game_exit") and self.stop_evt:
            self.log("auto-stopping tracking.")
            self.toggle()

    # ------------------------------------------------------------- logic
    def log(self, msg):
        self.log_q.put(f"{datetime.now():%H:%M:%S}  {msg}")

    def _drain_log(self):
        touched = False
        try:
            while True:
                line = self.log_q.get_nowait()
                self.act.configure(state="normal")
                self.act.insert("end", line + "\n")
                self.act.see("end")
                self.act.configure(state="disabled")
                if "[tracker]" in line:
                    touched = True
                if "MISSED" in line:
                    self.missed += 1
                    self._problem(f"{self.missed} match"
                                  f"{'es' if self.missed != 1 else ''} missed")
                elif " error:" in line or "failed:" in line:
                    self._problem(line.split("  ", 1)[-1][:60])
        except queue.Empty:
            pass
        if touched:
            self.refresh(keep=True)
            if self.cfg.get("cloud_auto_sync") and self.cfg.get("cloud_token"):
                self._cloud_sync(quiet=True)
        self.after(400, self._drain_log)

    def _problem(self, text):
        """
        Report a problem on the title bar.

        Errors used to be visible only in the Activity tab. With that tab
        hidden by default they have to show up somewhere the user is
        actually looking, so the status line turns red and stays that way
        until tracking is restarted.
        """
        self.status.configure(text=f"\u25cf {text}", fg="#ff9d97")
        if not self.cfg.get("developer_mode"):
            self.status.configure(
                text=f"\u25cf {text} - tick Developer mode for detail")

    def toggle(self):
        if self.stop_evt:
            self.stop_evt.set()
            self.stop_evt = None
            self.btn.configure(text="Start tracking")
            self._set_status_line()
            self._header_state()
            self.log("stopped.")
            return

        try:
            import ptcgl_tracker
        except ImportError as e:
            messagebox.showerror("Missing package", f"pip install {e.name}")
            return

        self.stop_evt = threading.Event()

        class Tee:
            def __init__(self, cb):
                self.cb = cb

            def write(self, s):
                s = s.strip()
                if s:
                    self.cb(s)

            def flush(self):
                pass

        def wrap(fn, label):
            def run():
                old = sys.stdout
                sys.stdout = Tee(self.log)
                try:
                    fn()
                except Exception as e:
                    self.log(f"{label} error: {e}")
                finally:
                    sys.stdout = old
            return run

        threading.Thread(target=wrap(
            lambda: ptcgl_tracker.watch_clipboard(
                stop=self.stop_evt,
                ignore_no_attack=self.cfg.get("ignore_no_attack", True)),
            "tracker"), daemon=True).start()
        self.log("clipboard watcher started.")

        def status(text):
            """Progress from the capture thread, shown on the title bar."""
            if text is None or text == "captured":
                self.after(0, lambda: self._set_status_line())
            else:
                self.after(0, lambda: self.status.configure(
                    text="\u25cf saving battle log\u2026", fg="#ffd76a"))

        def shield(rect):
            if not self.shield or not self.cfg.get("block_continue", True):
                return
            if rect is None:
                self.shield.hide()
            else:
                self.shield.show(rect)

        try:
            import autocopy
            autocopy.load_templates()
            threading.Thread(target=wrap(
                lambda: autocopy.watch_screen(stop=self.stop_evt,
                                              on_status=status,
                                              on_shield=shield),
                "autocopy"), daemon=True).start()
            self.log("screen watcher started.")
        except FileNotFoundError as e:
            self.log(f"auto-copy off: {e}")
        except ImportError as e:
            self.log(f"auto-copy off, missing package: {e.name}")

        self.btn.configure(text="Stop tracking")
        self._set_status_line()
        self._header_state()

    def refresh(self, keep=False):
        decks = ["All decks"] + decks_used()
        cur = self.deck_filter.get() if keep else "All decks"
        self.deck_filter.configure(values=decks)
        self.deck_filter.set(cur if cur in decks else "All decks")

        sel = self.deck_filter.get()

        vers = versions_for(sel)
        vlabels = ["All versions"] + [f"v{v}" for v in vers]
        curv = self.ver_filter.get() if keep else "All versions"
        self.ver_filter.configure(values=vlabels)
        self.ver_filter.set(curv if curv in vlabels else "All versions")
        self.ver_filter.configure(
            state="readonly" if len(vlabels) > 1 else "disabled")
        selv = self.ver_filter.get()

        d = stats(sel, selv)
        dec = d["w"] + d["l"]

        ignored = q("SELECT COUNT(*) AS n FROM matches WHERE "
                    "COALESCE(excluded,'') <> ''")
        ignored = ignored[0]["n"] if ignored else 0
        note = f"{d['n']} match{'es' if d['n'] != 1 else ''}"
        if sel != "All decks":
            note += f" with {sel}"
            if selv != "All versions":
                note += f" on {selv}"
            elif not vers:
                note += "  (no decklist saved -- use Paste decklist)"
        if ignored:
            note += (f"   \u00b7 {ignored} ignored "
                     f"(no attacks made)")
        self.filter_note.configure(text=note)

        self.card_widgets["record"][0].configure(text=f"{d['w']}-{d['l']}")
        self.card_widgets["record"][1].configure(text=f"{d['n']} recorded")
        # Win rates are colour-coded: at or above 50% green, below red.
        # No data stays white -- 0 matches is not a losing record.
        def wr_colour(w, n):
            if not n:
                return TEXT
            return WIN if (100.0 * w / n) >= 50 else RED

        self.card_widgets["wr"][0].configure(
            text=pct(d["w"], dec), fg=wr_colour(d["w"], dec))
        self.card_widgets["wr"][1].configure(text=f"{dec} decided")
        for k in ("first", "second"):
            n, w = d[k]
            self.card_widgets[k][0].configure(
                text=pct(w, n), fg=wr_colour(w, n))
            self.card_widgets[k][1].configure(text=f"{w}-{n-w}")

        for w in self.form.winfo_children():
            w.destroy()
        if d["recent"]:
            for r in d["recent"]:
                c = WIN if r == "win" else (LOSS if r == "loss" else LINE)
                tk.Frame(self.form, bg=c, width=26, height=26).pack(
                    side="left", padx=3)
        else:
            tk.Label(self.form, text="no matches yet", bg=SURFACE,
                     fg=MUTED).pack(anchor="w")

        t = sorted(d["turns"])
        self.stat_rows["turns"].configure(
            text=f"{t[len(t)//2]} turns" if t else "--")
        pd = avg(d["prizediff"])
        self.stat_rows["pd"].configure(
            text=f"{pd:+.2f}" if pd is not None else "--")
        for key, vals in (("mymull", d["my_mull"]), ("oppmull", d["opp_mull"]),
                          ("mymdraw", d["my_mdraw"]),
                          ("oppmdraw", d["opp_mdraw"])):
            a = avg(vals)
            self.stat_rows[key].configure(
                text=f"{a:.2f}" if a is not None else "--")

        self.tree.delete(*self.tree.get_children())
        rows = sorted(match_rows(sel, selv, include_excluded=True),
                      key=lambda r: -r["id"])
        for r in rows:
            order = {1: "first", 0: "second"}.get(r["went_first"], "?")
            pm, om = _col(r, "player_mulligans"), _col(r, "opponent_mulligans")
            mull = f"{pm}-{om}" if pm is not None else "-"
            excl = _col(r, "excluded")
            self.tree.insert(
                "", "end", iid=str(r["id"]),
                values=(r["captured_at"][:16].replace("T", " "),
                        ("ignored" if excl else (r["result"] or "?")),
                        r["deck_label"] or "unknown",
                        r["opponent"] or "?",
                        r["opponent_archetype"] or "unknown", order,
                        r["turns"] or "?",
                        f"{r['player_prizes_taken']}-{r['opponent_prizes_taken']}",
                        mull),
                tags=("ignored" if excl else (r["result"] or ""),))

        # matchups, restricted to the deck chosen above
        mu_head = "MATCHUPS"
        if sel != "All decks":
            mu_head += f"  \u2014  {sel.upper()}"
            if selv != "All versions":
                mu_head += f"  ({selv})"
        self.mu_title.configure(text=mu_head)
        self.mu_tree.delete(*self.mu_tree.get_children())
        agg = defaultdict(lambda: [0, 0])
        rows = [r for r in match_rows(sel, selv)
                if r["result"] in ("win", "loss")]
        rows = [{"k": r["opponent_archetype"], "result": r["result"]}
                for r in rows]
        for r in rows:
            k = r["k"] or "unknown"
            agg[k][0] += 1
            agg[k][1] += (r["result"] == "win")
        for k, (n, w) in sorted(agg.items(), key=lambda kv: (-kv[1][0], kv[0])):
            tag = "good" if (100.0 * w / n) >= 50 else "bad"
            self.mu_tree.insert("", "end",
                                values=(k, f"{w}-{n-w}", pct(w, n), n),
                                tags=(tag,))

    def _tip(self, widget, text):
        def enter(_e):
            widget._tip = tw = tk.Toplevel(widget)
            tw.overrideredirect(True)
            tw.attributes("-topmost", True)
            tk.Label(tw, text=text, bg=PANEL, fg=TEXT, padx=8, pady=4,
                     font=("Segoe UI", 9)).pack()
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tw.geometry(f"+{x}+{y}")

        def leave(_e):
            tw = getattr(widget, "_tip", None)
            if tw is not None:
                tw.destroy()
                widget._tip = None

        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    # ---- battle log viewer
    def _view_log(self):
        """
        Show the selected match's full battle log.

        The file on this PC is used when there is one -- real names, it's
        your own copy. A match synced down from another computer has no
        file here, so the server's copy is fetched instead, where the
        names are already You and Opponent.
        """
        sel = self.tree.selection()
        if not sel:
            self._toast("Select a match first.")
            return
        rows = q("SELECT * FROM matches WHERE id=?", (int(sel[0]),))
        if not rows:
            return
        r = rows[0]
        raw = _col(r, "raw_path")
        if raw and Path(raw).exists():
            try:
                text = Path(raw).read_text(encoding="utf-8",
                                           errors="replace")
            except OSError:
                text = None
            if text:
                self._log_window(r, text, anonymised=False,
                                 path=Path(raw))
                return

        token = self.cfg.get("cloud_token")
        if not token:
            self._toast("This match's log isn't on this PC. Sign in to "
                        "fetch it from your account.")
            return
        self._toast("fetching the log from your account…")

        def run():
            import cloud
            text = cloud.fetch_log(self._server(), token, r["log_hash"])

            def done():
                if text:
                    self._log_window(r, text, anonymised=True)
                else:
                    self._toast("No log for this match on this PC or in "
                                "your account.")
            self.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    def _toast(self, msg):
        """One-line note under the match list; the log gets it too."""
        self.log(msg)
        lbl = getattr(self, "_toast_lbl", None)
        if lbl is None:
            return
        lbl.configure(text=msg)
        self.after(6000, lambda: lbl.configure(text=""))

    def _log_window(self, r, text, anonymised, path=None):
        from ptcgl_parse import log_view_lines
        lines = log_view_lines(text, anonymise=anonymised)

        dlg = tk.Toplevel(self)
        result = (r["result"] or "?").upper()
        dlg.title(f"Battle log — {result} vs "
                  f"{r['opponent_archetype'] or 'unknown'}")
        dlg.configure(bg=SURFACE)
        dlg.geometry(f"720x760+{self.winfo_rootx()+80}+"
                     f"{self.winfo_rooty()+30}")

        head = tk.Frame(dlg, bg=HEADER)
        head.pack(fill="x")
        tk.Label(head, text=f"{result}   {r['deck_label'] or 'unknown'}  vs  "
                            f"{r['opponent_archetype'] or 'unknown'}",
                 bg=HEADER, fg=HEADER_FG,
                 font=("Segoe UI Semibold", 13)).pack(anchor="w", padx=16,
                                                      pady=(12, 0))
        order = {1: "went first", 0: "went second"}.get(r["went_first"], "")
        sub = "  ·  ".join(x for x in (
            (r["captured_at"] or "")[:16].replace("T", " "), order,
            f"{r['turns']} turns" if r["turns"] else "",
            f"prizes {r['player_prizes_taken']}-"
            f"{r['opponent_prizes_taken']}") if x)
        if anonymised:
            sub += "  ·  from your account"
        tk.Label(head, text=sub, bg=HEADER, fg="#a9b6da",
                 font=("Segoe UI", 9)).pack(anchor="w", padx=16,
                                            pady=(0, 12))
        tk.Frame(dlg, bg=ACCENT, height=4).pack(fill="x")

        frame = tk.Frame(dlg, bg=SURFACE)
        frame.pack(fill="both", expand=True, padx=16, pady=(12, 4))
        body = tk.Text(frame, bg="#ffffff", fg=TEXT, relief="flat",
                       font=("Segoe UI", 10), wrap="word", padx=14, pady=10,
                       spacing1=1, spacing3=1)
        bar = ttk.Scrollbar(frame, orient="vertical", command=body.yview)
        body.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        body.pack(side="left", fill="both", expand=True)

        body.tag_configure("turn", font=("Segoe UI Semibold", 10),
                           foreground=MUTED, spacing1=10, spacing3=3)
        body.tag_configure("turn_you", font=("Segoe UI Semibold", 10),
                           foreground=HEADER, spacing1=10, spacing3=3)
        body.tag_configure("turn_opp", font=("Segoe UI Semibold", 10),
                           foreground=MUTED, spacing1=10, spacing3=3)
        body.tag_configure("you", foreground=TEXT)
        body.tag_configure("opp", foreground="#3d4766")
        body.tag_configure("line", foreground=TEXT)
        body.tag_configure("detail", foreground=MUTED, lmargin1=18,
                           lmargin2=18, font=("Segoe UI", 9))
        body.tag_configure("cards", foreground=MUTED, lmargin1=30,
                           lmargin2=30, font=("Segoe UI", 9, "italic"))
        body.tag_configure("win", foreground=WIN,
                           font=("Segoe UI Semibold", 10))
        body.tag_configure("loss", foreground=LOSS,
                           font=("Segoe UI Semibold", 10))

        turn_no = 0
        for kind, t in lines:
            if kind == "gap":
                continue
            if kind in ("turn_you", "turn_opp") or \
                    (kind == "turn" and t != "Setup"):
                turn_no += 1
                t = f"{t.upper()}    ·  turn {turn_no}"
            elif kind == "turn":
                t = t.upper()
            elif kind == "cards":
                t = "• " + t
            body.insert("end", t + "\n", kind)
        body.configure(state="disabled")

        note = tk.Label(dlg, text="", bg=SURFACE, fg=MUTED,
                        font=("Segoe UI", 9))
        note.pack(anchor="w", padx=16)

        def copy_log():
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            note.configure(text="copied", fg=WIN)

        row = tk.Frame(dlg, bg=SURFACE)
        row.pack(fill="x", padx=16, pady=12)
        ttk.Button(row, text="Close", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="Copy log", command=copy_log).pack(
            side="right", padx=8)
        if path is not None:
            def open_file():
                try:
                    import os
                    os.startfile(str(path))       # Windows: default editor
                except Exception as e:
                    note.configure(text=f"couldn't open it: {e}", fg=LOSS)
            ttk.Button(row, text="Open file", command=open_file).pack(
                side="right")

        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.lift()
        dlg.focus_force()

    def _show_detail(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        rows = q("SELECT * FROM matches WHERE id=?", (int(sel[0]),))
        if not rows:
            return
        r = rows[0]
        self._detail_id = r["id"]

        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for label, col in ((f"YOUR DECK  ({r['deck_label'] or 'unknown'})",
                            "player_cards"),
                           (f"THEIR DECK  ({r['opponent_archetype'] or 'unknown'})",
                            "opponent_cards")):
            self.detail.insert("end", label + "\n", "hdr")
            try:
                cards = json.loads(r[col] or "{}")
            except Exception:
                cards = {}
            if not cards:
                self.detail.insert("end", "  (none recorded)\n")
            for name, n in sorted(cards.items(), key=lambda kv: (-kv[1], kv[0])):
                self.detail.insert("end", f"  {n:>2}x  {name}\n")
            self.detail.insert("end", "\n")
        self.detail.insert("end", "MATCH\n", "hdr")
        self.detail.insert("end", f"  result: {r['result']} "
                                  f"({r['win_reason'] or 'unknown'})\n")
        pm, om = _col(r, "player_mulligans"), _col(r, "opponent_mulligans")
        if pm is not None:
            self.detail.insert("end", f"  mulligans: you {pm}, them {om}\n")
            self.detail.insert(
                "end",
                f"  extra cards drawn: you {_col(r, 'player_mulligan_draws')}, "
                f"them {_col(r, 'opponent_mulligan_draws')}\n")
        self.detail.insert("end", f"  attack damage: you {r['player_damage']}, "
                                  f"them {r['opponent_damage']}\n")
        self.detail.insert("end",
                           "\nOnly cards actually played or revealed appear "
                           "here -- this is not a full 60.\n")
        self.detail.configure(state="disabled")


if __name__ == "__main__":
    App().mainloop()
