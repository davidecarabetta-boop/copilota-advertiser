import re
import shutil

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from copilota.data import SAMPLE_DIR, CsvSource
from copilota.web.app import app, client_dir


@pytest.fixture
def client(tmp_path):
    shutil.copytree(SAMPLE_DIR, tmp_path / "demo")
    app.state.data_root = tmp_path
    yield TestClient(app), tmp_path / "demo"
    del app.state.data_root


def test_pages_render(client):
    c, _ = client
    home = c.get("/")  # porta al primo account
    assert "Da fare" in home.text and "DEMO Auto (test)" in home.text
    google = c.get("/a/demo/1000000001").text
    assert "Tocca a te" in google and "Cosa succede" in google and "Non fare" in google
    meta = c.get("/a/demo/act_1000000002").text
    assert "è bloccato" in meta and "Copia il testo" in meta and "Oggetto: [Copilota]" in meta
    assert "Sostituisci la creatività" not in meta  # bloccato: solo il ticket
    for tab in ("dati", "segnali", "creativita"):
        assert c.get(f"/a/demo/act_1000000002?tab={tab}").status_code == 200
    for path in ("/c/demo/crm", "/c/demo/concetti", "/c/demo/tracciamento"):
        assert c.get(path).status_code == 200
    # due viste separate: adv (piattaforma contro il target) e business (CRM contro i KPI)
    adv = c.get("/c/demo/campagne?account=1000000001").text
    business = c.get("/c/demo/business?account=1000000001").text
    assert "Campagne · Adv" in adv and "Qualità dei lead, dal CRM" not in adv
    assert "Campagne · Business" in business and "Rispetto al target" not in business
    past = c.get("/a/demo/1000000001?tab=segnali&al=2026-11-10").text
    assert "stai guardando il 2026-11-10" in past and "Il 10/11" in past and "Il 21/11" not in past
    assert c.get("/a/demo/nessuno").status_code == 404


def test_unknown_client_404(client):
    c, _ = client
    assert c.get("/c/nessuno").status_code == 404
    for bad in ("..", "../demo", "demo/../..", ""):
        with pytest.raises(HTTPException):
            client_dir(bad)


def test_crm_upload_and_validation(client):
    c, folder = client
    good = "date,client,source,leads,qualified_leads,contracts\n2026-11-21,DEMO,google,10,4,1\n"
    r = c.post("/c/demo/crm", data={"text": good}, follow_redirects=False)
    assert r.status_code == 303 and "/c/demo?msg=" in r.headers["location"]
    assert len(CsvSource(folder).read("backend_daily")) == 1
    bad = "date,client,source,leads,qualified_leads,contracts\n2026-11-21,ALTRO,google,1,1,1\n"
    r = c.post("/c/demo/crm", data={"text": bad}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert len(CsvSource(folder).read("backend_daily")) == 1  # non sovrascritto


def test_concepts_save(client):
    c, folder = client
    data = {"ad_id": ["m1", "m2"], "concept": ["garanzia", ""], "angle": ["servizio", ""],
            "format": ["video", ""], "confirmed": ["m1"]}
    c.post("/c/demo/concetti", data=data)
    rows = CsvSource(folder).read("creative_concepts")
    assert rows == [{"ad_id": "m1", "concept": "garanzia", "angle": "servizio",
                     "format": "video", "confirmed": True}]


def test_tracking_save(client):
    c, folder = client
    data = {"1000000001__enhanced_conversions": "no", "1000000001__consent_rate_pct": "71,5",
            "1000000001__crm_last_upload": "2026-11-01",
            "act_1000000002__capi_active": "si"}
    c.post("/c/demo/tracciamento", data=data)
    t = {r["account_id"]: r for r in CsvSource(folder).read("tracking_status")}
    assert t["1000000001"]["enhanced_conversions"] is False
    assert t["1000000001"]["consent_rate_pct"] == 71.5
    assert t["act_1000000002"]["capi_active"] is True
    assert t["act_1000000002"]["consent_mode_v2"] is None


def test_register_actions(client):
    from datetime import date

    from copilota import register

    c, folder = client
    def e(iid, kind, decides, title, cid="1"):
        return {"id": iid, "created": date(2026, 11, 23), "account_id": "1000000001",
                "platform": "google", "campaign_id": cid, "campaign_name": f"pmax_{cid}",
                "kind": kind, "title": title, "why": "budget cambiato", "expected": "",
                "decides": decides, "status": "proposta", "decided": None, "applied": None,
                "check_after_days": 14, "until": date(2099, 1, 1), "baseline": "",
                "result": "", "note": ""}

    register.add(folder, e("T-0", "da_non_toccare", "Regola", "Blocco PMax"))
    register.add(folder, e("T-1", "modifica", "Specialist", "Rivedi il target"))
    register.add(folder, e("T-2", "modifica", "Advertiser", "Aggiungi asset", "2"))
    register.add(folder, e("T-3", "modifica", "Advertiser", "Negative", "1"))  # campagna bloccata
    def group_of(page, title):
        """Gruppo della riga dell'elenco con quel titolo (mine, decide, hold, later)."""
        m = re.search(r'data-group="(\w+)"[^>]*>\s*<span class="sev \w+"></span>\s*'
                      r'<span class="t">' + re.escape(title), page)
        return m and m[1]

    page = c.get("/a/demo/1000000001").text  # porta a /c/demo?account=...
    assert group_of(page, "pmax_1") == "hold"  # il blocco
    assert group_of(page, "Rivedi il target") == "decide" and "Decide: Specialist" in page
    assert group_of(page, "Aggiungi asset") == "mine"
    assert group_of(page, "Negative") == "later"  # campagna bloccata: non è tra le cose di oggi
    url = "/a/demo/1000000001/registro/T-1"
    r = c.post(url, data={"action": "applicata"})  # non ancora approvata
    assert "non si pu" in r.text and register.read(folder)[1]["status"] == "proposta"
    c.post(url, data={"action": "approva", "note": "ok specialist"})
    assert register.read(folder)[1]["status"] == "approvata"
    c.post("/a/demo/1000000001/registro/T-2", data={"action": "fatta"})
    assert register.read(folder)[2]["status"] == "applicata"
    page = c.get("/c/demo").text  # applicata: ora è tra le cose da non toccare
    assert "Modifica appena fatta" in page
    assert c.post("/a/demo/act_1000000002/registro/T-1",
                  data={"action": "approva"}).status_code == 404  # altro account