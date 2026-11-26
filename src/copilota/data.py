"""Accesso ai dati: un'unica interfaccia, che oggi legge i CSV di test e domani BigQuery.

Il resto del codice chiama solo `source.read("nome_tabella")` e riceve righe già tipizzate.
"""

import csv
from datetime import date
from pathlib import Path
from typing import Any, Protocol

SAMPLE_DIR = Path(__file__).parent.parent.parent / "data" / "sample"


def _bool(v: str) -> bool | None:
    return None if v == "" else v.strip().lower() == "true"


def _opt(cast):
    return lambda v: None if v == "" else cast(v)


# Colonne e tipi di ogni tabella. Valgono per i CSV e saranno lo schema delle tabelle BigQuery.
SCHEMAS: dict[str, dict[str, Any]] = {
    "accounts": {
        "account_id": str, "platform": str, "client": str, "name": str,
        "objective": str, "currency": str, "timezone": str,
    },
    "tracking_status": {
        "account_id": str, "enhanced_conversions": _bool, "capi_active": _bool,
        "capi_coverage_pct": _opt(float), "consent_mode_v2": _bool,
        "consent_rate_pct": _opt(float), "consent_rate_prev_pct": _opt(float),
        "optimization_event": str, "crm_quality_feedback": _bool,
        "crm_last_upload": _opt(date.fromisoformat),
        "customer_match_updated": _opt(date.fromisoformat),
    },
    # Totali del periodo per azione di conversione (Google): per capire su cosa si ottimizza
    "ga_conversion_actions": {
        "account_id": str, "conversion_action": str, "category": str, "conversions": float,
    },
    "ga_campaign_daily": {
        "date": date.fromisoformat, "account_id": str, "campaign_id": str,
        "campaign_name": str, "campaign_type": str, "status": str, "bidding_strategy": str,
        "budget": float, "cost": float, "impressions": int, "clicks": int,
        "conversions": float, "conversions_value": float,
    },
    "meta_ad_daily": {
        "date": date.fromisoformat, "account_id": str, "campaign_id": str, "adset_id": str,
        "ad_id": str, "ad_name": str, "concept": str, "spend": float, "impressions": int,
        "reach": int, "frequency": float, "clicks": int, "leads": float,
    },
    "meta_campaigns": {
        "account_id": str, "campaign_id": str, "campaign_name": str,
        "objective": str, "status": str,
    },
    # Annuncio -> concept (cosa si promuove), angolo (il messaggio), formato. Proposto dai nomi
    # e dalle creatività, confermato dall'advertiser (confirmed).
    "creative_concepts": {
        "ad_id": str, "concept": str, "angle": str, "format": str, "confirmed": _bool,
    },
    # Cronologia delle modifiche (Meta: activity log; Google: change_event). Serve a trovare
    # la causa di un crollo prima di dare la colpa al tracciamento.
    "change_events": {
        "date": date.fromisoformat, "account_id": str, "object_type": str, "object_id": str,
        "object_name": str, "change": str, "old_value": str, "new_value": str, "app": str,
    },
    # Export CRM del cliente (la verità): conteggi per giorno di arrivo del lead e piattaforma.
    # Specifica per il cliente in docs/export_crm.md.
    "backend_daily": {
        "date": date.fromisoformat, "client": str, "source": str,
        "leads": int, "qualified_leads": _opt(int), "contracts": _opt(int),
    },
    # Export CRM per campagna (dall'UTM campaign, nome normalizzato): solo conteggi
    "backend_campaign_daily": {
        "date": date.fromisoformat, "client": str, "source": str, "utm_campaign": str,
        "leads": int, "qualified_leads": int, "contracts": int,
    },
    # Fotografia per campagna (docs/pipeline.md): oggi costruita dal Copilota, domani da Ads
    # Guardian. Finestra assestata: si escludono gli ultimi 7 giorni.
    "campaign_snapshot": {
        "account_id": str, "platform": str, "campaign_id": str, "campaign_name": str,
        "campaign_type": str, "bidding": str, "bid_status": str,
        "date_from": date.fromisoformat, "date_to": date.fromisoformat,
        "spend": float, "conversions": float, "conversions_value": float,
        "target_cpa": _opt(float), "target_roas": _opt(float), "target_source": str,
        "budget_daily": _opt(float), "budget_planned_month": _opt(float),
        "pacing_pct": _opt(float), "lost_is_budget_pct": _opt(float),
        "lost_is_rank_pct": _opt(float), "frequency": _opt(float),
    },
    # Registro delle proposte (passo 4-5 della pipeline): dalla proposta alla verifica.
    # stato: proposta | approvata | scartata | applicata | verificata
    # tipo: modifica | da_non_toccare (blocco fino a `until`) | verifica (controllo da fare)
    "change_log": {
        "id": str, "created": date.fromisoformat, "account_id": str, "platform": str,
        "campaign_id": str, "campaign_name": str, "kind": str, "title": str, "why": str,
        "expected": str, "decides": str, "status": str,
        "decided": _opt(date.fromisoformat), "applied": _opt(date.fromisoformat),
        "check_after_days": _opt(int), "until": _opt(date.fromisoformat),
        "baseline": str, "result": str, "note": str,
        # pipeline di un brief: id del brief, ordine, passi da cui dipende (id separati da |),
        # chi esegue (Claude | Advertiser | Specialist | Senior), da quando si può fare
        "pipeline": str, "step": _opt(int), "depends": str, "executor": str,
        "start": _opt(date.fromisoformat),
    },
    # KPI dello specialist per piattaforma e linea di business (es. meta / AUTO_B2C), su due
    # livelli: adv (target_cpa, confrontato col CPA di piattaforma) e business (costi dal CRM)
    "kpi": {
        "platform": str, "line": str, "target_cpa": _opt(float), "cost_per_lead": _opt(float),
        "cost_per_qualified": _opt(float), "cost_per_contract": _opt(float),
        "leads_per_month": _opt(float), "monthly_budget": _opt(float),
    },
    # Stato degli oggetti da non toccare: test in corso e apprendimento (dagli MCP)
    "object_status": {
        "account_id": str, "object_type": str, "object_id": str, "object_name": str,
        "campaign_id": str, "learning": _bool, "in_test": _bool, "until": _opt(date.fromisoformat),
        "note": str,
    },
    # Spesa per campagna in un periodo (serve a confrontare con i lead maturi del CRM)
    "campaign_period": {
        "account_id": str, "campaign_id": str, "campaign_name": str,
        "date_from": date.fromisoformat, "date_to": date.fromisoformat, "spend": float,
        "platform_conversions": float,
    },
    # Conversioni offline ricevute dalla piattaforma (Salesforce -> Google, CRM -> Meta via CAPI):
    # quello che l'algoritmo vede davvero. stage = qualified | converted, per data di conversione.
    "offline_conversions_daily": {
        "date": date.fromisoformat, "account_id": str, "stage": str, "conversions": float,
    },
}

# Colonne aggiunte dopo: se il CSV non le ha ancora, si leggono vuote.
OPTIONAL_COLUMNS: dict[str, set[str]] = {
    "change_log": {"pipeline", "step", "depends", "executor", "start"},
}

Row = dict[str, Any]


class DataSource(Protocol):
    def read(self, table: str) -> list[Row]: ...


class CsvSource:
    """Legge <dir>/<tabella>.csv e converte i tipi secondo SCHEMAS."""

    def __init__(self, directory: Path = SAMPLE_DIR):
        self.directory = Path(directory)
        self._cache: dict[str, list[Row]] = {}

    def read(self, table: str) -> list[Row]:
        if table not in self._cache:
            schema = SCHEMAS[table]
            with open(self.directory / f"{table}.csv", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                missing = set(schema) - set(reader.fieldnames or [])
                missing -= OPTIONAL_COLUMNS.get(table, set())
                if missing:
                    raise ValueError(f"{table}.csv: colonne mancanti {sorted(missing)}")
                self._cache[table] = [{k: cast(r.get(k) or "") for k, cast in schema.items()}
                                      for r in reader]
        return self._cache[table]


def _to_csv(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def write_table(directory: Path, table: str, rows: list[Row]) -> None:
    """Scrive <dir>/<tabella>.csv con le colonne di SCHEMAS (usato dagli input a mano del tool)."""
    cols = list(SCHEMAS[table])
    Path(directory).mkdir(parents=True, exist_ok=True)
    with open(Path(directory) / f"{table}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_to_csv(r.get(c)) for c in cols])


def parse_rows(table: str, text: str) -> list[Row]:
    """Legge un CSV caricato dall'utente e lo valida contro SCHEMAS. Errori in italiano."""
    schema = SCHEMAS[table]
    reader = csv.DictReader(text.splitlines())
    missing = set(schema) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Colonne mancanti: {', '.join(sorted(missing))}")
    rows = []
    for n, r in enumerate(reader, start=2):
        try:
            rows.append({k: cast((r[k] or "").strip()) for k, cast in schema.items()})
        except ValueError as e:
            raise ValueError(f"Riga {n}: valore non valido ({e})") from e
    return rows


class BigQuerySource:
    """Da implementare in fase 01, quando le tabelle esistono: stessa interfaccia di CsvSource."""

    def __init__(self, project: str, dataset: str):
        self.project, self.dataset = project, dataset

    def read(self, table: str) -> list[Row]:
        raise NotImplementedError("BigQuerySource arriva con la fase 01. Per ora usare CsvSource.")
