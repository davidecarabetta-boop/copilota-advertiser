"""Modulo Creatività Meta (fase 03): semaforo affaticamento per concept e mappa della diversità.

Restituisce diagnosi strutturate (`Finding`, schema di `findings_daily`), non testi finali.

Approssimazioni finché non c'è la fase 01:
- la frequenza è impressioni / copertura sommata per giorno (non la frequenza a 7 giorni vera);
- la "copertura nuova" è la quota copertura / impressioni;
- i "primi 7 giorni" del concept sono i primi 7 giorni attivi dentro il periodo scaricato.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from copilota.data import DataSource, Row
from copilota.signals import META_CONV_OBJECTIVES

# Stati del semaforo
TOO_EARLY = "troppo presto"
OK = "ok"
PREPARE = "prepara il cambio"
LATE = "in ritardo"
NO_DATA = "dati insufficienti"
OFF = "spento"


@dataclass
class Finding:
    """Una riga di `findings_daily` (schema unico per tutti gli analizzatori)."""

    date: date
    account_id: str
    module: str
    object_type: str
    object_id: str
    issue_code: str
    evidence: dict = field(default_factory=dict)
    proposal: dict = field(default_factory=dict)
    action_key: str | None = None
    priority: int = 3  # 1 alta, 3 bassa


@dataclass
class _Window:
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    reach: int = 0
    leads: float = 0.0

    def add(self, r: Row) -> None:
        self.spend += r["spend"]
        self.impressions += r["impressions"]
        self.clicks += r["clicks"]
        self.reach += r["reach"]
        self.leads += r["leads"]

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions * 100 if self.impressions else 0.0

    @property
    def cpm(self) -> float:
        return self.spend / self.impressions * 1000 if self.impressions else 0.0

    @property
    def frequency(self) -> float:
        return self.impressions / self.reach if self.reach else 0.0

    @property
    def new_reach(self) -> float:
        return self.reach / self.impressions if self.impressions else 0.0

    @property
    def cpa(self) -> float | None:
        return self.spend / self.leads if self.leads else None


def _window(days: dict[date, list[Row]], start: date, end: date) -> _Window:
    w = _Window()
    for d, rows in days.items():
        if start <= d <= end:
            for r in rows:
                w.add(r)
    return w


def _concepts(source: DataSource) -> dict[str, Row]:
    return {c["ad_id"]: c for c in source.read("creative_concepts")}


def _label(r: Row, concepts: dict[str, Row]) -> tuple[str, str, str]:
    c = concepts.get(r["ad_id"])
    if c:
        return c["concept"], c["angle"], c["format"]
    return r["concept"] or f"? {r['ad_name']}", "da classificare", "da classificare"


def fatigue(rows: list[Row], th: dict, as_of: date, target_cpa: float | None) -> dict:
    """Stato del semaforo per un concept, dalle sue righe giornaliere (tutti i suoi annunci)."""
    s = th["creativita_semaforo"]
    up = 1 + s["salita_pct"] / 100
    days: dict[date, list[Row]] = defaultdict(list)
    for r in rows:
        if r["date"] <= as_of and r["spend"] > 0:
            days[r["date"]].append(r)
    active = sorted(days)
    ev: dict = {"giorni_attivi": len(active)}
    if not active or active[-1] < as_of - timedelta(days=s["attivo_se_spesa_ultimi_giorni"] - 1):
        return {"state": OFF, **ev}
    if len(active) <= s["troppo_presto"]["giorni_attivo_max"]:
        return {"state": TOO_EARLY, **ev}

    first = _window(days, active[0], active[6])
    last = _window(days, as_of - timedelta(days=6), as_of)
    prev = _window(days, as_of - timedelta(days=13), as_of - timedelta(days=7))
    if min(first.impressions, last.impressions) < s["impressioni_min_finestra"]:
        return {"state": NO_DATA, **ev}

    # picco del CTR su finestre mobili di 7 giorni
    peak = max(
        _window(days, d, d + timedelta(days=6)).ctr
        for d in active if d + timedelta(days=6) <= as_of
    )
    drop = (1 - last.ctr / peak) * 100 if peak else 0.0
    cpm_up = last.cpm > first.cpm * up
    freq_up = prev.impressions > 0 and last.frequency > prev.frequency * up
    reach_down = prev.impressions > 0 and last.new_reach * up < prev.new_reach
    ref_cpa = target_cpa or first.cpa
    cpa_over = (last.cpa is None and last.spend > 0) or (
        ref_cpa is not None and last.cpa is not None
        and last.cpa > ref_cpa * (1 + s["in_ritardo"]["cpa_oltre_target_pct"] / 100))
    n = s["in_ritardo"]["giorni_consecutivi"]
    low_days = all(
        _window(days, as_of - timedelta(days=i), as_of - timedelta(days=i)).ctr
        <= peak * (1 - s["in_ritardo"]["ctr_calo_dal_picco_pct"] / 100)
        for i in range(n)
    )
    ev.update({
        "ctr_picco_pct": round(peak, 2), "ctr_ultimi_7g_pct": round(last.ctr, 2),
        "calo_ctr_pct": round(drop, 1), "cpm_primi_7g": round(first.cpm, 2),
        "cpm_ultimi_7g": round(last.cpm, 2), "frequenza_ultimi_7g": round(last.frequency, 2),
        "frequenza_7g_prima": round(prev.frequency, 2),
        "cpa_ultimi_7g": round(last.cpa, 2) if last.cpa else None,
        "cpa_riferimento": round(ref_cpa, 2) if ref_cpa else None,
        "spesa_ultimi_7g": round(last.spend, 2),
    })
    if (drop >= s["in_ritardo"]["ctr_calo_dal_picco_pct"] and cpm_up and cpa_over
            and low_days):
        return {"state": LATE, **ev}
    if drop >= s["prepara_cambio"]["ctr_calo_dal_picco_pct"] and (freq_up or reach_down):
        return {"state": PREPARE, **ev}
    if cpm_up and drop < s["prepara_cambio"]["ctr_calo_dal_picco_pct"]:
        ev["nota"] = s["nota"]
    return {"state": OK, **ev}


def analyze_account(source: DataSource, account: Row, th: dict, as_of: date | None = None,
                    target_cpa: float | None = None) -> list[Finding]:
    """Semaforo per concept e mappa della diversità per ogni campagna Meta a conversione."""
    acc = account["account_id"]
    rows = [r for r in source.read("meta_ad_daily") if r["account_id"] == acc]
    if not rows:
        return []
    as_of = as_of or max(r["date"] for r in rows)
    rows = [r for r in rows if r["date"] <= as_of]
    campaigns = {c["campaign_id"]: c for c in source.read("meta_campaigns")}
    concepts = _concepts(source)
    div = th["creativita_diversita"]
    findings: list[Finding] = []

    by_campaign: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        c = campaigns.get(r["campaign_id"])
        if c is None or c["objective"] in META_CONV_OBJECTIVES:
            by_campaign[r["campaign_id"]].append(r)

    for cid, crow in by_campaign.items():
        cname = campaigns[cid]["campaign_name"] if cid in campaigns else cid
        since = as_of - timedelta(days=6)
        by_concept: dict[str, list[Row]] = defaultdict(list)
        combos: dict[str, set[tuple[str, str]]] = defaultdict(set)  # attivi negli ultimi 7g
        unconfirmed = 0
        for r in crow:
            concept, angle, fmt = _label(r, concepts)
            by_concept[concept].append(r)
            if r["date"] >= since and r["spend"] > 0:
                combos[concept].add((angle, fmt))
            unconfirmed += not (concepts.get(r["ad_id"]) or {}).get("confirmed")

        # Semaforo per concept
        states = {}
        for concept, crows in by_concept.items():
            st = fatigue(crows, th, as_of, target_cpa)
            states[concept] = st
            if st["state"] in (PREPARE, LATE):
                findings.append(Finding(
                    as_of, acc, "creativita", "concept", concept,
                    "fatigue_late" if st["state"] == LATE else "fatigue_prepare",
                    evidence={"campagna": cname, **st},
                    proposal={"azione": "nuova creatività sullo stesso concept, poi pausa "
                              "della vecchia quando la nuova è a regime",
                              "brief": "mantenere angolo e formato che funzionano, cambiare "
                              "visual e attacco"},
                    action_key="aggiunta_creativita_asset",
                    priority=1 if st["state"] == LATE else 2))

        # Mappa della diversità sui concept attivi (spesa negli ultimi 7 giorni)
        spend7 = {c: sum(r["spend"] for r in rs if r["date"] >= since)
                  for c, rs in by_concept.items()}
        active = {c: s for c, s in spend7.items() if s > 0}
        total = sum(active.values())
        matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for c in active:
            for angle, fmt in combos[c]:
                matrix[angle][fmt] += 1
        angles = sorted(matrix)
        formats = sorted({f for a in matrix.values() for f in a})
        evidence = {
            "campagna": cname,
            "concept_attivi": len(active),
            "angoli": angles,
            "formati": formats,
            "matrice": {a: dict(m) for a, m in matrix.items()},
            "quota_spesa_7g_pct": {c: round(s / total * 100, 1) for c, s in
                                   sorted(active.items(), key=lambda kv: -kv[1])} if total else {},
            "semaforo": {c: st["state"] for c, st in states.items()},
            "concept_da_confermare": unconfirmed > 0,
        }
        findings.append(Finding(as_of, acc, "creativita", "campaign", cid, "diversity_map",
                                evidence=evidence, priority=3))
        if not active:
            findings.append(Finding(as_of, acc, "creativita", "campaign", cid,
                                    "no_active_concepts", evidence=evidence, priority=1))
            continue
        short = []
        if len(active) < div["concept_min_per_campagna"]:
            short.append(f"{len(active)} concept (minimo {div['concept_min_per_campagna']})")
        if len(angles) < div["angoli_min_per_campagna"]:
            short.append(f"{len(angles)} angoli (minimo {div['angoli_min_per_campagna']})")
        if len(formats) < div["formati_min_per_campagna"]:
            short.append(f"{len(formats)} formati (minimo {div['formati_min_per_campagna']})")
        if short:
            findings.append(Finding(
                as_of, acc, "creativita", "campaign", cid, "diversity_low",
                evidence={**evidence, "sotto_minimo": short},
                proposal={"azione": "aggiungere concept con angoli e formati che mancano, "
                          "senza toccare quelli che funzionano",
                          "buchi": _gaps(angles, formats)},
                action_key="aggiunta_creativita_asset", priority=2))
        top, top_spend = max(active.items(), key=lambda kv: kv[1])
        if total and top_spend / total * 100 > div["quota_spesa_max_singolo_concept_pct"]:
            findings.append(Finding(
                as_of, acc, "creativita", "concept", top, "concept_concentration",
                evidence={**evidence, "quota_pct": round(top_spend / total * 100, 1)},
                proposal={"azione": "affiancare concept con angolo diverso: oggi la campagna "
                          "dipende da uno solo"},
                action_key="aggiunta_creativita_asset", priority=2))
    return findings


def _gaps(angles: list[str], formats: list[str]) -> list[str]:
    """Buchi della mappa: formati e angoli che mancano rispetto a un mix minimo."""
    gaps = []
    for f in ("video", "statico", "carosello"):
        if f not in formats:
            gaps.append(f"formato {f}")
    if len(angles) < 3:
        gaps.append("angoli diversi dall'offerta (es. problema da risolvere, prova sociale, "
                    "servizio / garanzia)")
    return gaps
