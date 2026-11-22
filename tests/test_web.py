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
    assert "DEMO" in c.get("/").text
    page = c.get("/c/demo").text
    assert "Segnali rosso" in page and "Mappa della diversità" in page
    assert "Creatività in ritardo" in page
    for path in ("/c/demo/crm", "/c/demo/concetti", "/c/demo/tracciamento"):
        assert c.get(path).status_code == 200
    past = c.get("/c/demo?al=2026-11-10").text
    assert "Vista come al" in past and "Il 10/11" in past and "Il 21/11" not in past


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
