"""Preparare l'applicazione di una proposta del registro, senza scrivere sulle piattaforme.

Due uscite per ogni voce pronta (decisa dall'advertiser o già approvata):
- testo da incollare in Google Ads Editor ("Modifiche multiple" → incolla), per le modifiche
  che Editor gestisce per campagna: budget giornaliero, CPA target, stato. La pubblicazione la
  fa una persona da Editor.
- prompt per Claude Code, che applica la modifica con l'MCP ufficiale seguendo le regole:
  controllo dei valori attuali, livello in `config/regole.yaml`, anteprima, ok esplicito,
  registro. Finché la fase 08 non è attiva gli strumenti di scrittura sono negati e il prompt
  dice di fermarsi.

La modifica strutturata sta nella colonna `change` del registro (JSON, lista):
    [{"type": "budget_daily", "campaign_id": "23977245050",
      "campaign": "IT_ita|LF|AUTO_B2C|GOO|SEA|Pronta_Consegna", "from": 150, "to": 180}]
Tipi: budget_daily, target_cpa, status (to: "Enabled" | "Paused"), altro (solo testo in `text`).
"""

import json

from copilota.data import Row

EDITOR_COLUMNS = {"budget_daily": "Budget", "target_cpa": "Target CPA",
                  "status": "Campaign status"}
LABELS = {"budget_daily": "budget giornaliero", "target_cpa": "CPA target",
          "status": "stato", "altro": "modifica"}
READY_STATUSES = {"proposta", "approvata"}


def changes(e: Row) -> list[dict]:
    """La modifica strutturata della voce; [] se la colonna è vuota o non leggibile."""
    try:
        value = json.loads(e.get("change") or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else [value]


def is_ready(e: Row) -> tuple[bool, str]:
    """(pronta, motivo). Pronta se è una modifica aperta che l'advertiser decide da solo o che
    chi decide ha già approvato."""
    if e["kind"] != "modifica" or e["status"] not in READY_STATUSES:
        return False, ""
    if e.get("waits"):
        return False, "I pulsanti per applicarla compaiono quando sono chiusi i passi da cui dipende."
    if e["status"] == "approvata" or e["decides"] == "Advertiser":
        return True, ""
    return False, f"I pulsanti per applicarla compaiono dopo l'ok di {e['decides'] or 'chi decide'}."


def _fmt(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).replace(".", ",") if isinstance(v, float) else str(v)


def editor_paste(e: Row) -> tuple[str | None, str]:
    """(testo con tabulazioni per Google Ads Editor, nota). None se Editor non serve qui."""
    if e["platform"] != "google":
        return None, "Google Ads Editor vale solo per Google Ads: per Meta usa il prompt."
    rows = [c for c in changes(e) if c.get("type") in EDITOR_COLUMNS and c.get("campaign")]
    if not rows:
        return None, ("Questa modifica non è una di quelle che Editor applica per campagna "
                      "(budget, CPA target, stato): usa il prompt o falla a mano.")
    cols = ["Campaign"] + sorted({EDITOR_COLUMNS[c["type"]] for c in rows},
                                 key=list(EDITOR_COLUMNS.values()).index)
    by_campaign: dict[str, dict] = {}
    for c in rows:
        by_campaign.setdefault(c["campaign"], {})[EDITOR_COLUMNS[c["type"]]] = c["to"]
    lines = ["\t".join(cols)]
    for name, vals in by_campaign.items():
        lines.append("\t".join([name] + [_fmt(vals[k]) if k in vals else "" for k in cols[1:]]))
    return "\n".join(lines), ("In Google Ads Editor: scarica le modifiche recenti dell'account, "
                              "poi Account › Modifiche multiple › Apporta modifiche multiple, "
                              "incolla, controlla l'anteprima e solo dopo Pubblica.")


def mcp_prompt(e: Row, client: str, account_name: str) -> str:
    """Richiesta per Claude Code: applicare la voce con l'MCP ufficiale, con i controlli."""
    platform = "Google Ads" if e["platform"] == "google" else "Meta Ads"
    lines = [f"Applica la proposta {e['id']} del registro del Copilota (cliente {client}).",
             f"Account {platform} {e['account_id']} ({account_name}).",
             f"Modifica: {e['title']}"]
    detail = changes(e)
    if detail:
        lines.append("Dettaglio:")
        for c in detail:
            if c.get("type") == "altro":
                lines.append(f"- {c.get('text', '')}")
                continue
            what = LABELS.get(c.get("type"), c.get("type"))
            lines.append(f"- campagna «{c.get('campaign', '')}» (id {c.get('campaign_id', '')}): "
                         f"{what} da {_fmt(c.get('from', '?'))} a {_fmt(c.get('to', '?'))}")
    else:
        lines.append(f"Campagne: {e['campaign_name']} (id {e['campaign_id'].replace('|', ', ')}).")
        if e.get("expected"):
            lines.append(f"Risultato atteso: {e['expected']}")
    lines += [f"Decide: {e['decides']} · stato nel registro: {e['status']}.",
              f"Perché: {e['why']}",
              "",
              "Procedura (regole del Copilota):",
              "1. Leggi con l'MCP i valori attuali e confrontali con quelli di partenza qui sopra. "
              "Se sono diversi, fermati e dimmelo.",
              "2. Controlla in config/regole.yaml il livello di questa azione. Se serve l'ok dello "
              "specialist o del senior e la proposta non è approvata, fermati.",
              "3. Mostrami l'anteprima prima/dopo e aspetta il mio ok esplicito.",
              "4. Applica solo con lo strumento di scrittura dell'MCP ufficiale. Se lo strumento è "
              "negato (fase 08 non attiva) o non esiste, non cercare altre strade: dimmelo e "
              "preparami il testo per Google Ads Editor.",
              f"5. Dopo: rileggi il valore e segna {e['id']} come applicata nel registro, con la "
              "data di oggi e i numeri di partenza aggiornati.",
              "Non toccare altro: nessun'altra campagna, nessuna modifica non elencata."]
    return "\n".join(lines)


def build(e: Row, client: str, account_name: str) -> dict | None:
    """Tutto quello che serve alla scheda di dettaglio; None se non è una modifica aperta."""
    ready, why_not = is_ready(e)
    if not ready and not why_not:
        return None
    if not ready:
        return {"ready": False, "why_not": why_not}
    paste, editor_note = editor_paste(e)
    return {"ready": True, "editor": paste, "editor_note": editor_note,
            "prompt": mcp_prompt(e, client, account_name)}
