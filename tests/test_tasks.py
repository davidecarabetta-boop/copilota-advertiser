from datetime import date

from copilota.creative import Finding
from copilota.signals import UNKNOWN, Check, Status
from copilota.tasks import build_plan

ACC = {"account_id": "1", "platform": "meta", "name": "Prova", "client": "X"}
D = date(2026, 11, 21)


def chk(name, status, detail="dettaglio", group="Tracking", blocking=False, data=None):
    return Check("1", group, name, status, detail, blocking, data or {})


def test_red_gives_only_the_ticket():
    checks = [chk("Andamento conversioni", Status.RED, "Conversioni crollate.", blocking=True),
              chk("Conversioni non-lead", Status.YELLOW, "19% YouTube", "Obiettivo")]
    fatigue = Finding(D, "1", "creativita", "concept", "Panda", "fatigue_late",
                      evidence={"calo_ctr_pct": 40, "cpa_ultimi_7g": 30, "cpa_riferimento": 10})
    plan = build_plan(ACC, checks, [fatigue])
    assert plan.blocked and len(plan.tasks) == 1
    t = plan.tasks[0]
    assert "ticket" in t.title and "Conversioni crollate." in t.ticket
    assert "19% YouTube" in t.ticket  # i problemi di dati gialli vanno nello stesso ticket


def test_tasks_follow_the_four_part_format_and_priority():
    camps = [{"name": "IT|LF|AUTO_B2C|GOO|SEA|usato_lombardia", "conversions": 12,
              "type": "SEARCH", "bidding": "MAXIMIZE_CONVERSIONS"},
             {"name": "IT|MF|AUTO_B2C|GOO|SEA|km0_lombardia", "conversions": 8,
              "type": "SEARCH", "bidding": "MAXIMIZE_CONVERSIONS"},
             {"name": "IT|MF|RENT_B2C|GOO|PMAX|noleggio_veneto", "conversions": 5,
              "type": "PERFORMANCE_MAX", "bidding": "MAXIMIZE_CONVERSIONS"}]
    checks = [chk("Conversioni per campagna", Status.YELLOW, "poche", "Volume",
                  data={"campaigns": camps, "min_conv": 30}),
              chk("Conversioni non-lead", Status.YELLOW, "YouTube", "Obiettivo")]
    fatigue = Finding(D, "1", "creativita", "concept", "Panda", "fatigue_late",
                      evidence={"calo_ctr_pct": 40, "cpa_ultimi_7g": 30, "cpa_riferimento": 10},
                      action_key="aggiunta_creativita_asset", priority=1)
    plan = build_plan(ACC, checks, [fatigue])
    assert not plan.blocked
    assert plan.tasks[0].title.startswith("Sostituisci la creatività «Panda»")
    for t in plan.tasks:
        assert t.cosa and t.perche and t.come and t.non_fare
    levels = {t.module: t.level for t in plan.tasks}
    assert levels["Creatività"] == "puoi_farlo" and levels["Vincoli"] == "serve_senior"
    merge = next(t for t in plan.tasks if t.rule == "accorpa_campagne")
    assert "usato_lombardia" in merge.title and "km0_lombardia" in merge.title
    assert "noleggio_veneto" not in merge.title  # altro tipo, linea e zona: resta da sola
    assert any("noleggio_veneto" in r for w in plan.waiting for r in w.reasons)


def test_unknown_data_becomes_missing_not_a_task():
    checks = [chk("CAPI", Status.YELLOW, UNKNOWN),
              chk("Qualità dei lead", Status.YELLOW, "Qualità dei lead non misurata: …", "Valore")]
    plan = build_plan(ACC, checks, [])
    assert not plan.tasks and not plan.blocked
    assert {m.page for m in plan.missing} == {"crm", "tracciamento"}


def test_cause_becomes_reactivate_task_with_link():
    cause = {"kind": "pausa", "date": D, "object_type": "adset", "object_id": "123",
             "object_name": "BROAD - Copia", "share_pct": 98, "per_day": 24, "still_off": True,
             "old_value": "Active", "new_value": "Inactive", "campaign_id": "c1"}
    data = {"cause": cause, "before": 18.5, "recent": 0.1, "cost_before": 299,
            "cost_recent": 12}
    crash = chk("Andamento conversioni", Status.RED, "crollo", data=data)
    crm = chk("Conversione di ottimizzazione", Status.RED, "niente CRM", "Obiettivo")
    within = [{"campaign_id": "c1", "kpi": {"cost_per_qualified": 500}}]  # rispetta il KPI
    camp = {"out": [], "within": within, "kpis": {("meta", "X"): {}}, "utm_lost": [],
            "from": D, "to": D}
    plan = build_plan({**ACC, "account_id": "act_9"}, [crash, crm], [], camp)
    assert not plan.blocked
    first = plan.tasks[0]
    assert first.title == "Riattiva l'ad set «BROAD - Copia»" and first.level == "serve_senior"
    assert "selected_adset_ids=123" in first.link[1] and "act=9" in first.link[1]
    assert any("ticket" in (t.button or "").lower() and t.ticket for t in plan.tasks)


def test_reactivation_without_crm_quality_is_senior_decision():
    cause = {"kind": "pausa", "date": D, "object_type": "adset", "object_id": "1",
             "object_name": "X", "share_pct": 90, "per_day": 10, "still_off": True,
             "old_value": "Active", "new_value": "Inactive", "campaign_id": "c"}
    crash = chk("Andamento conversioni", Status.RED, "crollo",
                data={"cause": cause, "before": 10, "recent": 0.1, "cost_before": 100,
                      "cost_recent": 5})
    plan = build_plan(ACC, [crash], [])  # nessun dato CRM: qualità non verificabile
    task = next(t for t in plan.tasks if t.rule == "riattiva_oggetto")
    assert task.level == "serve_senior"  # si propone, ma decide il senior
    assert any(c.state is None for c in task.conditions)


def test_conversion_cleanup_waits_for_green_signals():
    crm = chk("Conversione di ottimizzazione", Status.RED, "CRM fermo", "Obiettivo")
    junk = chk("Conversioni non-lead", Status.YELLOW, "19% YouTube", "Obiettivo")
    plan = build_plan(ACC, [crm, junk], [])
    assert not any(t.rule == "conversioni_secondarie" for t in plan.tasks)
    assert any(w.title.startswith("Rendi secondarie") for w in plan.waiting)


def test_no_new_creatives_in_campaign_with_learning_ad_sets():
    div = Finding(D, "1", "creativita", "campaign", "c1", "diversity_low",
                  evidence={"campagna": "C", "concept_attivi": 1, "angoli": ["a"],
                            "formati": ["statico"]},
                  proposal={"buchi": ["formato video"]}, action_key="aggiunta_creativita_asset")
    camp = {"out": [], "within": [], "kpis": {("meta", "X"): {}}, "utm_lost": [],
            "from": D, "to": D, "blocked_ids": {"c1"}}
    plan = build_plan(ACC, [], [div], camp)
    assert not any(t.rule == "nuove_creativita" for t in plan.tasks)
    assert any("apprendimento" in r for w in plan.waiting for r in w.reasons)


def test_unmatched_utm_is_not_a_task():
    # lead senza UTM o con l'UTM di una campagna chiusa/rinominata: informazione, non errore
    camp = {"out": [], "within": [], "kpis": {("meta", "X"): {}},
            "utm_lost": [("campagna-rinominata", 500)], "from": D, "to": D}
    plan = build_plan(ACC, [], [], camp)
    assert not any("UTM" in t.title for t in plan.tasks)
