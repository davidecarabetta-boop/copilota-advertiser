from datetime import date, timedelta

from copilota.config import load_thresholds
from copilota.creative import LATE, OFF, OK, PREPARE, TOO_EARLY, analyze_account, fatigue
from copilota.data import CsvSource

TH = load_thresholds()
END = date(2026, 11, 21)


def days(n, ctr=lambda i: 1.5, cpm=lambda i: 10.0, freq=lambda i: 1.2, leads=lambda i: 3.0,
         spend=40.0, end=END, ad="a1"):
    rows = []
    for i in range(n):
        d = end - timedelta(days=n - 1 - i)
        impr = round(spend * 1000 / cpm(i))
        rows.append({"date": d, "ad_id": ad, "ad_name": ad, "concept": "", "spend": spend,
                     "impressions": impr, "reach": round(impr / freq(i)),
                     "clicks": round(impr * ctr(i) / 100), "leads": leads(i),
                     "campaign_id": "c1", "account_id": "act_1"})
    return rows


def state(rows, target=None):
    return fatigue(rows, TH, END, target)["state"]


def test_too_early_and_off():
    assert state(days(5)) == TOO_EARLY
    assert state(days(20, end=END - timedelta(days=10))) == OFF


def test_stable_concept_is_ok():
    assert state(days(30)) == OK


def test_cpm_up_with_stable_ctr_is_not_fatigue():
    st = fatigue(days(30, cpm=lambda i: 10 * (1 + 0.02 * i)), TH, END, None)
    assert st["state"] == OK and "nota" in st


def test_prepare_change():
    rows = days(30, ctr=lambda i: 1.5 * (1 - 0.009 * i), freq=lambda i: 1.2 + 0.05 * i)
    assert state(rows) == PREPARE


def test_late():
    rows = days(30, ctr=lambda i: 1.8 * (1 - 0.015 * i), cpm=lambda i: 9 * (1 + 0.012 * i),
                freq=lambda i: 1.2 + 0.1 * i, leads=lambda i: 3 * (1 - 0.025 * i))
    assert state(rows) == LATE


def test_sample_account():
    src = CsvSource()
    meta = next(a for a in src.read("accounts") if a["platform"] == "meta")
    findings = {(f.issue_code, f.object_id) for f in analyze_account(src, meta, TH)}
    assert ("fatigue_late", "finanziamento") in findings
    assert ("diversity_low", "mc1") in findings
    dmap = next(f for f in analyze_account(src, meta, TH) if f.issue_code == "diversity_map")
    assert dmap.evidence["matrice"]["servizio e garanzia"] == {"video": 1, "carosello": 1}
