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
    checks = [chk("Conversioni per campagna", Status.YELLOW, "poche", "Volume"),
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


def test_unknown_data_becomes_missing_not_a_task():
    checks = [chk("CAPI", Status.YELLOW, UNKNOWN),
              chk("Qualità dei lead", Status.YELLOW, "Qualità dei lead non misurata: …", "Valore")]
    plan = build_plan(ACC, checks, [])
    assert not plan.tasks and not plan.blocked
    assert {m.page for m in plan.missing} == {"crm", "tracciamento"}


def test_cause_becomes_reactivate_task_with_link():
    cause = {"kind": "pausa", "date": D, "object_type": "adset", "object_id": "123",
             "object_name": "BROAD - Copia", "share_pct": 98, "per_day": 24, "still_off": True,
             "old_value": "Active", "new_value": "Inactive"}
    data = {"cause": cause, "before": 18.5, "recent": 0.1, "cost_before": 299,
            "cost_recent": 12}
    crash = chk("Andamento conversioni", Status.RED, "crollo", data=data)
    crm = chk("Conversione di ottimizzazione", Status.RED, "niente CRM", "Obiettivo")
    plan = build_plan({**ACC, "account_id": "act_9"}, [crash, crm], [])
    assert not plan.blocked
    first = plan.tasks[0]
    assert first.title == "Riattiva l'ad set «BROAD - Copia»" and first.level == "puoi_farlo"
    assert "selected_adset_ids=123" in first.link[1] and "act=9" in first.link[1]
    assert any("ticket" in (t.button or "").lower() and t.ticket for t in plan.tasks)
