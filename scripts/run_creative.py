"""Esegue il modulo Creatività Meta e stampa semaforo e mappa della diversità.

Uso: .venv/Scripts/python scripts/run_creative.py [cartella_csv] [--al AAAA-MM-GG]
--al valuta come se oggi fosse quella data (utile per confrontare col giudizio del senior).
"""

import sys
from datetime import date
from pathlib import Path

import yaml

from copilota.config import CONFIG_DIR, load_thresholds
from copilota.creative import analyze_account
from copilota.data import SAMPLE_DIR, CsvSource
from copilota.signals import Status, check_account, gate

LABELS = {
    "fatigue_late": "Creatività in ritardo",
    "fatigue_prepare": "Prepara il cambio",
    "diversity_low": "Diversità bassa",
    "concept_concentration": "Spesa concentrata su un concept",
    "no_active_concepts": "Nessun concept attivo",
    "diversity_map": "Mappa della diversità",
}


def target_cpa(client: str) -> float | None:
    f = CONFIG_DIR / "clienti" / f"{client.lower()}.yaml"
    if not f.exists():
        return None
    return ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("target") or {}).get("cpa")


def main() -> None:
    args = sys.argv[1:]
    as_of = None
    if "--al" in args:
        i = args.index("--al")
        as_of = date.fromisoformat(args[i + 1])
        del args[i:i + 2]
    source = CsvSource(Path(args[0]) if args else SAMPLE_DIR)
    for account in source.read("accounts"):
        if account["platform"] != "meta":
            continue
        th = load_thresholds(account["client"])
        esito = gate(check_account(source, account, th))
        findings = analyze_account(source, account, th, as_of, target_cpa(account["client"]))
        print(f"\n=== Creatività {account['name']} ({account['account_id']}) ===")
        if esito is Status.RED:
            print("  BLOCCATO: Segnali rossi. Per l'advertiser vale solo il ticket; "
                  "diagnosi mostrate per sviluppo e confronto col senior.")
        if not findings:
            print("  Nessun problema sulle creatività.")
        for f in sorted(findings, key=lambda f: f.priority):
            ev = f.evidence
            print(f"\n  [P{f.priority}] {LABELS.get(f.issue_code, f.issue_code)}: {f.object_id}")
            print(f"    Campagna: {ev.get('campagna')}")
            if f.issue_code == "diversity_map":
                print(f"    Matrice angolo x formato (concept attivi): {ev['matrice']}")
            if ev.get("sotto_minimo"):
                print(f"    Sotto il minimo: {'; '.join(ev['sotto_minimo'])}")
            if "concept_attivi" in ev and f.issue_code in ("diversity_map",):
                print(f"    Concept attivi: {ev['concept_attivi']} | angoli: {ev['angoli']} | "
                      f"formati: {ev['formati']}")
                print(f"    Quota spesa 7g: {ev['quota_spesa_7g_pct']}")
                print(f"    Semaforo: {ev['semaforo']}")
                if ev.get("concept_da_confermare"):
                    print("    (concept proposti dai nomi: da confermare con l'advertiser)")
            if "calo_ctr_pct" in ev:
                print(f"    CTR {ev['ctr_ultimi_7g_pct']}% (picco {ev['ctr_picco_pct']}%, "
                      f"-{ev['calo_ctr_pct']}%), CPM {ev['cpm_primi_7g']} -> "
                      f"{ev['cpm_ultimi_7g']}, frequenza {ev['frequenza_7g_prima']} -> "
                      f"{ev['frequenza_ultimi_7g']}, CPA {ev['cpa_ultimi_7g']} "
                      f"(rif. {ev['cpa_riferimento']})")
            if f.proposal:
                print(f"    Proposta: {f.proposal}")
            if f.action_key:
                print(f"    Azione in regole.yaml: {f.action_key}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
