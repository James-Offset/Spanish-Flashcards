import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flashcards as fc  # noqa: E402

FAKE_DICT = {"pantalla": "screen", "techo": "roof", "career": "career", "wires": "wires"}


def fake_translate(text):
    return FAKE_DICT.get(text.lower(), f"EN:{text}")


def offline(text):
    raise fc.TranslationUnavailable("offline")


def run(tmp_path, source, translate=fake_translate):
    src = tmp_path / "source.md"
    src.write_text(source, encoding="utf-8")
    deck = tmp_path / "words.json"
    stats = fc.build(src, deck, translate, log=lambda *a: None)
    cards = {c["es"]: c for c in json.loads(deck.read_text(encoding="utf-8"))["cards"]}
    return stats, cards


# ---- parsing

def test_noise_lines_skipped():
    for line in ["", "   ", "___________", "-", "_____-", "https://youtu.be/x video", "# comment"]:
        assert fc.parse_line(line) is None


def test_prefix_suffix_cleanup():
    assert fc.parse_line("-El dinero no compra") == ("El dinero no compra", None, None)
    assert fc.parse_line("->Los jóvenes ") == ("Los jóvenes", None, None)
    assert fc.parse_line("Hay la percepción** ") == ("Hay la percepción", None, None)
    assert fc.parse_line('“La tecnología nos hace" ') == ("La tecnología nos hace", None, None)


def test_equals_and_clue():
    assert fc.parse_line("Pantalla = screen") == ("Pantalla", "screen", None)
    assert fc.parse_line("Techo = roof ## think house") == ("Techo", "roof", "think house")
    assert fc.parse_line("Techo ## think house") == ("Techo", None, "think house")
    assert fc.parse_line("Calmada - tranquila = calm") == ("Calmada - tranquila", "calm", None)


def test_id_stable():
    assert fc.card_id("El dinero no compra la felicidad") == fc.card_id("  el DINERO no compra la felicidad. ")
    assert fc.card_id("Él") != fc.card_id("El")  # accents matter


# ---- build / merge

def test_translates_once(tmp_path):
    stats, cards = run(tmp_path, "Techo\nCapacidad\n")
    assert stats["translated"] == 2 and cards["Techo"]["en"] == "roof"
    stats, _ = run(tmp_path, "Techo\nCapacidad\n", translate=offline)
    assert stats["translated"] == 0 and stats["added"] == 0


def test_offline_leaves_blank_and_retries(tmp_path):
    _, cards = run(tmp_path, "Techo\n", translate=offline)
    assert cards["Techo"]["en"] is None
    stats, cards = run(tmp_path, "Techo\n")
    assert stats["translated"] == 1 and cards["Techo"]["en"] == "roof"


def test_english_first_swapped(tmp_path):
    _, cards = run(tmp_path, "Career = carrera\nPantalla = screen\n")
    assert cards["carrera"]["en"] == "Career"
    assert cards["Pantalla"]["en"] == "screen"


def test_levels_kept_and_deactivate_restore(tmp_path):
    run(tmp_path, "Techo\nCapacidad\n")
    deck_path = tmp_path / "words.json"
    data = json.loads(deck_path.read_text(encoding="utf-8"))
    for c in data["cards"]:
        c["level"] = "learned"
    deck_path.write_text(json.dumps(data), encoding="utf-8")

    stats, cards = run(tmp_path, "Capacidad\n  techo  \n")
    assert cards["Capacidad"]["level"] == "learned" and stats["added"] == 0

    stats, cards = run(tmp_path, "Capacidad\n")
    assert stats["deactivated"] == 1 and not cards["techo"]["active"]

    stats, cards = run(tmp_path, "Capacidad\nTecho\n")
    assert stats["restored"] == 1 and cards["Techo"]["level"] == "learned"


def test_source_english_overrides_auto(tmp_path):
    run(tmp_path, "Capacidad\n")
    _, cards = run(tmp_path, "Capacidad = capacity\n")
    assert cards["Capacidad"]["en"] == "capacity" and cards["Capacidad"]["en_source"] == "source"


def test_duplicates_merged(tmp_path):
    _, cards = run(tmp_path, "-El dinero no compra\n->El dinero no compra\n")
    assert len(cards) == 1


# ---- import / clue precedence

def write_progress(tmp_path, changes):
    p = tmp_path / "progress.json"
    p.write_text(json.dumps({"exported_at": 1, "changes": changes}), encoding="utf-8")
    return p


def test_import_newer_wins(tmp_path):
    run(tmp_path, "Techo\n")
    cid = fc.card_id("Techo")
    deck = tmp_path / "words.json"
    p = write_progress(tmp_path, {cid: {"level": "learned", "level_changed_at": 100,
                                        "clue": "roof", "clue_changed_at": 100}})
    assert fc.import_progress(p, deck, log=lambda *a: None) == (1, 1)
    p = write_progress(tmp_path, {cid: {"level": "infrequent", "level_changed_at": 50}})
    assert fc.import_progress(p, deck, log=lambda *a: None) == (0, 0)
    card = fc.load_deck(deck)[cid]
    assert card["level"] == "learned" and card["clue"] == "roof"


def test_app_clue_survives_rebuild_until_source_clue_changes(tmp_path):
    run(tmp_path, "Techo\n")
    cid = fc.card_id("Techo")
    deck = tmp_path / "words.json"
    p = write_progress(tmp_path, {cid: {"clue": "from app", "clue_changed_at": 10**13}})
    fc.import_progress(p, deck, log=lambda *a: None)

    _, cards = run(tmp_path, "Techo\n")
    assert cards["Techo"]["clue"] == "from app"

    _, cards = run(tmp_path, "Techo ## from source\n")
    assert cards["Techo"]["clue"] == "from source"


def test_english_first_rechecked_after_offline(tmp_path):
    _, cards = run(tmp_path, "Career = carrera\n", translate=offline)
    assert "Career" in cards
    _, cards = run(tmp_path, "Career = carrera\n")
    assert "carrera" in cards and "Career" not in cards and cards["carrera"]["en"] == "Career"
