from datetime import date

from copilota.config import load_thresholds
from copilota.diagnosis import BAD, CHAT, NA, WARN, diagnose
from copilota.selection import select

TH = load_thresholds()
ACC = {"account_id": "g", "platform": "google", "client": "X", "name": "G"}


class FakeSource:
    def __init__(self, **t):
        self.t = t

    def read(self, table):
        if table not in self.t:
            raise FileNotFoundError(table)
        return self.t[table]


def snap(cid, name, spend, conv, target=None, lost_b=0.0, status="ENABLED",
         ctype="SEARCH", bidding="MAXIMIZE_CONVERSIONS"):
    return {"account_id": "g", "platform": "google", "campaign_id": cid, "campaign_name": name,
            "campaign_type": ctype, "bidding": bidding, "bid_status": status,
            "date_from": date(2026, 10, 16), "date_to": date(2026, 11, 15), "spend": spend,
            "conversions": conv, "conversions_value": 0.0, "target_cpa": target,
            "target_roas": None, "target_source": "piattaforma" if target else "",
            "budget_daily": 100.0, "budget_planned_month": None, "pacing_pct": None,
            "lost_is_budget_pct": lost_b, "lost_is_rank_pct": 50.0, "frequency": None}


def source():
    return FakeSource(campaign_snapshot=[
        snap("1", "IT|LF|AUTO_B2C|GOO|PMAX|a", 12000, 480, target=18,
             ctype="PERFORMANCE_MAX"),  # CPA 25: sotto target
        snap("2", "IT|LF|AUTO_B2C|GOO|PMAX|b", 6000, 280, target=20),    # CPA 21.4: +7%, ok
        snap("3", "IT|MF|RENT_NLT|SEA|c", 600, 20, target=30, lost_b=90,
             status="LIMITED_BY_BUDGET"),
        snap("4", "IT|MF|AUTO_B2C|GOO|DSA|d", 4000, 270),                # senza target
        snap("5", "IT|UF|AUTO_B2C|GOO|YT|e", 2000, 0, bidding="TARGET_CPV", ctype="VIDEO"),
        snap("6", "IT|MF|AUTO_B2C|GOO|SEA|f", 100, 1, target=10),        # spesa troppo bassa
    ])


def test_selection_orders_by_impact_and_finds_scale_opportunities():
    r = select(source(), ACC, TH, {})
    assert [c["campaign_id"] for c in r["below"]] == ["1"]
    assert round(r["below"][0]["impact"]) == 12000 - 18 * 480
    assert [c["campaign_id"] for c in r["scale"]] == ["3"]
    assert r["scale"][0]["extra_conv"] == 20 * 0.2  # +20% di budget, il passo consentito
    assert [c["campaign_id"] for c in r["no_target"]] == ["4"]  # il video non cerca conversioni
    assert [c["campaign_id"] for c in r["ok"]] == ["2"]


def test_specialist_kpi_gives_a_target_when_platform_has_none():
    kpis = {("google", "AUTO_B2C"): {"target_cpa": 10.0}}
    r = select(source(), ACC, TH, kpis)
    d = next(c for c in r["below"] if c["campaign_id"] == "4")  # CPA 14.8 > 10
    assert d["target_origin"] == "KPI dello specialist"


def test_business_kpi_is_not_a_platform_target():
    # il costo per lead del CRM (livello business) non diventa il target del CPA di piattaforma
    kpis = {("google", "AUTO_B2C"): {"cost_per_lead": 10.0, "cost_per_qualified": 100.0}}
    r = select(source(), ACC, TH, kpis)
    assert "4" not in [c["campaign_id"] for c in r["below"]]


def test_diagnosis_follows_campaign_type():
    r = select(source(), ACC, TH, {})
    below = diagnose(source(), r["below"][0], TH, None, [])
    texts = {f.text: f for f in below}
    assert texts["CPA della finestra assestata contro il target"].state == BAD
    assert any(f.state == CHAT and "canale" in f.ask for f in below)  # PMax: canali
    scale = diagnose(source(), r["scale"][0], TH, None, [])
    assert next(f for f in scale if f.text.startswith("Quota di impressioni persa per budget")
                ).state == WARN
    assert any(f.state == CHAT and "termini di ricerca" in f.ask for f in scale)  # Search
    assert next(f for f in scale if f.text.startswith("Modifiche")).state == NA


def test_no_snapshot_means_not_available():
    assert select(FakeSource(), ACC, TH, {}) == {"available": False}
