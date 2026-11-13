"""
The Windows tray icon, for "Minimise to the tray" in Settings.

With that setting on, minimising the window or closing it with the X
hides it instead, and Full Bench keeps recording matches. The icon by
the clock opens the window again (click it, or Open in its menu) and
Quit there closes the app for real.

The icon is drawn by pystray, on a thread of its own. Nothing here
touches Tk: every click is handed to `call`, which the window uses to
run it on its own thread.

If pystray isn't in this build the tray is simply not available, and the
window minimises and closes the way it always did.
"""
import sys

WINDOWS = sys.platform == "win32"


def _load():
    """(pystray, PIL.Image), or None when this build has no tray."""
    if not WINDOWS:
        return None
    try:
        import pystray
        from PIL import Image
        return pystray, Image
    except Exception:
        return None


def available():
    return _load() is not None


class Tray:
    def __init__(self, icon_path, title, on_open, on_quit, call,
                 load=_load, log=None):
        """
        icon_path: the .ico to show.
        on_open, on_quit: what the icon's menu does.
        call(fn): run fn on the window's thread.
        """
        self.icon_path = str(icon_path)
        self.title = title
        self.on_open = on_open
        self.on_quit = on_quit
        self.call = call
        self._load = load
        self.log = log or (lambda *_: None)
        self.icon = None

    @property
    def shown(self):
        return self.icon is not None

    def show(self):
        """Put the icon by the clock. True if it's there."""
        if self.icon is not None:
            return True
        mods = self._load()
        if not mods:
            return False
        pystray, Image = mods
        try:
            image = Image.open(self.icon_path)
            menu = pystray.Menu(
                # default=True: a click on the icon itself opens the window
                pystray.MenuItem("Open Full Bench",
                                 lambda *_: self.call(self.on_open),
                                 default=True),
                pystray.MenuItem("Quit",
                                 lambda *_: self.call(self.on_quit)))
            icon = pystray.Icon("FullBench", image, self.title, menu)
            icon.run_detached()
            self.icon = icon
            return True
        except Exception as e:
            self.log(f"tray: couldn't show the icon: {e}")
            self.icon = None
            return False

    def tell(self, message):
        """A balloon from the icon. Quietly nothing if Windows won't."""
        if self.icon is None:
            return
        try:
            self.icon.notify(message, self.title)
        except Exception:
            pass

    def hide(self):
        """Take the icon away (the setting was turned off, or quitting)."""
        icon, self.icon = self.icon, None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass
