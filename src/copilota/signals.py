"""Modulo Segnali (fase 02): il cancello.

Per ogni account produce una lista di controlli verde/giallo/rosso e un esito complessivo (`gate`).
Se l'esito è rosso, gli altri moduli dicono solo "apri ticket".

Controlli implementati: conversione principale assente, Enhanced Conversions / CAPI e copertura,
riconciliazione piattaforma vs CRM (con deduplica), Consent Mode v2, conversione di ottimizzazione
per lead gen, aggiornamento Customer Match, volume di conversioni per campagna.
Non ancora: valore/margine (solo e-commerce) e obiettivo nuovi clienti (mancano i dati).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from copilota.data import DataSource, Row


class Status(StrEnum):
    GREEN = "verde"
    YELLOW = "giallo"
    RED = "rosso"

    @property
    def rank(self) -> int:
        return [Status.GREEN, Status.YELLOW, Status.RED].index(self)


@dataclass(frozen=True)
class Check:
    account_id: str
    group: str  # Tracking, Obiettivo, First-party, Volume
    name: str
    status: Status
    detail: str  # testo per l'advertiser, in italiano


def gate(checks: list[Check]) -> Status:
    return max((c.status for c in checks), key=lambda s: s.rank, default=Status.GREEN)


def _daily(rows: list[Row], account_id: str, metric: str) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for r in rows:
        if r["account_id"] == account_id:
            out[r["date"]] += r[metric]
    return out


def check_account(source: DataSource, account: Row, th: dict) -> list[Check]:
    acc, platform = account["account_id"], account["platform"]
    seg, vol = th["segnali"], th["volume"]
    table, cost_col, conv_col, camp_col = (
        ("ga_campaign_daily", "cost", "conversions", "campaign_name")
        if platform == "google"
        else ("meta_ad_daily", "spend", "leads", "campaign_id")
    )
    rows = [r for r in source.read(table) if r["account_id"] == acc]
    tracking = next((t for t in source.read("tracking_status") if t["account_id"] == acc), None)
    checks: list[Check] = []

    def add(group: str, name: str, status: Status, detail: str) -> None:
        checks.append(Check(acc, group, name, status, detail))

    if not rows:
        add("Tracking", "Dati presenti", Status.RED, "Nessun dato per questo account.")
        return checks
    today = max(r["date"] for r in rows)

    # Conversione principale assente nell'ultimo giorno
    cost, conv = _daily(rows, acc, cost_col), _daily(rows, acc, conv_col)
    if cost[today] > 0 and conv[today] == 0:
        add("Tracking", "Conversione principale", Status.RED,
            f"Il {today:%d/%m} si è speso {cost[today]:.0f} € con zero conversioni: "
            "il tracciamento potrebbe essere rotto.")
    else:
        add("Tracking", "Conversione principale", Status.GREEN,
            f"Il {today:%d/%m} registrate {conv[today]:.0f} conversioni.")

    # Enhanced Conversions (Google) / CAPI (Meta)
    if tracking:
        if platform == "google":
            ok = tracking["enhanced_conversions"]
            add("Tracking", "Enhanced Conversions", Status.GREEN if ok else Status.YELLOW,
                "Attive." if ok else "Non attive: Google vede meno conversioni di quelle reali.")
        else:
            cov, min_cov = tracking["capi_coverage_pct"], seg["copertura_capi_min_pct"]
            if not tracking["capi_active"]:
                add("Tracking", "CAPI", Status.YELLOW,
                    "Conversions API non attiva: Meta vede solo gli eventi del Pixel.")
            elif cov is not None and cov < min_cov:
                add("Tracking", "CAPI", Status.YELLOW,
                    f"Copertura CAPI {cov:.0f}%, sotto il minimo del {min_cov}%.")
            else:
                add("Tracking", "CAPI", Status.GREEN, "Attiva, copertura sufficiente.")

    # Riconciliazione piattaforma vs CRM
    win = seg["finestra_riconciliazione_giorni"]
    start = today - timedelta(days=win - 1)
    plat = sum(v for d, v in conv.items() if d >= start)
    crm = sum(
        b["leads"]
        for b in source.read("backend_daily")
        if b["client"] == account["client"]
        and b["source"] == platform
        and start <= b["date"] <= today
    )
    if crm == 0:
        add("Tracking", "Riconciliazione con CRM", Status.YELLOW,
            f"Nessun lead dal CRM negli ultimi {win} giorni: impossibile verificare i numeri.")
    else:
        gap = (plat - crm) / crm * 100
        txt = f"Ultimi {win} giorni: piattaforma {plat:.0f}, CRM {crm}, scarto {gap:+.0f}%."
        if plat / crm >= seg["rapporto_rosso_piattaforma_su_backend"]:
            add("Tracking", "Riconciliazione con CRM", Status.RED,
                txt + " La piattaforma conta più del doppio: "
                "probabile doppio conteggio Pixel/CAPI.")
        elif abs(gap) > seg["scarto_rosso_piattaforma_vs_backend_pct"]:
            add("Tracking", "Riconciliazione con CRM", Status.RED, txt)
        elif abs(gap) > seg["scarto_max_piattaforma_vs_backend_pct"]:
            add("Tracking", "Riconciliazione con CRM", Status.YELLOW, txt)
        else:
            add("Tracking", "Riconciliazione con CRM", Status.GREEN, txt)

    if tracking:
        # Consent Mode v2 (solo dove il dato c'è)
        if tracking["consent_mode_v2"] is False:
            add("Tracking", "Consent Mode v2", Status.RED, "Consent Mode v2 assente.")
        elif tracking["consent_mode_v2"]:
            now, prev = tracking["consent_rate_pct"], tracking["consent_rate_prev_pct"]
            drop = (prev - now) if now is not None and prev is not None else 0
            if drop > seg["calo_consenso_alert_punti"]:
                add("Tracking", "Consent Mode v2", Status.YELLOW,
                    f"Tasso di consenso sceso di {drop:.0f} punti ({prev:.0f}% → {now:.0f}%).")
            else:
                add("Tracking", "Consent Mode v2", Status.GREEN, "Attivo, consenso stabile.")

        # Obiettivo: lead gen senza qualità dal CRM
        if account["objective"].startswith("lead") and tracking["crm_quality_feedback"] is False:
            add("Obiettivo", "Conversione di ottimizzazione", Status.RED,
                f"Si ottimizza su '{tracking['optimization_event']}' senza la qualità dal CRM: "
                "la piattaforma cerca lead qualsiasi, non lead buoni.")
        else:
            add("Obiettivo", "Conversione di ottimizzazione", Status.GREEN,
                f"Ottimizzazione su '{tracking['optimization_event']}'.")

        # First-party: Customer Match
        upd, max_days = tracking["customer_match_updated"], seg["customer_match_max_giorni"]
        if upd is None:
            add("First-party", "Customer Match", Status.YELLOW, "Nessun pubblico clienti caricato.")
        elif (today - upd).days > max_days:
            add("First-party", "Customer Match", Status.YELLOW,
                f"Pubblico clienti fermo al {upd:%d/%m/%Y} ({(today - upd).days} giorni, "
                f"massimo {max_days}).")
        else:
            add("First-party", "Customer Match", Status.GREEN, f"Aggiornato il {upd:%d/%m/%Y}.")

    # Volume: conversioni negli ultimi 30 giorni per campagna
    month = today - timedelta(days=29)
    per_camp: dict[str, float] = defaultdict(float)
    days_seen: dict[str, set] = defaultdict(set)
    for r in rows:
        if r["date"] >= month:
            per_camp[r[camp_col]] += r[conv_col]
            days_seen[r[camp_col]].add(r["date"])
    min_conv = vol["conversioni_min_mese_per_campagna"]
    min_days = vol["giorni_min_prima_di_giudicare"]
    low = sorted(
        (c, n) for c, n in per_camp.items() if n < min_conv and len(days_seen[c]) >= min_days
    )
    if low:
        names = "; ".join(f"{c} ({n:.0f})" for c, n in low)
        add("Volume", "Conversioni per campagna", Status.YELLOW,
            f"Sotto le {min_conv} conversioni al mese: {names}. "
            "L'algoritmo impara poco: valutare di accorpare.")
    else:
        add("Volume", "Conversioni per campagna", Status.GREEN,
            f"Tutte le campagne sopra le {min_conv} conversioni al mese.")

    return checks


def ticket_text(account: Row, checks: list[Check]) -> str:
    """Testo precompilato per il team analytics quando l'account è rosso."""
    reds = [c for c in checks if c.status is Status.RED]
    where = f"{account['platform']} {account['account_id']}"
    lines = [f"[Copilota] Segnali rossi su {account['name']} ({where})", ""]
    lines += [f"- {c.group} / {c.name}: {c.detail}" for c in reds]
    lines += ["", "Finché non è risolto, sull'account non si fanno altre modifiche."]
    return "\n".join(lines)
