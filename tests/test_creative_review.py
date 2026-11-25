import shutil

import pytest
import yaml
from fastapi.testclient import TestClient

from copilota import creative_review
from copilota.data import SAMPLE_DIR, CsvSource
from copilota.web.app import app

RUBRIC = creative_review.load_rubric()

GOOD = {
    "creative_id": "c1", "nome": "Permuta in 24h", "ad_ids": ["m3"],
    "immagine": "img/permuta.jpg", "confermata": False,
    "campi": {"leva": "garanzia_servizio", "soggetto": "prodotto_singolo", "formato": "1:1",
              "palette": "colorata", "densita_testo": "media", "prezzo_in_immagine": False,
              "condizioni_in_immagine": False, "cta_in_immagine": True},
    "punti_forti": ["Un solo messaggio, chiaro."],
    "controlli": [{"id": c["id"], "esito": "ok"} for c in RUBRIC["controlli"]
                  if c["id"] != "tipo_di_offerta"]
                 + [{"id": "tipo_di_offerta", "esito": "problema", "nota": "Non dice se è usato."}],
    "test": [{"cambia": "Aggiungere 'Usato garantito'", "ipotesi": "Lead più qualificati."}],
}


def write(folder, scheda, name="c1.yaml"):
    d = folder / creative_review.FOLDER
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(yaml.safe_dump(scheda, allow_unicode=True), encoding="utf-8")


def test_validate_ok_and_errors():
    assert creative_review.validate(GOOD, RUBRIC) == []
    bad = {**GOOD,
           "campi": {**GOOD["campi"], "leva": "simpatia", "prezzo_in_immagine": "sì"},
           "controlli": [{"id": "inventato", "esito": "ok"},
                         {"id": "contrasto", "esito": "attenzione"}],
           "test": [{"cambia": "x"}] * 4}
    errors = " | ".join(creative_review.validate(bad, RUBRIC))
    assert "'leva': valore 'simpatia' non ammesso" in errors
    assert "'prezzo_in_immagine' deve essere true o false" in errors
    assert "controllo sconosciuto 'inventato'" in errors
    assert "controllo 'contrasto': manca la nota" in errors
    assert "più di 3 test" in errors
    assert "mancano i controlli" in errors  # ne ha solo due


def test_rubric_is_abcd_with_sources():
    groups = {g["id"] for g in RUBRIC["gruppi"]}
    assert groups == {"A", "B", "C", "D", "S"}
    for c in RUBRIC["controlli"]:
        assert c["gruppo"] in groups and c["fonte"] in RUBRIC["fonti"], c["id"]
        if c["gruppo"] != "S":  # le lettere ABCD citano la linea guida da cui vengono
            assert c.get("linea_guida"), c["id"]
    assert all(c["fonte"] == "searchon" for c in RUBRIC["controlli"] if c["gruppo"] == "S")


def test_groups_follow_abcd_order():
    checks = [{**c, "esito": "ok"} for c in RUBRIC["controlli"]]
    checks[-1]["esito"] = "problema"
    groups = creative_review._groups(checks, RUBRIC)
    assert [g["id"] for g in groups] == ["A", "B", "C", "D", "S"]
    s = groups[-1]
    assert s["checks"][0]["esito"] == "problema" and s["ok"] == len(s["checks"]) - 1
    assert s["fonti"] == ["Regole SearchOn per il settore"]


def test_build_adds_numbers_and_comparison(tmp_path):
    shutil.copytree(SAMPLE_DIR, tmp_path / "demo")
    folder = tmp_path / "demo"
    write(folder, GOOD)
    write(folder, {**GOOD, "creative_id": "altro", "ad_ids": ["non_esiste"]}, "altro.yaml")
    out = creative_review.build(CsvSource(folder), folder, "act_1000000002")
    assert len(out["cards"]) == 1  # la scheda senza annunci nell'account non compare
    card = out["cards"][0]
    rows = [r for r in CsvSource(folder).read("meta_ad_daily") if r["ad_id"] == "m3"]
    assert card["perf"]["spend"] == pytest.approx(sum(r["spend"] for r in rows), abs=0.01)
    assert card["campaign"]["spend"] > card["perf"]["spend"]
    assert card["campaigns"] == ["IT|LEAD|AUTO_B2C"]
    assert card["checks"][0]["esito"] == "problema"  # i problemi vengono prima
    assert card["problems"] == 1 and card["errors"] == []
    assert card["judgement"]
    assert out["levers"][0]["leva"] == "garanzia_servizio"


def test_judgement_needs_enough_data():
    camp = {"cpl": 20.0}
    few = {"impressions": 500, "leads": 10, "cpl": 10.0}
    assert "pochi dati" in creative_review._judgement(few, camp, RUBRIC)
    cheap = {"impressions": 50000, "leads": 40, "cpl": 12.0}
    assert "più basso" in creative_review._judgement(cheap, camp, RUBRIC)
    dear = {"impressions": 50000, "leads": 40, "cpl": 30.0}
    assert "più alto" in creative_review._judgement(dear, camp, RUBRIC)


def test_no_folder_no_cards(tmp_path):
    shutil.copytree(SAMPLE_DIR, tmp_path / "demo")
    out = creative_review.build(CsvSource(tmp_path / "demo"), tmp_path / "demo", "act_1000000002")
    assert out == {"cards": [], "levers": []}


@pytest.fixture
def client(tmp_path):
    shutil.copytree(SAMPLE_DIR, tmp_path / "demo")
    app.state.data_root = tmp_path
    yield TestClient(app), tmp_path / "demo"
    del app.state.data_root


def test_page_shows_review_and_image(client):
    c, folder = client
    page = c.get("/c/demo/creativita?account=act_1000000002").text
    assert "Nessuna scheda per questo account" in page
    write(folder, GOOD)
    (folder / creative_review.FOLDER / "img").mkdir()
    (folder / creative_review.FOLDER / "img" / "permuta.jpg").write_bytes(b"\xff\xd8\xff")
    page = c.get("/c/demo/creativita?account=act_1000000002").text
    assert "Schede delle creatività" in page and "Permuta in 24h" in page
    assert "Non dice se è usato." in page and "da confermare" in page
    assert c.get("/c/demo/schede/permuta.jpg").status_code == 200
    assert c.get("/c/demo/schede/..%2Faccounts.csv").status_code == 404
    assert c.get("/c/demo/schede/manca.jpg").status_code == 404
