from datetime import date, timedelta

from copilota.campaigns import _in_scope, _key, campaign_quality, judge
from copilota.config import load_thresholds
from copilota.signals import Check, Status
from copilota.tasks import build_plan

TH = load_thresholds()
D0, D1 = date(2026, 7, 24), date(2026, 10, 22)
ACC = {"account_id": "act_1", "platform": "meta", "client": "X", "name": "M",
       "objective": "lead_qualificato"}


class FakeSource:
    def __init__(self, **t):
        self.t = t

    def read(self, table):
        return self.t.get(table, [])


def period(cid, name, spend):
    return {"account_id": "act_1", "campaign_id": cid, "campaign_name": name, "date_from": D0,
            "date_to": D1, "spend": spend, "platform_conversions": 0.0}


def crm(utm, leads, qualified, contracts, day=D0 + timedelta(days=10)):
    return {"date": day, "client": "X", "source": "meta", "utm_campaign": utm, "leads": leads,
            "qualified_leads": qualified, "contracts": contracts}


def test_key_ignores_case_dashes_plus_and_funnel():
    assert _key("IT_ita|LF|AUTO_B2C|GOO|SEA|pronta-consegna") == \
        _key("IT_ita|MF|AUTO_B2C|GOO|SEA|Pronta_Consegna")
    assert _key("IT_ita + | + LF + | + AUTO I B2C") == _key("IT_ita | LF | AUTO I B2C")


def test_scope_reads_the_business_line_segment():
    assert _in_scope("IT_ita|LF|AUTO_B2C|GOO|PMAX|auto_promo", ["AUTO"])
    assert not _in_scope("IT_ita|LF|RENT_B2C|GOO|PMAX|auto_noleggio", ["AUTO"])


def source():
    return FakeSource(
        campaign_period=[period("1", "IT | MF | AUTO I B2C | META | LEAD", 36000),
                         period("2", "IT | LF | AUTO I B2C | META | LEAD I RMK", 9000)],
        backend_campaign_daily=[
            crm("IT | MF | AUTO I B2C | META | LEAD", 248, 11, 0),
            crm("IT | LF | AUTO I B2C | META | LEAD I RMK", 250, 29, 2),
            crm("IT | MF | AUTO I B2C | META | LEAD_suffisso", 10, 1, 0),  # suffisso UTM
            crm("vecchia-campagna", 80, 3, 0),
            crm("IT | MF | AUTO I B2C | META | LEAD", 99, 99, 9, day=D1 + timedelta(days=5)),
        ])


KPIS = {("meta", "AUTO_B2C"): {"platform": "meta", "line": "AUTO_B2C", "cost_per_lead": None,
                                "cost_per_qualified": 1000.0, "cost_per_contract": None,
                                "leads_per_month": None, "monthly_budget": None}}


def test_quality_matches_and_judges_against_specialist_kpis():
    q = campaign_quality(source(), ACC)
    rows = {r["campaign_id"]: r for r in q["rows"]}
    assert rows["1"]["leads"] == 258  # 248 + suffisso; fuori periodo escluso
    assert round(rows["2"]["cost_per_qualified"]) == 310
    j = judge(q, TH, KPIS, "meta")
    assert [o["campaign_id"] for o in j["out"]] == ["1"]  # 36000/12 = 3000 > KPI 1000
    assert j["out"][0]["over"][0]["metric"] == "costo per lead qualificato"
    assert [w["campaign_id"] for w in j["within"]] == ["2"]
    assert j["utm_lost"] == [("vecchia-campagna", 80)]


def test_without_kpis_nothing_is_judged():
    j = judge(campaign_quality(source(), ACC), TH, {}, "meta")
    assert not j["out"] and j["missing_kpi"] == ["AUTO_B2C"]
    plan = build_plan(ACC, [], [], {**j, "from": D0, "to": D1})
    assert plan.missing[0].page == "kpi"
    assert not plan.tasks or all(t.rule == "ticket_analytics" for t in plan.tasks)


def test_out_of_kpi_goes_to_specialist_unless_in_learning():
    q = campaign_quality(source(), ACC)
    camp = {**judge(q, TH, KPIS, "meta"), "from": D0, "to": D1, "status_known": True}
    task = next(t for t in build_plan(ACC, [], [], camp).tasks
                if t.rule == "campagna_fuori_kpi")
    assert task.level == "decide_specialist" and "segnalalo allo specialist" in task.title
    blocked = {**judge(q, TH, KPIS, "meta", {"1"}), "from": D0, "to": D1, "status_known": True}
    plan = build_plan(ACC, [], [], blocked)
    assert not any(t.rule == "campagna_fuori_kpi" for t in plan.tasks)
    assert any("fuori KPI" in w.title for w in plan.waiting)


def test_reactivation_of_out_of_kpi_campaign_is_a_senior_decision():
    q = campaign_quality(source(), ACC)
    camp = {**judge(q, TH, KPIS, "meta"), "from": D0, "to": D1}
    cause = {"kind": "pausa", "date": date(2026, 11, 9), "object_type": "adset",
             "object_id": "9", "object_name": "BROAD", "share_pct": 98, "per_day": 24,
             "still_off": True, "old_value": "Active", "new_value": "Inactive",
             "campaign_id": "1"}
    crash = Check("act_1", "Tracking", "Andamento conversioni", Status.RED, "crollo", False,
                  {"cause": cause, "before": 18, "recent": 0.1, "cost_before": 300,
                   "cost_recent": 12})
    plan = build_plan(ACC, [crash], [], camp)
    assert plan.tasks[0].title.startswith("Prima di riattivare «BROAD» decidi col senior")
    assert plan.tasks[0].level == "serve_senior"
    assert not any(t.title.startswith("Sposta budget") for t in plan.tasks)


def test_contract_kpi_does_not_judge_single_campaigns():
    from copilota.campaigns import KPI_FIELDS
    # il CRM collega a un lead solo una parte delle vendite: per campagna il costo per
    # contratto esce gonfiato, quindi vale solo per la linea
    assert "cost_per_contract" not in KPI_FIELDS
