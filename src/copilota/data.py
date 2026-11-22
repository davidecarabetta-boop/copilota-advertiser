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
    # Export CRM del cliente (la verità): conteggi per giorno di arrivo del lead e piattaforma.
    # Specifica per il cliente in docs/export_crm.md.
    "backend_daily": {
        "date": date.fromisoformat, "client": str, "source": str,
        "leads": int, "qualified_leads": _opt(int), "contracts": _opt(int),
    },
    # Conversioni offline ricevute dalla piattaforma (Salesforce -> Google, CRM -> Meta via CAPI):
    # quello che l'algoritmo vede davvero. stage = qualified | converted, per data di conversione.
    "offline_conversions_daily": {
        "date": date.fromisoformat, "account_id": str, "stage": str, "conversions": float,
    },
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
                if missing:
                    raise ValueError(f"{table}.csv: colonne mancanti {sorted(missing)}")
                self._cache[table] = [{k: cast(r[k]) for k, cast in schema.items()} for r in reader]
        return self._cache[table]


class BigQuerySource:
    """Da implementare in fase 01, quando le tabelle esistono: stessa interfaccia di CsvSource."""

    def __init__(self, project: str, dataset: str):
        self.project, self.dataset = project, dataset

    def read(self, table: str) -> list[Row]:
        raise NotImplementedError("BigQuerySource arriva con la fase 01. Per ora usare CsvSource.")
