import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flashcards as fc  # noqa: E402

FAKE_DICT = {"pantalla": "screen", "techo": "roof", "career": "career", "wires": "wires"}
QUIET = lambda *a: None  # noqa: E731


def fake_translate(text):
    return FAKE_DICT.get(text.lower(), f"EN:{text}")


def offline(text):
    raise fc.TranslationUnavailable("offline")


def run(tmp_path, source, translate=fake_translate):
    src = tmp_path / "source.md"
    src.write_text(source, encoding="utf-8")
    deck = tmp_path / "words.json"
    stats = fc.build(src, deck, translate, log=QUIET)
    cards = {c["es"]: c for c in json.loads(deck.read_text(encoding="utf-8"))["cards"]}
    return stats, cards


def write_progress(path, changes, exported_at=1):
    path.write_text(json.dumps({"exported_at": exported_at, "changes": changes}), encoding="utf-8")
    return path


# ---- parsing

def test_noise_lines_skipped():
    for line in ["", "   ", "___________", "-", "_____-", "https://youtu.be/x video", "# comment", ">>"]:
        assert fc.parse_line(line) is None


def test_prefix_suffix_cleanup():
    assert fc.parse_line("-El dinero no compra") == ("El dinero no compra", None, None, None)
    assert fc.parse_line("->Los jóvenes ") == ("Los jóvenes", None, None, None)
    assert fc.parse_line("Hay la percepción** ") == ("Hay la percepción", None, None, None)
    assert fc.parse_line('“La tecnología nos hace" ') == ("La tecnología nos hace", None, None, None)
    assert fc.parse_line("He ponido --> he puesto") == ("He ponido --> he puesto", None, None, None)


def test_equals_and_clues():
    assert fc.parse_line("Pantalla = screen") == ("Pantalla", "screen", None, None)
    assert fc.parse_line("Techo = roof ## house") == ("Techo", "roof", "house", None)
    assert fc.parse_line("Techo = roof >> starts with T") == ("Techo", "roof", None, "starts with T")
    assert fc.parse_line("Techo = roof ## house >> T") == ("Techo", "roof", "house", "T")
    assert fc.parse_line("Techo >> T ## house") == ("Techo", None, "house", "T")
    assert fc.parse_line("Calmada - tranquila = calm") == ("Calmada - tranquila", "calm", None, None)


def test_id_stable():
    assert fc.card_id("El dinero no compra la felicidad") == fc.card_id("  el DINERO no compra la felicidad. ")
    assert fc.card_id("Él") != fc.card_id("El")  # accents matter


# ---- build / merge

def test_translates_once(tmp_path):
    stats, cards = run(tmp_path, "Techo\nCapacidad\n")
    assert stats["translated"] == 2 and cards["Techo"]["en"] == "roof"
    stats, _ = run(tmp_path, "Techo\nCapacidad\n", translate=offline)
    assert stats["translated"] == 0 and stats["added"] == 0 and not stats["saved"]


def test_offline_leaves_blank_and_retries(tmp_path):
    _, cards = run(tmp_path, "Techo\n", translate=offline)
    assert cards["Techo"]["en"] is None
    stats, cards = run(tmp_path, "Techo\n")
    assert stats["translated"] == 1 and cards["Techo"]["en"] == "roof"


def test_english_first_swapped(tmp_path):
    _, cards = run(tmp_path, "Career = carrera\nPantalla = screen\n")
    assert cards["carrera"]["en"] == "Career"
    assert cards["Pantalla"]["en"] == "screen"


def test_english_first_rechecked_after_offline(tmp_path):
    _, cards = run(tmp_path, "Career = carrera\n", translate=offline)
    assert "Career" in cards
    _, cards = run(tmp_path, "Career = carrera\n")
    assert "carrera" in cards and "Career" not in cards and cards["carrera"]["en"] == "Career"


def test_levels_kept_and_deactivate_restore(tmp_path):
    run(tmp_path, "Techo\nCapacidad\n")
    deck_path = tmp_path / "words.json"
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    for c in data["cards"]:
        c["modes"]["es"]["level"] = "learned"
    deck_path.write_text(json.dumps(data), encoding="utf-8")

    stats, cards = run(tmp_path, "Capacidad\n  techo  \n")
    assert cards["Capacidad"]["modes"]["es"]["level"] == "learned" and stats["added"] == 0

    stats, cards = run(tmp_path, "Capacidad\n")
    assert stats["deactivated"] == 1 and not cards["techo"]["active"]

    stats, cards = run(tmp_path, "Capacidad\nTecho\n")
    assert stats["restored"] == 1 and cards["Techo"]["modes"]["es"]["level"] == "learned"


def test_source_english_overrides_auto(tmp_path):
    run(tmp_path, "Capacidad\n")
    _, cards = run(tmp_path, "Capacidad = capacity\n")
    assert cards["Capacidad"]["en"] == "capacity" and cards["Capacidad"]["en_source"] == "source"


def test_duplicates_merged(tmp_path):
    _, cards = run(tmp_path, "-El dinero no compra\n->El dinero no compra\n")
    assert len(cards) == 1


def test_clues_go_to_their_own_mode(tmp_path):
    _, cards = run(tmp_path, "Techo = roof ## house >> starts with T\nPantalla >> screen-ish\n")
    assert cards["Techo"]["modes"]["es"]["clue"] == "house"
    assert cards["Techo"]["modes"]["en"]["clue"] == "starts with T"
    assert cards["Pantalla"]["modes"]["es"]["clue"] is None
    assert cards["Pantalla"]["modes"]["en"]["clue"] == "screen-ish"


def test_old_deck_migrates_into_spanish_mode(tmp_path):
    old = {"generated": 1, "cards": [{
        "id": fc.card_id("Techo"), "es": "Techo", "en": "roof", "en_source": "auto",
        "clue": "from phone", "clue_src": None, "clue_updated": 5,
        "level": "learned", "level_updated": 7, "added": "2026-10-18", "active": True}]}
    (tmp_path / "words.json").write_text(json.dumps(old), encoding="utf-8")
    _, cards = run(tmp_path, "Techo\n")
    modes = cards["Techo"]["modes"]
    assert modes["es"] == {"level": "learned", "level_updated": 7, "clue": "from phone",
                           "clue_src": None, "clue_updated": 5}
    assert modes["en"] == fc.new_mode()
    assert "level" not in cards["Techo"] and "clue" not in cards["Techo"]


# ---- import / clue precedence

def test_import_newer_wins_per_mode(tmp_path):
    run(tmp_path, "Techo\n")
    cid, deck = fc.card_id("Techo"), tmp_path / "words.json"
    p = write_progress(tmp_path / "p.json", {cid: {
        "es": {"level": "learned", "level_changed_at": 100, "clue": "roof", "clue_changed_at": 100},
        "en": {"level": "infrequent", "level_changed_at": 100}}})
    counts = fc.import_progress(p, deck, log=QUIET)
    assert counts == {"es": {"levels": 1, "clues": 1}, "en": {"levels": 1, "clues": 0}}

    p = write_progress(tmp_path / "p.json", {cid: {"en": {"level": "learned", "level_changed_at": 50}}})
    fc.import_progress(p, deck, log=QUIET)  # older: ignored
    p = write_progress(tmp_path / "p.json", {cid: {"en": {"level": "learned", "level_changed_at": 200}}})
    fc.import_progress(p, deck, log=QUIET)
    modes = fc.load_deck(deck)[cid]["modes"]
    assert modes["es"]["level"] == "learned" and modes["es"]["clue"] == "roof"
    assert modes["en"]["level"] == "learned" and modes["en"]["clue"] is None


def test_old_format_progress_imports_into_spanish_mode(tmp_path):
    run(tmp_path, "Techo\n")
    cid, deck = fc.card_id("Techo"), tmp_path / "words.json"
    p = write_progress(tmp_path / "p.json", {cid: {"level": "learned", "level_changed_at": 100}})
    fc.import_progress(p, deck, log=QUIET)
    modes = fc.load_deck(deck)[cid]["modes"]
    assert modes["es"]["level"] == "learned" and modes["en"]["level"] == "frequent"


def test_app_clue_survives_rebuild_until_source_clue_changes(tmp_path):
    run(tmp_path, "Techo\n")
    cid, deck = fc.card_id("Techo"), tmp_path / "words.json"
    p = write_progress(tmp_path / "p.json", {cid: {
        "es": {"clue": "app es", "clue_changed_at": 10**13},
        "en": {"clue": "app en", "clue_changed_at": 10**13}}})
    fc.import_progress(p, deck, log=QUIET)

    _, cards = run(tmp_path, "Techo\n")
    assert cards["Techo"]["modes"]["es"]["clue"] == "app es"

    _, cards = run(tmp_path, "Techo ## source es\n")
    assert cards["Techo"]["modes"]["es"]["clue"] == "source es"
    assert cards["Techo"]["modes"]["en"]["clue"] == "app en"


# ---- no-argument "update everything"

def test_update_everything_imports_downloads_and_archives(tmp_path):
    project, downloads = tmp_path / "project", tmp_path / "Downloads"
    project.mkdir(), downloads.mkdir()
    src, deck = project / "source.md", project / "words.json"
    src.write_text("Techo\n", encoding="utf-8")
    fc.build(src, deck, fake_translate, log=QUIET)
    cid = fc.card_id("Techo")

    write_progress(downloads / "progress (1).json", {cid: {"es": {"level": "learned", "level_changed_at": 300}}},
                   exported_at=300)
    write_progress(project / "progress.json", {cid: {"es": {"level": "infrequent", "level_changed_at": 200}}},
                   exported_at=200)
    (downloads / "progress (2).json").write_text("not json", encoding="utf-8")

    imported, _ = fc.update_everything(src, deck, fake_translate, project, downloads, log=QUIET)
    assert imported == 2
    assert fc.load_deck(deck)[cid]["modes"]["es"]["level"] == "learned"  # newest export wins
    assert len(list((project / "imported").glob("*.json"))) == 2
    assert not (project / "progress.json").exists() and not (downloads / "progress (1).json").exists()
    assert (downloads / "progress (2).json").exists()  # a bad file is left alone

    (downloads / "progress (2).json").unlink()
    imported, stats = fc.update_everything(src, deck, fake_translate, project, downloads, log=QUIET)
    assert imported == 0 and not stats["saved"]
