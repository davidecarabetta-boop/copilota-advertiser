"""Scheda creativa: giudizio su una singola creatività statica, accanto ai suoi numeri.

Le schede le compila Claude guardando l'immagine (procedura nella skill), una per creatività,
in `data/<cliente>/schede_creative/<creative_id>.yaml`. I campi e i controlli ammessi stanno in
`config/scheda_creativa.yaml`: qui si validano le schede e si aggiungono spesa, lead, CTR e
costo per lead degli annunci che usano la creatività, con il confronto sulla loro campagna.

Formato di una scheda:
    creative_id: "1424298183231130"
    nome: Citroën C3 Aircross - 26 Ottobre
    ad_ids: ["52596724665557"]
    immagine: img/62528bcb.jpg          # relativo a schede_creative/
    compilata_il: 2026-11-24
    confermata: false                   # true dopo la revisione dell'advertiser o del senior
    campi: {leva: prezzo_modello, soggetto: prodotto_singolo, formato: "1:1", ...}
    testi: {titolo: ..., offerta: ..., claim: ..., cta: ..., testo_principale: ...}
    punti_forti: [frase, ...]
    controlli: [{id: tipo_di_offerta, esito: problema, nota: ...}, ...]
    test: [{cambia: ..., ipotesi: ...}, ...]
"""

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from copilota.config import CONFIG_DIR
from copilota.data import DataSource, Row

FOLDER = "schede_creative"
OUTCOMES = ("ok", "attenzione", "problema")


def load_rubric(config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    return yaml.safe_load((config_dir / "scheda_creativa.yaml").read_text(encoding="utf-8"))


def load(folder: Path) -> list[dict]:
    """Le schede del cliente, in ordine di nome file. Cartella assente = nessuna scheda."""
    d = folder / FOLDER
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.yaml")):
        s = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        s["_file"] = f.name
        out.append(s)
    return out


def validate(scheda: dict, rubric: dict) -> list[str]:
    """Errori della scheda rispetto a config/scheda_creativa.yaml (lista vuota = valida)."""
    errors = []
    for key in ("creative_id", "ad_ids", "campi", "controlli"):
        if not scheda.get(key):
            errors.append(f"manca '{key}'")
    for name, value in (scheda.get("campi") or {}).items():
        allowed = rubric["campi"].get(name)
        if allowed is None:
            errors.append(f"campo sconosciuto '{name}'")
        elif allowed == "bool":
            if not isinstance(value, bool):
                errors.append(f"'{name}' deve essere true o false")
        elif value not in allowed:
            errors.append(f"'{name}': valore '{value}' non ammesso")
    known = {c["id"] for c in rubric["controlli"]}
    missing = known - {c.get("id") for c in scheda.get("controlli") or []}
    if scheda.get("controlli") and missing:
        errors.append("mancano i controlli " + ", ".join(sorted(missing)))
    for c in scheda.get("controlli") or []:
        if c.get("id") not in known:
            errors.append(f"controllo sconosciuto '{c.get('id')}'")
        if c.get("esito") not in OUTCOMES:
            errors.append(f"controllo '{c.get('id')}': esito '{c.get('esito')}' non ammesso")
        elif c["esito"] != "ok" and not c.get("nota"):
            errors.append(f"controllo '{c.get('id')}': manca la nota")
    if len(scheda.get("test") or []) > rubric["test"]["max_per_scheda"]:
        errors.append(f"più di {rubric['test']['max_per_scheda']} test")
    return errors


def _totals(rows: list[Row]) -> dict:
    spend = sum(r["spend"] for r in rows)
    impr = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    leads = sum(r["leads"] for r in rows)
    return {
        "spend": round(spend, 2), "impressions": impr, "clicks": clicks, "leads": leads,
        "ctr_pct": round(clicks / impr * 100, 2) if impr else None,
        "cpl": round(spend / leads, 2) if leads else None,
    }


def _judgement(perf: dict, campaign: dict, rubric: dict) -> str | None:
    """Una frase sul costo per lead rispetto alla campagna, solo con abbastanza dati."""
    n = rubric["numeri"]
    if perf["impressions"] < n["impressioni_min"]:
        return "pochi dati: troppe poche impressioni per giudicare"
    if perf["leads"] < n["lead_min"]:
        return f"pochi dati: {perf['leads']:.0f} lead"
    if not campaign.get("cpl") or not perf["cpl"]:
        return None
    ratio = perf["cpl"] / campaign["cpl"]
    if ratio <= 0.8:
        return "costo per lead più basso della media della campagna"
    if ratio >= 1.2:
        return "costo per lead più alto della media della campagna"
    return "costo per lead in linea con la media della campagna"


def _groups(checks: list[dict], rubric: dict) -> list[dict]:
    """Controlli divisi per lettera ABCD (più il gruppo SearchOn), i problemi prima."""
    sources = rubric.get("fonti") or {}
    out = []
    for g in rubric.get("gruppi") or []:
        items = [c for c in checks if c.get("gruppo") == g["id"]]
        if not items:
            continue
        items.sort(key=lambda c: -OUTCOMES.index(c["esito"]) if c.get("esito") in OUTCOMES else 0)
        names = sorted({sources.get(c["fonte"], {}).get("nome", c["fonte"])
                        for c in items if c.get("fonte")})
        out.append({**g, "checks": items, "fonti": names,
                    "ok": sum(c.get("esito") == "ok" for c in items)})
    return out


def build(source: DataSource, folder: Path, account_id: str,
          rubric: dict | None = None) -> dict:
    """Schede dell'account con numeri e confronto, più un riepilogo per leva."""
    rubric = rubric or load_rubric()
    try:
        rows = [r for r in source.read("meta_ad_daily") if r["account_id"] == account_id]
    except FileNotFoundError:
        rows = []
    try:
        names = {c["campaign_id"]: c["campaign_name"] for c in source.read("meta_campaigns")}
    except FileNotFoundError:
        names = {}
    by_ad: dict[str, list[Row]] = defaultdict(list)
    by_campaign: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_ad[r["ad_id"]].append(r)
        by_campaign[r["campaign_id"]].append(r)
    controls = {c["id"]: c for c in rubric["controlli"]}

    cards = []
    for s in load(folder):
        ad_ids = [str(a) for a in s.get("ad_ids") or []]
        ad_rows = [r for a in ad_ids for r in by_ad.get(a, [])]
        if rows and not ad_rows:
            continue  # creatività di un altro account o fuori dal periodo
        perf = _totals(ad_rows)
        camp_ids = sorted({r["campaign_id"] for r in ad_rows})
        camp = _totals([r for c in camp_ids for r in by_campaign[c]]) if camp_ids else {}
        checks = [{**c, **{k: controls.get(c.get("id"), {}).get(k, "")
                           for k in ("perche", "gruppo", "fonte", "linea_guida")},
                   "domanda": controls.get(c.get("id"), {}).get("domanda", c.get("id"))}
                  for c in s.get("controlli") or []]
        cards.append({
            "s": s, "perf": perf, "campaign": camp,
            "campaigns": [names.get(c, c) for c in camp_ids],
            "judgement": _judgement(perf, camp, rubric) if ad_rows else None,
            "checks": sorted(checks, key=lambda c: -OUTCOMES.index(c.get("esito", "ok"))
                             if c.get("esito") in OUTCOMES else 0),
            "groups": _groups(checks, rubric),
            "problems": sum(c.get("esito") == "problema" for c in checks),
            "warnings": sum(c.get("esito") == "attenzione" for c in checks),
            "errors": validate(s, rubric),
        })
    cards.sort(key=lambda c: -c["perf"]["spend"])

    # Riepilogo per leva: somma dei numeri delle schede con la stessa leva
    by_lever: dict[str, list[Row]] = defaultdict(list)
    count: dict[str, int] = defaultdict(int)
    for c in cards:
        lever = (c["s"].get("campi") or {}).get("leva", "?")
        count[lever] += 1
        by_lever[lever].extend(r for a in c["s"].get("ad_ids") or [] for r in by_ad.get(str(a), []))
    levers = sorted(({"leva": k, "schede": count[k], **_totals(v)} for k, v in by_lever.items()),
                    key=lambda x: -x["spend"])
    return {"cards": cards, "levers": levers}
