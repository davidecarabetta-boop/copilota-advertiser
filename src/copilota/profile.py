"""Scheda cliente: lo studio del cliente da cui parte ogni brief.

Metà viene dai dati (struttura degli account, spesa per linea, qualità dal CRM, KPI, stato del
tracciamento, cosa non si può toccare), metà la scrive chi conosce il cliente in
data/<cliente>/profilo.yaml (cosa vende, margini, stagionalità). Quello che non si sa resta
"da confermare": la scheda non inventa.
"""

from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

from copilota import register
from copilota.campaigns import campaign_quality, read_kpis
from copilota.config import load_client, load_thresholds
from copilota.data import DataSource, Row
from copilota.rules import funnel_of, line_of
from copilota.signals import lead_quality

FUNNEL = {"UF": "awareness", "MF": "prospecting", "LF": "fondo del funnel"}


def _safe(source: DataSource, table: str) -> list[Row]:
    try:
        return source.read(table)
    except FileNotFoundError:
        return []


def manual(folder: Path) -> dict:
    f = Path(folder) / "profilo.yaml"
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}


def build(source: DataSource, folder: Path, today: date | None = None) -> dict:
    accounts = source.read("accounts")
    client = accounts[0]["client"]
    cfg, th = load_client(client), load_thresholds(client)
    snap = _safe(source, "campaign_snapshot")
    today = today or date.today()

    # Struttura: spesa per linea e piattaforma nella fotografia
    lines: dict[str, dict] = defaultdict(lambda: {"google": 0.0, "meta": 0.0, "campaigns": 0})
    for s in snap:
        x = lines[line_of(s["campaign_name"])]
        x[s["platform"]] += s["spend"]
        x["campaigns"] += 1
    total = sum(x["google"] + x["meta"] for x in lines.values()) or 1
    structure = sorted(({"line": k, **v, "share": (v["google"] + v["meta"]) / total * 100}
                        for k, v in lines.items()), key=lambda r: -r["share"])
    period = (min(s["date_from"] for s in snap), max(s["date_to"] for s in snap)) if snap else None

    # Cosa funziona: costo per lead in trattativa dal CRM, campagne con abbastanza lead
    min_leads = th["campagne"]["lead_min"]
    quality, crm = [], []
    for a in accounts:
        q = campaign_quality(source, a)
        if q:
            for r in q["rows"]:
                if r["leads"] >= min_leads and r["cost_per_qualified"]:
                    quality.append({**r, "platform": a["platform"],
                                    "funnel": FUNNEL.get(funnel_of(r["name"]), "?")})
        lq = lead_quality(source, a, today, th)
        if lq and lq.get("recent"):
            crm.append({"account": a, **lq["recent"]})
    quality.sort(key=lambda r: r["cost_per_qualified"])

    # Tracciamento e vincoli
    tracking = {t["account_id"]: t for t in _safe(source, "tracking_status")}
    track = []
    for a in accounts:
        t = tracking.get(a["account_id"], {})
        last = t.get("crm_last_upload")
        track.append({"account": a, "event": t.get("optimization_event") or "?",
                      "crm_back": t.get("crm_quality_feedback"),
                      "crm_last": last, "crm_days": (today - last).days if last else None})
    log = _safe(source, "change_log")
    holds = [{"what": e["campaign_name"], "until": e["until"], "why": e["why"]}
             for e in register.dont_touch(log, today)]
    holds += [{"what": s["object_name"], "until": s["until"],
               "why": "In apprendimento." if s["learning"] else "In un test."}
              for s in _safe(source, "object_status") if s["learning"] or s["in_test"]]

    kpis = read_kpis(source)
    perimeter = (cfg.get("perimetro") or {}).get("linee") or []
    missing_kpi = [f"{p} {line}" for line in perimeter for p in ("google", "meta")
                   if (p, line) not in kpis and any(
                       r["line"] == line and r[p] > 0 for r in structure)]
    return {
        "client": client, "accounts": accounts, "manual": manual(folder),
        "brand": (cfg.get("brand") or {}).get("termini") or [],
        "objective": cfg.get("obiettivo"), "verified": cfg.get("tracciamento_verificato"),
        "crm_rules": cfg.get("crm") or {}, "perimeter": perimeter,
        "structure": structure, "period": period,
        "best": quality[:3], "worst": quality[-3:][::-1] if len(quality) > 3 else [],
        "crm": crm, "tracking": track, "holds": holds,
        "kpis": kpis, "missing_kpi": missing_kpi,
    }
