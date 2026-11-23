"""Registro delle proposte: proposta → decisione dello specialist → applicazione → verifica.

Ogni voce tiene i numeri di partenza (`baseline`, JSON) presi dalla fotografia, così alla data
di verifica si confronta prima e dopo sulla stessa campagna.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from copilota.data import CsvSource, Row, write_table

STATI = ["proposta", "approvata", "applicata", "verificata", "scartata"]
STATO_LABEL = {"proposta": "Da decidere", "approvata": "Approvata, da applicare",
               "applicata": "Applicata, in attesa del risultato",
               "verificata": "Verificata", "scartata": "Scartata"}
AZIONI = {  # azione -> (stato di partenza ammessi, stato di arrivo)
    "approva": ({"proposta"}, "approvata"),
    "scarta": ({"proposta", "approvata"}, "scartata"),
    "applicata": ({"approvata"}, "applicata"),
    "verificata": ({"applicata"}, "verificata"),
}


def read(folder: Path) -> list[Row]:
    try:
        return CsvSource(folder).read("change_log")
    except FileNotFoundError:
        return []


def baseline_from_snapshot(snap: Row) -> str:
    """Numeri di partenza di una campagna dalla fotografia, in JSON."""
    keys = ["date_from", "date_to", "spend", "conversions", "budget_daily",
            "lost_is_budget_pct", "lost_is_rank_pct", "target_cpa"]
    b = {k: (snap[k].isoformat() if isinstance(snap[k], date) else snap[k]) for k in keys}
    b["cpa"] = round(snap["spend"] / snap["conversions"], 2) if snap["conversions"] else None
    return json.dumps(b, ensure_ascii=False)


def check_date(e: Row) -> date | None:
    """Quando guardare il risultato: dall'applicazione (o dalla decisione) + i giorni previsti."""
    start = e["applied"] or e["decided"]
    if start is None or e["check_after_days"] is None:
        return None
    return start + timedelta(days=e["check_after_days"])


def due(entries: list[Row], today: date) -> list[Row]:
    """Voci applicate per cui è arrivato il momento di verificare."""
    return [e for e in entries if e["status"] == "applicata"
            and (d := check_date(e)) is not None and d <= today]


def dont_touch(entries: list[Row], today: date) -> list[Row]:
    return [e for e in entries if e["kind"] == "da_non_toccare"
            and e["status"] not in ("scartata", "verificata")
            and (e["until"] is None or e["until"] >= today)]


def apply_action(folder: Path, entry_id: str, action: str, today: date, note: str = "",
                 result: str = "") -> Row:
    """Cambia lo stato di una voce. Solleva ValueError se il passaggio non è ammesso."""
    entries = read(folder)
    e = next((x for x in entries if x["id"] == entry_id), None)
    if e is None:
        raise ValueError("Voce non trovata nel registro")
    allowed, target = AZIONI[action]
    if e["status"] not in allowed:
        raise ValueError(f"Da «{STATO_LABEL[e['status']]}» non si può fare «{action}»")
    e["status"] = target
    if action in ("approva", "scarta"):
        e["decided"] = today
    if action == "applicata":
        e["applied"] = today
    if note:
        e["note"] = (e["note"] + " | " if e["note"] else "") + f"{today:%d/%m}: {note}"
    if result:
        e["result"] = result
    write_table(folder, "change_log", entries)
    return e


def add(folder: Path, entry: Row) -> None:
    entries = read(folder)
    if any(x["id"] == entry["id"] for x in entries):
        raise ValueError(f"Esiste già una voce con id {entry['id']}")
    write_table(folder, "change_log", entries + [entry])
