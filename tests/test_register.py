import json
from datetime import date

import pytest

from copilota import register


def entry(iid="X-1", kind="modifica", status="proposta", until=None, days=14):
    return {"id": iid, "created": date(2026, 11, 23), "account_id": "g", "platform": "google",
            "campaign_id": "1", "campaign_name": "pmax", "kind": kind, "title": "t", "why": "w",
            "expected": "e", "decides": "Specialist", "status": status, "decided": None,
            "applied": None, "check_after_days": days, "until": until, "baseline": "",
            "result": "", "note": ""}


def test_full_cycle_sets_dates_and_due(tmp_path):
    register.add(tmp_path, entry())
    register.apply_action(tmp_path, "X-1", "approva", date(2026, 11, 24))
    e = register.apply_action(tmp_path, "X-1", "applicata", date(2026, 11, 25), note="fatto")
    assert e["decided"] == date(2026, 11, 24) and e["applied"] == date(2026, 11, 25)
    assert register.check_date(e) == date(2026, 12, 9)
    log = register.read(tmp_path)
    assert register.due(log, date(2026, 12, 8)) == []
    assert [x["id"] for x in register.due(log, date(2026, 12, 9))] == ["X-1"]
    e = register.apply_action(tmp_path, "X-1", "verificata", date(2026, 12, 9), result="CPA -10%")
    assert e["status"] == "verificata" and e["result"] == "CPA -10%"
    assert "25/11: fatto" in e["note"]


def test_invalid_transitions_are_refused(tmp_path):
    register.add(tmp_path, entry())
    with pytest.raises(ValueError):
        register.apply_action(tmp_path, "X-1", "applicata", date(2026, 11, 24))  # non approvata
    with pytest.raises(ValueError):
        register.add(tmp_path, entry())  # id duplicato
    with pytest.raises(ValueError):
        register.apply_action(tmp_path, "nope", "approva", date(2026, 11, 24))


def test_dont_touch_until_date():
    log = [entry("A", kind="da_non_toccare", until=date(2026, 12, 3)),
           entry("B", kind="da_non_toccare", until=date(2026, 12, 3), status="scartata"),
           entry("C")]
    assert [e["id"] for e in register.dont_touch(log, date(2026, 12, 3))] == ["A"]
    assert register.dont_touch(log, date(2026, 12, 4)) == []


def test_baseline_has_cpa():
    snap = {"date_from": date(2026, 10, 16), "date_to": date(2026, 11, 15), "spend": 100.0,
            "conversions": 4.0, "budget_daily": 10.0, "lost_is_budget_pct": 1.0,
            "lost_is_rank_pct": 80.0, "target_cpa": 20.0}
    b = json.loads(register.baseline_from_snapshot(snap))
    assert b["cpa"] == 25.0 and b["date_from"] == "2026-10-16"
