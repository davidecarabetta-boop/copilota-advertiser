"""Selezione (passo 2 della pipeline, docs/pipeline.md): quali campagne guardare oggi.

Legge solo la fotografia `campaign_snapshot` (finestra assestata). Il target viene, in ordine,
dalla fotografia (Ads Guardian o piattaforma) o dai KPI dello specialist per piattaforma e linea.
"""

from copilota.data import DataSource, Row
from copilota.rules import funnel_of, line_of
from copilota.signals import GOOGLE_CONV_BIDDING, META_CONV_OBJECTIVES


def _is_conversion(c: Row) -> bool:
    if c["platform"] == "google":
        return c["bidding"] in GOOGLE_CONV_BIDDING
    return c["campaign_type"] in META_CONV_OBJECTIVES


def _target(c: Row, kpis: dict) -> tuple[float | None, str]:
    if c["target_cpa"]:
        return c["target_cpa"], c["target_source"] or "piattaforma"
    k = kpis.get((c["platform"], line_of(c["campaign_name"])))
    if k and k.get("cost_per_lead"):
        return k["cost_per_lead"], "KPI dello specialist"
    return None, ""


def select(source: DataSource, account: Row, th: dict, kpis: dict) -> dict:
    s = th["selezione"]
    try:
        snap = [c for c in source.read("campaign_snapshot")
                if c["account_id"] == account["account_id"]]
    except FileNotFoundError:
        return {"available": False}
    below, scale, no_target, ok = [], [], [], []
    for c in snap:
        if not _is_conversion(c) or c["spend"] < s["spesa_min"]:
            continue
        cpa = c["spend"] / c["conversions"] if c["conversions"] else None
        target, origin = _target(c, kpis)
        row = {**c, "cpa": cpa, "target": target, "target_origin": origin,
               "line": line_of(c["campaign_name"]), "funnel": funnel_of(c["campaign_name"])}
        if target is None:
            no_target.append(row)
            continue
        if cpa is None or cpa > target * (1 + s["tolleranza_target_pct"] / 100):
            # impatto: euro spesi oltre quanto sarebbe costato stare in target
            row["impact"] = c["spend"] - target * c["conversions"]
            row["deviation_pct"] = (cpa / target - 1) * 100 if cpa else None
            below.append(row)
            continue
        lost = c["lost_is_budget_pct"] or 0
        if lost >= s["quota_persa_budget_min_pct"] or c["bid_status"] == "LIMITED_BY_BUDGET":
            # effetto atteso di un passo di budget consentito dalle regole (+20%): se la
            # campagna è limitata dal budget, le conversioni crescono circa in proporzione
            step = s["passo_budget_pct"] / 100
            row["budget_step_pct"] = s["passo_budget_pct"]
            row["extra_conv"] = c["conversions"] * step
            row["extra_spend"] = c["spend"] * step
            scale.append(row)
        else:
            ok.append(row)
    period = (snap[0]["date_from"], snap[0]["date_to"]) if snap else None
    return {
        "available": True, "period": period,
        "below": sorted(below, key=lambda r: -r["impact"]),
        "scale": sorted(scale, key=lambda r: -r["extra_conv"]),
        "no_target": sorted(no_target, key=lambda r: -r["spend"]),
        "ok": ok,
    }
