"""Genera i dati di test in data/sample/ (CSV con la forma delle tabelle della fase 01).

Account finto "DEMO", sul modello di Rattix (lead gen). Problemi messi apposta:
- Google: la campagna MOTO fa ~20 conversioni/mese (sotto la soglia di volume) -> giallo.
- Meta: la piattaforma conta ~2,2 volte i lead del CRM (deduplica Pixel/CAPI rotta) -> rosso.
- Meta: copertura CAPI 65% (sotto l'80%) -> giallo.
- Meta: pubblico Customer Match non aggiornato da settembre -> giallo.
- Meta: un annuncio con frequenza alta e CTR in calo (servirà alla fase 03).

Deterministico: rilanciarlo produce sempre gli stessi file.
Uso: .venv/Scripts/python scripts/make_sample_data.py
"""

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "sample"
END = date(2026, 11, 21)  # ultimo giorno completo
DAYS = 30
GOOGLE = "1000000001"
META = "act_1000000002"

rng = random.Random(42)


def days():
    return [END - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]


def noisy(x: float, pct: float = 0.15) -> float:
    return max(0.0, x * (1 + rng.uniform(-pct, pct)))


def count(mean: float) -> int:
    """Intero casuale con media `mean` (somma di Bernoulli, abbastanza per dati finti)."""
    whole = int(mean)
    extra = 1 if rng.random() < mean - whole else 0
    return whole + extra + rng.choice([-1, 0, 0, 1]) * (whole > 2)


def write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{name}.csv: {len(rows)} righe")


accounts = [
    {"account_id": GOOGLE, "platform": "google", "client": "DEMO", "name": "DEMO Auto (test)",
     "objective": "lead_qualificato", "currency": "EUR", "timezone": "Europe/Rome"},
    {"account_id": META, "platform": "meta", "client": "DEMO", "name": "DEMO Auto (test)",
     "objective": "lead_qualificato", "currency": "EUR", "timezone": "Europe/Rome"},
]

tracking = [
    {"account_id": GOOGLE, "enhanced_conversions": "true", "capi_active": "",
     "capi_coverage_pct": "", "consent_mode_v2": "true", "consent_rate_pct": "72",
     "consent_rate_prev_pct": "74", "optimization_event": "lead_form",
     "crm_quality_feedback": "true", "customer_match_updated": "2026-11-10"},
    {"account_id": META, "enhanced_conversions": "", "capi_active": "true",
     "capi_coverage_pct": "65", "consent_mode_v2": "", "consent_rate_pct": "",
     "consent_rate_prev_pct": "", "optimization_event": "lead",
     "crm_quality_feedback": "true", "customer_match_updated": "2026-09-01"},
]

# Google: (id, nome, tipo, budget, costo/giorno, clic/giorno, conversioni/giorno)
G_CAMPAIGNS = [
    ("g1", "IT|BOF|AUTO_B2C|Search|Brand", "SEARCH", 100, 80, 120, 4.0),
    ("g2", "IT|TOF|AUTO_B2C|PMax", "PERFORMANCE_MAX", 180, 150, 210, 5.0),
    ("g3", "IT|MOF|MOTO_B2C|Search|Generic", "SEARCH", 50, 40, 55, 0.6),
]
ga_rows, g_conv_by_day = [], {}
for d in days():
    for cid, name, ctype, budget, cost, clicks, conv in G_CAMPAIGNS:
        c = count(conv)
        k = round(noisy(clicks))
        ga_rows.append({
            "date": d.isoformat(), "account_id": GOOGLE, "campaign_id": cid,
            "campaign_name": name, "campaign_type": ctype, "status": "ENABLED",
            "bidding_strategy": "MAXIMIZE_CONVERSIONS", "budget": budget,
            "cost": round(noisy(cost), 2), "impressions": k * rng.randint(18, 25),
            "clicks": k, "conversions": c, "conversions_value": 0,
        })
        g_conv_by_day[d] = g_conv_by_day.get(d, 0) + c

# Meta: (ad_id, nome, concept, spesa/giorno, CTR %, lead/giorno, frequenza iniziale)
M_ADS = [
    ("m1", "Usato garantito - video", "garanzia", 35, 1.4, 3.0, 1.3),
    ("m2", "Usato garantito - carosello", "garanzia", 25, 1.1, 2.0, 1.2),
    ("m3", "Permuta in 24h - statico", "permuta", 30, 1.6, 2.5, 1.4),
    ("m4", "Finanziamento tasso zero", "finanziamento", 40, 1.8, 3.5, 2.0),  # in affaticamento
    ("m5", "Moto - test ride", "moto", 15, 0.9, 1.0, 1.1),
    ("m6", "Noleggio lungo termine", "noleggio", 20, 1.0, 1.5, 1.2),
]
meta_rows, m_leads_by_day = [], {}
for i, d in enumerate(days()):
    for ad, name, concept, spend, ctr, leads, freq in M_ADS:
        tired = ad == "m4"
        f = freq + (i * 0.12 if tired else i * 0.01)
        ctr_d = ctr * (1 - 0.015 * i) if tired else ctr
        impr = round(noisy(spend * 1000 / 9))
        n = count(leads)
        meta_rows.append({
            "date": d.isoformat(), "account_id": META, "campaign_id": "mc1",
            "adset_id": "ms1" if ad in ("m1", "m2", "m3", "m4") else "ms2", "ad_id": ad,
            "ad_name": name, "concept": concept, "spend": round(noisy(spend), 2),
            "impressions": impr, "reach": round(impr / f), "frequency": round(f, 2),
            "clicks": round(impr * noisy(ctr_d, 0.1) / 100), "leads": n,
        })
        m_leads_by_day[d] = m_leads_by_day.get(d, 0) + n

backend = []
for d in days():
    g = round(g_conv_by_day[d] * rng.uniform(0.9, 1.0))  # Google allineato (scarto < 10%)
    m = round(m_leads_by_day[d] / 2.2)  # Meta gonfiato: deduplica rotta
    backend.append({"date": d.isoformat(), "client": "DEMO", "source": "google",
                    "leads": g, "qualified_leads": round(g * 0.6)})
    backend.append({"date": d.isoformat(), "client": "DEMO", "source": "meta",
                    "leads": m, "qualified_leads": round(m * 0.4)})

write("accounts", accounts)
write("tracking_status", tracking)
write("ga_campaign_daily", ga_rows)
write("meta_ad_daily", meta_rows)
write("backend_daily", backend)
