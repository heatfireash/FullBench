# Full Bench

Stat tracker for Pokémon TCG Live. Records your matches automatically and keeps the numbers.

It works from the game's own post-match **Battle Log**. Nothing reads the
game's memory or network traffic, nothing is injected into the client.
The only automation is clicking the Battle Log and copy buttons for you,
on the result screen, so you don't have to remember.

## Files

| file | what it does |
|---|---|
| `FullBench.exe` | **start here** — the app (built with `build.py`) |
| `ptcgl_gui.py` | the GUI, if running from source |
| `ptcgl.py` | command-line runner, no GUI |
| `ptcgl_tracker.py` | watches the clipboard, parses logs, stores matches |
| `ptcgl_parse.py` | the battle log parser |
| `autocopy.py` | watches the game window, clicks Battle Log → copy |
| `ptcgl_stats.py` | reads the database: win rates, matchups, recent games |
| `selftest.py` | checks the templates match your screen without clicking |
| `build.py` | packages everything into a single .exe |
| `make_logo.py` | regenerates `icon.ico` / `logo.png` |
| `overlay.py` | the "don't press Continue" banner |
| `settings.py` | settings file and Windows startup entry |
| `game_watch.py` | detects whether PTCGL is running |
| `battlelog_button.png` | template: the BATTLE LOG button |
| `copy_button.png` | template: the export icon inside the log panel |
| `continue_button.png` | template: CONTINUE — confirms it's the result screen |
| `calibration.json` | your window size, written by `--calibrate` |

Put all of them in one folder.

## Building the exe

The packages must be installed **on the machine you build on**, into the
same Python you build with. PyInstaller bundles what it can import; it
does not install anything. Miss this and the exe builds fine, then asks
the user to `pip install pyperclip` when they run it.

```powershell
py -m pip install pyinstaller pyperclip mss opencv-python-headless numpy pygetwindow pydirectinput pillow
py build.py
```

`build.py` checks for all of them first and refuses to build rather than
producing a broken exe.

Produces `dist\FullBench.exe`. The button templates are bundled
inside it; a re-cropped PNG placed beside the exe overrides the bundled
one.

## Running from source instead

```powershell
pip install pyperclip mss opencv-python-headless numpy pygetwindow pydirectinput
py ptcgl_gui.py
```

The three `.png` templates were cropped from a 2560×1440 window. They
should match other sizes too (tested 720p–4K). If `selftest.py` reports
a low score, re-crop from a fresh `--calibrate` screenshot.

## Run

Double-click **FullBench.exe**, press **Start tracking**, and play.
Both decks are detected from the battle log — nothing to type in.

Windows SmartScreen will warn the first time, because the exe isn't
code-signed: *More info* → *Run anyway*.

Tabs:

- **Dashboard** — pick a deck from the dropdown to filter every stat:
  record, win rate, going first / going second, mulligans, and the
  matchup breakdown for that deck. Win rates are green at 50% or above,
  red below
- **Matches** — every game; click one to see the cards both players showed
- **Settings** — startup and auto-tracking options
- **Activity** — hidden unless **Developer mode** is ticked in Settings;
  a live log of what the watchers are doing

From source instead: `py ptcgl_gui.py`, or `py ptcgl.py` for the
command-line version.

After each match it will:

1. detect the result screen
2. click BATTLE LOG, then the copy icon
3. parse the log off the clipboard and file it

Both decks, yours and your opponent's, are named from the cards played
-- see "How decks get named" below.

Clipboard-only mode (you copy the log yourself):

```powershell
py ptcgl.py --no-autocopy
```

## Stats

```powershell
py ptcgl_stats.py               # summary, play/draw split, prize diff
py ptcgl_stats.py --decks       # by your deck
py ptcgl_stats.py --matchups    # by opponent archetype
py ptcgl_stats.py --recent 20
py ptcgl_stats.py --export csv
```

## Where things go

- `~\ptcgl_matches.db` — SQLite, one row per match
- `~\ptcgl_logs\` — raw battle log text, one file per match

Keep the raw logs. When the parser improves, rebuild everything from
them:

```powershell
py ptcgl_stats.py --reparse
```

## When something's off

**Rows with missing fields** — `py ptcgl_stats.py --unparsed` lists
them and points at the raw log. Those are log variants the parser
hasn't seen yet (concessions, deckouts, ties). Send one and it gets
fixed; `--reparse` then backfills.

**The exe says "pip install pyperclip"** — it was built on a machine
where that package wasn't installed, so it never made it into the exe.
Install the packages listed under *Building the exe* and build again.
The finished exe needs nothing installed on the machines you copy it to.

**"table matches has no column named ..."** — your database was made by
an older build. It upgrades itself now: just start the app again. Then
run `py ptcgl_stats.py --reparse` to fill the new columns in from your
saved logs. No match history is lost.

**Nothing gets captured** — problems appear next to the app title
whether or not Developer mode is on. Tick **Developer mode** in Settings
to see the Activity tab and the full log. On a result screen you can also
run `py selftest.py`.
It prints match scores for each template and saves
`~\ptcgl_selftest.png` with a red circle where it would click.

**Click lands in the wrong place** — usually Windows display scaling
on a multi-monitor setup. The script sets DPI awareness; if that isn't
enough, set both monitors to the same scaling as a test.

**A match wasn't captured** — you pressed Continue before the copy
finished. Capture takes roughly 0.6s from the result screen appearing;
a red bar reading DON'T PRESS CONTINUE covers the top of the screen the
whole time and turns green when the log is safely captured, and the
Continue button itself is covered so the click can't land early.

The cover is a small window over your own screen; it never touches the
game. It clears when the copy finishes, after four seconds regardless,
or if you click it or press Escape — and it can be switched off under
Settings. PTCGL discards the battle log at that point and there is no
way to recover it, so that game is simply lost. The app now shows a red
**"match over - capturing"** banner at the top of the screen the moment
a match ends; wait for it to turn green (about a second) before pressing
Continue. Misses are counted next to the status dot.

**It fires during a game** — it shouldn't: clicking requires the
CONTINUE button to be on screen. If it ever does, stop it and report
what was on screen.

## Hands-off setup

In the **Settings** tab:

- **Start Full Bench when Windows starts** — writes a per-user entry
  under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. No
  admin rights, only your account, and you can also switch it off from
  Task Manager's Startup tab. Nothing is written unless you tick it.
- **Start tracking automatically when PTCGL launches** — on by default.
  The app watches for the game window, falling back to the process list
  so a minimised game still counts, and begins tracking on its own.
- **Stop tracking when PTCGL closes** — on by default.
- **Start minimised** — pair with the two above and you never touch the
  app at all: log in, play, check stats whenever you like.

The Settings tab also shows whether the game is currently detected.

## How decks get named

Automatically, from what was played. While you're signed in, the names
come from fullbench.gg, which groups every player's games together, and
each sync brings them down to the app. Signed out, the app does the same
grouping with just your own games.

The deck is its attacker: games are grouped by which Pokemon led the
damage, then by overlap of the rest, and every group is
named after the Pokemon that does the attacking. A game where your main
attacker never came out still lands under the right name once the group
exists.

A second Pokemon joins the name if it does real work: a quarter of the
damage or more, or an ability fired twice a game or more, whichever is
the stronger claim. A Metang using Metal Maker four times a game earns
"Mega Excadrill ex / Metang"; a Pokemon that is merely present every
game earns nothing.

Engine Pokemon are worked out from the data. Anything seen alongside
several different main attackers -- a Mega Kangaskhan that draws cards
in a dozen decks and attacks in none -- is treated as an engine and
stops counting as evidence of which deck it is. A deck that genuinely
attacks with it stays separate.

Nothing to type, nothing to maintain. New decks name themselves when a
set drops.

There is no renaming. One name per deck, worked out the same way for
everyone, is what lets your stats line up with global stats.

It is sometimes wrong. Two decks sharing an engine can merge; a deck
that shows different Pokemon in different games can split. That shrinks
as more games are recorded.

    py ptcgl_stats.py --merge-decks     # re-run the naming by hand

## Duplicate matches

Every match is keyed on a hash of its battle log, stored in a UNIQUE
column, so recording the same log twice stores one row. That check is a
single indexed lookup — about 0.005 ms with 5,000 matches stored — so it
never needs limiting to recent logs.

Two further guards: the screen watcher will not capture again until the
result screen has been away for 12 seconds, so clicking off it and back
does not re-capture; and a match with the same result, turn count and
prize totals recorded within ten minutes is treated as a rerun, which
catches logs differing only in whitespace.

## Known limits

- Parser has been validated against one real log (a loss on prizes).
- Damage totals are the sum of attack lines, not the game's figure
  (bench splash and ability damage aren't counted).
- Deck names are the headline Pokemon seen, not real archetype names
  ("Mega Excadrill ex" rather than "Metal Box"). Proper archetype
  identification needs a card-cluster model.
- Windows only.
