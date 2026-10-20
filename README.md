# Spanish Flashcards

A flashcard app for your phone (a single web page), plus one Python script that builds the deck from your word list.

The app is at **https://james-offset.github.io/Spanish-Flashcards/app/**

- **`word_source_file.md`**: your word list. Edit it whenever you like.
- **`Update flashcards.bat`**: double-click it to bring in progress from your phone and update the deck.
- **`app/`**: the phone app. `words.json` is the generated deck. Don't edit it by hand.

You only need Python and GitHub Desktop. There's nothing else to install.

---

## The two modes

At the top of the app, choose:
- **Spanish → English**: see the Spanish, recall the meaning.
- **English → Spanish**: see the English, produce the Spanish.

Each mode has its **own levels, clues and place in the deck**. A word can be *Learned* one way and still *Frequent* the other way.

---

## Writing the word list

One word, phrase or sentence per line. The rest is optional:

```
Techo                                    <- English is filled in automatically
Pantalla = screen                        <- your own English (always wins)
Acogedor = cosy ## like a warm cafe      <- clue shown with the Spanish (Spanish → English mode)
Acogedor = cosy >> starts with "aco"     <- clue shown with the English (English → Spanish mode)
Acogedor = cosy ## like a warm cafe >> starts with "aco"   <- both
```

- Blank lines, `____` / `-` separator lines, links and lines starting with `#` are ignored.
- Leading `-` / `->` and trailing `**` are removed automatically.
- Put **Spanish on the left** of `=`. If you write `Career = carrera` by mistake, the update will usually spot it and swap it.
- Deleting a line hides the card. Its levels are kept in case you add it back.
- You can also add or edit clues in the app (**✎ Add clue**). Whichever was changed most recently wins.

---

## Everyday routine

1. **Make your changes.** Edit the word list, and/or send progress from your phone: in the app, **☰ Menu → Send progress to my PC → Share file**, then save the file on your PC. Your **Downloads** folder or this folder both work, and a name like `progress (1).json` is fine.
2. **Double-click `Update flashcards.bat`.** It:
   - imports any progress files it finds here or in Downloads, then moves them into `imported/` so they're never imported twice;
   - adds and translates new words (only new ones, nothing is redone);
   - lists anything worth checking, such as lines that look like English or names;
   - tells you whether there's anything to publish.
3. **Publish with GitHub Desktop:**
   1. Open GitHub Desktop. The current repository should be **Spanish-Flashcards**.
   2. Bottom-left, type a summary such as `Update words`, then click **Commit to main**.
   3. Click **Push origin** at the top.
4. **Wait a few minutes**, then reopen the app on your phone. GitHub Pages takes 1–2 minutes to update, and the repo's **Actions** tab on github.com shows a green tick when it's done. Your phone may keep the old page for up to 10 more minutes, so if you don't see a change yet, wait and pull down to refresh.

Instead of the .bat file, you can also open `flashcards.py` in VS Code and click **▶ Run Python File**.

---

## How the app picks cards
Each **round** is a shuffle of all your cards for the current mode:
- **Frequent**: 3 times per round. New cards start here.
- **Infrequent**: once per round.
- **Learned**: in about 1 round in 4.

Repeats of the same card are kept apart. Your position is saved after every card, separately for each mode.

## Your data
- **On your PC:** `app/words.json` stores the levels and clues you've imported.
- **On your phone:** Chrome stores your place in the deck, plus any changes you haven't sent yet. Clearing Chrome's site data for the app erases these, so send your progress now and then. The top bar shows how many changes haven't been sent.

## For tinkering
```
python flashcards.py build                  # only update from the word list
python flashcards.py import progress.json   # import one specific file
cd app && python -m http.server             # try the app on your PC at http://localhost:8000
pip install pytest && python -m pytest tests
```
