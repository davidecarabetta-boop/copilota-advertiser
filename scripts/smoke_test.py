"""Fase 00 - criterio di completamento.

Legge campagne e metriche di ieri dall'account pilota su Google Ads e Meta, in sola lettura.
Uso: python scripts/smoke_test.py [--only google|meta]
"""

import argparse
import sys

from copilota.settings import Settings, get_settings


def google(s: Settings) -> None:
    from google.ads.googleads.client import GoogleAdsClient

    client = GoogleAdsClient.load_from_dict(
        {
            "developer_token": s.google_ads_developer_token.get_secret_value(),
            "client_id": s.google_ads_client_id,
            "client_secret": s.google_ads_client_secret.get_secret_value(),
            "refresh_token": s.google_ads_refresh_token.get_secret_value(),
            "login_customer_id": s.google_ads_login_customer_id,
            "use_proto_plus": True,
        }
    )
    accessible = client.get_service("CustomerService").list_accessible_customers()
    print(f"[google] account accessibili: {len(accessible.resource_names)}")

    query = """
        SELECT campaign.id, campaign.name, campaign.advertising_channel_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date DURING YESTERDAY AND campaign.status = 'ENABLED'
    """
    ga = client.get_service("GoogleAdsService")
    n = 0
    for batch in ga.search_stream(customer_id=s.pilot_google_customer_id, query=query):
        for r in batch.results:
            n += 1
            print(
                f"  {r.campaign.name[:40]:40} {r.campaign.advertising_channel_type.name:16}"
                f" imp={r.metrics.impressions} cost={r.metrics.cost_micros / 1e6:.2f}"
                f" conv={r.metrics.conversions:.1f}"
            )
    print(f"[google] campagne con dati ieri: {n}")


def meta(s: Settings) -> None:
    from facebook_business.adobjects.adaccount import AdAccount
    from facebook_business.api import FacebookAdsApi

    FacebookAdsApi.init(
        s.meta_app_id,
        s.meta_app_secret.get_secret_value(),
        s.meta_access_token.get_secret_value(),
    )
    rows = AdAccount(s.pilot_meta_ad_account_id).get_insights(
        fields=["campaign_id", "campaign_name", "impressions", "clicks", "spend", "actions"],
        params={"level": "campaign", "date_preset": "yesterday"},
    )
    n = 0
    for r in rows:
        n += 1
        print(f"  {r['campaign_name'][:40]:40} imp={r['impressions']} spend={r['spend']}")
    print(f"[meta] campagne con dati ieri: {n}")


REQUIRED = {
    "google": [
        "google_ads_developer_token", "google_ads_client_id", "google_ads_client_secret",
        "google_ads_refresh_token", "google_ads_login_customer_id", "pilot_google_customer_id",
    ],
    "meta": ["meta_app_id", "meta_app_secret", "meta_access_token", "pilot_meta_ad_account_id"],
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["google", "meta"])
    args = p.parse_args()
    s = get_settings()
    ok = True
    for name, fn in (("google", google), ("meta", meta)):
        if args.only and args.only != name:
            continue
        missing = [k.upper() for k in REQUIRED[name] if getattr(s, k) is None]
        if missing:
            ok = False
            print(f"[{name}] mancano nel .env: {', '.join(missing)}", file=sys.stderr)
            continue
        try:
            fn(s)
        except Exception as e:  # noqa: BLE001 - smoke test, riportiamo e proseguiamo
            ok = False
            print(f"[{name}] ERRORE: {type(e).__name__}: {e}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
