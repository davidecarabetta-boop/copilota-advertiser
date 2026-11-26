"""Diagnosi (passo 3 della pipeline): la checklist del tipo di campagna, da config/diagnosi.yaml.

Le verifiche `auto` le calcola il Copilota con i dati che ha; quelle `chat` restano da fare con
Claude e gli MCP, con la richiesta già scritta. Esito: ok, attenzione, problema, da fare,
non disponibile.
"""

from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

import yaml

from copilota.config import CONFIG_DIR
from copilota.data import DataSource, Row

OK, WARN, BAD, CHAT, NA, INFO = ("ok", "attenzione", "problema", "da fare con Claude",
                                 "non disponibile", "informazione")
STATUS_TEXT = {
    "LIMITED_BY_BUDGET": (WARN, "limitata dal budget"),
    "LEARNING_NEW": (WARN, "in apprendimento (nuova)"),
    "LEARNING_SETTING_CHANGE": (WARN, "in apprendimento (impostazioni cambiate)"),
    "LEARNING_BUDGET_CHANGE": (WARN, "in apprendimento (budget cambiato)"),
    "LIMITED_BY_INVENTORY": (WARN, "limitata dall'inventario"),
    "ENABLED": (OK, "attiva, senza limiti"),
}


@lru_cache(maxsize=1)
def checklists() -> dict:
    return yaml.safe_load((CONFIG_DIR / "diagnosi.yaml").read_text(encoding="utf-8"))


@dataclass
class Finding:
    text: str
    base: bool
    state: str
    detail: str
    ask: str | None = None


def _safe(source: DataSource, table: str) -> list:
    try:
        return source.read(table)
    except FileNotFoundError:
        return []


def diagnose(source: DataSource, c: Row, th: dict, quality: dict | None,
             creative_findings: list) -> list[Finding]:
    """Checklist compilata per una campagna selezionata (`c` è una riga di selection.select)."""
    cfg = checklists()
    kind = cfg["tipi"].get(c["campaign_type"], {"verifiche": []})
    out = []
    for v in cfg["comuni"] + kind["verifiche"]:
        if v["fonte"] == "chat":
            out.append(Finding(v["testo"], v["base"], CHAT, "", v.get("chiedi")))
            continue
        state, detail = _auto(v["id"], source, c, th, quality, creative_findings)
        out.append(Finding(v["testo"], v["base"], state, detail))
    return out


def _auto(check: str, source: DataSource, c: Row, th: dict, quality: dict | None,
          creative_findings: list) -> tuple[str, str]:
    s = th["selezione"]
    if check == "target_vs_cpa":
        if c["target"] is None or c["cpa"] is None:
            return NA, "Manca il target: va dato dallo specialist o da Ads Guardian."
        dev = (c["cpa"] / c["target"] - 1) * 100
        state = BAD if dev > s["tolleranza_target_pct"] else OK
        return state, (f"CPA {c['cpa']:.1f} € contro un target di {c['target']:.1f} € "
                       f"({dev:+.0f}%, target da {c['target_origin']}).")
    if check == "stato_strategia":
        if c["platform"] == "meta":
            return NA, "Meta non espone lo stato della strategia: vedi apprendimento degli ad set."
        state, text = STATUS_TEXT.get(c["bid_status"], (WARN, c["bid_status"].lower()))
        return state, f"Strategia {c['bidding'].lower()}: {text}."
    if check == "modifiche_recenti":
        events = [e for e in _safe(source, "change_events")
                  if e["account_id"] == c["account_id"]]
        if not events:
            return NA, "Cronologia delle modifiche non importata per questo account."
        since = c["date_to"] - timedelta(days=14)
        adsets = {o["object_id"] for o in _safe(source, "object_status")
                  if o["campaign_id"] == c["campaign_id"]}
        mine = [e for e in events if e["date"] >= since and e["change"] in ("status", "budget")
                and (e["object_id"] == c["campaign_id"] or e["object_id"] in adsets)]
        if not mine:
            return OK, "Nessuna modifica di stato o budget nelle 2 settimane prima."
        last = max(mine, key=lambda e: e["date"])
        return WARN, (f"{len(mine)} modifiche di stato o budget; l'ultima il "
                      f"{last['date']:%d/%m} su «{last['object_name']}» ({last['change']}: "
                      f"{last['old_value']} → {last['new_value']}).")
    if check == "qualita_crm":
        row = next((r for r in (quality or {}).get("rows", [])
                    if r["campaign_id"] == c["campaign_id"]), None)
        if row is None or not row["leads"]:
            return NA, "Nessun lead di questa campagna nell'export CRM (o export mancante)."
        cpq = f"{row['cost_per_qualified']:.0f} €" if row["cost_per_qualified"] else "—"
        cpc = f"{row['cost_per_contract']:.0f} €" if row["cost_per_contract"] else "—"
        kpi = (row.get("kpi") or {}).get("cost_per_qualified")
        tol = 1 + th["campagne"]["tolleranza_kpi_pct"] / 100
        state = INFO if not kpi or not row["cost_per_qualified"] else (
            BAD if row["cost_per_qualified"] > kpi * tol else OK)
        return state, (f"{row['leads']} lead nel CRM, {row['qualified']} qualificati, "
                    f"{row['contracts']} contratti: {cpq} per qualificato, {cpc} per contratto."
                    + ("" if kpi else " Senza KPI dello specialist non c'è un giudizio."))
    if check in ("persa_budget", "persa_ranking"):
        v = c["lost_is_budget_pct"] if check == "persa_budget" else c["lost_is_rank_pct"]
        if v is None:
            return NA, "Dato non disponibile."
        state = WARN if v >= s["quota_persa_budget_min_pct"] else OK
        why = ("budget" if check == "persa_budget"
               else "ranking: offerta troppo bassa o annunci poco pertinenti")
        return state, f"Perde il {v:.0f}% delle impressioni per {why}."
    if check == "frequenza":
        f = c["frequency"]
        if f is None:
            return NA, "Dato non disponibile."
        state = WARN if f > s["frequenza_max_mese"] else OK
        return state, f"Frequenza {f:.1f} nella finestra (limite {s['frequenza_max_mese']:g})."
    if check == "apprendimento":
        st = [o for o in _safe(source, "object_status") if o["campaign_id"] == c["campaign_id"]
              and (o["learning"] or o["in_test"])]
        if not st:
            return OK, "Nessun ad set in apprendimento o in test."
        return WARN, "In apprendimento o test: " + ", ".join(f"«{o['object_name']}»" for o in st)
    if check == "stanchezza":
        tired = [f for f in creative_findings if f.issue_code in ("fatigue_late", "fatigue_prepare")
                 and f.evidence.get("campagna_id") == c["campaign_id"]]
        if not tired:
            return OK, "Nessuna creatività stanca secondo il semaforo."
        return WARN, "Creatività stanche: " + ", ".join(f"«{f.object_id}»" for f in tired)
    return NA, "Verifica non ancora implementata."
