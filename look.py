"""
The app's fonts.

Segoe UI on Windows. A Mac doesn't have it, and Tk would quietly swap in
something else at a different size, so there it's Helvetica Neue, with
bold standing in for Segoe UI Semibold.

Numbers are monospaced, as on fullbench.gg, so they line up: Consolas on
Windows, Menlo on a Mac -- both come with the system.
"""

import sys

MAC = sys.platform == "darwin"
FAMILY = "Helvetica Neue" if MAC else "Segoe UI"


def ui(size, *style):
    """Body text: ui(9), ui(8, "bold")."""
    return (FAMILY, size) + style


def semi(size, *style):
    """Headings and values: Segoe UI Semibold, or bold on a Mac."""
    if MAC:
        return (FAMILY, size) + (() if "bold" in style else ("bold",)) + style
    return ("Segoe UI Semibold", size) + style


def num(size, *style):
    """A number: num(22) for a stat card's value."""
    return ("Menlo" if MAC else "Consolas", size, "bold") + style
