# Stato del progetto

| Fase | Stato | Note |
|---|---|---|
| 00 Setup e accessi | In corso | Fatto: classificazione strumenti MCP, `deny` scritture Meta, scheletro repo, `scripts/smoke_test.py`, config pilota Rattix. Manca: developer token Standard, OAuth Google, utente di sistema Meta, progetto GCP, `.env`, smoke test verde |
| 00b Prototipo in chat con MCP ufficiali | – | In parallelo alla 01. Skill + MCP in sola lettura sui clienti pilota, calibrazione soglie |
| 01 Dati in BigQuery | – | |
| 02 Segnali | In corso (su dati di test) | Fatto: `src/copilota/signals.py` (7 controlli + `gate` + testo ticket), lettore unico `data.py` (CSV ora, BigQuery in fase 01), dati finti in `data/sample/` generati da `scripts/make_sample_data.py`, prova con `scripts/run_signals.py`. Manca: valore/margine e nuovi clienti, tabella `signals_daily`, verifica su dati reali con un analista senior |
| 03 Analisi Google, Meta, Creatività | – | |
| 03b Post-click: pertinenza LP e CRO | – | Richiede export GA4 in BigQuery del cliente |
| 04 Misurazione | – | |
| 04b Test A/B, lift, esperimenti | – | |
| 05 Briefing | – | |
| 06 Interfaccia (sola lettura) | – | |
| 07 Skill su BigQuery e MCP del Copilota | – | |
| 08 Scrittura via MCP ufficiali + hook di guardrail | – | |
| 09 Tool creativo | – | In parallelo alla 06, dipende dal formato di input del tool creativo |

## Decisioni prese
- 2026-11-22: perimetro = Segnali, Google, Meta, Creatività, Misurazione, Briefing. Esclusi alert, guardiano del budget e lead (coperti da altri tool o non necessari).
- 2026-11-22: le regole vivono in `config/regole.yaml`; la skill guida, gli hook proteggono.
- 2026-11-22: le scritture sulle piattaforme passano dagli MCP ufficiali Google Ads e Meta Ads, protetti da hook `PreToolUse` in impostazioni gestite di Claude Code. Niente motore di scrittura proprio, niente App Review Meta per `ads_management`.
- 2026-11-22: BigQuery resta necessario per storico, semaforo, interfaccia.
- 2026-11-22: tutto in sola lettura fino alla fase 08 (scritture negate con `deny`).
- 2026-11-22: aggiunti i moduli Post-click (pertinenza LP, CRO) e Test (A/B, lift, esperimenti). Gli oggetti in test sono intoccabili fino alla fine del test.

- 2026-11-22: il connettore Google Ads ufficiale è **solo lettura** (3 strumenti: `customers_list_accessible_customers`, `metadata_get_resource_metadata`, `search_search`). In fase 08 le scritture Google non possono passare da lì: va rivista la strategia di scrittura Google.
- 2026-11-22: il connettore Meta espone ~48 strumenti di scrittura (create/update/delete/activate/duplicate su campagne, creatività, cataloghi, pubblico, pixel, esperimenti): tutti in `deny` in `.claude/settings.json`. Alcuni account Meta (es. Loca Top) hanno l'MCP non ancora abilitato (rollout Meta).
- 2026-11-22: confermati Python 3.12 e BigQuery. Interfaccia e hosting si decidono dopo (probabile Render).
- 2026-11-22: BigQuery su un nuovo progetto GCP dedicato.
- 2026-11-22: accesso all'interfaccia con Google Workspace SSO.
- 2026-11-22: cliente pilota = Rattix (Ratti Auto).
- 2026-11-22: dati reali Rattix (30 giorni, 23/10–21/11) presi dagli MCP Google e Meta e salvati in `data/rattix/` (esclusa da git), convertiti con `scripts/import_mcp_export.py`. Mancano CRM, CAPI, Consent Mode e Customer Match: il modulo li segna "da verificare". Primo esito: Google giallo, Meta rosso (campagna LEAD: lead crollati dal 9-10/11, poi la spesa si è quasi azzerata). Causa trovata dalla cronologia: il 9/11 l'ad set che portava i lead ("BROAD - Copia", annunci per modello) è stato messo in pausa e sostituito da "Broad- Aggiornamento" (annunci catalogo, creato via ads MCP server), che non consegna ed è ancora in apprendimento (3 conversioni; apprendimento ripartito il 19/11 dopo modifica di budget). Pixel ed evento LEAD sono gli stessi: non è un problema di tracciamento. Lezione per il tool: il controllo "conversioni crollate" deve guardare anche la cronologia delle modifiche prima di suggerire "controlla il tracciamento". Da verificare anche: su Google ci sono conversioni primarie non-lead (visualizzazioni di pagina, azioni locali, YouTube).
- 2026-11-22: **senza la qualità dei lead dal CRM l'account non è giudicabile sul rendimento** (si sa solo se tracciamento e impostazioni reggono). Il modulo lo dichiara in testa all'esito; nuovo controllo "Qualità dei lead" (tasso di lead qualificati e calo) su `backend_daily`, e la qualità dal CRM ferma da oltre 7 giorni è rosso. Rattix: caricamento Salesforce su Google fermo dal 20/10/2026 (`NO_RECENT_UPLOAD`); Meta senza eventi dal CRM; il 19% delle conversioni Google sono iscrizioni YouTube (nuovo controllo "Conversioni non-lead"). Dato da chiedere al cliente: export CRM giornaliero per piattaforma con lead e lead qualificati (contattati / contratti).
- 2026-11-22: qualità dei lead da **due fonti**: export CRM (verità, `backend_daily` con `qualified_leads` e `contracts`, specifica in `docs/export_crm.md`) e conversioni offline sulle piattaforme (`offline_conversions_daily`, ciò che vede l'algoritmo). Priorità all'export CRM; nuovo controllo "Caricamento offline vs CRM" (giallo se la piattaforma riceve oltre il 20% in meno dei qualificati). L'ultima data di caricamento offline si ricava anche dai dati.
- 2026-11-22: i controlli di volume e conversioni mancanti guardano solo le campagne a conversione; aggiunto il controllo "conversioni crollate" (ultimi 7 giorni vs prima).
- 2026-11-22: in attesa delle credenziali si sviluppa su dati di test scritti a mano (`data/sample/`, account finto DEMO). Il codice legge solo tramite `DataSource`, quindi il passaggio a BigQuery non tocca la logica. Aggiunte in `soglie.yaml` le soglie rosse di riconciliazione (30%, 2x) e la finestra di 30 giorni.

## Decisioni aperte
- Scrittura Google Ads in fase 08: connettore ufficiale solo lettura → API diretta con hook propri, o aspettare un MCP che scriva?
- Blocco scritture portabile: fatto `hooks/blocca_scritture.py` (PreToolUse su `mcp__.*`, in `.claude/settings.json`). Su Meta passa solo una lista di strumenti di lettura (fail closed); su altri MCP blocca i verbi di scrittura. Resta da distribuirlo come impostazione gestita ai PC degli advertiser (con percorso assoluto e Python installato).
- Rattix pilota: Google Ads 3107401529 (Rattix, Italia), Meta act_347410153 (Ratti Auto), obiettivo lead. Perimetro pilota: tutta l'Italia (auto, moto, noleggio). Spagna esclusa: Google 6467759995 e i due account Meta Rattix Motors (solo campagne ES_spa).
- Tool creativo: API o input strutturato? Formato del brief.
- Advertiser e senior che approvano: chi sono.
- Validazione di `config/regole.yaml` e `config/soglie.yaml`.
