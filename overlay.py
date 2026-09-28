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
    so it has three independent ways out: the capture code hides it when
    finished, a watchdog kills it after MAX_MS regardless, and clicking
    or pressing Escape dismisses it immediately.
    """

    MAX_MS = 4000          # hard ceiling, whatever else happens

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.win = None
        self._watchdog = None
        self._pump()

    # --- any thread
    def show(self, rect):
        self.q.put(("show", rect))

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

    def _show(self, rect):
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
            # clicking the shield dismisses it: never trap the user
            for w_ in (self.win, f, self.lbl):
                w_.bind("<Button-1>", lambda e: self._hide())
            self.win.bind("<Escape>", lambda e: self._hide())
        self.win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)

        if self._watchdog:
            try:
                self.root.after_cancel(self._watchdog)
            except Exception:
                pass
        self._watchdog = self.root.after(self.MAX_MS, self._hide)

    def _hide(self):
        if self._watchdog:
            try:
                self.root.after_cancel(self._watchdog)
            except Exception:
                pass
            self._watchdog = None
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
        """Bottom-right of the game window, else of the screen."""
        x = y = None
        try:
            import game_watch
            g = game_watch.game_window(require_visible=True)
            if g and g.width > self.W + 60 and g.height > self.H + 60:
                x = g.left + g.width - self.W - 24
                y = g.top + g.height - self.H - 24
        except Exception:
            pass
        if x is None:
            right, bottom = _work_area(self.root)
            x, y = right - self.W - 16, bottom - self.H - 16
        self.win.geometry(f"{self.W}x{self.H}+{int(x)}+{int(y)}")


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
