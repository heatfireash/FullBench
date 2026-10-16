"""
The macOS side of Full Bench: everything the Windows build does through
Windows itself, done the Mac way.

  * finding the game's window      CGWindowListCopyWindowInfo
  * seeing it                       ScreenCaptureKit (macOS 14+), or
                                    CGWindowListCreateImage on older Macs
  * clicking Battle Log and copy    CGEvent mouse events
  * telling a fresh copy from old   NSPasteboard's change count
  * permissions                     Screen Recording and Accessibility

Only the game's own window is captured, never the rest of the screen,
and the pictures are only held in memory while the buttons are looked
for. Nothing is saved or sent anywhere.

Coordinates are in points (what macOS calls screen units): window
positions, clicks and the pictures handed to the rest of the app all
use them, so a Retina screen needs no conversions anywhere else.
ScreenCaptureKit captures the window at its full Retina resolution,
because asked for a smaller picture it can hand back just a corner of
the window instead of shrinking it; grab() then scales it to points.

Needs pyobjc (pip install pyobjc-framework-Quartz
pyobjc-framework-ScreenCaptureKit pyobjc-framework-CoreMedia
pyobjc-framework-ApplicationServices pyobjc-framework-libdispatch).

One rule: nothing here may create the NSApplication. Tk creates its own
(a subclass), and if pyobjc made a plain one first, Tk would break. The
calls used here -- window lists, events, the pasteboard, running
applications -- don't need it.
"""

import os
import platform
import subprocess
import threading
import time
import unicodedata

import numpy as np
import objc
import Quartz
from AppKit import (NSPasteboard, NSRunningApplication, NSWorkspace)

# The Mac App Store and the direct download both use this bundle id.
GAME_BUNDLE_IDS = ("com.pokemon.pokemontcgl",)
GAME_NAME = "pokemon tcg live"

# Privacy & Security panes, for the buttons that open them.
SETTINGS_SCREEN = ("x-apple.systempreferences:"
                   "com.apple.preference.security?Privacy_ScreenCapture")
SETTINGS_INPUT = ("x-apple.systempreferences:"
                  "com.apple.preference.security?Privacy_Accessibility")

FPS = 12                     # frames a second while the game is open
STALE_S = 90.0               # no frame at all for this long: start over
# The game was out of sight (another Space, or full screen and the player
# switched away) for at least this long and no frame came in meanwhile:
# start the stream again rather than trust it to pick up where it was.
AWAY_S = 1.0
SCK_RETRY_S = 30             # after ScreenCaptureKit fails, try it again


def _pooled(fn):
    """
    Run fn inside an autorelease pool. These are called from a worker
    thread several times a second for hours; without a pool there,
    everything macOS hands back would pile up until the thread ends.
    """
    import functools

    @functools.wraps(fn)
    def run(*a, **k):
        with objc.autorelease_pool():
            return fn(*a, **k)
    return run


def _norm(text):
    """'Pokémon TCG Live' -> 'pokemon tcg live'."""
    t = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def macos_version():
    try:
        return tuple(int(p) for p in platform.mac_ver()[0].split(".")[:2])
    except ValueError:
        return (0, 0)


# ------------------------------------------------------------ permissions

def screen_access(ask=False):
    """
    Screen Recording permission, which macOS needs before anything can
    see another app's window. ask=True shows macOS's own request (once;
    after that only System Settings can change it).
    """
    try:
        if Quartz.CGPreflightScreenCaptureAccess():
            return True
        if ask:
            Quartz.CGRequestScreenCaptureAccess()
    except Exception:
        return True          # too old a macOS to ask: it just works
    return False


def input_access(ask=False):
    """Accessibility permission, which macOS needs before an app may
    click for you. ask=True shows macOS's prompt."""
    try:
        from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                         kAXTrustedCheckOptionPrompt)
        return bool(AXIsProcessTrustedWithOptions(
            {kAXTrustedCheckOptionPrompt: bool(ask)}))
    except Exception:
        return False


def open_settings(which):
    """Open System Settings at the Screen Recording or Accessibility
    list. which: "screen" or "input"."""
    url = SETTINGS_SCREEN if which == "screen" else SETTINGS_INPUT
    try:
        subprocess.Popen(["open", url])
    except OSError:
        pass


# ---------------------------------------------------------------- windows

_game_pids = {}              # pid -> (is the game, bundle id)


def _is_game(pid, owner):
    """Whether a window's owner is PTCGL. A browser tab or a Finder
    window with the game's name in it belongs to another app, so it's
    the owning app that's checked, never a title."""
    if pid == os.getpid():
        return False, ""
    if pid in _game_pids:
        return _game_pids[pid]
    bid = ""
    try:
        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        bid = (app.bundleIdentifier() or "") if app else ""
    except Exception:
        pass
    if bid:
        ok = bid in GAME_BUNDLE_IDS
    else:
        # no bundle id to go on: only an app named exactly like the game
        ok = _norm(owner).strip() == GAME_NAME
    _game_pids[pid] = (ok, bid)
    return ok, bid


class MacWindow:
    """
    The game's window, in the shape the rest of the app expects from
    pygetwindow on Windows: left, top, width, height, title, visible,
    activate().
    """

    def __init__(self, info, bundle_id=""):
        b = info.get(Quartz.kCGWindowBounds) or {}
        self.left = int(round(b.get("X", 0)))
        self.top = int(round(b.get("Y", 0)))
        self.width = int(round(b.get("Width", 0)))
        self.height = int(round(b.get("Height", 0)))
        self.window_id = int(info.get(Quartz.kCGWindowNumber, 0))
        self.pid = int(info.get(Quartz.kCGWindowOwnerPID, 0))
        self.title = str(info.get(Quartz.kCGWindowOwnerName) or "")
        # off-screen windows don't carry the key at all
        self.visible = bool(info.get(Quartz.kCGWindowIsOnscreen, False))
        self.bundle_id = bundle_id

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    def activate(self):
        bring_to_front(self.pid)

    def __repr__(self):
        return (f"<MacWindow {self.title!r} id={self.window_id} pid={self.pid}"
                f" {self.width}x{self.height}+{self.left}+{self.top}>")


def _window_list(on_screen):
    opts = Quartz.kCGWindowListExcludeDesktopElements
    if on_screen:
        opts |= Quartz.kCGWindowListOptionOnScreenOnly
    try:
        return Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) \
            or []
    except Exception:
        return []


@_pooled
def game_window(require_visible=False, pid=None):
    """
    The game's main window, or None. pid picks a window by its owner
    instead (the self-test's stand-in game).

    Normal windows sit at layer 0; a full-screen game might not, so a
    window a little above that counts when there's nothing at 0. Menus,
    the menu bar and the Dock are far higher and never count.
    """
    best, best_area, best_layer = None, 0, None
    for info in _window_list(on_screen=require_visible):
        layer = int(info.get(Quartz.kCGWindowLayer, 0))
        if not 0 <= layer < 20:
            continue
        owner_pid = int(info.get(Quartz.kCGWindowOwnerPID, 0))
        if pid is not None:
            if owner_pid != pid:
                continue
            bid = ""
        else:
            ok, bid = _is_game(owner_pid, info.get(Quartz.kCGWindowOwnerName))
            if not ok:
                continue
        w = MacWindow(info, bid)
        if w.width < 200 or w.height < 150:
            continue                       # splash screens, tool windows
        better = (best is None or (layer == 0) > (best_layer == 0)
                  or ((layer == 0) == (best_layer == 0)
                      and w.width * w.height > best_area))
        if better:
            best, best_area, best_layer = w, w.width * w.height, layer
    return best


@_pooled
def frontmost_pid():
    """The app whose window is frontmost, read from the window list (which
    is always current, unlike NSWorkspace off the main thread)."""
    for info in _window_list(on_screen=True):
        if info.get(Quartz.kCGWindowLayer, 0) == 0:
            return int(info.get(Quartz.kCGWindowOwnerPID, 0))
    return None


def bring_to_front(pid, wait=0.4):
    """Make the game the active app, if it isn't, and wait for it."""
    if not pid or frontmost_pid() == pid:
        return True
    try:
        with objc.autorelease_pool():
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(
                pid)
            if app is None:
                return False
            # 1 << 1 = NSApplicationActivateIgnoringOtherApps. From macOS 14
            # an app that isn't itself in front may be refused; asking the
            # system to open the (already running) game brings it forward.
            if not app.activateWithOptions_(1 << 1):
                url = app.bundleURL()
                if url is not None:
                    from AppKit import NSWorkspaceOpenConfiguration
                    cfg = NSWorkspaceOpenConfiguration.configuration()
                    cfg.setActivates_(True)
                    NSWorkspace.sharedWorkspace(). \
                        openApplicationAtURL_configuration_completionHandler_(
                            url, cfg, None)
    except Exception:
        return False
    deadline = time.time() + wait
    while time.time() < deadline:
        if frontmost_pid() == pid:
            return True
        time.sleep(0.03)
    return False


# ---------------------------------------------------------------- capture

def _bgr_from_cgimage(img):
    """A CGImage as a BGR numpy array."""
    w, h = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    if Quartz.CGImageGetBitsPerPixel(img) != 32:
        raise RuntimeError("unexpected picture format from macOS")
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    arr = np.frombuffer(bytes(data), dtype=np.uint8)
    arr = arr[:bpr * h].reshape(h, bpr)[:, :w * 4].reshape(h, w, 4)
    return np.ascontiguousarray(arr[:, :, :3])


def _grab_cg(win):
    """
    One picture of the window, the older way. Fine on macOS 12 and 13;
    newer versions slow it down on purpose, which is why it's only the
    fallback there.
    """
    img = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull, Quartz.kCGWindowListOptionIncludingWindow,
        win.window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming
        | Quartz.kCGWindowImageNominalResolution)
    if img is None:
        raise RuntimeError("could not capture the game window "
                           "(Screen Recording permission?)")
    return _bgr_from_cgimage(img)


_SINK_CLASS = None


def _sink_class():
    """The object ScreenCaptureKit hands frames to. Objective-C classes
    can only be defined once per process, so it's made on first use."""
    global _SINK_CLASS
    if _SINK_CLASS is not None:
        return _SINK_CLASS
    import ScreenCaptureKit as SCK
    from Foundation import NSObject

    class FullBenchFrameSink(NSObject):
        def init(self):
            self = objc.super(FullBenchFrameSink, self).init()
            if self is None:
                return None
            self.lock = threading.Lock()
            self.buf = None
            self.seq = 0
            self.at = 0.0
            self.dead = False
            return self

        # as the stream's delegate: macOS stopped it (window closed, ...)
        def stream_didStopWithError_(self, stream, error):
            self.dead = True

        def stream_didOutputSampleBuffer_ofType_(self, stream, sbuf, kind):
            if kind != SCK.SCStreamOutputTypeScreen:
                return
            if not _frame_complete(sbuf):
                return      # "idle": nothing changed, keep the last one
            with self.lock:
                self.buf = sbuf
                self.seq += 1
                self.at = time.time()

    _SINK_CLASS = FullBenchFrameSink
    return _SINK_CLASS


def _frame_complete(sbuf):
    import CoreMedia
    import ScreenCaptureKit as SCK
    try:
        att = CoreMedia.CMSampleBufferGetSampleAttachmentsArray(sbuf, False)
        if not att:
            return False
        status = att[0].get(SCK.SCStreamFrameInfoStatus)
        return status is not None and int(status) == SCK.SCFrameStatusComplete
    except Exception:
        return False


def _bgr_from_sample(sbuf):
    import CoreMedia
    pb = CoreMedia.CMSampleBufferGetImageBuffer(sbuf)
    if pb is None:
        return None
    Quartz.CVPixelBufferLockBaseAddress(pb, 1)          # read-only
    try:
        h = Quartz.CVPixelBufferGetHeight(pb)
        w = Quartz.CVPixelBufferGetWidth(pb)
        bpr = Quartz.CVPixelBufferGetBytesPerRow(pb)
        base = Quartz.CVPixelBufferGetBaseAddress(pb)
        arr = np.frombuffer(base.as_buffer(bpr * h), dtype=np.uint8)
        arr = arr.reshape(h, bpr)[:, :w * 4].reshape(h, w, 4)
        return np.ascontiguousarray(arr[:, :, :3])       # BGRA -> BGR
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(pb, 1)


def _frame_details(sbuf):
    """What macOS says about a frame: where the window sits in it and at
    what scale. Only for the self-test's report."""
    import CoreMedia
    import ScreenCaptureKit as SCK
    found = {}
    try:
        att = CoreMedia.CMSampleBufferGetSampleAttachmentsArray(sbuf, False)
        att = att[0] if att else {}
        for name in ("ContentRect", "ContentScale", "ScaleFactor"):
            key = getattr(SCK, "SCStreamFrameInfo" + name, None)
            v = att.get(key) if key is not None else None
            if v is None:
                continue
            if hasattr(v, "items"):
                v = " ".join(f"{k}={float(x):g}" for k, x in sorted(v.items()))
            else:
                v = f"{float(v):g}"
            found["frame " + name] = v
    except Exception as e:
        found["frame details"] = f"unreadable ({e})"
    return found


def _wait(fn, timeout=3.0):
    """Call an API that answers through a completion handler, and wait
    for the answer. Returns the handler's arguments."""
    done, out = threading.Event(), []

    def handler(*args):
        out.append(args)
        done.set()

    fn(handler)
    if not done.wait(timeout):
        raise TimeoutError("macOS didn't answer")
    return out[0]


class _Stream:
    """
    A ScreenCaptureKit stream of the game's window: macOS sends a new
    frame whenever the window changes, a dozen times a second at most,
    and the latest one is kept. It captures the window itself, so other
    windows on top of the game don't get in the way.

    size "pixels" (the default) captures at the window's full Retina
    resolution. "points" asks macOS for a point-sized picture with the
    window shrunk to fit it: less work, but it depends on macOS doing the
    shrinking rather than cutting the window off.
    """

    def __init__(self, win, size="pixels"):
        import CoreMedia
        import ScreenCaptureKit as SCK
        import dispatch

        self.window_id = win.window_id
        self.size = (win.width, win.height)
        self.info = {"size asked for": size}
        content, err = _wait(lambda h: SCK.SCShareableContent.
                             getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                                 True, False, h))
        if content is None:
            raise RuntimeError(f"no access to windows: {err}")
        target = None
        for w in content.windows():
            if int(w.windowID()) == self.window_id:
                target = w
                break
        if target is None:
            raise RuntimeError("the game window isn't available to capture")

        filt = SCK.SCContentFilter.alloc().initWithDesktopIndependentWindow_(
            target)
        # the window's size in points and how many pixels a point is, as
        # ScreenCaptureKit sees it (macOS 14+)
        pw, ph, scale = float(win.width), float(win.height), None
        try:
            rect = filt.contentRect()
            scale = float(filt.pointPixelScale())
            if rect.size.width >= 1 and rect.size.height >= 1:
                pw, ph = float(rect.size.width), float(rect.size.height)
            self.info["window per macOS"] = (
                f"{pw:g}x{ph:g} points, {scale:g} pixels a point")
        except Exception as e:
            self.info["window per macOS"] = f"unknown ({e})"
        if not scale or scale < 1:
            scale = _screen_scale()
        if size == "points":
            scale = 1.0
        out_w, out_h = max(1, round(pw * scale)), max(1, round(ph * scale))
        self.info["frame asked for"] = f"{out_w}x{out_h}"

        cfg = SCK.SCStreamConfiguration.alloc().init()
        cfg.setWidth_(out_w)
        cfg.setHeight_(out_h)
        try:
            cfg.setScalesToFit_(True)       # shrink the window, never crop it
        except AttributeError:
            pass
        cfg.setShowsCursor_(False)      # the pointer would spoil the search
        cfg.setPixelFormat_(0x42475241)  # 'BGRA'
        cfg.setMinimumFrameInterval_(CoreMedia.CMTimeMake(1, FPS))
        cfg.setQueueDepth_(5)
        try:
            cfg.setIgnoreShadowsSingleWindow_(True)   # macOS 14+
        except AttributeError:
            pass
        try:
            # plain sRGB, so the gold of Continue reads the same on a wide
            # colour (P3) screen as it does on Windows
            cfg.setColorSpaceName_(Quartz.kCGColorSpaceSRGB)
        except Exception:
            pass

        self.sink = _sink_class().alloc().init()
        self.queue = dispatch.dispatch_queue_create(
            b"gg.fullbench.capture", dispatch.DISPATCH_QUEUE_SERIAL)
        self.stream = SCK.SCStream.alloc().initWithFilter_configuration_delegate_(
            filt, cfg, self.sink)
        ok, err = self.stream.addStreamOutput_type_sampleHandlerQueue_error_(
            self.sink, SCK.SCStreamOutputTypeScreen, self.queue, None)
        if not ok:
            raise RuntimeError(f"could not add the frame handler: {err}")
        try:
            (err,) = _wait(
                lambda h: self.stream.startCaptureWithCompletionHandler_(h))
        except Exception:
            self.stop()
            raise
        if err is not None:
            raise RuntimeError(f"capture refused: {err}")
        self.started = time.time()
        self._seq, self._img = -1, None

    def latest(self):
        """The newest frame as BGR, or None before the first one."""
        with self.sink.lock:
            seq, buf = self.sink.seq, self.sink.buf
        if buf is None:
            return None
        if seq != self._seq:
            self._img, self._seq = _bgr_from_sample(buf), seq
            if "frame received" not in self.info and self._img is not None:
                h, w = self._img.shape[:2]
                self.info["frame received"] = f"{w}x{h}"
                self.info.update(_frame_details(buf))
        return self._img

    def stale(self):
        """macOS stopped the stream. (No new frames on its own just means
        the window hasn't changed, so only a very long silence counts.)"""
        last = self.sink.at or self.started
        return self.sink.dead or time.time() - last > STALE_S

    def stop(self):
        import ScreenCaptureKit as SCK
        try:
            _wait(lambda h: self.stream.stopCaptureWithCompletionHandler_(h),
                  timeout=2.0)
        except Exception:
            pass
        try:
            self.stream.removeStreamOutput_type_error_(
                self.sink, SCK.SCStreamOutputTypeScreen, None)
        except Exception:
            pass


def _screen_scale():
    """Pixels a point on the sharpest screen: the fallback when macOS
    doesn't say for the window itself."""
    try:
        from AppKit import NSScreen
        return max(float(s.backingScaleFactor()) for s in NSScreen.screens())
    except Exception:
        return 2.0


class Capturer:
    """Pictures of the game window, by whichever means this Mac allows."""

    def __init__(self, use_sck=None, size=None):
        self.stream = None
        if use_sck is None:
            use_sck = os.environ.get("FULLBENCH_CAPTURE") != "cg"
        self.use_sck = bool(use_sck) and macos_version() >= (14, 0)
        self.size = size or os.environ.get("FULLBENCH_SCK_SIZE", "pixels")
        self.lock = threading.Lock()
        self.note = ""
        self.retry_at = 0.0
        self.last_call = 0.0      # when the app last asked for a picture
        self.restarts = 0         # streams started again after a return

    def describe(self):
        """How the last ScreenCaptureKit stream was set up, for the
        self-test's report."""
        s = self.stream
        if s is None:
            return ""
        return "; ".join(f"{k}: {v}" for k, v in s.info.items())

    def grab(self, win):
        with self.lock, objc.autorelease_pool():
            if self.use_sck and time.time() >= self.retry_at:
                try:
                    img = self._grab_sck(win)
                    self.note = ""
                    return img
                except Exception as e:
                    # often passing (the game going full screen, its window
                    # not listed yet), so ScreenCaptureKit gets another go
                    # in a while rather than being given up for good
                    self.note = (f"ScreenCaptureKit failed ({e}); using the "
                                 f"older way for {SCK_RETRY_S}s")
                    print(f"[capture] {self.note}")
                    self._stop()
                    self.retry_at = time.time() + SCK_RETRY_S
            return _grab_cg(win)

    def _grab_sck(self, win):
        s = self.stream
        now = time.time()
        away_since, self.last_call = self.last_call, now
        if (s is not None and now - away_since > AWAY_S
                and (s.sink.at or s.started) < away_since):
            # The app stopped looking because the game went out of sight
            # (switched to another Space, or away from its full-screen
            # one), and no frame has come since. A stream of a window
            # that left the screen can stay silent after it comes back,
            # which left the app staring at a picture from before.
            self.restarts += 1
            self._stop()
            s = None
        if s is not None and (s.window_id != win.window_id
                              or abs(s.size[0] - win.width) > 2
                              or abs(s.size[1] - win.height) > 2
                              or s.stale()):
            self._stop()            # a different window, resized, or stuck
            s = None
        if s is None:
            s = self.stream = _Stream(win, self.size)
        img = s.latest()
        deadline = time.time() + 1.0
        while img is None and time.time() < deadline:
            time.sleep(0.03)        # the first frame of a new stream
            img = s.latest()
        if img is None:
            raise RuntimeError("no frame from the game window yet")
        return img

    def _stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream = None

    def release(self):
        """Stop capturing (tracking stopped, or the game closed)."""
        with self.lock:
            self._stop()


_capturer = Capturer()


def fit(img, win):
    """A capture scaled to the window's size in points."""
    h, w = img.shape[:2]
    if (w, h) != (win.width, win.height) and win.width > 0 and win.height > 0:
        import cv2
        img = cv2.resize(img, (win.width, win.height),
                         interpolation=cv2.INTER_AREA)
    return img


def grab(win):
    """The game window, BGR, sized width x height in points."""
    return fit(_capturer.grab(win), win)


def release_capture():
    _capturer.release()


# ------------------------------------------------------------------ input

def _post_mouse(kind, x, y):
    ev = Quartz.CGEventCreateMouseEvent(None, kind, (x, y),
                                        Quartz.kCGMouseButtonLeft)
    if kind in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState, 1)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


@_pooled
def click(x, y, pid=None):
    """
    Click at a screen point, as a real mouse would: move there, let the
    game see it arrive, press, release.

    Each event carries its own position, so the press and release land
    on the button even if the player's mouse is moving. The pointer is
    also put back on the button just before the press.
    """
    if pid:
        bring_to_front(pid)
    _post_mouse(Quartz.kCGEventMouseMoved, x, y)
    time.sleep(0.05)
    try:
        # puts the pointer back if the player moved it in the last 50ms,
        # and holds off their mouse for a moment while the click happens
        Quartz.CGWarpMouseCursorPosition((x, y))
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    except Exception:
        pass
    _post_mouse(Quartz.kCGEventMouseMoved, x, y)
    time.sleep(0.04)
    _post_mouse(Quartz.kCGEventLeftMouseDown, x, y)
    time.sleep(0.06)
    _post_mouse(Quartz.kCGEventLeftMouseUp, x, y)
    time.sleep(0.05)


def move(x, y):
    """Move the pointer to a screen point, as a mouse move the game sees.
    No click."""
    _post_mouse(Quartz.kCGEventMouseMoved, x, y)
    try:
        Quartz.CGWarpMouseCursorPosition((x, y))
        Quartz.CGAssociateMouseAndMouseCursorPosition(True)
    except Exception:
        pass


_KEYS = {"a": 0, "c": 8}
_CMD = 55


@_pooled
def command_key(letter):
    """Cmd+letter, for the select-all / copy fallback: Command pressed,
    the letter, Command released, as a person would type it."""
    def post(code, down, flags):
        ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.02)
    cmd = Quartz.kCGEventFlagMaskCommand
    post(_CMD, True, cmd)
    post(_KEYS[letter], True, cmd)
    post(_KEYS[letter], False, cmd)
    post(_CMD, False, 0)


# -------------------------------------------------------------- clipboard

@_pooled
def clipboard_count():
    """Goes up every time anything is copied, even the same text again --
    the Mac's version of Windows' clipboard sequence number."""
    try:
        return int(NSPasteboard.generalPasteboard().changeCount())
    except Exception:
        return None


# ---------------------------------------------------------- overlay help

class NativePanel:
    """
    A cover or note drawn by macOS itself instead of Tk: an NSPanel that
    never takes focus and is allowed into every Space, a full-screen
    game's included. Tk's own windows are ordinary windows that macOS
    keeps on the desktop. Main thread only (Tk's thread).
    """

    def __init__(self, colour=(0.85, 0.12, 0.12), alpha=0.85,
                 text="", text_size=15):
        from AppKit import (NSPanel, NSColor, NSTextField, NSFont,
                            NSMakeRect, NSBackingStoreBuffered)
        borderless, nonactivating = 0, 1 << 7
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(-10000, -10000, 10, 10), borderless | nonactivating,
            NSBackingStoreBuffered, False)
        p = self.panel
        p.setFloatingPanel_(True)
        p.setHidesOnDeactivate_(False)
        p.setBecomesKeyOnlyIfNeeded_(True)
        p.setIgnoresMouseEvents_(False)       # the cover has to block clicks
        # above full-screen apps: the level menu-bar extras and HUDs use
        p.setLevel_(1000)                     # NSScreenSaverWindowLevel
        # all Spaces (1), stationary (16), out of Cmd-` (64), may sit over a
        # full-screen app (256)
        p.setCollectionBehavior_(1 | 16 | 64 | 256)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(
            colour[0], colour[1], colour[2], alpha))
        self.label = NSTextField.labelWithString_(text)
        self.label.setTextColor_(NSColor.whiteColor())
        self.label.setFont_(NSFont.boldSystemFontOfSize_(text_size))
        self.label.setAlignment_(1)           # centred
        p.contentView().addSubview_(self.label)

    def show(self, rect, text=None):
        """rect: (x, y, w, h) in screen points, measured from the top
        left like everything else in the app."""
        from AppKit import NSMakeRect, NSScreen
        x, y, w, h = rect
        top = NSScreen.screens()[0].frame().size.height
        self.panel.setFrame_display_(NSMakeRect(x, top - y - h, w, h), True)
        if text is not None:
            self.label.setStringValue_(text)
        self.label.sizeToFit()
        lw, lh = self.label.frame().size.width, self.label.frame().size.height
        self.label.setFrameOrigin_(((w - lw) / 2, (h - lh) / 2))
        self.panel.orderFrontRegardless()

    def hide(self):
        self.panel.orderOut_(None)

    def on_screen(self):
        try:
            return bool(self.panel.isOnActiveSpace()) and \
                bool(self.panel.isVisible())
        except Exception:
            return None


_menu_target_cls = None


def _menu_target_class():
    """An Objective-C object for the menu bar menu to call back into. Made
    once: a class name can only be registered with macOS one time."""
    global _menu_target_cls
    if _menu_target_cls is None:
        from Foundation import NSObject

        class FullBenchMenuTarget(NSObject):
            def initWithActions_(self, actions):
                self = objc.super(FullBenchMenuTarget, self).init()
                if self is None:
                    return None
                self.actions = actions
                return self

            def run_(self, sender):
                fn = self.actions.get(int(sender.tag()))
                if fn:
                    fn()

        _menu_target_cls = FullBenchMenuTarget
    return _menu_target_cls


class StatusItem:
    """
    Full Bench's icon in the menu bar, at the top right of the screen. As
    a menu-bar app it has no Dock icon, so this is how its window is
    opened again and how it's quit. Main thread only.

    items: [(title, callback)], in menu order; None for a separator line.
    """

    def __init__(self, items, icon_path=None, tooltip="Full Bench"):
        from AppKit import (NSStatusBar, NSMenu, NSMenuItem, NSImage)
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(-1.0)
        button = self.item.button()
        img = None
        if icon_path:
            try:
                img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                if img is not None:
                    img.setSize_((18, 18))
            except Exception:
                img = None
        if img is not None:
            button.setImage_(img)
        else:
            button.setTitle_("FB")
        button.setToolTip_(tooltip)

        actions = {}
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        for i, entry in enumerate(items):
            if entry is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            title, fn = entry
            mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "run:", "q" if title.startswith("Quit") else "")
            mi.setTag_(i)
            actions[i] = fn
            menu.addItem_(mi)
        self.target = _menu_target_class().alloc().initWithActions_(actions)
        for mi in menu.itemArray():
            if not mi.isSeparatorItem():
                mi.setTarget_(self.target)
        self.item.setMenu_(menu)
        self.menu = menu

    def remove(self):
        try:
            from AppKit import NSStatusBar
            NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        except Exception:
            pass


def activate_self():
    """Make Full Bench the active app, so its window can be typed in. A
    menu-bar app isn't made active just by showing a window."""
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    except Exception:
        pass


def set_accessory(on):
    """
    Accessory: no Dock icon and no menu bar, like a menu-bar app. macOS
    only lets an app's windows appear over another app's full-screen
    Space when the app is one of these; an ordinary app's windows stay
    behind on the desktop however they're set up. It has to be set
    before the cover and pop-ups are first shown: switching later leaves
    them on the desktop (tested on macOS 26 with PTCGL full screen).
    Returns True if macOS took it.
    """
    try:
        from AppKit import NSApplication
        # NSApplicationActivationPolicyAccessory = 1, Regular = 0
        return bool(NSApplication.sharedApplication().setActivationPolicy_(
            1 if on else 0))
    except Exception:
        return False


def float_window(tk_window):
    """
    Keep one of the app's small Tk windows (the cover over Continue, the
    pop-ups) above the game, including when the game is full screen in
    its own Space. Main thread only, after the window exists.
    """
    try:
        from AppKit import NSApplication
        app = NSApplication.sharedApplication()   # Tk's, already made
        token = f"fullbench-overlay-{id(tk_window)}"
        old = tk_window.title()
        tk_window.title(token)
        tk_window.update_idletasks()
        target = None
        for w in app.windows():
            if str(w.title() or "") == token:
                target = w
                break
        tk_window.title(old or "")
        if target is None:
            return False
        target.setLevel_(101)                  # NSPopUpMenuWindowLevel
        # can join all Spaces (1), ignores Cmd-` (64), can sit over a
        # full-screen app (256)
        target.setCollectionBehavior_(1 | 64 | 256)
        target.setHidesOnDeactivate_(False)
        # bring it forward without making Full Bench the active app
        target.orderFrontRegardless()
        return True
    except Exception:
        return False
