"""Esegue il modulo Segnali sui dati di test e stampa l'esito per account.

Uso: .venv/Scripts/python scripts/run_signals.py [cartella_csv]
"""

import sys
from pathlib import Path

from copilota.config import load_thresholds
from copilota.data import SAMPLE_DIR, CsvSource
from copilota.signals import Status, check_account, gate, ticket_text

ICON = {Status.GREEN: "[VERDE] ", Status.YELLOW: "[GIALLO]", Status.RED: "[ROSSO] "}


def main() -> None:
    source = CsvSource(Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE_DIR)
    for account in source.read("accounts"):
        checks = check_account(source, account, load_thresholds(account["client"]))
        esito = gate(checks)
        print(f"\n=== {account['name']} - {account['platform']} {account['account_id']}: "
              f"{esito.value.upper()} ===")
        for c in checks:
            print(f"  {ICON[c.status]} {c.group} / {c.name}: {c.detail}")
        if esito is Status.RED:
            ticket = ticket_text(account, checks).replace("\n", "\n    ")
            print("\n  Ticket da aprire:\n    " + ticket)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
