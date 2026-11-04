# Before every app release

Ten minutes, and it catches the kind of thing 1.36.1 did (the app stopped
copying games and nobody knew).

## On Windows

1. Build it and install it over the last release, the way a player would
   get it (from the update prompt, if you can).
2. Open Pokémon TCG Live and play one match to the end. Don't touch the
   result screen.
3. Check the app copied it by itself: the match shows up, and the About
   tab's "Last 30 days" line has one more "copied by itself".
4. Play a second match and click around the result screen while it
   copies (Battle Log, Continue). It should still save, and Continue
   should stay covered until it's done.
5. Check fullbench.gg: both games are on My stats, with replays.

## On the Mac (when the Mac build changes)

Same as Windows, steps 1 to 5, with the Mac beta.

## After it's out

- Next day, look at **Automatic copy, last 14 days** on the admin page.
  The new version should copy at least as many games by itself as the
  one before. A red number there means something broke.
- If the server emails "the app may be missing games", believe it until
  you've played a game and seen it copy.
