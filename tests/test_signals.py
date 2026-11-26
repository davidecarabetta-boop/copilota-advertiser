from datetime import date, timedelta

import pytest

from copilota.config import load_thresholds
from copilota.data import CsvSource
from copilota.signals import Status, check_account, gate

TH = load_thresholds()
END = date(2026, 11, 21)


class FakeSource:
    def __init__(self, **tables):
        self.tables = {"tracking_status": [], "backend_daily": [], "meta_campaigns": [],
                       "ga_conversion_actions": [],
                       "offline_conversions_daily": [],
                       **tables}

    def read(self, table):
        return self.tables.get(table, [])


ACCOUNT = {"account_id": "g", "platform": "google", "client": "X", "name": "X",
           "objective": "lead_qualificato"}


def tracking(**kw):
    base = {"account_id": "g", "enhanced_conversions": True, "capi_active": None,
            "capi_coverage_pct": None, "consent_mode_v2": True, "consent_rate_pct": 70.0,
            "consent_rate_prev_pct": 72.0, "optimization_event": "lead_form",
            "crm_quality_feedback": True, "crm_last_upload": END,
            "customer_match_updated": END}
    return {**base, **kw}


def google_rows(conv_per_day=2.0, last_day_conv=None, days=30):
    rows = []
    for i in range(days):
        d = END - timedelta(days=days - 1 - i)
        c = last_day_conv if (d == END and last_day_conv is not None) else conv_per_day
        rows.append({"date": d, "account_id": "g", "campaign_name": "c1", "cost": 50.0,
                     "bidding_strategy": "MAXIMIZE_CONVERSIONS",
                     "conversions": c})
    return rows


def backend(total, days=150, client="X"):
    """`total` lead ogni 30 giorni, storico di `days` giorni (serve per i lead maturi)."""
    per_day = total / 30
    return [{"date": END - timedelta(days=i), "client": client, "source": "google",
             "leads": per_day, "qualified_leads": per_day / 2, "contracts": per_day * 0.02}
            for i in range(days)]


def status_of(checks, name):
    return next(c.status for c in checks if c.name == name)


def run(rows=None, track=None, back=None):
    src = FakeSource(ga_campaign_daily=rows or google_rows(),
                     tracking_status=[track or tracking()],
                     backend_daily=back if back is not None else backend(60))
    return check_account(src, ACCOUNT, TH)


def test_sample_data_end_to_end():
    src = CsvSource()
    result = {a["platform"]: gate(check_account(src, a, TH)) for a in src.read("accounts")}
    assert result == {"google": Status.YELLOW, "meta": Status.RED}


def test_all_good_is_green():
    assert gate(run()) is Status.GREEN


def test_zero_conversions_last_day_is_red():
    rows = google_rows(conv_per_day=4, last_day_conv=0)  # CPA ~13 €, spesa 50 € > 2 CPA
    assert status_of(run(rows=rows), "Conversione principale") is Status.RED


def test_zero_conversions_with_small_spend_is_not_red():
    rows = google_rows(conv_per_day=2, last_day_conv=0)  # CPA ~26 €, spesa 50 € < 2 CPA
    assert status_of(run(rows=rows), "Conversione principale") is Status.GREEN


def test_conversion_crash_is_red():
    rows = google_rows(conv_per_day=5)
    for r in rows[-7:]:
        r["conversions"] = 0.5
    assert status_of(run(rows=rows), "Andamento conversioni") is Status.RED


def test_non_conversion_campaigns_ignored_for_volume():
    rows = google_rows(conv_per_day=2) + [
        {**r, "campaign_name": "video", "bidding_strategy": "TARGET_CPM", "conversions": 0}
        for r in google_rows()
    ]
    assert status_of(run(rows=rows), "Conversioni per campagna") is Status.GREEN


@pytest.mark.parametrize("crm,expected", [
    (57, Status.GREEN),   # +5%
    (50, Status.YELLOW),  # +20%
    (44, Status.RED),     # +36%
    (29, Status.RED),     # piattaforma > 2x
    (0, Status.YELLOW),   # nessun dato CRM
])
def test_reconciliation(crm, expected):
    checks = run(back=backend(crm) if crm else [])
    assert status_of(checks, "Riconciliazione con CRM") is expected


def test_consent_missing_is_red_and_drop_is_yellow():
    assert status_of(run(track=tracking(consent_mode_v2=False)), "Consent Mode v2") is Status.RED
    drop = tracking(consent_rate_pct=55.0, consent_rate_prev_pct=70.0)
    assert status_of(run(track=drop), "Consent Mode v2") is Status.YELLOW


def test_lead_gen_without_crm_quality_is_red():
    checks = run(track=tracking(crm_quality_feedback=False))
    assert status_of(checks, "Conversione di ottimizzazione") is Status.RED


def test_stale_customer_match_is_yellow():
    old = tracking(customer_match_updated=END - timedelta(days=60))
    assert status_of(run(track=old), "Customer Match") is Status.YELLOW


def test_low_volume_is_yellow():
    rows = google_rows(conv_per_day=0.5)
    assert status_of(run(rows=rows, back=backend(15)), "Conversioni per campagna") is Status.YELLOW


def test_gate_empty_is_green():
    assert gate([]) is Status.GREEN


def test_csv_missing_column(tmp_path):
    (tmp_path / "accounts.csv").write_text("account_id,platform\n1,google\n", encoding="utf-8")
    with pytest.raises(ValueError, match="colonne mancanti"):
        CsvSource(tmp_path).read("accounts")


def test_client_override(tmp_path):
    (tmp_path / "clienti").mkdir()
    (tmp_path / "soglie.yaml").write_text("volume:\n  a: 1\n  b: 2\n", encoding="utf-8")
    demo = tmp_path / "clienti" / "demo.yaml"
    demo.write_text("soglie:\n  volume:\n    b: 5\n", encoding="utf-8")
    assert load_thresholds("DEMO", tmp_path) == {"volume": {"a": 1, "b": 5}}


def test_crm_upload_stopped_is_red():
    track = tracking(crm_last_upload=END - timedelta(days=30))
    assert status_of(run(track=track), "Conversione di ottimizzazione") is Status.RED


def test_non_lead_conversions_share():
    def actions(junk):
        return [{"account_id": "g", "conversion_action": "form", "category": "SUBMIT_LEAD_FORM",
                 "conversions": 100 - junk},
                {"account_id": "g", "conversion_action": "YouTube", "category": "ENGAGEMENT",
                 "conversions": junk}]
    for junk, expected in [(2, Status.GREEN), (19, Status.YELLOW), (40, Status.RED)]:
        src = FakeSource(ga_campaign_daily=google_rows(), tracking_status=[tracking()],
                         backend_daily=backend(60), ga_conversion_actions=actions(junk))
        assert status_of(check_account(src, ACCOUNT, TH), "Conversioni non-lead") is expected


def test_lead_quality():
    assert status_of(run(), "Qualità dei lead") is Status.GREEN
    assert status_of(run(back=[]), "Qualità dei lead") is Status.YELLOW
    back = backend(60)
    for b in back[30:60]:  # lead maturi recenti (30-59 giorni fa): nessun contratto
        b["contracts"] = 0
    assert status_of(run(back=back), "Qualità dei lead") is Status.RED
    young = backend(60)
    for b in young[:30]:  # lead degli ultimi 30 giorni: ancora aperti, non contano
        b["contracts"] = 0
    assert status_of(run(back=young), "Qualità dei lead") is Status.GREEN


def offline(per_day, days=30):
    return [{"date": END - timedelta(days=i), "account_id": "g", "stage": "qualified",
             "conversions": per_day} for i in range(days)]


def run_with(**tables):
    base = dict(ga_campaign_daily=google_rows(), tracking_status=[tracking()],
                backend_daily=backend(60))
    return check_account(FakeSource(**{**base, **tables}), ACCOUNT, TH)


def test_quality_from_offline_when_no_crm():
    checks = run_with(backend_daily=[], offline_conversions_daily=offline(1))
    q = next(c for c in checks if c.name == "Qualità dei lead")
    assert q.status is Status.GREEN and "conversioni offline" in q.detail


def test_offline_vs_crm_alignment():
    # CRM: 1 qualificato al giorno; piattaforma: 0.5 -> perde il 50%
    assert status_of(run_with(offline_conversions_daily=offline(0.5)),
                     "Caricamento offline vs CRM") is Status.YELLOW
    assert status_of(run_with(offline_conversions_daily=offline(1)),
                     "Caricamento offline vs CRM") is Status.GREEN


def test_last_upload_taken_from_offline_data():
    # tracking dice fermo da 30 giorni, ma ieri sono arrivate conversioni offline: non rosso
    track = tracking(crm_last_upload=END - timedelta(days=30))
    checks = run_with(tracking_status=[track], offline_conversions_daily=offline(1, days=2))
    assert status_of(checks, "Conversione di ottimizzazione") is Status.GREEN


def test_verified_tracking_turns_crm_gap_into_attribution():
    acc = {**ACCOUNT, "client": "RATTIX"}  # config/clienti/rattix.yaml: tracciamento verificato
    src = FakeSource(ga_campaign_daily=google_rows(), tracking_status=[tracking()],
                     backend_daily=backend(20, client="RATTIX"))
    c = next(c for c in check_account(src, acc, TH) if c.name == "Riconciliazione con CRM")
    assert c.status is Status.YELLOW and not c.blocking and c.data.get("attribution")
    blocking = next(c for c in run(back=backend(20)) if c.name == "Riconciliazione con CRM")
    assert blocking.status is Status.RED and blocking.blocking


def test_unexplained_crash_blocks_but_explained_does_not():
    rows = google_rows(conv_per_day=5)
    for r in rows[-7:]:
        r["conversions"] = 0.5
    crash = next(c for c in run(rows=rows) if c.name == "Andamento conversioni")
    assert crash.blocking  # nessuna causa, tracciamento non verificato


def meta_rows():
    rows = []
    for i in range(30):
        d = END - timedelta(days=29 - i)
        on = i < 21  # l'ad set buono va in pausa 9 giorni fa
        for adset, leads in (("good", 10 if on else 0), ("weak", 0.2)):
            rows.append({"date": d, "account_id": "act_1", "campaign_id": "c1",
                         "adset_id": adset, "ad_id": adset, "ad_name": adset, "concept": "",
                         "spend": 100.0 if (on or adset == "weak") else 0.0,
                         "impressions": 1000, "reach": 800, "frequency": 1.2, "clicks": 20,
                         "leads": leads})
    return rows


def test_cause_found_in_change_history():
    acc = {"account_id": "act_1", "platform": "meta", "client": "X", "name": "M",
           "objective": "lead_qualificato"}
    events = [{"date": END - timedelta(days=9), "account_id": "act_1", "object_type": "adset",
               "object_id": "good", "object_name": "BROAD", "change": "status",
               "old_value": "Active", "new_value": "Inactive", "app": "Power Editor"}]
    src = FakeSource(meta_ad_daily=meta_rows(), change_events=events,
                     tracking_status=[tracking(account_id="act_1")])
    c = next(c for c in check_account(src, acc, TH) if c.name == "Andamento conversioni")
    assert c.status is Status.RED and not c.blocking
    cause = c.data["cause"]
    assert cause["object_name"] == "BROAD" and cause["still_off"] and cause["share_pct"] >= 90


def test_brand_campaigns_not_proposed_for_merge():
    rows = google_rows(conv_per_day=0.5) + [
        {**r, "campaign_name": "IT|LF|AUTO|SEA|Brand_Exact"} for r in google_rows(0.5)]
    c = next(c for c in run(rows=rows, back=backend(15)) if c.name == "Conversioni per campagna")
    assert [x["name"] for x in c.data["campaigns"]] == ["c1"]
