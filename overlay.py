"""
The click shield.

A small always-on-top window that covers the Continue button while the
battle log is being copied, so a fast click cannot throw the match away.
PTCGL discards the log the moment Continue is pressed and there is no way
to get it back.

There was also a full-width banner across the top of the screen. It was
removed: that is exactly where the battle log's own copy icon sits, so it
covered the button the capture needs to click.

Runs on the Tk main thread; worker threads call show()/hide() from
anywhere.
"""

import queue
import tkinter as tk

# The banner and the click shield stay red deliberately. They are
# warnings -- "don't press Continue" has to read as urgent, and the
# app's gold accent would look like decoration.
RED = "#d63031"
WHITE = "#fafafc"
BLACK = "#12193a"
GREEN = "#43c06a"


class ClickShield:
    """
    A small always-on-top window placed over the Continue button while
    the battle log is being copied, so a click lands on the shield
    instead of throwing the log away.

    It covers one button on the user's own screen for well under a
    second. It does not touch the game, read it, or send it anything.

    A shield that got stuck would be worse than the problem it solves,
    so it always has a way out: the capture code hides it when finished,
    and a watchdog takes it down after its time regardless -- a few
    seconds normally, or the length of the wait while the player copies
    the log by hand (when the pop-up also has a Skip button). Escape
    dismisses it too.

    Clicking it does NOT take it down. It used to, and that was the
    hole: someone clicking about on the result screen could knock the
    shield away with one click and press Continue with the next.
    """

    MAX_MS = 6000          # ceiling for one automatic copy attempt

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.win = None
        self._watchdog = None
        self._pump()

    # --- any thread
    def show(self, rect, hold_s=None):
        """Cover rect. hold_s: stay up this long (the manual-copy wait)
        instead of the usual few seconds."""
        self.q.put(("show", (rect, hold_s)))

    def hide(self):
        self.q.put(("hide", None))

    # --- main thread
    def _pump(self):
        try:
            while True:
                kind, arg = self.q.get_nowait()
                if kind == "show":
                    self._show(arg)
                else:
                    self._hide()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _show(self, arg):
        rect, hold_s = arg
        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return
        if self.win is None or not tk.Toplevel.winfo_exists(self.win):
            self.win = tk.Toplevel(self.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            try:
                self.win.attributes("-alpha", 0.82)
            except tk.TclError:
                pass
            f = tk.Frame(self.win, bg=RED)
            f.pack(fill="both", expand=True)
            self.lbl = tk.Label(f, text="saving battle log\u2026", bg=RED,
                                fg=WHITE, font=("Segoe UI Semibold", 13))
            self.lbl.pack(expand=True)
            # a click only says why it's there; it never takes it down
            for w_ in (self.win, f, self.lbl):
                w_.bind("<Button-1>", lambda e: self._nudge())
            self.win.bind("<Escape>", lambda e: self._hide())
        self._text = ("copy the battle log first" if hold_s
                      else "saving battle log\u2026")
        self.lbl.configure(text=self._text)
        self.win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

        if self._watchdog:
            try:
                self.root.after_cancel(self._watchdog)
            except Exception:
                pass
        limit = int(hold_s * 1000) if hold_s else self.MAX_MS
        self._watchdog = self.root.after(limit, self._hide)

    def _nudge(self):
        """Clicked: say so, briefly, then go back to the usual text."""
        try:
            self.lbl.configure(text="not yet \u2014 saving the log")
            self.root.after(900, lambda: self.lbl.configure(
                text=getattr(self, "_text", "saving battle log\u2026")))
        except tk.TclError:
            pass

    def _hide(self):
        if self._watchdog:
            try:
                self.root.after_cancel(self._watchdog)
            except Exception:
                pass
            self._watchdog = None
        if self.win is not None and tk.Toplevel.winfo_exists(self.win):
            self.win.withdraw()


class ExportPrompt:
    """
    "Battle log not saved yet" -- shown when the automatic copy missed
    twice, asking the player to click Battle Log and the copy icon
    themselves while Continue stays covered.

    Sits where the match pop-up does, bottom right of the game window,
    clear of the Battle Log button, the copy icon and Continue. Counts
    down the wait, and has a Skip button that uncovers Continue straight
    away. Clicking anywhere else on it does nothing, so a stray click
    can't skip by accident.

    Worker threads call waiting()/saved()/missed() from anywhere; like
    the shield, it runs on the Tk main thread through a queue. It never
    takes focus from the game.
    """

    W, H = 400, 80
    MISSED_MS = 7000       # how long "not saved" stays up

    def __init__(self, root, on_skip=None):
        self.root = root
        self.on_skip = on_skip
        self.q = queue.Queue()
        self.win = None
        self._tick = None
        self._left = 0
        self._pump()

    # --- any thread
    def waiting(self, seconds):
        self.q.put(("waiting", seconds))

    def saved(self):
        self.q.put(("hide", None))

    def missed(self):
        self.q.put(("missed", None))

    def hide(self):
        self.q.put(("hide", None))

    # --- main thread
    def _pump(self):
        try:
            while True:
                kind, arg = self.q.get_nowait()
                if kind == "waiting":
                    self._waiting(arg)
                elif kind == "missed":
                    self._missed()
                else:
                    self._hide()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    def _build(self):
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg="#dbe2ee")
        card = tk.Frame(w, bg=WHITE)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Frame(card, bg=RED, width=5).pack(side="left", fill="y")
        self.dot = tk.Label(card, text="!", bg=WHITE, fg=RED,
                            font=("Segoe UI Semibold", 18))
        self.dot.pack(side="left", padx=(12, 8))
        right = tk.Frame(card, bg=WHITE)
        right.pack(side="right", fill="y", padx=(6, 12))
        self.count = tk.Label(right, bg=WHITE, fg="#5b6683",
                              font=("Segoe UI", 8, "bold"))
        self.count.pack(anchor="e", pady=(10, 2))
        self.skip = tk.Label(right, text="Skip", bg="#f1f4fa", fg=BLACK,
                             font=("Segoe UI Semibold", 9), padx=10, pady=2,
                             cursor="hand2")
        self.skip.pack(anchor="e")
        self.skip.bind("<Button-1>", lambda e: self._skip())
        text = tk.Frame(card, bg=WHITE)
        text.pack(side="left", fill="both", expand=True, pady=9)
        self.title = tk.Label(text, bg=WHITE, fg=BLACK, anchor="w",
                              font=("Segoe UI Semibold", 11))
        self.title.pack(fill="x")
        # wraps inside the space left of the countdown, not under it
        self.sub = tk.Label(text, bg=WHITE, fg="#5b6683", anchor="w",
                            justify="left", wraplength=215,
                            font=("Segoe UI", 9))
        self.sub.pack(fill="x")
        w.update_idletasks()
        _no_activate(w)
        self.win = w

    def _open(self):
        if self.win is None or not tk.Toplevel.winfo_exists(self.win):
            self._build()
        x, y = _corner(self.root, self.W, self.H)
        self.win.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")
        fg = _foreground()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.update_idletasks()
        _no_activate(self.win)
        _restore_foreground(fg)

    def _waiting(self, seconds):
        self._open()
        self.title.configure(text="Battle log not saved yet")
        self.sub.configure(text="Click BATTLE LOG, then the copy icon "
                                "in the log.")
        self.skip.pack(anchor="e")
        self._left = int(seconds)
        self._stop_tick()
        self._countdown()

    def _countdown(self):
        if self._left <= 0:
            return
        self.count.configure(text=f"CONTINUE IN {self._left}s")
        self._left -= 1
        self._tick = self.root.after(1000, self._countdown)

    def _missed(self):
        self._stop_tick()
        self._open()
        self.title.configure(text="Battle log not saved")
        self.sub.configure(text="This match wasn't recorded.")
        self.count.configure(text="")
        self.skip.pack_forget()
        self._tick = self.root.after(self.MISSED_MS, self._hide)

    def _skip(self):
        self._stop_tick()
        if self.on_skip:
            try:
                self.on_skip()
            except Exception:
                pass

    def _stop_tick(self):
        if self._tick:
            try:
                self.root.after_cancel(self._tick)
            except Exception:
                pass
            self._tick = None

    def _hide(self):
        self._stop_tick()
        if self.win is not None and tk.Toplevel.winfo_exists(self.win):
            self.win.withdraw()


class MatchToast:
    """
    The "match recorded" notice.

    A small card in the bottom-right corner of the game window -- clear
    of the Continue button (bottom centre) and the battle log's copy icon
    (upper right) -- saying what was recorded and whether it reached the
    website. It goes away by itself, or on a click.

    It must never take focus from the game: a fullscreen game that loses
    focus can minimise. So the window is marked no-activate, and if
    showing it moved focus anyway, focus is handed straight back.
    """

    SHOW_MS = 6000          # how long it stays after its last change
    W, H = 390, 66

    _SYNC = {
        "saving": ("SAVED", "#5b6683"),
        "syncing": ("SYNCING…", "#5b6683"),
        "synced": ("SYNCED", "#14752f"),
        "local": ("SAVED", "#5b6683"),        # not signed in / auto-sync off
        "failed": ("NOT SYNCED", "#c5221f"),
    }
    _RESULT = {"win": ("Win", "#14752f"), "loss": ("Loss", "#c5221f")}

    def __init__(self, root):
        self.root = root
        self.win = None
        self._timer = None

    # --- main thread only
    def show(self, result, opponent, turns=None, sync="saving"):
        word, colour = self._RESULT.get(result, ("Recorded", "#5b6683"))
        if self.win is None or not tk.Toplevel.winfo_exists(self.win):
            self._build()
        self._turns = turns
        self.stripe.configure(bg=colour)
        self.dot.configure(fg=colour, text="✓" if result == "win"
                           else ("✕" if result == "loss" else "•"))
        self.title.configure(text=f"Match recorded: {word}")
        sub = f"vs {opponent}" if opponent else "opponent's deck unknown"
        if turns:
            sub += f" · {turns} turns"
        self.set_sync(sync)
        self.sub.configure(text=sub)
        self._place()
        fg = _foreground()
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.update_idletasks()
        _no_activate(self.win)
        _restore_foreground(fg)
        # only now does the label have a real width to fit the text to
        self.win.update_idletasks()
        self.sub.configure(text=self._fit(self.sub, sub))

    def set_opponent(self, opponent, turns=None):
        """Swap in fullbench.gg's name for the opponent's deck once the
        match has synced."""
        if self.win is None or not tk.Toplevel.winfo_exists(self.win):
            return
        turns = turns or getattr(self, "_turns", None)
        sub = f"vs {opponent}" if opponent else "opponent's deck unknown"
        if turns:
            sub += f" · {turns} turns"
        self.sub.configure(text=self._fit(self.sub, sub))

    def set_sync(self, state):
        if self.win is None or not tk.Toplevel.winfo_exists(self.win):
            return
        text, colour = self._SYNC.get(state, self._SYNC["saving"])
        self.state.configure(text=text, fg=colour)
        self._restart_timer()

    def hide(self):
        if self._timer:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None
        if self.win is not None and tk.Toplevel.winfo_exists(self.win):
            self.win.withdraw()

    # --- internals
    @staticmethod
    def _fit(label, text):
        """Cut text to the label's width, ending in an ellipsis."""
        try:
            import tkinter.font as tkfont
            f = tkfont.Font(font=label.cget("font"))
            room = label.master.winfo_width() - 4
            if room <= 20 or f.measure(text) <= room:
                return text
            while text and f.measure(text + "\u2026") > room:
                text = text[:-1]
            return text.rstrip(" /\u00b7") + "\u2026"
        except Exception:
            return text

    def _restart_timer(self):
        if self._timer:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
        self._timer = self.root.after(self.SHOW_MS, self.hide)

    def _build(self):
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg="#dbe2ee")            # 1px border colour
        card = tk.Frame(w, bg=WHITE)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        self.stripe = tk.Frame(card, bg=GREEN, width=5)
        self.stripe.pack(side="left", fill="y")
        self.dot = tk.Label(card, text="✓", bg=WHITE,
                            font=("Segoe UI Semibold", 16))
        self.dot.pack(side="left", padx=(10, 6))
        # packed before the text, so a long deck name is what gets cut
        # short rather than the sync state
        self.state = tk.Label(card, bg=WHITE, font=("Segoe UI", 8, "bold"))
        self.state.pack(side="right", padx=(6, 12))
        text = tk.Frame(card, bg=WHITE)
        text.pack(side="left", fill="both", expand=True, pady=8)
        self.title = tk.Label(text, bg=WHITE, fg=BLACK, anchor="w",
                              font=("Segoe UI Semibold", 11))
        self.title.pack(fill="x")
        self.sub = tk.Label(text, bg=WHITE, fg="#5b6683", anchor="w",
                            font=("Segoe UI", 9))
        self.sub.pack(fill="x")
        for x in (w, card, self.stripe, self.dot, text, self.title,
                  self.sub, self.state):
            x.bind("<Button-1>", lambda e: self.hide())
        # set no-activate while still hidden, so even the first showing
        # can't pull focus off the game
        w.update_idletasks()
        _no_activate(w)
        self.win = w

    def _place(self):
        x, y = _corner(self.root, self.W, self.H)
        self.win.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")


def _corner(root, W, H):
    """Top-left for a W x H card at the bottom right of the game window,
    else of the screen -- clear of Continue (bottom centre), the Battle
    Log button just above it, and the log's copy icon (upper right)."""
    try:
        import game_watch
        g = game_watch.game_window(require_visible=True)
        if g and g.width > W + 60 and g.height > H + 60:
            return g.left + g.width - W - 24, g.top + g.height - H - 24
    except Exception:
        pass
    right, bottom = _work_area(root)
    return right - W - 16, bottom - H - 16


# --- Windows helpers; every one is a harmless no-op elsewhere -----------

def _user32():
    try:
        import ctypes
        return ctypes.windll.user32
    except Exception:
        return None


def _foreground():
    u = _user32()
    try:
        return u.GetForegroundWindow() if u else None
    except Exception:
        return None


def _restore_foreground(hwnd):
    u = _user32()
    if not u or not hwnd:
        return
    try:
        if u.GetForegroundWindow() != hwnd:
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _no_activate(win):
    """Mark a Tk toplevel so clicking or showing it never takes focus."""
    u = _user32()
    if not u:
        return
    try:
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x80, 0x08000000
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
        u.SetWindowLongW(hwnd, GWL_EXSTYLE,
                         style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        pass


def _work_area(root):
    """Right and bottom edge of the primary screen, minus the taskbar."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x30, 0,
                                                     ctypes.byref(r), 0):
            return r.right, r.bottom
    except Exception:
        pass
    return root.winfo_screenwidth(), root.winfo_screenheight() - 48
