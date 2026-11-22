"""Cerca nella cronologia delle modifiche la causa di un crollo delle conversioni.

Prima di dire "controlla il tracciamento" si guarda cosa è stato toccato: un ad set o una
campagna che portava gran parte delle conversioni messo in pausa, o un budget tagliato.
Oggi lavora su Meta (activity log); per Google servirà la risorsa change_event.
"""

from datetime import date, timedelta

from copilota.data import DataSource, Row

PAUSED = {"Inactive", "Paused", "Deleted", "Archived"}
LEVEL_COL = {"adset": "adset_id", "campaign": "campaign_id"}


def _share(rows: list[Row], col: str, obj_id: str, start: date, end: date) -> tuple[float, float]:
    """(quota delle conversioni dell'oggetto, conversioni al giorno dell'oggetto) nel periodo."""
    period = [r for r in rows if start <= r["date"] <= end]
    total = sum(r["leads"] for r in period)
    mine = sum(r["leads"] for r in period if r[col] == obj_id)
    days = (end - start).days + 1
    return (mine / total * 100 if total else 0.0), mine / days


def find_cause(source: DataSource, account: Row, crash_from: date, today: date,
               min_share_pct: float) -> dict | None:
    if account["platform"] != "meta":
        return None
    acc = account["account_id"]
    rows = [r for r in source.read("meta_ad_daily") if r["account_id"] == acc]
    try:
        events = [e for e in source.read("change_events") if e["account_id"] == acc]
    except FileNotFoundError:
        return None
    best = None
    # modifiche da una settimana prima dell'inizio del calo fino a oggi
    for e in events:
        if not (crash_from - timedelta(days=7) <= e["date"] <= today):
            continue
        col = LEVEL_COL.get(e["object_type"])
        if col is None:
            continue
        paused = e["change"] == "status" and e["new_value"] in PAUSED
        cut = False
        if e["change"] == "budget":
            try:
                old, new = float(e["old_value"]), float(e["new_value"])
                cut = old > 0 and new <= old * 0.7
            except ValueError:
                pass
        if not (paused or cut):
            continue
        share, per_day = _share(rows, col, e["object_id"],
                                e["date"] - timedelta(days=14), e["date"] - timedelta(days=1))
        if share < min_share_pct:
            continue
        still_off = paused and not any(
            x["object_id"] == e["object_id"] and x["change"] == "status"
            and x["new_value"] == "Active" and x["date"] > e["date"] for x in events)
        campaign_id = (e["object_id"] if e["object_type"] == "campaign" else
                       next((r["campaign_id"] for r in rows if r[col] == e["object_id"]), ""))
        cause = {
            "kind": "pausa" if paused else "budget", "date": e["date"],
            "campaign_id": campaign_id,
            "object_type": e["object_type"], "object_id": e["object_id"],
            "object_name": e["object_name"], "share_pct": round(share),
            "per_day": round(per_day, 1), "still_off": still_off,
            "old_value": e["old_value"], "new_value": e["new_value"],
        }
        if best is None or share > best["share_pct"]:
            best = cause
    return best


def ads_manager_link(account_id: str, object_type: str, object_id: str) -> str:
    act = account_id.removeprefix("act_")
    level = {"adset": "adsets", "campaign": "campaigns", "ad": "ads"}[object_type]
    key = {"adset": "selected_adset_ids", "campaign": "selected_campaign_ids",
           "ad": "selected_ad_ids"}[object_type]
    return f"https://adsmanager.facebook.com/adsmanager/manage/{level}?act={act}&{key}={object_id}"
