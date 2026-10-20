"""Spanish flashcards pipeline.

    python flashcards.py                          # do everything: import phone progress, then build
    python flashcards.py build                    # source file -> app/words.json
    python flashcards.py import progress.json     # merge one file exported from the app, then build

Or just double-click "Update flashcards.bat".

The source file (word_source_file.md) holds the words. app/words.json holds
everything else (translations, levels, clues) and is never thrown away.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE / "word_source_file.md"
DEFAULT_DECK = HERE / "app" / "words.json"
DOWNLOADS = Path.home() / "Downloads"

LEVELS = ("frequent", "infrequent", "learned")
MODES = ("es", "en")  # which language is shown on the front of the card
MODE_NAMES = {"es": "Spanish→English", "en": "English→Spanish"}
CLUE_MARKERS = {"##": "es", ">>": "en"}
SPANISH_CHARS = re.compile(r"[ñáéíóúü¿¡]", re.IGNORECASE)
NOISE_LINE = re.compile(r"^[\s_\-–—*.>]*$")
LEADING_JUNK = re.compile(r"^(?:-+>|[-–—•*>]+)\s*")
QUOTES = "\"'“”‘’«» "

PUBLISH_STEPS = (
    "Now publish it to your phone with GitHub Desktop:\n"
    "  1. Open GitHub Desktop (current repository: Spanish-Flashcards).\n"
    "  2. Bottom-left, type a summary such as 'Update words', then click 'Commit to main'.\n"
    "  3. Click 'Push origin' at the top.\n"
    "The app on your phone updates a few minutes later."
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
    """Return (es, en, clue_es, clue_en) - any but es may be None - or None for non-cards.

    '## clue' is shown with the Spanish side, '>> clue' with the English side."""
    line = line.strip()
    if not line or line.startswith("#") or NOISE_LINE.match(line) or "http" in line:
        return None
    parts = re.split(r"(##|>>)", line)
    line, clues = parts[0], {"es": None, "en": None}
    for marker, text in zip(parts[1::2], parts[2::2]):
        clues[CLUE_MARKERS[marker]] = clean(text) or None
    en = None
    if "=" in line:
        line, en = line.split("=", 1)
        en = clean(en) or None
    es = clean(line)
    if not es:
        return None
    return es, en, clues["es"], clues["en"]


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

def new_mode():
    return {"level": "frequent", "level_updated": 0, "clue": None, "clue_src": None, "clue_updated": 0}


def migrate_card(card):
    """Cards saved before there were two modes keep their level and clue as Spanish→English."""
    if "modes" not in card:
        es_mode = new_mode()
        for key in es_mode:
            if key in card:
                es_mode[key] = card.pop(key)
        card["modes"] = {"es": es_mode, "en": new_mode()}
    return card


def load_deck(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {card["id"]: migrate_card(card) for card in data["cards"]}


def save_deck(path, deck):
    """Write the deck; returns False (and leaves the file alone) if nothing changed."""
    cards = sorted(deck.values(), key=lambda c: (c["added"], c["es"].lower()))
    text = json.dumps({"cards": cards}, ensure_ascii=False, indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def new_card(cid, es):
    return {
        "id": cid,
        "es": es,
        "en": None,
        "en_source": None,
        "added": date.today().isoformat(),
        "active": True,
        "modes": {m: new_mode() for m in MODES},
    }


def apply_source_clue(mode, clue):
    """Only react when the source clue itself changes, so clues edited in the app survive rebuilds."""
    if clue == mode["clue_src"]:
        return False
    if clue or mode["clue"] == mode["clue_src"]:
        mode["clue"] = clue
        mode["clue_updated"] = now_ms()
    mode["clue_src"] = clue
    return True


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

    for es, en, clue_es, clue_en in records:
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

        changed |= apply_source_clue(card["modes"]["es"], clue_es)
        changed |= apply_source_clue(card["modes"]["en"], clue_en)

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

    stats["saved"] = save_deck(deck_path, deck)

    active = [c for c in deck.values() if c["active"]]
    log(f"Word list: {len(active)} cards  ({stats['added']} new, {stats['updated']} changed, "
        f"{stats['deactivated']} removed, {stats['restored']} restored, {stats['translated']} translated)")
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
        log(f"\n{len(missing)} cards have no English yet; they will be translated next time.")
        if offline_reason:
            log(f"  Reason: {offline_reason}")
    return stats


# ---------------------------------------------------------------- importing phone progress

class BadProgressFile(Exception):
    pass


def read_progress(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data.get("changes"), dict):
            raise ValueError
        return data
    except (ValueError, AttributeError, OSError):
        raise BadProgressFile(f"{path.name} isn't a progress file exported from the app.")


def import_progress(progress_path, deck_path, log=print):
    """Merge one exported file into the deck; the newest change wins. Returns counts per mode."""
    changes = read_progress(progress_path)["changes"]
    deck = load_deck(deck_path)
    counts = {m: {"levels": 0, "clues": 0} for m in MODES}
    skipped = 0
    for cid, ch in changes.items():
        card = deck.get(cid)
        if card is None:
            skipped += 1
            continue
        if not any(m in ch for m in MODES):
            ch = {"es": ch}  # exported by the app before it had two modes
        for m in MODES:
            change, mode = ch.get(m) or {}, card["modes"][m]
            if change.get("level") in LEVELS and change.get("level_changed_at", 0) > mode["level_updated"]:
                mode["level"], mode["level_updated"] = change["level"], change["level_changed_at"]
                counts[m]["levels"] += 1
            if "clue" in change and change.get("clue_changed_at", 0) > mode["clue_updated"]:
                mode["clue"] = (change["clue"] or "").strip() or None
                mode["clue_updated"] = change["clue_changed_at"]
                counts[m]["clues"] += 1
    save_deck(deck_path, deck)
    summary = "; ".join(f"{MODE_NAMES[m]}: {c['levels']} levels, {c['clues']} clues" for m, c in counts.items())
    log(f"Imported {progress_path.name}  ({summary})")
    if skipped:
        log(f"  ({skipped} changes were for cards no longer in the word list and were skipped.)")
    return counts


def find_progress_files(folders):
    """Exported files in the given folders (e.g. progress.json, 'progress (1).json'), oldest export first."""
    found = {}
    for folder in folders:
        if folder.is_dir():
            for path in folder.glob("progress*.json"):
                found[path.resolve()] = path
    dated = []
    for path in found.values():
        try:
            dated.append((read_progress(path).get("exported_at", 0), path))
        except BadProgressFile:
            dated.append((0, path))  # reported when imported
    return [path for _, path in sorted(dated, key=lambda d: d[0])]


def archive(path, imported_dir):
    """Move an imported file out of the way so it isn't imported again."""
    imported_dir.mkdir(exist_ok=True)
    try:
        stamp = datetime.fromtimestamp(read_progress(path)["exported_at"] / 1000).strftime("%Y-%m-%d_%H%M%S")
    except (BadProgressFile, KeyError, TypeError, ValueError, OSError):
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    target, n = imported_dir / f"progress_{stamp}.json", 1
    while target.exists():
        n += 1
        target = imported_dir / f"progress_{stamp}_{n}.json"
    shutil.move(str(path), str(target))
    return target


def update_everything(source, deck, translate, project_dir=HERE, downloads=DOWNLOADS, log=print):
    """What happens with no arguments: import any exported progress files, then build."""
    files = find_progress_files([project_dir, downloads])
    imported = 0
    if files:
        log(f"Found {len(files)} progress file(s) from your phone:")
        for path in files:
            try:
                import_progress(path, deck, log=lambda msg: log("  " + msg))
            except BadProgressFile as exc:
                log(f"  Skipped: {exc}")
                continue
            archive(path, project_dir / "imported")
            imported += 1
        log(f"  (moved to the 'imported' folder so they won't be imported twice)\n")
    else:
        log("No progress files from your phone found (looked in this folder and Downloads).\n")
    stats = build(source, deck, translate)
    return imported, stats


# ---------------------------------------------------------------- CLI

def launched_by_double_click():
    """True when Windows opened a console just for this script (it would vanish on exit)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleProcessList((ctypes.c_uint * 2)(), 2) == 1
    except Exception:
        return False


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(
        prog="python flashcards.py",
        description="Spanish flashcards. With no command: import progress from your phone, then update the word list.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help=argparse.SUPPRESS)
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK, help=argparse.SUPPRESS)
    parser.add_argument("--no-translate", action="store_true", help="skip auto-translation")
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.add_parser("build", help="only update app/words.json from word_source_file.md")
    imp = sub.add_parser("import", help="merge one progress file exported from the app, then build")
    imp.add_argument("file", type=Path, nargs="?", default=Path("progress.json"))
    args = parser.parse_args(argv)

    translate = None if args.no_translate else google_translator()
    before = args.deck.read_text(encoding="utf-8") if args.deck.exists() else None

    if args.command is None:
        update_everything(args.source, args.deck, translate)
    else:
        if args.command == "import":
            path = args.file
            if not path.exists() and (HERE / path).exists():
                path = HERE / path  # run from another folder
            if not path.exists():
                raise SystemExit(f"Can't find {path}. Save the file exported from the app into this folder.")
            try:
                import_progress(path, args.deck)
            except BadProgressFile as exc:
                raise SystemExit(str(exc))
            print()
        build(args.source, args.deck, translate)

    if args.deck.read_text(encoding="utf-8") != before:
        print("\n" + PUBLISH_STEPS)
    else:
        print("\nNothing changed, so there's nothing to publish.")


if __name__ == "__main__":
    wait = launched_by_double_click()
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc.code if isinstance(exc.code, str) else f"Stopped (code {exc.code}).")
    finally:
        if wait:
            input("\nPress Enter to close...")
