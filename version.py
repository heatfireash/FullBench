"""
Version and changelog.

Bump VERSION and add an entry at the top of CHANGELOG for every change
worth telling a user about. The About tab reads both from here, so there
is one place to edit.
"""

VERSION = "1.35.4"

# Where the "support Full Bench" links point. Ko-fi charges no fee on
# donations; Buy Me a Coffee takes 5%. Either works -- change the URL.
DONATE_URL = "https://ko-fi.com/fullbench"
DONATE_LABEL = "Support Full Bench on Ko-fi"

CHANGELOG = [
    ("1.35.4", "2026-10-02", [
        "The first try at copying the battle log no longer misses. The app "
        "was clicking the copy icon while the log panel was still sliding "
        "in, before the game would take the click, so every capture needed "
        "a second go. It now waits for the icon to stop moving, then "
        "clicks.",
        "Clicks are sent the way a mouse sends them: the pointer moves "
        "onto the button first, then the button goes down and comes back "
        "up, instead of all at once.",
        "The app no longer has any way to save a screenshot. The screen "
        "is only ever looked at in memory, to find the Battle Log and "
        "copy buttons, and nothing from it is saved or uploaded. (The "
        "old --calibrate option, which saved one screenshot for "
        "cropping those buttons, has been removed.)",
    ]),
    ("1.35.3", "2026-10-01", [
        "When the game ignores the first click on the copy icon, the app "
        "clicks it again after 0.7 seconds instead of waiting nearly 3 "
        "seconds to start over, so those captures finish about two "
        "seconds sooner.",
        "A deck is no longer grouped under another deck that only shares "
        "its helpers. A Charizard deck that runs Kangaskhan, Latias and "
        "Meowth for draw was being named after a Kangaskhan deck, though "
        "Charizard did all the damage. A deck now only joins a group "
        "that plays the Pokémon doing its damage.",
    ]),
    ("1.35.2", "2026-10-01", [
        "Moving the mouse as a match ends no longer makes the capture miss. "
        "The app's clicks on Battle Log and the copy icon could land "
        "wherever your mouse had wandered to. The pointer is now held on "
        "the button for the tenth of a second each click takes, then let "
        "go.",
        "Decks that run both Mega Charizard X ex and Mega Charizard Y ex "
        "get one name, \"Mega Charizard ex\", whichever one attacked. "
        "Before, the same deck was called Charizard X in one game and "
        "Charizard Y in the next. The same goes for any Pokémon with X "
        "and Y Mega forms. Matches already recorded are renamed the next "
        "time the app starts.",
    ]),
    ("1.35.1", "2026-09-30", [
        "Fixed a missed capture that looked like a success. If the copy "
        "click didn't take and the clipboard still held your previous "
        "match's log, the app took that old log as the new one, then "
        "threw it away as a repeat, so it never retried or asked you to "
        "copy it. Now only a log copied after the match ends counts, so "
        "a copy that didn't take gets the retry and the pop-up.",
    ]),
    ("1.35.0", "2026-09-29", [
        "A missed copy gets a second chance. If a click closes the battle "
        "log before the app can copy it, it tries again straight away. If "
        "that misses too, a pop-up asks you to click Battle Log and then "
        "the copy icon yourself, and Continue stays covered for up to 20 "
        "seconds while you do. Skip on the pop-up uncovers it right away.",
        "Clicking the red box over Continue no longer removes it. One "
        "click could knock it away and the next could land on Continue, "
        "and the match was gone.",
        "Card names no longer carry the game's internal codes, like "
        "\"(mebsp_33) Mega Lucario ex\". They made the same card look like "
        "two different ones, which split decks and lost their sprites. "
        "Matches already recorded are fixed the next time the app starts.",
    ]),
    ("1.34.1", "2026-09-29", [
        "Decks are no longer named after two stages of the same Pokémon, "
        "like \"Garchomp ex / Gabite\". The app now knows which Pokémon "
        "evolve into which, instead of guessing from how the names start, "
        "which missed lines like Gible, Gabite and Garchomp or Dreepy, "
        "Drakloak and Dragapult. Pokémon that evolve differently, like "
        "Gardevoir and Gallade, can still share a deck name.",
        "Matches already recorded are renamed the next time the app "
        "starts.",
        "New logo: an F made of three cards, with a yellow card across "
        "the top. It's the app icon, the taskbar icon and the logo on "
        "fullbench.gg.",
    ]),
    ("1.34.0", "2026-09-28", [
        "Updates install from inside the app. Press Update now and Full "
        "Bench downloads the new version, checks it's the right file, "
        "and restarts itself. No more replacing the exe by hand, and no "
        "Windows warning on updates -- that only shows the first time "
        "you download it from the website.",
        "If an update can't install that way, nothing on your PC changes "
        "and you can still get it from the download page.",
    ]),
    ("1.33.0", "2026-09-28", [
        "One name per deck, everywhere. While you're signed in, deck "
        "names come from fullbench.gg, so the app, your dashboard and "
        "global stats all call a deck the same thing. Each sync updates "
        "the names in the app, for your decks and your opponents'.",
        "The match pop-up switches to fullbench.gg's name for your "
        "opponent's deck once the match has synced.",
        "Removed deck versions and pasting decklists. A saved list could "
        "pin a deck to the wrong name for good. Your old lists aren't "
        "deleted, they're just no longer used.",
        "Removed renaming decks. Every deck is named the same way for "
        "everyone, which is what lets your stats line up with global "
        "stats. Decks you renamed before are named automatically again. "
        "Double-clicking a match now opens its battle log.",
    ]),
    ("1.32.1", "2026-09-28", [
        "Matches now sync with the time they were played in UTC as well "
        "as your local time, so fullbench.gg can list everyone's games in "
        "the right order whatever time zone they're in. A PC with its "
        "time zone set wrong no longer makes its games look hours newer "
        "than they are.",
    ]),
    ("1.32.0", "2026-09-28", [
        "A pop-up now confirms every match that's recorded: the result, "
        "the opponent's deck, and whether it synced to fullbench.gg. It "
        "sits in the bottom-right corner of the game window, away from "
        "the Continue button, never takes focus from the game, and goes "
        "away by itself after a few seconds (or click it). Turn it off in "
        "Settings.",
        "New setting: Hide my email address. Shows 'signed in' instead of "
        "your email at the top of the app and in Settings -- for "
        "streaming or screenshots.",
        "Sharp taskbar icon. The window was handing Windows the 16px "
        "version of the icon for everything, which the taskbar stretched "
        "to 24px. It now sets the exact size the taskbar and title bar "
        "draw at, for any display scaling, and the icon has a frame drawn "
        "for each of those sizes.",
    ]),
    ("1.31.1", "2026-09-26", [
        "Deck names follow one rule everywhere: the first name is the "
        "Pokemon that did the most damage; the second is whichever other "
        "Pokemon did the most work -- a quarter of the damage, or its "
        "ability used twice or more a game. Team Rocket's Mewtwo ex / "
        "Team Rocket's Spidops now gets its Spidops.",
        "Three things were in the way. The website's copy of the log "
        "reader never counted ability uses, so no deck there could earn "
        "a second name from an ability. The name saved with each match "
        "counted how many different abilities a Pokemon had, not how "
        "often it used them. And every Team Rocket's card -- or Lillie's, "
        "Ethan's, Misty's -- looked like the same Pokemon, so none could "
        "be named beside another.",
        "Evolutions from Grand Tree and Rare Candy are counted now.",
        "Games group into decks from the first game. The bar for a "
        "Pokemon to count as a deck's main attacker was three games, "
        "which is right at a few hundred games and meant nothing grouped "
        "at all early on: two games of one deck showed as two decks, and "
        "short games showed up as 'Metang' or 'Drilbur'. It now scales "
        "with how many games there are, and small groups are named by "
        "the same damage/ability rule as big ones.",
        "A game recorded by the app before logs were kept, then pasted "
        "on the website, was stored twice -- the website had no log to "
        "compare it with. Games are now also matched on who won, who "
        "lost, turns, how it ended and prizes when a stored copy has no "
        "log, and the website clears out any duplicates already stored. "
        "The app drops its extra copy on its next sync.",
        "The website has an icon in the browser tab, on phone home "
        "screens and in bookmarks -- it had none.",
        "The app's own icon was only drawn at 16x16 and stretched "
        "everywhere else, so it looked blurry on the desktop and "
        "taskbar. It now carries every size from 16 to 256.",
        "Matches already recorded are re-read with the fix once, "
        "automatically, on the app's first start and on the website. "
        "Decks you renamed yourself keep your name.",
    ]),
    ("1.31.0", "2026-09-26", [
        "Tracking no longer switches on with the game closed. Any window "
        "with 'Pokemon TCG Live' in its title used to count as the game "
        "-- a browser tab on a deck site, a YouTube video, an Explorer "
        "window on the install folder. A window now only counts if it "
        "belongs to the game itself, and the running/closed state has to "
        "be seen twice in a row before tracking starts or stops.",
        "The log names the window it recognised as the game, so if it "
        "ever gets it wrong again the culprit is right there. Running "
        "'py game_watch.py' lists every candidate window and why each "
        "was accepted or ignored.",
        "The app checks for a newer version when it starts and every six "
        "hours, and offers to open the download page. Updating is up to "
        "you -- older versions keep tracking and syncing. Only if a "
        "release fixes what gets uploaded will older ones be asked to "
        "update before syncing, and then nothing is lost: every match "
        "uploads once you have.",
        "Clicking download after an update could hand you the old exe "
        "back from your browser's cache. The download link now always "
        "points at the current version's own file.",
        "Read back any game: 'View battle log' on the Matches tab opens "
        "the full log, turn by turn. On the website, the new Log column "
        "on your dashboard does the same, with You and Opponent in place "
        "of names. Logs of matches you've already synced fill in on the "
        "next sync.",
        "Syncing sends only what the server doesn't have. It used to "
        "re-upload every match every time -- about 1.3 MB at 120 games -- "
        "and now a sync with nothing new is around 16 KB. A long backlog "
        "goes up newest first, as fast as the hourly upload limit allows, "
        "instead of being sent in full and mostly turned away.",
        "Played on your phone? 'Add a match' on the website dashboard takes "
        "a pasted battle log and records it like any other game. It's "
        "checked the same way, names are removed before it's saved, and "
        "if the log doesn't make clear which player you were, it asks.",
        "The same game can't be counted twice, whichever way it arrives: "
        "pasted twice, pasted and also recorded by the app, or recorded on "
        "two PCs. Games are matched on their content, not on how the text "
        "was copied, and the app adopts the website's copy instead of "
        "keeping its own.",
        "Website dashboard: the Matchups heading showed '<Macro deck>' and "
        "the deck filter forgot what you'd picked. Both fixed, and a "
        "filtered dashboard now shows the chosen deck with its sprites "
        "above the stats, with one click back to all decks.",
    ]),
    ("1.30.0", "2026-09-25", [
        "Website footer now links to @fullbenchgg on X, alongside the "
        "support link and the download.",
    ]),
    ("1.29.0", "2026-09-25", [
        "Signing in is one button. The server address is built in, and "
        "the email and password fields are gone -- authentication "
        "happens in your browser, where you can see the address bar and "
        "the certificate. The app never handles a password, and the code "
        "that could accept one has been removed.",
    ]),
    ("1.28.0", "2026-09-25", [
        "The website works on a phone. The navigation wrapped off the "
        "screen, wide tables stretched the page sideways, and the header "
        "did not reach the edge. Tables now scroll inside their own "
        "panel, the navigation wraps to its own line, and the stat "
        "strips become a two-column grid on narrow screens.",
    ]),
    ("1.27.0", "2026-09-25", [
        "Downloads are rate limited to 6 an hour per address, so a "
        "flood cannot run up a bandwidth bill.",
        "Caddy is now built with the rate-limiting module it needs; the "
        "stock image would have refused to start on the config.",
        "make_logo.py also produces a 1500x500 header and a square "
        "avatar for social accounts.",
    ]),
    ("1.26.0", "2026-09-25", [
        "Global stats shows how many distinct cards have been seen "
        "instead of the minimum sample size -- a number that says how "
        "much is actually known, rather than restating a setting.",
        "New Decks page listing every deck tracked, not just the top "
        "ten, sortable by name, win rate, games or share, with how many "
        "cards each has been seen playing. Click through for a deck's "
        "cards and matchups as before.",
    ]),
    ("1.25.0", "2026-09-25", [
        "The second Pokemon in a deck's name can now be its ability "
        "engine, not only a second attacker. A Metang firing Metal Maker "
        "four times a game is more a part of the deck than a Pokemon "
        "that landed one 60-damage attack, so ability uses and damage "
        "are weighed on the same footing and the larger wins. Your deck "
        "is now 'Mega Excadrill ex / Metang'.",
    ]),
    ("1.24.0", "2026-09-25", [
        "Decks are now grouped and named by what attacks. A Slowking deck "
        "is Slowking, not the Mega Kangaskhan that sits in it and never "
        "attacks -- and Kangaskhan decks that actually attack with it are "
        "kept separate.",
        "Engine Pokemon are found from the data: anything seen alongside "
        "several different main attackers is treated as an engine and "
        "stops counting as evidence of which deck it is.",
        "A one-off game where a side attacker took the KOs no longer "
        "founds a new archetype or drags other games into one.",
    ]),
    ("1.23.0", "2026-09-25", [
        "Deck names are now worked out the same way in the app as on the "
        "website: matches are grouped by the Pokemon seen and each group "
        "is named after the one doing the attacking. Yours and your "
        "opponents' both. Nothing to type, nothing to maintain, and one "
        "deck stays under one name however each game happened to go.",
        "Pasting a decklist is optional and only adds versioning.",
    ]),
    ("1.22.1", "2026-09-25", [
        "Your dashboard on the website shows what each of your decks "
        "plays as in global stats, next to whatever you called it. Your "
        "own names stay yours; the global page only ever shows the "
        "archetype worked out from the cards.",
        "Fixed the last-10 feed on the global page, which could show a "
        "player's personal deck name instead of the archetype.",
    ]),
    ("1.22.0", "2026-09-25", [
        "A decklist copied in PTCGL is imported on its own. The app "
        "already watches the clipboard for battle logs; now a list copied "
        "with the game's own Copy button is filed under the deck it "
        "matches, with nothing to paste. Copy a list once and that deck "
        "is named from it from then on.",
    ]),
    ("1.21.0", "2026-09-25", [
        "Deck names that mean the same deck are now merged. One deck was "
        "ending up as 'Mega Excadrill ex', 'Mega Excadrill ex / Metang' "
        "and 'Metagross / Metang' depending on which Pokemon turned up "
        "that game. After every match the app compares the cards behind "
        "each name and folds together any that overlap by half or more, "
        "keeping the best-evidenced name -- or your saved decklist's "
        "name, if one matches.",
        "py ptcgl_stats.py --merge-decks runs it by hand, with an "
        "optional overlap threshold.",
    ]),
    ("1.20.0", "2026-09-25", [
        "If you have pasted a decklist, matches are named from it "
        "directly instead of being guessed: whichever of your saved "
        "lists contains most of the cards seen is the deck you played, "
        "and the match is filed under that list's version. This is exact "
        "for your own decks and does not care which Pokemon happened to "
        "come out that game.",
        "Added find_decks.py, which checks whether PTCGL keeps your "
        "decks on disk -- if it does, the selected deck could be read "
        "directly and pasting would not be needed.",
    ]),
    ("1.19.0", "2026-09-25", [
        "Deck names on the website are now worked out from the data "
        "rather than a list somebody has to maintain. Matches are "
        "grouped by the Pokemon seen in play and each group is named "
        "after the one doing the attacking, so new decks name themselves "
        "when a set drops.",
        "It will sometimes merge or split a deck wrongly. That is the "
        "trade for never having to update a definition file, and it "
        "improves as more games are recorded.",
        "archetypes.json is now empty and optional -- only for forcing a "
        "name the automatic one gets wrong.",
    ]),
    ("1.18.0", "2026-09-25", [
        "Sprites now work for owned Pokemon: \"Team Rocket's Spidops\" and "
        "\"N's Zoroark\" show Spidops and Zoroark. Farfetch'd and "
        "Sirfetch'd are left alone.",
        "Deck definitions gained 'requires_any': a deck is recognised by "
        "any one of several signature cards, not only its headline "
        "Pokemon. A Team Rocket's deck in a game where Mewtwo never hit "
        "the board is still named correctly.",
    ]),
    ("1.17.1", "2026-09-25", [
        "Described as a stat tracker rather than a match tracker.",
    ]),
    ("1.17.0", "2026-09-25", [
        "New logo: FULL in gold above a bench of five cards spelling "
        "BENCH, a letter to a card.",
        "Icons step down in two stages, because a five-letter wordmark "
        "cannot survive a taskbar: blank cards at 40-48px, and the FB "
        "monogram at 32px and below.",
    ]),
    ("1.16.0", "2026-09-25", [
        "Added a support link in About and on the website. Full Bench is "
        "free and will stay free; the link covers the server.",
    ]),
    ("1.15.0", "2026-09-25", [
        "Deck names on the website show a sprite of the Pokemon they are "
        "named after -- two for names like 'Charizard ex / Pidgeot'. "
        "Rankings, the match feed, deck pages and your own dashboard.",
    ]),
    ("1.14.0", "2026-09-25", [
        "Battle logs are checked for completeness and consistency before "
        "being recorded: a partial paste, a log cut off before the "
        "result, or one whose prize counts don't add up is refused and "
        "kept in ptcgl_logs/rejected for inspection.",
        "The server now parses each uploaded log itself instead of "
        "trusting the app's summary. The log is sent with player names "
        "replaced, so no handle ever leaves the machine.",
        "The same game uploaded by both players is counted once in the "
        "global figures.",
        "Global rankings need a deck to have been played from at least "
        "three accounts, and uploads are rate-limited per account.",
    ]),
    ("1.13.0", "2026-09-24", [
        "Matches where neither player attacked no longer count. An "
        "instant concede is not a game, and counting it moves your win "
        "rate without saying anything about how the decks play. They are "
        "flagged rather than discarded: still listed in the Matches tab, "
        "greyed out, and the dashboard says how many were ignored. Can "
        "be switched off in Settings.",
        "Ignored matches are not uploaded, so they cannot reach the "
        "global figures either.",
        "Sign in through your browser instead of typing a password into "
        "the app: it shows a short code, opens the site, and you approve "
        "the computer there. Email and password still works.",
        "Removed the contribution toggle. An account syncs and counts "
        "towards the global figures; the app and the site say so plainly "
        "instead.",
    ]),
    ("1.12.0", "2026-09-24", [
        "Leaving the result screen and coming back no longer triggers a "
        "second capture of the same match. The screen has to stay gone "
        "for 12 seconds before another capture is allowed, and a capture "
        "that turns out to be the same log as the last one is ignored "
        "rather than reported as a new match.",
        "Added a second duplicate check for logs that differ only in "
        "whitespace, which would otherwise hash differently and slip "
        "through: a match with the same result, turn count and prize "
        "totals recorded within ten minutes is treated as a rerun.",
    ]),
    ("1.11.1", "2026-09-24", [
        "The server address no longer has to include http://. A browser "
        "adds it for you silently, so '127.0.0.1:8000' worked there and "
        "failed in the app, reported as 'could not reach the server'. "
        "Pasted paths, quotes and trailing slashes are trimmed too, and "
        "the box shows the address that will actually be used.",
        "Connection errors say what went wrong: nothing listening, name "
        "doesn't resolve, no answer (firewall), or a TLS problem.",
    ]),
    ("1.11.0", "2026-09-24", [
        "Settings scrolls. It had grown past the height of a windowed "
        "app, so the cloud sync section was simply unreachable without "
        "maximising. The scrollbar appears only when the content "
        "actually overflows.",
        "About scrolls the same way, and no longer has a scroller inside "
        "a scroller.",
    ]),
    ("1.10.1", "2026-09-24", [
        "The bench is back in the small icons. It was dropped below 24px "
        "on the assumption FB plus three cards would be unreadable at "
        "that scale; rendering it showed otherwise.",
    ]),
    ("1.10.0", "2026-09-24", [
        "Decks are named from a shared definition list, archetypes.json, "
        "instead of each machine guessing. This is what will let stats "
        "be compared between players later; it also just makes the names "
        "right more often.",
        "py ptcgl_stats.py --unclassified lists decks with no definition "
        "yet, grouped by the Pokemon seen, so it's clear what to add.",
        "A definition now wins outright. Previously the local guess "
        "could override it and rename a correctly identified deck.",
        "Card-overlap matching no longer applies to opponents: it was "
        "merging different strangers' decks that happened to share "
        "staples. It still applies to your own decks.",
        "Password reset by email on the server, with a console fallback "
        "so it works before you configure a mail provider.",
    ]),
    ("1.9.0", "2026-09-24", [
        "Removed the banner across the top of the screen. It sat exactly "
        "where the battle log's copy button is, so it covered the button "
        "the capture needs to click. The cover over Continue, which is "
        "the one that actually protects the match, stays.",
        "Capture progress now shows on the app's title bar instead.",
        "The header shows whether you're signed in, with Sign in or Sync "
        "beside it.",
        "Stop tracking and Refresh are hidden unless Developer mode is "
        "on. Tracking starts and stops with the game, so they were "
        "clutter. Start tracking still appears when tracking is off.",
        "The website refreshes itself every 30 seconds while its tab is "
        "visible, and shows how old the figures are. There's a Refresh "
        "button too.",
    ]),
    ("1.8.0", "2026-09-24", [
        "Logo now reads FB in gold above the bench, rather than a blank "
        "gold card. Icons at 24px and below drop the bench and show just "
        "the monogram, because two letters four pixels tall are not "
        "readable next to anything else.",
    ]),
    ("1.7.0", "2026-09-24", [
        "Builds are ~30 MB smaller: switched to headless OpenCV, which "
        "is the same library without the GUI parts this app never used.",
        "The website serves the download itself, with a long cache "
        "lifetime and resumable transfers.",
    ]),
    ("1.6.0", "2026-09-24", [
        "Sign in with an email and password from inside the app -- no "
        "keys to copy. You can create an account from Settings too.",
        "Each computer gets its own sign-in, so signing one out leaves "
        "the others alone. The Account page on the website lists them.",
        "The app stores a device token, never your password.",
    ]),
    ("1.5.0", "2026-09-24", [
        "Cloud sync: your history uploads to your own account and pulls "
        "back anything recorded on another PC, so two machines share one "
        "record.",
        "Sync is keyed on each battle log's hash, so it is safe to run "
        "twice and nothing is ever deleted or duplicated.",
        "Player names are never uploaded, yours or your opponents'.",
    ]),
    ("1.4.0", "2026-09-24", [
        "Selected tab text is dark blue again -- white on gold was hard "
        "to read.",
        "Deck and list pickers use a larger typeface, so the dashboard "
        "can be read at a glance.",
        "Dropped card image fetching. The card service was unreliable "
        "and returning server errors, and the pictures were never worth "
        "the dependency.",
        "View list gained a Copy list button: it puts the list back on "
        "the clipboard exactly as PTCGL produced it, ready to paste into "
        "the game's deck import.",
    ]),
    ("1.3.0", "2026-09-24", [
        "Light theme: white throughout, with the blue kept for the header "
        "bar and gold for selection. The all-blue window was too heavy.",
        "Selected rows and the active tab are gold with dark text.",
        "Win and loss colours darkened so they stay readable on white; "
        "every text colour now clears the 4.5 contrast threshold.",
        "Taskbar icon no longer looks blurry. Each icon size is drawn at "
        "its real size with whole-pixel geometry instead of being shrunk "
        "from a large image, which was antialiasing it into mush.",
    ]),
    ("1.2.0", "2026-09-24", [
        "Card images failing now say why, instead of silently leaving the "
        "plain text list. The view reports how many cards matched and "
        "what went wrong.",
        "Images are decoded and resized through Pillow, so a JPEG or "
        "WebP from the card service no longer loads as a blank tile, and "
        "thumbnails are sharp at any size.",
        "Added diag_cards.py, which walks the whole lookup path and "
        "prints where it breaks.",
    ]),
    ("1.1.0", "2026-09-24", [
        "Recoloured to deep blue, white and gold -- the colours from the "
        "back of a Pokemon card.",
        "The capture banner and the Continue cover stay red on purpose: "
        "they are warnings, and the gold accent would read as "
        "decoration.",
        "Activity log recoloured to match; every widget in the app now "
        "draws from the palette.",
    ]),
    ("1.0.0", "2026-09-24", [
        "Renamed to Full Bench. The old name leaned on a trademark that "
        "Nintendo actively defends, which would have been a problem the "
        "moment this went on a public domain.",
        "New logo: an active Pokemon above a full row of five benched, "
        "drawn from plain shapes with no game artwork. Small icon sizes "
        "use a simplified three-card bench so they stay readable.",
    ]),
    ("0.11.0", "2026-09-24", [
        "Paste decklist now reads straight from the clipboard -- copy in "
        "PTCGL, click once, done. The result is reported next to the "
        "deck picker instead of in a popup.",
        "View list shows card images. The list carries set code and "
        "collector number, so each print is identified exactly rather "
        "than guessed.",
        "Removed the images checkbox from the Matches tab.",
    ]),
    ("0.10.0", "2026-09-24", [
        "Decklists can be pasted in and stored against a deck. Paste an "
        "updated list and it is kept as v2, v3 and so on; pasting the "
        "same list again does not create a new version.",
        "A version picker sits beside the deck picker on the Dashboard, "
        "so you can see how a deck performed on each list.",
        "Every match records which list was current when it was played, "
        "so changing a list never rewrites past results.",
        "View list shows the stored decklist for the selected version.",
    ]),
    ("0.9.0", "2026-09-24", [
        "Matchups moved onto the Dashboard and now follow the deck "
        "picker, so choosing a deck shows that deck's matchups rather "
        "than every deck's at once.",
        "Removed the Decks tab; deck renaming lives in the Matches tab "
        "and archetype renaming sits under the matchup list.",
        "Win rates are green at 50% or above and red below it, on the "
        "cards and in the matchup list. No data stays white -- an empty "
        "record is not a losing one.",
        "Confirmed working windowed at 1600x900.",
    ]),
    ("0.8.0", "2026-09-24", [
        "The Continue button is now covered while the battle log is being "
        "saved, so a fast click can't throw the match away. The cover "
        "clears itself when the copy finishes, after four seconds "
        "regardless, or if you click it or press Escape. It can be "
        "turned off in Settings.",
    ]),
    ("0.7.0", "2026-09-24", [
        "Capture reacts about 3.5x faster. The result screen is now "
        "spotted by a colour check on the CONTINUE bar costing 0.2ms, "
        "instead of matching templates across the whole screen; "
        "detection went from ~430ms to ~125ms, and the whole capture "
        "from roughly 1.5s to 0.6s.",
        "The warning banner is now a full-width bar across the top of "
        "the screen reading DON'T PRESS CONTINUE, rather than a small "
        "box that was easy to miss.",
        "Confirmed working at 1080p as well as 1440p.",
    ]),
    ("0.6.1", "2026-09-24", [
        "build.py now checks that every required package is installed "
        "before building, instead of producing an exe that fails on "
        "launch asking for pip install.",
    ]),
    ("0.6.0", "2026-09-22", [
        "Decks are now identified by card overlap with matches already "
        "recorded, not just by what happened in one game. A two-turn "
        "concession gets the right deck name because the cards match a "
        "deck played before.",
        "When a later match names a deck better than an earlier one did, "
        "the earlier matches are renamed to match.",
        "Opponent archetypes get the same treatment, so the same deck "
        "isn't filed under two names.",
        "Cards revealed on bullet lines -- search effects, your opening "
        "hand -- are now recorded. They were being dropped entirely.",
        "Evolutions now count towards naming a deck, which is often the "
        "only evidence in a short game.",
    ]),
    ("0.5.0", "2026-09-22", [
        "Deck names are now worked out from damage dealt and ability use "
        "rather than alphabetically, so the main attacker names the deck "
        "instead of whichever card sorted first.",
        "Deck names can be edited by hand, per match or across every match "
        "at once. Hand-edited names survive a reparse.",
        "Added this About tab.",
        "Fixed a modal dialog leaving its grab held, which could stop the "
        "next dialog from opening.",
        "Activity tab is hidden unless Developer mode is ticked.",
    ]),
    ("0.4.0", "2026-09-22", [
        "Databases from older versions upgrade themselves instead of "
        "failing with a missing-column error.",
        "Fixed a parser bug that filed the word 'them' as a card.",
    ]),
    ("0.3.0", "2026-09-22", [
        "Start with Windows, and start tracking automatically when PTCGL "
        "launches.",
        "Capture is about four times faster, and a banner warns you not to "
        "press Continue while it works.",
        "Missed captures are counted and reported.",
    ]),
    ("0.2.0", "2026-09-22", [
        "Desktop app with Dashboard, Matches and Decks tabs.",
        "Both decks detected from the battle log automatically.",
        "Mulligan counts and the extra cards each side drew from them.",
        "Dashboard filters by deck; going first / going second split.",
    ]),
    ("0.1.0", "2026-09-22", [
        "First working version: clipboard watcher, battle log parser, "
        "SQLite storage, automatic copying from the result screen.",
    ]),
]


def latest():
    return CHANGELOG[0] if CHANGELOG else (VERSION, "", [])
