"""Converte gli export JSON degli MCP ufficiali (Google Ads, Meta) nei CSV di data/<cliente>/.

Ponte temporaneo finché non c'è l'estrazione notturna in BigQuery (fase 01).
Uso:
  python scripts/import_mcp_export.py google <export.json> <account_id> <cartella_out>
  python scripts/import_mcp_export.py meta   <export.json> <account_id> <cartella_out>
"""

import csv
import json
import sys
from pathlib import Path


def google(rows: list[dict], account_id: str) -> list[dict]:
    return [{
        "date": r["segments.date"], "account_id": account_id,
        "campaign_id": str(r["campaign.id"]), "campaign_name": r["campaign.name"],
        "campaign_type": r["campaign.advertising_channel_type"],
        "status": r["campaign.status"], "bidding_strategy": r["campaign.bidding_strategy_type"],
        "budget": r.get("campaign_budget.amount_micros", 0) / 1e6,
        "cost": round(r["metrics.cost_micros"] / 1e6, 2),
        "impressions": r["metrics.impressions"], "clicks": r["metrics.clicks"],
        "conversions": round(r["metrics.conversions"], 2),
        "conversions_value": round(r["metrics.conversions_value"], 2),
    } for r in rows]


def meta(rows: list[dict], account_id: str) -> list[dict]:
    def num(v):
        if isinstance(v, dict):
            v = v.get("value", 0)
        return float(v or 0)

    return [{
        "date": r["date_start"], "account_id": account_id,
        "campaign_id": r.get("campaign_id", ""), "adset_id": r.get("adset_id", ""),
        "ad_id": r["id"], "ad_name": r.get("name", ""), "concept": "",
        "spend": num(r.get("amount_spent")), "impressions": int(num(r.get("impressions"))),
        "reach": int(num(r.get("reach"))), "frequency": num(r.get("frequency")),
        "clicks": int(num(r.get("link_click"))), "leads": num(r.get("lead")),
    } for r in rows]


def main() -> None:
    kind, src, account_id, out = sys.argv[1:5]
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    rows = data["result"] if isinstance(data, dict) and "result" in data else data
    table, conv = {"google": ("ga_campaign_daily", google), "meta": ("meta_ad_daily", meta)}[kind]
    out_rows = conv(rows, account_id)
    Path(out).mkdir(parents=True, exist_ok=True)
    with open(Path(out) / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    print(f"{table}.csv: {len(out_rows)} righe")


if __name__ == "__main__":
    main()
