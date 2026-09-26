# Full Bench

Stat tracker for Pokemon TCG Live. Records your matches automatically
from the game's own post-match battle log — win rate by deck, matchups,
going first vs. second, mulligans, all of it — and optionally syncs to
[fullbench.gg](https://fullbench.gg) so two computers share one history
and you can see global deck stats across everyone using it.

**[Download the Windows build](https://fullbench.gg/download)** —
or build it yourself from this source, see below.

## Why this exists

Playing PTCGL and not knowing your actual win rate with a deck, or
whether going first is really the edge it feels like, got annoying
enough to fix. This is that fix.

## How it works, and what it doesn't do

Pokemon TCG Live shows a **Battle Log** after every match — every card
played, the result, prizes, all of it, in plain text. Full Bench watches
your clipboard for that text, parses it, and stores the result. A small
screen-watcher clicks the game's own "Battle Log" and copy buttons for
you so there's nothing to remember.

That's the whole trick. It does **not**:

- read the game's memory
- intercept or decrypt network traffic
- modify the client in any way
- see anything before the match ends — the log doesn't exist until then,
  so there's no way for this to show you an opponent's hand or deck
  early. If that's not obvious from the code, that's worth an issue.

Everything the app does to your screen is: watch the clipboard, and
click two buttons on the result screen. `autocopy.py` and `overlay.py`
are the whole surface area for that.

## About the Windows warning

The .exe isn't code-signed — that costs money I haven't spent on a
free hobby project yet — so Windows SmartScreen will say "Windows
protected your PC." Click **More info → Run anyway**. It's not flagged
as malware, just unsigned. This is exactly the situation this repo
exists to help with: don't take my word for it, read the source.

## Running from source

```powershell
py -m pip install pyperclip mss opencv-python-headless numpy pygetwindow pydirectinput pillow
py ptcgl_gui.py
```

Windows only. `pydirectinput` and `pygetwindow` are Windows-specific;
this hasn't been ported to macOS or Linux.

### Building the .exe yourself

```powershell
py -m pip install pyinstaller
py build.py
```

Produces `dist/FullBench.exe`. `build.py` checks every dependency is
importable in the interpreter you're building with before it starts,
so a missing package fails loudly instead of producing a broken exe.

## What's in here

| | |
|---|---|
| `ptcgl_gui.py` | the desktop app |
| `ptcgl_tracker.py` | clipboard watcher, storage, deck naming |
| `ptcgl_parse.py` | the battle log parser |
| `autocopy.py` | screen detection, clicks the game's own buttons |
| `overlay.py` | the "don't press Continue yet" cover |
| `cluster.py` | works out deck archetypes from cards actually played |
| `cloud.py` | optional sync to a Full Bench server |
| `ptcgl_stats.py` | command-line stats, `--reparse`, `--unclassified` |

Full docs on parsing, deck naming, duplicate detection and sync are in
[`FULLBENCH.md`](FULLBENCH.md).

This repo is the desktop app only. The fullbench.gg server isn't
published — its anti-spam and data-validation checks work better when
nobody can read exactly what they look for. Sync is optional and off
until you sign in; `cloud.py` is the complete record of what gets sent.
Player names are stripped from logs before upload (`pseudonymise()` in
`ptcgl_parse.py`). The server keeps each log, without names, so you can
read your games back on the website; only your own account can open
them.

## Contributing / reporting a bug

Open an issue. If the deck-naming logic gets something wrong, include
the raw battle log if you can (from `~/ptcgl_logs/`, or the `Matches`
tab's "not counted" list) — that's the fastest way to fix it.

## License

Not produced by, endorsed by, or affiliated with Pokemon, Nintendo,
Game Freak or Creatures. "Full Bench" and its logo are original work;
this project reads publicly-displayed game text and links to public
card sprite assets, and claims no ownership of Pokemon's IP.
