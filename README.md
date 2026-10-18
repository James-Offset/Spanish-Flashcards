# Spanish Flashcards

A flashcard app for your phone (a single web page), plus one Python script that builds the deck from your word list.

- **`word_source_file.md`**: your word list. Edit it whenever you like.
- **`flashcards.py`**: turns the word list into the deck and merges progress from your phone.
- **`app/`**: the phone app. `words.json` is the generated deck. Don't edit it by hand.

You only need Python. There's nothing else to install.

---

## Writing the word list

One word, phrase or sentence per line. The rest is optional:

```
Techo                              <- English is filled in automatically
Pantalla = screen                  <- your own English (always wins)
Acogedor = cosy ## like a warm cafe  <- English and a clue
Estar oxidada ## out of practice   <- clue only
```

- Blank lines, `____` / `-` separator lines, links and lines starting with `#` are ignored.
- Leading `-` / `->` and trailing `**` are removed automatically.
- Put **Spanish on the left** of `=`. If you write `Career = carrera` by mistake, the build will usually spot it and swap it.
- Deleting a line hides the card. Its level is kept in case you add it back.

---

## Everyday routines

Open a terminal in this folder (in VS Code: **Terminal → New Terminal**).

### I added or changed words
```
python flashcards.py build
git add -A
git commit -m "Update flashcards"
git push
```
The build only translates new cards. At the end it lists anything it thinks you should check, such as lines that look like English or names.

### I changed levels or clues on my phone
1. In the app: **☰ Menu → Send progress to my PC → Share file**, and send it to yourself (Drive or email).
2. Save the file in this folder as `progress.json`. If your phone named it `progress (1).json`, rename it.
3. Run:
   ```
   python flashcards.py import progress.json
   git add -A
   git commit -m "Update flashcards"
   git push
   ```
You can delete `progress.json` afterwards. It isn't committed to git anyway.

---

## One-time setup: getting it on your phone

The app is published free with GitHub Pages.

1. Create a **public** repository on GitHub and push this project to it. GitHub Desktop is the easiest way. Note that a public repo means your word list is visible to anyone.
2. On GitHub: **Settings → Pages → Source: Deploy from a branch → Branch: `main`, folder `/ (root)` → Save**.
3. After a minute your app is at:
   `https://<your-username>.github.io/<repo-name>/Spanish%20Flashcards/app/`
   If this folder is the repo root, drop `Spanish%20Flashcards/` from the URL.
4. Open that link in Chrome on your phone, then **⋮ → Add to Home screen**.

The app downloads the latest deck each time you open it, so a `git push` is all it takes to update it. Your place in the deck, plus any levels and clues you haven't sent yet, stay saved on the phone.

---

## How the app picks cards
Each **round** is a shuffle of all your cards:
- **Frequent**: 3 times per round. New cards start here.
- **Infrequent**: once per round.
- **Learned**: in about 1 round in 4.

Repeats of the same card are kept apart. Your position in the round is saved after every card, so you always carry on where you stopped.

## Trying it on your PC
```
cd app
python -m http.server
```
Then open http://localhost:8000. Opening `index.html` directly won't work, because browsers block it from loading `words.json`.

## Tests
```
pip install pytest
python -m pytest tests
```
