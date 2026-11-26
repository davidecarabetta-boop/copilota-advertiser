"""Le proposte di config/regole.yaml: quando il Copilota può suggerire un'azione.

Ogni proposta ha condizioni `proponi_se` (devono essere tutte vere) e `non_proporre_se`
(nessuna deve essere vera). Il codice valuta le condizioni per id; quelle che non si possono
controllare con i dati disponibili restano "da verificare" e si mostrano come tali.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from copilota.config import CONFIG_DIR

REGIONS = ["lombardia", "veneto", "piemonte", "emilia", "toscana", "lazio", "campania",
           "puglia", "sicilia", "sardegna", "liguria", "friuli", "trentino", "marche",
           "umbria", "abruzzo", "calabria", "basilicata", "molise", "valle"]


@lru_cache(maxsize=1)
def proposals() -> dict:
    return yaml.safe_load((CONFIG_DIR / "regole.yaml").read_text(encoding="utf-8"))["proposte"]


@dataclass
class Condition:
    text: str
    state: bool | None  # True soddisfatta, False no, None non verificabile coi dati
    exclusion: bool = False  # True se viene da non_proporre_se


def evaluate(key: str, values: dict[str, bool | None]) -> tuple[bool, list[Condition]]:
    """Valuta la proposta `key` con i valori calcolati dal codice.

    Si propone se tutte le `proponi_se` sono True e nessuna `non_proporre_se` è True.
    Un'esclusione non verificabile (None) non blocca ma resta in vista come "da verificare".
    """
    p = proposals()[key]
    conds = [Condition(c["testo"], values.get(c["id"])) for c in p["proponi_se"]]
    conds += [Condition(c["testo"], values.get(c["id"]), True) for c in p["non_proporre_se"]]
    ok = (all(c.state is True for c in conds if not c.exclusion)
          and not any(c.state is True for c in conds if c.exclusion))
    return ok, conds


def name_parts(name: str) -> list[str]:
    return [p.strip() for p in name.split("|")]


def line_of(name: str) -> str:
    """Linea di business dal naming <paese>|<funnel>|<LINEA>|...: AUTO_B2C, RENT_NLT…"""
    parts = name_parts(name)
    return parts[2].replace(" I ", "_").upper() if len(parts) > 2 else "?"


def funnel_of(name: str) -> str:
    """Fase del funnel dal naming: UF (awareness), MF (considerazione), LF (retargeting)."""
    parts = name_parts(name)
    return parts[1].upper() if len(parts) > 1 else "?"


def zone_of(name: str) -> str:
    found = [r for r in REGIONS if re.search(rf"\b{r}", name.lower())]
    return "+".join(found) if found else "tutte"


def is_brand(name: str) -> bool:
    return "brand" in name.lower()
