"""Qualità dei lead per campagna: quanto costa un lead che arriva in trattativa (e un contratto),
dall'export CRM per UTM campaign incrociato con la spesa delle piattaforme nello stesso periodo.

Si usano solo lead maturi (il periodo di `campaign_period`), tutti della stessa età: così la
quota "in trattativa o oltre" è confrontabile tra campagne, anche se non lo è nel tempo.
"""

from collections import defaultdict

from copilota.config import load_client
from copilota.data import DataSource, Row


def _key(name: str) -> str:
    """Chiave di abbinamento: minuscole, '-' come '_', niente '+', spazi singoli, senza la fase
    del funnel (2° segmento), che cambia tra UTM e nome campagna."""
    s = " ".join(name.replace("+", " ").replace("-", "_").lower().split())
    parts = [p.strip() for p in s.split("|")]
    if len(parts) > 2:
        parts = parts[:1] + parts[2:]
    return "|".join(parts)


def _in_scope(name: str, lines: list[str]) -> bool:
    """La linea è il 3° segmento del naming (AUTO_B2C, RENT_B2C, AUTO I B2C…)."""
    parts = [p.strip() for p in name.split("|")]
    line = parts[2] if len(parts) > 2 else name
    return not lines or any(line.upper().startswith(x.upper()) for x in lines)


def campaign_quality(source: DataSource, account: Row) -> dict | None:
    try:
        period = [c for c in source.read("campaign_period")
                  if c["account_id"] == account["account_id"]]
        crm = source.read("backend_campaign_daily")
    except FileNotFoundError:
        return None
    if not period:
        return None
    start, end = period[0]["date_from"], period[0]["date_to"]
    lines = (load_client(account["client"]).get("crm") or {}).get("linee_perimetro") or []
    by_key = {_key(c["campaign_name"]): c for c in period}
    by_id = {c["campaign_id"]: c for c in period}

    stats: dict[str, dict] = {}
    unmatched: dict[str, int] = defaultdict(int)
    for r in crm:
        if r["source"] != account["platform"] or not (start <= r["date"] <= end):
            continue
        k = _key(r["utm_campaign"])
        camp = by_key.get(k) or by_id.get(r["utm_campaign"])
        if camp is None:  # l'UTM a volte aggiunge un suffisso al nome della campagna
            cands = [kk for kk in by_key if k.startswith(kk)]
            camp = by_key[max(cands, key=len)] if cands else None
        if camp is None:
            unmatched[r["utm_campaign"]] += r["leads"]
            continue
        s = stats.setdefault(camp["campaign_id"], {"leads": 0, "qualified": 0, "contracts": 0})
        s["leads"] += r["leads"]
        s["qualified"] += r["qualified_leads"]
        s["contracts"] += r["contracts"]

    rows = []
    for c in period:
        if not _in_scope(c["campaign_name"], lines):
            continue
        s = stats.get(c["campaign_id"], {"leads": 0, "qualified": 0, "contracts": 0})
        if not s["leads"] and c["spend"] < 1:
            continue
        rows.append({
            "campaign_id": c["campaign_id"], "name": c["campaign_name"], "spend": c["spend"],
            "platform_conversions": c["platform_conversions"], **s,
            "cost_per_lead": c["spend"] / s["leads"] if s["leads"] else None,
            "cost_per_qualified": c["spend"] / s["qualified"] if s["qualified"] else None,
            "cost_per_contract": c["spend"] / s["contracts"] if s["contracts"] else None,
        })
    with_leads = [r for r in rows if r["leads"]]
    spend = sum(r["spend"] for r in with_leads)
    qualified = sum(r["qualified"] for r in with_leads)
    return {
        "from": start, "to": end, "rows": sorted(rows, key=lambda r: -r["spend"]),
        "avg_cost_per_qualified": spend / qualified if qualified else None,
        "unmatched": sorted(unmatched.items(), key=lambda kv: -kv[1]),
        "lines": lines,
    }


def judge(q: dict, th: dict) -> dict:
    """Campagne che spendono molto per pochi lead buoni, e la migliore dove spostare budget."""
    s = th["campagne"]
    avg = q["avg_cost_per_qualified"]
    rated = [r for r in q["rows"] if r["leads"] >= s["lead_min"]]
    total = sum(r["spend"] for r in rated)
    best = min((r for r in rated if r["qualified"] >= s["trattative_min_migliore"]),
               key=lambda r: r["cost_per_qualified"], default=None)
    poor = []
    if avg:
        for r in rated:
            share = r["spend"] / total * 100 if total else 0
            cpq = r["cost_per_qualified"]
            if share >= s["quota_spesa_min_pct"] and (cpq is None or cpq >= avg * s["volte_media"]):
                poor.append({**r, "share_pct": round(share)})
    utm_lost = [(u, n) for u, n in q["unmatched"] if n >= s["utm_non_abbinati_min_lead"]]
    return {"poor": poor, "best": best, "avg": avg, "utm_lost": utm_lost}
