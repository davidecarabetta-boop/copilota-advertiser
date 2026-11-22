# Fase 07 – Skill su dati BigQuery e MCP del Copilota (sola lettura)

## Obiettivo
Spostare la skill nata in fase 00b dai dati letti al volo ai dati già calcolati in BigQuery, così la chat risponde come l'interfaccia, in modo veloce e ripetibile.

## MCP del Copilota (sola lettura, piccolo)
Non sostituisce gli MCP ufficiali: espone solo ciò che calcola il Copilota.
- `list_accounts` – account assegnati all'utente.
- `get_briefing(account)` – attività aperte e "da non toccare".
- `get_signals(account)` – esito del cancello e controlli.
- `get_findings(account, module)` – diagnosi Google, Meta, creatività, misurazione.
- `get_creative_status(account, concept?)` – semaforo e mappa della diversità.
- `get_rules()` – `config/regole.yaml`.
- `mark_task(task_id, status, reason)` – unica scrittura, solo sul database del tool.

Alternativa più leggera da valutare: connettore BigQuery + viste dedicate, senza MCP proprio.

## Skill
Aggiornare `skill/SKILL.md`:
- prima fonte: MCP del Copilota (briefing, findings, semaforo);
- MCP ufficiali solo per dettagli che il Copilota non ha (es. anteprima di un annuncio) e, dalla fase 08, per eseguire le modifiche;
- tono e formato invariati rispetto alla 00b.

## Fatto quando
Le risposte in chat coincidono con l'interfaccia su un set di 20 domande tipo scritte con gli advertiser pilota.
