"""Converte gli export JSON degli MCP ufficiali (Google Ads, Meta) nei CSV di data/<cliente>/.

Ponte finché non c'è l'estrazione notturna in BigQuery (fase 01). Le query che producono
gli export sono in skill/riferimenti/. Il JSON può essere il risultato grezzo dell'MCP
(salvato su file dal client o scritto a mano) con dentro `result` o `ad_entities`.

Uso:
  python scripts/import_mcp_export.py <tipo> <export.json> <account_id> <cartella_out>

Tipi:
  google          campagne per giorno           -> ga_campaign_daily.csv
  google_actions  conversioni per azione (tot.)  -> ga_conversion_actions.csv
  google_offline  qualificati/contratti offline -> offline_conversions_daily.csv (accoda)
  meta            annunci per giorno            -> meta_ad_daily.csv
  meta_campaigns  campagne con obiettivo        -> meta_campaigns.csv
  meta_changes    cronologia modifiche (activity log) -> change_events.csv (accoda)
"""

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

# Categorie Google che valgono come lead qualificato / contratto nelle conversioni offline
OFFLINE_STAGE = {"QUALIFIED_LEAD": "qualified", "CONVERTED_LEAD": "converted",
                 "IMPORTED_LEAD": "qualified"}


def _num(v) -> float:
    if isinstance(v, dict):
        v = v.get("value", 0)
    return float(v or 0)


def google(rows, acc):
    return [{
        "date": r["segments.date"], "account_id": acc,
        "campaign_id": str(r["campaign.id"]), "campaign_name": r["campaign.name"],
        "campaign_type": r["campaign.advertising_channel_type"],
        "status": r["campaign.status"], "bidding_strategy": r["campaign.bidding_strategy_type"],
        "budget": r.get("campaign_budget.amount_micros", 0) / 1e6,
        "cost": round(r["metrics.cost_micros"] / 1e6, 2),
        "impressions": r["metrics.impressions"], "clicks": r["metrics.clicks"],
        "conversions": round(r["metrics.conversions"], 2),
        "conversions_value": round(r["metrics.conversions_value"], 2),
    } for r in rows]


def google_actions(rows, acc):
    return [{
        "account_id": acc, "conversion_action": r["segments.conversion_action_name"],
        "category": r["segments.conversion_action_category"],
        "conversions": round(r["metrics.conversions"], 2),
    } for r in rows]


def google_offline(rows, acc):
    out = []
    for r in rows:
        stage = OFFLINE_STAGE.get(r["segments.conversion_action_category"])
        if stage:
            value = r.get("metrics.all_conversions_by_conversion_date",
                          r.get("metrics.all_conversions", 0))
            out.append({"date": r["segments.date"], "account_id": acc, "stage": stage,
                        "conversions": round(value, 2)})
    return out


def meta(rows, acc):
    return [{
        "date": r["date_start"], "account_id": acc,
        "campaign_id": r.get("campaign_id", ""), "adset_id": r.get("adset_id", ""),
        "ad_id": r["id"], "ad_name": r.get("name", ""), "concept": "",
        "spend": _num(r.get("amount_spent")), "impressions": int(_num(r.get("impressions"))),
        "reach": int(_num(r.get("reach"))), "frequency": _num(r.get("frequency")),
        "clicks": int(_num(r.get("link_click"))), "leads": _num(r.get("lead")),
    } for r in rows if _num(r.get("amount_spent")) > 0 or _num(r.get("impressions")) > 0]


def meta_campaigns(rows, acc):
    return [{
        "account_id": acc, "campaign_id": r["id"], "campaign_name": r.get("name", ""),
        "objective": r.get("objective", ""), "status": r.get("effective_status", ""),
    } for r in rows]


def _meta_value(v):
    """Valore leggibile da extra_data: stato ("Inactive") o budget in euro."""
    if isinstance(v, dict):
        amount = v.get("old_value", v.get("new_value"))
        if v.get("type") == "payment_amount" and amount is not None:
            return f"{amount / 100:.0f}"
        return ""
    return "" if v is None else str(v)


def meta_changes(rows, acc):
    out = []
    for r in rows:
        ev = r["event_type"]
        kind = ("adset" if ev.startswith("Ad set") else "campaign" if ev.startswith("Campaign")
                else "ad")
        try:
            extra = json.loads(r.get("extra_data") or "{}")
        except json.JSONDecodeError:
            extra = {}
        day = datetime.strptime(r["datetime"].split(" at ")[0], "%m/%d/%Y").date()
        if "budget" in ev.lower():
            change = "budget"
        elif "status" in ev.lower():
            change = "status"
        elif "created" in ev.lower():
            change = "created"
        else:
            change = ev.split(" ", 2)[-1].lower() if " " in ev else ev
        out.append({
            "date": day.isoformat(), "account_id": acc, "object_type": kind,
            "object_id": r["object_id"], "object_name": r.get("object_name", ""),
            "change": change,
            # valori solo per stato e budget: il resto (targeting, ecc.) basta sapere che è cambiato
            "old_value": _meta_value(extra.get("old_value")) if change in ("status", "budget")
            else "",
            "new_value": _meta_value(extra.get("new_value")) if change in ("status", "budget")
            else "",
            "app": r.get("application_name", ""),
        })
    return out


KINDS = {
    "google": ("ga_campaign_daily", google, False),
    "google_actions": ("ga_conversion_actions", google_actions, False),
    "google_offline": ("offline_conversions_daily", google_offline, True),
    "meta": ("meta_ad_daily", meta, False),
    "meta_campaigns": ("meta_campaigns", meta_campaigns, False),
    "meta_changes": ("change_events", meta_changes, True),
}
APPEND_FIELDS = {
    "offline_conversions_daily": ["date", "account_id", "stage", "conversions"],
    "change_events": ["date", "account_id", "object_type", "object_id", "object_name", "change",
                      "old_value", "new_value", "app"],
}


def load_rows(src: Path) -> list[dict]:
    data = json.loads(src.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("result", data.get("ad_entities", data))
    if isinstance(data, str):  # Meta restituisce la lista come stringa JSON
        data = json.loads(data)
    return data


def main() -> None:
    kind, src, acc, out = sys.argv[1:5]
    table, convert, append = KINDS[kind]
    rows = convert(load_rows(Path(src)), acc)
    path = Path(out) / f"{table}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        # tabella condivisa tra account e tra export: si aggiunge senza duplicare
        old = []
        if path.exists():
            with open(path, encoding="utf-8", newline="") as f:
                old = list(csv.DictReader(f))
        if table == "offline_conversions_daily":
            old = [r for r in old if r["account_id"] != acc]
        seen, merged = set(), []
        for r in old + rows:
            key = tuple(str(r[k]) for k in APPEND_FIELDS[table])
            if key not in seen:
                seen.add(key)
                merged.append(r)
        rows = merged
    fields = APPEND_FIELDS[table] if append else (list(rows[0]) if rows else None)
    if not fields:
        sys.exit(f"{kind}: nessuna riga nell'export, file non scritto")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{table}.csv: {len(rows)} righe")


if __name__ == "__main__":
    main()
