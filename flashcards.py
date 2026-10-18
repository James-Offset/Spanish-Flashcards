"""Spanish flashcards pipeline.

    python flashcards.py build                    # source file -> app/words.json
    python flashcards.py import progress.json     # merge levels/clues exported from the app, then build

The source file (word_source_file.md) holds the words. app/words.json holds
everything else (translations, levels, clues) and is never thrown away.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "word_source_file.md"
DEFAULT_DECK = HERE / "app" / "words.json"

LEVELS = ("frequent", "infrequent", "learned")
SPANISH_CHARS = re.compile(r"[ñáéíóúü¿¡]", re.IGNORECASE)
NOISE_LINE = re.compile(r"^[\s_\-–—*.>]*$")
LEADING_JUNK = re.compile(r"^(?:-+>|[-–—•*>]+)\s*")
QUOTES = "\"'“”‘’«» "

GIT_STEPS = (
    "Now publish it to your phone:\n"
    "    git add -A\n"
    '    git commit -m "Update flashcards"\n'
    "    git push"
)


def now_ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------- parsing

def clean(text):
    text = re.sub(r"\s+", " ", text).strip()
    prev = None
    while prev != text:
        prev = text
        text = LEADING_JUNK.sub("", text)
        text = re.sub(r"\*+$", "", text).strip()
        text = text.strip(QUOTES)
    return text


def parse_line(line):
    """Return (es, en or None, clue or None), or None for lines that aren't cards."""
    line = line.strip()
    if not line or line.startswith("#") or NOISE_LINE.match(line) or "http" in line:
        return None
    clue = None
    if "##" in line:
        line, clue = line.split("##", 1)
        clue = clean(clue) or None
    en = None
    if "=" in line:
        line, en = line.split("=", 1)
        en = clean(en) or None
    es = clean(line)
    if not es:
        return None
    return es, en, clue


def parse_source(text):
    return [rec for rec in map(parse_line, text.splitlines()) if rec]


def card_id(es):
    """Stable ID: ignores case, punctuation and spacing, but keeps accents."""
    norm = re.sub(r"[^\w\s]", "", es.lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]


# ---------------------------------------------------------------- translation

class TranslationUnavailable(Exception):
    pass


def google_translator():
    """Free Google Translate endpoint; needs no API key and no extra packages."""
    last_call = [0.0]

    def request(text):
        query = urllib.parse.urlencode({"client": "gtx", "sl": "es", "tl": "en", "dt": "t", "q": text})
        url = "https://translate.googleapis.com/translate_a/single?" + query
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return "".join(part[0] for part in data[0] if part[0]).strip()

    def translate(text):
        error = None
        for attempt in range(3):
            wait = last_call[0] + 0.3 - time.time()  # stay well under Google's rate limit
            if wait > 0:
                time.sleep(wait)
            last_call[0] = time.time()
            try:
                return request(text)
            except Exception as exc:  # network errors, rate limits, odd responses
                error = exc
                time.sleep(2 * (attempt + 1))
        raise TranslationUnavailable(
            f"Translation failed ({error}). Check your internet connection, or try again later."
        )

    return translate


def looks_english_first(left, translate):
    """For 'A = B' lines: if Spanish->English leaves A unchanged, A is probably English.

    Returns None when it couldn't be checked (offline)."""
    if SPANISH_CHARS.search(left):
        return False
    result = translate(left)
    if result is None:
        return None
    return result.strip().lower() == left.strip().lower()


# ---------------------------------------------------------------- deck

def load_deck(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {card["id"]: card for card in data["cards"]}


def save_deck(path, deck):
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = sorted(deck.values(), key=lambda c: (c["added"], c["es"].lower()))
    data = {"generated": now_ms(), "cards": cards}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def new_card(cid, es):
    return {
        "id": cid,
        "es": es,
        "en": None,
        "en_source": None,
        "clue": None,
        "clue_src": None,
        "clue_updated": 0,
        "level": "frequent",
        "level_updated": 0,
        "added": date.today().isoformat(),
        "active": True,
    }


def build(source_path, deck_path, translate=None, log=print):
    """Merge the source into the deck. `translate` is a function es->en (None = no translating)."""
    if not source_path.exists():
        raise SystemExit(f"Source file not found: {source_path}")
    records = parse_source(source_path.read_text(encoding="utf-8-sig"))
    deck = load_deck(deck_path)
    stats = dict(added=0, updated=0, restored=0, deactivated=0, translated=0)
    swapped, seen = [], set()
    offline_reason = None

    def try_translate(text):
        nonlocal translate, offline_reason
        if translate is None:
            return None
        try:
            return translate(text)
        except TranslationUnavailable as exc:
            offline_reason, translate = str(exc), None  # stop trying for the rest of this run
            return None

    for es, en, clue in records:
        cid = card_id(es)
        direction_checked = True
        if en and cid not in deck and card_id(en) in deck:
            es, en, cid = en, es, card_id(en)  # already known as an English-first line
        elif en and (cid not in deck or not deck[cid].get("direction_checked", True)):
            english_first = looks_english_first(es, try_translate)
            direction_checked = english_first is not None
            if english_first:
                swapped.append(f"{es} = {en}")
                old = deck.pop(cid, None)
                es, en, cid = en, es, card_id(en)
                if old:  # re-key a card saved before it could be checked, keeping its state
                    deck[cid] = dict(old, id=cid)

        if cid in seen:  # duplicate line: only fill gaps
            card = deck[cid]
            if en and card["en_source"] != "source":
                card["en"], card["en_source"] = en, "source"
            continue
        seen.add(cid)

        card = deck.get(cid)
        is_new = card is None
        if is_new:
            card = deck[cid] = new_card(cid, es)
            stats["added"] += 1
        elif not card["active"]:
            card["active"] = True
            stats["restored"] += 1
        changed = card["es"] != es
        card["es"] = es
        if direction_checked:
            card.pop("direction_checked", None)
        else:
            card["direction_checked"] = False

        if en and (card["en"] != en or card["en_source"] != "source"):
            card["en"], card["en_source"] = en, "source"
            changed = True
        elif not en and card["en_source"] == "source":
            card["en"], card["en_source"] = None, None  # English removed from source: re-translate
            changed = True

        if clue != card["clue_src"]:  # only react when the source clue itself changes
            if clue or card["clue"] == card["clue_src"]:
                card["clue"] = clue
                card["clue_updated"] = now_ms()
            card["clue_src"] = clue
            changed = True

        if changed and not is_new:
            stats["updated"] += 1

    for cid, card in deck.items():
        if cid not in seen and card["active"]:
            card["active"] = False
            stats["deactivated"] += 1

    for card in deck.values():
        if card["active"] and not card["en"]:
            result = try_translate(card["es"])
            if result:
                card["en"], card["en_source"] = result, "auto"
                stats["translated"] += 1

    save_deck(deck_path, deck)

    active = [c for c in deck.values() if c["active"]]
    log(f"Deck saved: {len(active)} cards in {deck_path}")
    log("  " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    if swapped:
        log("\nThese looked English-first, so I swapped them (put Spanish on the left to be sure):")
        for line in swapped:
            log(f"  - {line}")
    suspicious = [c["es"] for c in active
                  if c["en_source"] == "auto" and c["en"].strip().lower() == c["es"].strip().lower()]
    if suspicious:
        log("\nCheck these - the translation came back identical (English, a name, or a note?).")
        log("Fix them in the source with 'Spanish = English', or delete the line:")
        for es in suspicious:
            log(f"  - {es}")
    missing = [c["es"] for c in active if not c["en"]]
    if missing:
        log(f"\n{len(missing)} cards have no English yet; they will be translated on the next build.")
        if offline_reason:
            log(f"  Reason: {offline_reason}")
    return stats


def import_progress(progress_path, deck_path, log=print):
    if not progress_path.exists() and (HERE / progress_path).exists():
        progress_path = HERE / progress_path  # run from another folder
    if not progress_path.exists():
        raise SystemExit(
            f"Can't find {progress_path}.\n"
            "Save the file you exported from the app into this folder, then run:\n"
            "    python flashcards.py import progress.json"
        )
    try:
        changes = json.loads(progress_path.read_text(encoding="utf-8-sig"))["changes"]
    except (ValueError, KeyError):
        raise SystemExit(f"{progress_path} isn't a progress file exported from the app.")
    deck = load_deck(deck_path)
    levels = clues = skipped = 0
    for cid, ch in changes.items():
        card = deck.get(cid)
        if card is None:
            skipped += 1
            continue
        if ch.get("level") in LEVELS and ch.get("level_changed_at", 0) > card["level_updated"]:
            card["level"], card["level_updated"] = ch["level"], ch["level_changed_at"]
            levels += 1
        if "clue" in ch and ch.get("clue_changed_at", 0) > card["clue_updated"]:
            card["clue"], card["clue_updated"] = (ch["clue"] or "").strip() or None, ch["clue_changed_at"]
            clues += 1
    save_deck(deck_path, deck)
    log(f"Imported: {levels} levels updated, {clues} clues updated.")
    if skipped:
        log(f"  ({skipped} changes were for cards no longer in the deck and were skipped.)")
    return levels, clues


# ---------------------------------------------------------------- CLI

def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        prog="python flashcards.py",
        description="Spanish flashcards: turn your word list into the phone app's deck.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help=argparse.SUPPRESS)
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK, help=argparse.SUPPRESS)
    parser.add_argument("--no-translate", action="store_true", help="skip auto-translation")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("build", help="read word_source_file.md and update app/words.json")
    imp = sub.add_parser("import", help="merge a progress file exported from the app, then build")
    imp.add_argument("file", type=Path, nargs="?", default=Path("progress.json"))
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        print(
            "\nEveryday use:\n"
            "  Added words?      python flashcards.py build\n"
            "  Synced phone?     python flashcards.py import progress.json"
        )
        return

    translate = None
    if not args.no_translate:
        try:
            translate = google_translator()
        except TranslationUnavailable as exc:
            print(f"Note: {exc}\nContinuing without translating.\n")

    if args.command == "import":
        import_progress(args.file, args.deck)
        print()
    build(args.source, args.deck, translate)
    print("\n" + GIT_STEPS)


if __name__ == "__main__":
    main()
