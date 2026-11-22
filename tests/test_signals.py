from datetime import date, timedelta

import pytest

from copilota.config import load_thresholds
from copilota.data import CsvSource
from copilota.signals import Status, check_account, gate

TH = load_thresholds()
END = date(2026, 11, 21)


class FakeSource:
    def __init__(self, **tables):
        self.tables = {"tracking_status": [], "backend_daily": [], **tables}

    def read(self, table):
        return self.tables.get(table, [])


ACCOUNT = {"account_id": "g", "platform": "google", "client": "X", "name": "X",
           "objective": "lead_qualificato"}


def tracking(**kw):
    base = {"account_id": "g", "enhanced_conversions": True, "capi_active": None,
            "capi_coverage_pct": None, "consent_mode_v2": True, "consent_rate_pct": 70.0,
            "consent_rate_prev_pct": 72.0, "optimization_event": "lead_form",
            "crm_quality_feedback": True, "customer_match_updated": END}
    return {**base, **kw}


def google_rows(conv_per_day=2.0, last_day_conv=None, days=30):
    rows = []
    for i in range(days):
        d = END - timedelta(days=days - 1 - i)
        c = last_day_conv if (d == END and last_day_conv is not None) else conv_per_day
        rows.append({"date": d, "account_id": "g", "campaign_name": "c1", "cost": 50.0,
                     "conversions": c})
    return rows


def backend(total, days=30):
    return [{"date": END - timedelta(days=i), "client": "X", "source": "google",
             "leads": total / days} for i in range(days)]


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
    assert status_of(run(rows=google_rows(last_day_conv=0)), "Conversione principale") is Status.RED


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
