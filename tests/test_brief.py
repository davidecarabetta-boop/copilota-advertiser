import shutil
from datetime import date

import pytest
import yaml
from fastapi.testclient import TestClient

from copilota import brief, register
from copilota.data import SAMPLE_DIR, CsvSource, write_table
from copilota.web.app import app

TODAY = date(2026, 11, 23)


def snap(cid, name, ctype, platform="google", budget=100.0, lost_b=30.0, spend=3000.0):
    acc = "1000000001" if platform == "google" else "act_1000000002"
    return {"account_id": acc, "platform": platform, "campaign_id": cid, "campaign_name": name,
            "campaign_type": ctype, "bidding": "MAXIMIZE_CONVERSIONS", "bid_status": "ENABLED",
            "date_from": date(2026, 10, 16), "date_to": date(2026, 11, 15), "spend": spend,
            "conversions": 100.0, "conversions_value": 0.0, "target_cpa": 20.0,
            "target_roas": None, "target_source": "piattaforma", "budget_daily": budget,
            "budget_planned_month": None, "pacing_pct": None, "lost_is_budget_pct": lost_b,
            "lost_is_rank_pct": 50.0, "frequency": None}


BRIEF = {
    "id": "T-BF", "titolo": "Promo", "scritto_da": "Advertiser", "data": TODAY,
    "periodo": {"dal": "2026-11-26", "al": "2026-12-07"}, "linea": "AUTO_B2C",
    "obiettivo": "Più contratti", "budget_extra": {"google": 1000, "meta": 500},
    "materiali": "", "testo": "",
    "richieste": [
        {"id": "R1", "tipo": "nuova_campagna", "piattaforma": "google",
         "campagna_tipo": "PERFORMANCE_MAX", "cosa": "PMax nuova"},
        {"id": "R2", "tipo": "budget_su", "piattaforma": "google",
         "campagna": "IT|LF|AUTO_B2C|GOO|SEA|pronta", "euro_al_giorno": 100,
         "cosa": "+100 €/giorno"},
        {"id": "R3", "tipo": "riattiva", "piattaforma": "meta", "oggetto": "BROAD",
         "cosa": "Riattiva BROAD"},
    ],
    "materiali_claude": {"google": {"titolo": "Testi"}},
}


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "demo"
    shutil.copytree(SAMPLE_DIR, f)
    write_table(f, "campaign_snapshot", [
        snap("p1", "IT|LF|AUTO_B2C|GOO|PMAX|promo", "PERFORMANCE_MAX"),
        snap("p2", "IT|LF|AUTO_B2C|GOO|PMAX|altra", "PERFORMANCE_MAX"),
        snap("s1", "IT|LF|AUTO_B2C|GOO|SEA|pronta", "SEARCH", budget=150.0, lost_b=39.0),
    ])
    register.add(f, {
        "id": "B-1", "created": TODAY, "account_id": "1000000001", "platform": "google",
        "campaign_id": "p1|p2", "campaign_name": "promo + altra", "kind": "da_non_toccare",
        "title": "Blocco PMax", "why": "budget dimezzati", "expected": "", "decides": "Regola",
        "status": "proposta", "decided": None, "applied": None, "check_after_days": None,
        "until": date(2026, 12, 3), "baseline": "", "result": "", "note": ""})
    (f / "briefs").mkdir()
    (f / "briefs" / "T-BF.yaml").write_text(yaml.safe_dump(BRIEF, allow_unicode=True),
                                           encoding="utf-8")
    return f


def test_brief_check_applies_the_rules(folder):
    r = brief.check(CsvSource(folder), brief.load(folder)[0], TODAY)
    out = {o.req["id"]: o for o in r["results"]}
    assert out["R1"].esito == "modificata" and "asset group" in out["R1"].proposta
    assert "senior" in out["R1"].proposta  # la PMax è bloccata: serve un'eccezione
    assert out["R2"].esito == "modificata" and "150 € → 180 €" in out["R2"].proposta
    assert out["R3"].esito == "sconsigliata"
    assert any("KPI" in o.titolo for o in r["prereq"])  # i dati di prova non hanno KPI
    steps = {s["title"]: s for s in r["steps"]}
    decision = next(s for t, s in steps.items() if t.startswith("Budget"))
    set_budget = next(s for t, s in steps.items() if t.startswith("Porta"))
    assert decision["kind"] == "decisione" and decision["decides"] == "Specialist"
    assert set_budget["depends"] == decision["id"] and set_budget["executor"] == "Advertiser"
    prep = next(s for s in r["steps"] if s["kind"] == "preparazione")
    assert prep["status"] == "applicata"  # Claude l'ha già preparato
    ag = next(s for t, s in steps.items() if t.startswith("Aggiungi l'asset group"))
    assert prep["id"] in ag["depends"].split("|")


def test_pipeline_goes_to_register_and_waits_for_decisions(folder, tmp_path):
    app.state.data_root = tmp_path
    try:
        c = TestClient(app)
        page = c.get("/c/demo/brief").text
        assert "Crea la pipeline nel registro" in page and "Si fa, ma diversamente" in page
        assert c.get("/c/demo/scheda").status_code == 200
        c.post("/c/demo/brief/T-BF/pipeline")
        log = register.read(folder)
        steps = [e for e in log if e["pipeline"] == "T-BF"]
        assert steps and "Vai a Da fare" in c.get("/c/demo/brief").text
        assert brief.create_pipeline(folder, steps) == 0  # non duplica
        decision = next(e for e in steps if e["title"].startswith("Budget"))
        set_budget = next(e for e in steps if e["title"].startswith("Porta"))
        assert [b["id"] for b in register.blockers(set_budget, log)] == [decision["id"]]
        register.apply_action(folder, decision["id"], "approva", TODAY)
        assert register.blockers(set_budget, register.read(folder)) == []
        todo = c.get("/c/demo").text
        assert "passo" in todo and "Decide: Specialist" in todo
    finally:
        del app.state.data_root
