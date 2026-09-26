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
