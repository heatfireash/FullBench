"""
The sign-in welcome.

Shown over the app each time it opens while nobody is signed in: the app
dimmed behind it, a big yellow "Create a free account" button (the
browser opens on the sign-up form, and the app connects by itself once
it's done), "I already have an account: sign in" under it, a small
"Continue without signing in" link, and a short look at what an account
gives you on fullbench.gg.

It is two borderless windows tied to the main one -- a dimmed grey cover
the size of the app, and the card on top of it. They are separate because
a window's see-through setting applies to everything in it, and the card
has to stay solid. The cover also takes the clicks, so the app behind
can't be used until one of the two choices is made.

Nothing here can get in the way of the app: any failure while drawing
simply means no welcome, and the app works as it always has.
"""

import base64
import tkinter as tk
from fractions import Fraction

from look import semi, ui

# the app's own colours (ptcgl_gui.py): paper, white tiles, ink
SURFACE = "#f6f5f1"
SOFT = "#ffffff"
LINE = "#e2dfd5"
TEXT = "#15140f"
MUTED = "#6a6558"
ACCENT = "#f5c518"
ACCENT_HI = "#ffd43b"
ACCENT_DK = "#d9ab0f"
SCRIM = "#2f3340"
SCRIM_ALPHA = 0.62

# sizes below are at 96 dpi; everything is multiplied by the screen scale
CARD_W = 900
IMG_W, IMG_H = 215, 120
SIDE = 40                 # space either side of the tiles inside the card

TILES = [
    ("gate_replays.png", "Match replays",
     "Watch any game back move by move, and share a link with Discord or "
     "a friend. Player names are left out."),
    ("gate_stats.png", "Your stats and matchups",
     "Win rate by deck, going first vs. second, and the matchups that "
     "keep beating you. Deck versions too."),
    ("gate_devices.png", "Every PC, one record",
     "Your history lives in your account. Two computers share it, nothing "
     "is lost if one dies, and you can open it on your phone."),
    ("gate_meta.png", "Help shape the meta",
     "Your games count toward the global top decks, meta share and matchup "
     "chart. Decks only, never player names."),
]


class SignInGate:
    """
    asset(name) -> Path of a bundled file.
    on_signin() starts the sign-in; on_skip() is "continue without".
    """

    def __init__(self, root, asset, on_signin, on_skip):
        self.root = root
        self.asset = asset
        self.on_signin = on_signin
        self.on_skip = on_skip
        self.scrim = None
        self.card = None
        self.status = None
        self._open = False
        self._imgs = {}          # kept alive, and not rescaled every time
        self._built_for = None   # (card width, compact) of what's drawn
        self._ids = []
        self._after = None
        self._status_text = ("", MUTED)

    @property
    def is_open(self):
        return self._open

    # ---------------------------------------------------------- show/hide
    def show(self):
        if self._open:
            return
        try:
            self.scrim = tk.Toplevel(self.root)
            self.scrim.overrideredirect(True)
            self.scrim.configure(bg=SCRIM, cursor="arrow")
            try:
                self.scrim.attributes("-alpha", SCRIM_ALPHA)
            except tk.TclError:
                pass                     # opaque grey, still fine
            self.scrim.transient(self.root)

            self.card = tk.Toplevel(self.root)
            self.card.overrideredirect(True)
            self.card.configure(bg=LINE)
            self.card.transient(self.root)

            self._open = True
            self._layout()
            for ev in ("<Configure>", "<Map>", "<Unmap>"):
                self._ids.append((ev, self.root.bind(
                    ev, self._on_root, add="+")))
        except Exception:
            self.close()                 # never leave half a cover behind

    def close(self):
        self._open = False
        if self._after:
            try:
                self.root.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        for ev, fid in self._ids:
            try:
                self.root.unbind(ev, fid)
            except Exception:
                pass
        self._ids = []
        for w in (self.card, self.scrim):
            try:
                if w is not None:
                    w.destroy()
            except Exception:
                pass
        self.card = self.scrim = self.status = None
        self._built_for = None

    def set_status(self, text, fg=MUTED):
        """The line under the buttons: what the sign-in is waiting for."""
        self._status_text = (text, fg)
        try:
            if self.status is not None:
                self.status.configure(text=text or " ", fg=fg)
                # a longer line can make the card taller: fit it again
                self.root.after_idle(self._relayout)
        except tk.TclError:
            pass

    def _relayout(self):
        try:
            if self._open:
                self._layout()
        except Exception:
            pass

    # ------------------------------------------------------ following the app
    def _on_root(self, e):
        if e.widget is not self.root or not self._open:
            return
        if self._after:
            try:
                self.root.after_cancel(self._after)
            except Exception:
                pass
        self._after = self.root.after(30, self._follow)

    def _follow(self):
        self._after = None
        if not self._open:
            return
        try:
            if self.root.state() in ("iconic", "withdrawn"):
                self.scrim.withdraw()
                self.card.withdraw()
                return
            self.scrim.deiconify()
            self.card.deiconify()
            self._layout()
        except tk.TclError:
            self.close()

    # ------------------------------------------------------------- layout
    def _scale(self):
        try:
            return max(1.0, min(2.5, self.root.winfo_fpixels("1i") / 96.0))
        except tk.TclError:
            return 1.0

    def _layout(self):
        r = self.root
        r.update_idletasks()
        s = self._scale()
        x, y, w, h = (r.winfo_rootx(), r.winfo_rooty(),
                      r.winfo_width(), r.winfo_height())
        if w < 100 or h < 100:
            return
        self.scrim.geometry(f"{w}x{h}+{x}+{y}")

        cw = min(int(CARD_W * s), w - int(60 * s))
        room = h - int(24 * s)
        # try with the pictures; without them if the window is short
        for compact in (False, True):
            if self._built_for != (cw, compact, s):
                self._fill(cw, compact, s)
                self._built_for = (cw, compact, s)
            self.card.update_idletasks()
            ch = self.card.winfo_reqheight()
            if ch <= room or compact:
                break
        ch = min(ch, room)
        where = (f"{cw}x{ch}+{x + (w - cw) // 2}"
                 f"+{y + max(0, (h - ch) // 2)}")
        self.card.geometry(where)
        self.scrim.lift()
        self.card.lift()
        # a window's first position is sometimes lost as it is mapped
        self.card.update_idletasks()
        self.card.geometry(where)

    # ----------------------------------------------------------- the card
    def _fill(self, cw, compact, s):
        for child in self.card.winfo_children():
            child.destroy()
        px = lambda v: int(round(v * s))          # noqa: E731
        f = tk.Frame(self.card, bg=SURFACE)
        f.pack(fill="both", expand=True, padx=1, pady=1)

        top = tk.Frame(f, bg=SURFACE)
        top.pack(fill="x", pady=(px(14 if compact else 22), 0))
        if not compact:
            logo = self._image("logo_small.png", px(44), px(44))
            if logo:
                tk.Label(top, image=logo, bg=SURFACE).pack()
        tk.Label(top, text="Get more out of Full Bench with a free account",
                 bg=SURFACE, fg=TEXT, font=semi(20 if not compact else 18),
                 wraplength=cw - px(2 * SIDE)).pack(pady=(px(8), px(4)))
        tk.Label(top, text="Your games are saved to your account, so you can "
                           "watch replays, see your stats and check them "
                           "from any computer or your phone.",
                 bg=SURFACE, fg=MUTED, font=ui(11), justify="center",
                 wraplength=px(640)).pack()

        # the one button that matters: big and yellow, flat like the
        # site's Download button
        lip = tk.Frame(top, bg=ACCENT, width=px(420), height=px(54))
        lip.pack_propagate(False)
        lip.pack(pady=(px(16), 0))
        btn = tk.Label(lip, text="Create a free account", bg=ACCENT,
                       fg=TEXT, font=semi(16), cursor="hand2")
        btn.pack(fill="both", expand=True)
        btn.bind("<Button-1>", lambda e: self._signin(new=True))
        btn.bind("<Enter>", lambda e: (btn.configure(bg=ACCENT_DK),
                                       lip.configure(bg=ACCENT_DK)))
        btn.bind("<Leave>", lambda e: (btn.configure(bg=ACCENT),
                                       lip.configure(bg=ACCENT)))

        # the other two choices, side by side under the button
        row = tk.Frame(top, bg=SURFACE)
        row.pack(pady=(px(8), 0))
        have = tk.Label(row, text="I already have an account: sign in",
                        bg=SURFACE, fg=TEXT, font=ui(10, "underline"),
                        cursor="hand2")
        have.pack(side="left")
        have.bind("<Button-1>", lambda e: self._signin(new=False))
        tk.Label(row, text="\u00b7", bg=SURFACE, fg=MUTED,
                 font=ui(10)).pack(side="left", padx=px(10))
        link = tk.Label(row, text="Continue without signing in", bg=SURFACE,
                        fg=MUTED, font=ui(10, "underline"), cursor="hand2")
        link.pack(side="left")
        self.status = tk.Label(top, text=self._status_text[0] or " ",
                               bg=SURFACE, fg=self._status_text[1],
                               font=ui(10), wraplength=px(640))
        self.status.pack(pady=(px(8), 0))
        link.bind("<Button-1>", lambda e: self._skip())
        link.bind("<Enter>", lambda e: link.configure(fg=TEXT))
        link.bind("<Leave>", lambda e: link.configure(fg=MUTED))

        # what an account gives you
        rule = tk.Frame(f, bg=SURFACE)
        rule.pack(fill="x", padx=px(SIDE), pady=(px(14), px(10)))
        tk.Frame(rule, bg=LINE, height=1).pack(side="left", fill="x",
                                               expand=True, pady=px(1))
        tk.Label(rule, text="What you get with an account", bg=SURFACE,
                 fg=TEXT, font=semi(11)).pack(side="left", padx=px(12))
        tk.Frame(rule, bg=LINE, height=1).pack(side="left", fill="x",
                                               expand=True, pady=px(1))

        grid = tk.Frame(f, bg=SURFACE)
        grid.pack(fill="x", padx=px(SIDE))
        gap = px(14)
        tile_w = (cw - 2 - 2 * px(SIDE) - gap) // 2
        img_w = 0 if compact else px(IMG_W)
        for i, (pic, title, body) in enumerate(TILES):
            tile = tk.Frame(grid, bg=SOFT, highlightbackground=LINE,
                            highlightthickness=1, width=tile_w)
            tile.grid(row=i // 2, column=i % 2, sticky="nsew",
                      padx=(0, gap) if i % 2 == 0 else 0,
                      pady=(0, px(10)))
            if not compact:
                im = self._image(pic, px(IMG_W), px(IMG_H))
                if im:
                    tk.Label(tile, image=im, bg=SURFACE, bd=0).pack(
                        side="left", fill="y")
                    tk.Frame(tile, bg=LINE, width=1).pack(side="left",
                                                          fill="y")
            col = tk.Frame(tile, bg=SOFT)
            col.pack(side="left", fill="both", expand=True,
                     padx=px(14), pady=px(8))
            inner = tk.Frame(col, bg=SOFT)
            inner.pack(expand=True, anchor="w")
            tk.Label(inner, text=title, bg=SOFT, fg=TEXT, font=semi(11),
                     justify="left", anchor="w",
                     wraplength=max(px(120), tile_w - img_w - px(44))
                     ).pack(anchor="w")
            tk.Label(inner, text=body, bg=SOFT, fg="#3d3a33", font=ui(9),
                     justify="left", anchor="w",
                     wraplength=max(px(120), tile_w - img_w - px(44))
                     ).pack(anchor="w", pady=(px(3), 0))
        grid.columnconfigure(0, weight=1, uniform="t")
        grid.columnconfigure(1, weight=1, uniform="t")

        tk.Label(f, text="It's free, with no game limits. You can sign in "
                         "later from the button at the top right.",
                 bg=SURFACE, fg=MUTED, font=ui(9)).pack(
            pady=(px(2), px(12)))

    # ----------------------------------------------------------- the clicks
    def _signin(self, new=False):
        """new: the person has no account yet, so the browser opens on
        the sign-up form."""
        try:
            self.on_signin(new=new)
        except TypeError:
            self.on_signin()             # an on_signin that takes nothing
        except Exception:
            pass

    def _skip(self):
        try:
            self.on_skip()
        except Exception:
            pass

    # ------------------------------------------------------------- pictures
    def _image(self, name, w, h):
        """A bundled picture at w x h pixels, or None. The files are kept
        at twice the size they are shown at, and scaled with OpenCV (which
        the app already carries) so they stay sharp at any screen scale."""
        key = (name, w, h)
        if key in self._imgs:
            return self._imgs[key]
        img = None
        try:
            path = self.asset(name)
            if path.exists():
                img = self._scaled(path, w, h)
        except Exception:
            img = None
        self._imgs[key] = img
        return img

    @staticmethod
    def _scaled(path, w, h):
        try:
            import cv2
            import numpy as np
            a = cv2.imdecode(np.fromfile(str(path), np.uint8),
                             cv2.IMREAD_UNCHANGED)
            a = cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", a)
            if ok:
                return tk.PhotoImage(
                    data=base64.b64encode(buf.tobytes()).decode("ascii"))
        except Exception:
            pass
        # no OpenCV: let Tk do it, in whole-number steps
        im = tk.PhotoImage(file=str(path))
        f = Fraction(w, im.width()).limit_denominator(4)
        if f.numerator > 1:
            im = im.zoom(f.numerator)
        if f.denominator > 1:
            im = im.subsample(f.denominator)
        return im
