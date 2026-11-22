"""Modulo Segnali (fase 02): il cancello.

Per ogni account produce una lista di controlli verde/giallo/rosso e un esito complessivo (`gate`).
Se l'esito è rosso, gli altri moduli dicono solo "apri ticket".

Controlli implementati: conversioni crollate, conversione principale assente (solo campagne a
conversione), Enhanced Conversions / CAPI e copertura,
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


UNKNOWN = "dato non disponibile, da verificare a mano."


def gate(checks: list[Check]) -> Status:
    return max((c.status for c in checks), key=lambda s: s.rank, default=Status.GREEN)


def _daily(rows: list[Row], account_id: str, metric: str) -> dict[date, float]:
    out: dict[date, float] = defaultdict(float)
    for r in rows:
        if r["account_id"] == account_id:
            out[r["date"]] += r[metric]
    return out


# Campagne che ottimizzano per conversioni: solo su queste hanno senso i controlli di volume
# e di conversioni mancanti (traffico, interazione, video non cercano lead).
GOOGLE_CONV_BIDDING = {
    "MAXIMIZE_CONVERSIONS", "TARGET_CPA", "MAXIMIZE_CONVERSION_VALUE", "TARGET_ROAS",
}
META_CONV_OBJECTIVES = {"OUTCOME_LEADS", "OUTCOME_SALES", "LEAD_GENERATION", "CONVERSIONS"}
# Categorie di azione di conversione Google che sono davvero lead o vendite
LEAD_CATEGORIES = {
    "SUBMIT_LEAD_FORM", "PHONE_CALL_LEAD", "IMPORTED_LEAD", "QUALIFIED_LEAD", "CONVERTED_LEAD",
    "BOOK_APPOINTMENT", "REQUEST_QUOTE", "CONTACT", "PURCHASE", "STORE_SALE",
}


def _crm_quality(source: DataSource, account: Row, today: date) -> dict[date, tuple]:
    """{giorno: (lead, lead qualificati)} dall'export CRM, solo giorni con il dato di qualità."""
    return {b["date"]: (b["leads"], b["qualified_leads"]) for b in source.read("backend_daily")
            if b["client"] == account["client"] and b["source"] == account["platform"]
            and b["date"] <= today and b["qualified_leads"] is not None}


def _offline_quality(offline_q: dict[date, float], conv: dict[date, float]) -> dict[date, tuple]:
    """{giorno: (conversioni piattaforma, qualificati caricati offline)}; vuoto se non c'è
    nessun caricamento offline."""
    if not any(offline_q.values()):
        return {}
    return {d: (conv[d], offline_q.get(d, 0.0)) for d in conv}


def quality_measured(source: DataSource, account: Row) -> bool:
    """True se c'è una fonte di qualità (export CRM o conversioni offline): senza, l'esito dice
    se il tracciamento regge, non se l'account rende."""
    crm = any(b["client"] == account["client"] and b["source"] == account["platform"]
              and b["qualified_leads"] for b in source.read("backend_daily"))
    offline = any(o["account_id"] == account["account_id"] and o["conversions"] > 0
                  for o in source.read("offline_conversions_daily"))
    return crm or offline


def _conversion_rows(source: DataSource, platform: str, rows: list[Row]) -> list[Row]:
    """Righe delle sole campagne a conversione, con `campaign_label` leggibile."""
    if platform == "google":
        return [{**r, "campaign_label": r["campaign_name"]} for r in rows
                if r["bidding_strategy"] in GOOGLE_CONV_BIDDING]
    campaigns = {c["campaign_id"]: c for c in source.read("meta_campaigns")}
    out = []
    for r in rows:
        c = campaigns.get(r["campaign_id"])
        if c is None or c["objective"] in META_CONV_OBJECTIVES:  # sconosciuta: la teniamo
            out.append({**r, "campaign_label": c["campaign_name"] if c else r["campaign_id"]})
    return out


def check_account(source: DataSource, account: Row, th: dict) -> list[Check]:
    acc, platform = account["account_id"], account["platform"]
    seg, vol = th["segnali"], th["volume"]
    table, cost_col, conv_col = (
        ("ga_campaign_daily", "cost", "conversions")
        if platform == "google"
        else ("meta_ad_daily", "spend", "leads")
    )
    all_rows = [r for r in source.read(table) if r["account_id"] == acc]
    rows = _conversion_rows(source, platform, all_rows)
    tracking = next((t for t in source.read("tracking_status") if t["account_id"] == acc), None)
    checks: list[Check] = []

    def add(group: str, name: str, status: Status, detail: str) -> None:
        checks.append(Check(acc, group, name, status, detail))

    if not all_rows:
        add("Tracking", "Dati presenti", Status.RED, "Nessun dato per questo account.")
        return checks
    today = max(r["date"] for r in all_rows)
    if not rows:
        add("Obiettivo", "Campagne a conversione", Status.YELLOW,
            "Nessuna campagna ottimizza per conversioni: l'algoritmo non cerca lead.")
    cost, conv = _daily(rows, acc, cost_col), _daily(rows, acc, conv_col)

    # Conversioni crollate: ultimi N giorni contro il periodo precedente
    recent_days = seg["giorni_recenti"]
    cut = today - timedelta(days=recent_days - 1)
    before = [d for d in conv if d < cut]
    if before:
        conv_before = sum(conv[d] for d in before) / len(before)
        conv_recent = sum(v for d, v in conv.items() if d >= cut) / recent_days
        cost_before = sum(cost[d] for d in before) / len(before)
        cost_recent = sum(v for d, v in cost.items() if d >= cut) / recent_days
        drop = (1 - conv_recent / conv_before) * 100 if conv_before else 0
        if drop >= seg["calo_conversioni_rosso_pct"]:
            add("Tracking", "Andamento conversioni", Status.RED,
                f"Conversioni crollate del {drop:.0f}%: da {conv_before:.1f} a "
                f"{conv_recent:.1f} al giorno negli ultimi {recent_days} giorni "
                f"(spesa da {cost_before:.0f} € a {cost_recent:.0f} € al giorno). "
                "Controllare subito modulo e tracciamento, poi la consegna delle campagne.")
        else:
            add("Tracking", "Andamento conversioni", Status.GREEN,
                f"{conv_recent:.1f} conversioni al giorno negli ultimi {recent_days} giorni "
                f"(prima {conv_before:.1f}).")

    # Zero conversioni nell'ultimo giorno, con una spesa che ne avrebbe dovute portare
    total_cost, total_conv = sum(cost.values()), sum(conv.values())
    cpa = total_cost / total_conv if total_conv else None
    min_spend = cpa * seg["zero_conversioni_se_spesa_oltre_cpa_x"] if cpa else 0
    if rows and conv[today] == 0 and cost[today] > 0 and cost[today] >= min_spend:
        add("Tracking", "Conversione principale", Status.RED,
            f"Il {today:%d/%m} si è speso {cost[today]:.0f} € con zero conversioni "
            f"(di solito una ogni {cpa or 0:.0f} €): il tracciamento potrebbe essere rotto.")
    elif rows:
        add("Tracking", "Conversione principale", Status.GREEN,
            f"Il {today:%d/%m}: {conv[today]:.0f} conversioni con {cost[today]:.0f} € di spesa.")
    conv_all = _daily(all_rows, acc, conv_col)
    # Conversioni offline: nessuna riga per l'account = dato non importato (diverso da zero)
    offline_rows = [o for o in source.read("offline_conversions_daily") if o["account_id"] == acc]
    offline_q: dict[date, float] = defaultdict(float)
    for o in offline_rows:
        if o["stage"] == "qualified":
            offline_q[o["date"]] += o["conversions"]

    if not tracking:
        add("Tracking", "Stato del tracciamento", Status.YELLOW,
            "Stato del tracciamento non disponibile: " + UNKNOWN)

    # Enhanced Conversions (Google) / CAPI (Meta)
    if tracking:
        if platform == "google":
            ok = tracking["enhanced_conversions"]
            if ok is None:
                add("Tracking", "Enhanced Conversions", Status.YELLOW, UNKNOWN)
            else:
                off = "Non attive: Google vede meno conversioni di quelle reali."
                add("Tracking", "Enhanced Conversions", Status.GREEN if ok else Status.YELLOW,
                    "Attive." if ok else off)
        else:
            cov, min_cov = tracking["capi_coverage_pct"], seg["copertura_capi_min_pct"]
            if tracking["capi_active"] is None:
                add("Tracking", "CAPI", Status.YELLOW, UNKNOWN)
            elif not tracking["capi_active"]:
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
    plat = sum(v for d, v in conv_all.items() if d >= start)
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
        # Consent Mode v2 (Google; su Meta non si applica)
        if tracking["consent_mode_v2"] is None:
            if platform == "google":
                add("Tracking", "Consent Mode v2", Status.YELLOW, UNKNOWN)
        elif tracking["consent_mode_v2"] is False:
            add("Tracking", "Consent Mode v2", Status.RED, "Consent Mode v2 assente.")
        elif tracking["consent_mode_v2"]:
            now, prev = tracking["consent_rate_pct"], tracking["consent_rate_prev_pct"]
            drop = (prev - now) if now is not None and prev is not None else 0
            if drop > seg["calo_consenso_alert_punti"]:
                add("Tracking", "Consent Mode v2", Status.YELLOW,
                    f"Tasso di consenso sceso di {drop:.0f} punti ({prev:.0f}% → {now:.0f}%).")
            else:
                add("Tracking", "Consent Mode v2", Status.GREEN, "Attivo, consenso stabile.")

        # Obiettivo: lead gen senza qualità dal CRM (anche quando il caricamento si è fermato)
        is_lead = account["objective"].startswith("lead")
        uploads = [d for d, v in offline_q.items() if v > 0]
        last = max([d for d in [tracking["crm_last_upload"], *uploads] if d], default=None)
        stale = last is not None and (today - last).days > seg["crm_max_giorni_senza_caricamento"]
        if is_lead and tracking["crm_quality_feedback"] and stale:
            add("Obiettivo", "Conversione di ottimizzazione", Status.RED,
                f"Il CRM non manda più la qualità dei lead dal {last:%d/%m/%Y} "
                f"({(today - last).days} giorni): la piattaforma ottimizza su lead qualsiasi. "
                "Far ripartire il caricamento delle conversioni offline.")
        elif is_lead and tracking["crm_quality_feedback"] is None:
            add("Obiettivo", "Conversione di ottimizzazione", Status.YELLOW,
                "Ritorno della qualità dei lead dal CRM alla piattaforma: " + UNKNOWN)
        elif is_lead and tracking["crm_quality_feedback"] is False:
            add("Obiettivo", "Conversione di ottimizzazione", Status.RED,
                f"Si ottimizza su '{tracking['optimization_event']}' senza la qualità dal CRM: "
                "la piattaforma cerca lead qualsiasi, non lead buoni.")
        else:
            add("Obiettivo", "Conversione di ottimizzazione", Status.GREEN,
                f"Ottimizzazione su '{tracking['optimization_event']}', "
                "con la qualità dei lead dal CRM.")

        # First-party: Customer Match
        upd, max_days = tracking["customer_match_updated"], seg["customer_match_max_giorni"]
        if upd is None:
            add("First-party", "Customer Match", Status.YELLOW,
                "Data dell'ultimo aggiornamento del pubblico clienti: " + UNKNOWN)
        elif (today - upd).days > max_days:
            add("First-party", "Customer Match", Status.YELLOW,
                f"Pubblico clienti fermo al {upd:%d/%m/%Y} ({(today - upd).days} giorni, "
                f"massimo {max_days}).")
        else:
            add("First-party", "Customer Match", Status.GREEN, f"Aggiornato il {upd:%d/%m/%Y}.")

    # Obiettivo: conversioni contate che non sono lead (es. iscrizioni YouTube, visite)
    actions = [a for a in source.read("ga_conversion_actions") if a["account_id"] == acc]
    total_actions = sum(a["conversions"] for a in actions)
    if total_actions:
        junk = sorted((a for a in actions if a["category"] not in LEAD_CATEGORIES),
                      key=lambda a: -a["conversions"])
        share = sum(a["conversions"] for a in junk) / total_actions * 100
        names = ", ".join(f"{a['conversion_action']} ({a['conversions']:.0f})" for a in junk[:3])
        txt = (f"Il {share:.0f}% delle conversioni non sono lead: {names}. "
               "L'algoritmo le insegue come se fossero clienti: toglierle dalle conversioni "
               "principali.")
        if share >= seg["quota_conversioni_non_lead_rosso_pct"]:
            add("Obiettivo", "Conversioni non-lead", Status.RED, txt)
        elif share >= seg["quota_conversioni_non_lead_giallo_pct"]:
            add("Obiettivo", "Conversioni non-lead", Status.YELLOW, txt)
        else:
            add("Obiettivo", "Conversioni non-lead", Status.GREEN,
                "Quasi tutte le conversioni contate sono lead.")

    # Valore: qualità dei lead. Fonte: export CRM se c'è, altrimenti conversioni offline.
    if account["objective"].startswith("lead"):
        crm, offline = _crm_quality(source, account, today), _offline_quality(offline_q, conv_all)
        label, qual = ("export CRM", crm) if crm else ("conversioni offline", offline)
        recent = [v for d, v in qual.items() if d >= cut]
        older = [v for d, v in qual.items() if d < cut]
        if not recent or not older or not sum(v[0] for v in older):
            add("Valore", "Qualità dei lead", Status.YELLOW,
                "Qualità dei lead non misurata: né export CRM né conversioni offline. Non si può "
                "dire se l'account porta clienti. Servono l'export CRM (docs/export_crm.md) e il "
                "caricamento offline dei lead qualificati sulla piattaforma.")
        else:
            r_old = sum(v[1] for v in older) / sum(v[0] for v in older) * 100
            r_new = (sum(v[1] for v in recent) / sum(v[0] for v in recent) * 100
                     if sum(v[0] for v in recent) else 0)
            drop = (1 - r_new / r_old) * 100 if r_old else 0
            txt = (f"Lead qualificati ({label}): {r_new:.0f}% negli ultimi {recent_days} giorni "
                   f"(prima {r_old:.0f}%).")
            if drop >= seg["calo_tasso_qualificati_rosso_pct"]:
                lag = (" Con le conversioni offline una parte del calo può essere ritardo di "
                       "caricamento: verificare." if label != "export CRM" else "")
                add("Valore", "Qualità dei lead", Status.RED,
                    txt + " La qualità è crollata: più lead non vuol dire più clienti." + lag)
            else:
                add("Valore", "Qualità dei lead", Status.GREEN, txt)

        # Allineamento: il caricamento offline porta alla piattaforma tutti i qualificati del CRM?
        win_start = today - timedelta(days=seg["finestra_riconciliazione_giorni"] - 1)
        crm_q = sum(v[1] for d, v in crm.items() if d >= win_start)
        off_q = sum(v for d, v in offline_q.items() if d >= win_start)
        if crm_q and offline_rows:
            gap = (crm_q - off_q) / crm_q * 100
            txt = (f"Lead qualificati ultimi {seg['finestra_riconciliazione_giorni']} giorni: "
                   f"CRM {crm_q:.0f}, caricati sulla piattaforma {off_q:.0f}.")
            if gap > seg["scarto_offline_vs_crm_giallo_pct"]:
                add("Valore", "Caricamento offline vs CRM", Status.YELLOW,
                    txt + f" Il caricamento ne perde il {gap:.0f}%: l'algoritmo impara su una "
                    "parte dei lead buoni.")
            else:
                add("Valore", "Caricamento offline vs CRM", Status.GREEN, txt)

    # Volume: conversioni negli ultimi 30 giorni per campagna
    month = today - timedelta(days=29)
    per_camp: dict[str, float] = defaultdict(float)
    days_seen: dict[str, set] = defaultdict(set)
    for r in rows:
        if r["date"] >= month:
            per_camp[r["campaign_label"]] += r[conv_col]
            days_seen[r["campaign_label"]].add(r["date"])
    min_conv = vol["conversioni_min_mese_per_campagna"]
    min_days = vol["giorni_min_prima_di_giudicare"]
    low = sorted(
        (c, n) for c, n in per_camp.items() if n < min_conv and len(days_seen[c]) >= min_days
    )
    if not rows:
        pass
    elif low:
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
