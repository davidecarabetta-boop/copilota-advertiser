# Copilota Advertiser

Tool interno SearchOn che dice agli advertiser **cosa fare, account per account**, su Google Ads e Meta Ads. Il target è un advertiser poco esperto: il tool non chiede analisi, dà istruzioni pronte e blocca le azioni pericolose.

Mockup di riferimento: `docs/mockup.html` (pubblicato anche come artefatto "Copilota Advertiser").

## Principio
Le piattaforme oggi fanno da sole targeting, offerte e posizionamenti (PMax, AI Max, Demand Gen, Advantage+). Il lavoro dell'advertiser è dare all'algoritmo:
1. **Segnali**: tracking corretto, obiettivo giusto (vendita con valore, lead qualificato), valore (margine), dati first-party, volume minimo.
2. **Creatività**: diversità reale di concept, formati e angoli. La creatività è il targeting.
3. **Vincoli**: target di offerta, esclusioni, brand, consolidamento.
4. **Misurazione**: quanto è incrementale ciò che la piattaforma si attribuisce.

Non si costruiscono funzioni da "vecchio advertising" (micro-gestione di keyword, bid manuali, frazionamento di ad set) se non come guardrail.

## Moduli
| Modulo | Cosa fa |
|---|---|
| Segnali (cancello) | Controlli su tracking, obiettivo, valore, first-party, volume. Se è rosso, il resto si blocca per l'account |
| Google Ads | Consolidamento, diagnosi target, canali PMax, copertura asset, esclusioni |
| Meta Ads | Struttura, semaforo affaticamento, miglioramenti Advantage+ creative, esclusioni |
| Creatività | Mappa della diversità, brief per i buchi, invio al tool creativo, risultati per concept |
| Post-click | Diagnosi a quadranti CTR × conversione, pertinenza annuncio ↔ landing page, problemi del sito e CRO dal funnel GA4. Se il problema è il sito, l'advertiser non tocca le campagne e apre un ticket |
| Misurazione | Brand in PMax, clienti esistenti su Meta, attribuzione |
| Test | A/B, esperimenti Google, conversion lift, geo-test: quando, come impostarli, cosa non toccare durante, come leggerli, registro |
| Briefing | La to-do dell'advertiser: cosa succede, perché, come fare, cosa non fare |

Fuori perimetro (esistono già altri tool o non servono ora): alert, guardiano del budget, gestione lead.

## Fonte unica delle regole
- `config/regole.yaml`: azioni ammesse, livello (`puoi_farlo`, `serve_senior`, `vietato`), limiti.
- `config/soglie.yaml`: soglie di analisi (semaforo, volumi minimi, scarti).
Interfaccia, hook e skill leggono **questi file**. Nessuna regola duplicata nel codice. La skill guida, gli hook proteggono.

## Architettura
- **Lettura e scrittura sulle piattaforme**: MCP ufficiali Google Ads e Meta Ads, usati da Claude Code.
- **Guardrail**: hook `PreToolUse` / `PostToolUse` di Claude Code, distribuiti come impostazioni gestite, che applicano `regole.yaml` a ogni strumento di scrittura degli MCP e registrano ogni modifica. Valgono solo in Claude Code: i connettori in scrittura non vanno abilitati agli advertiser altrove.
- **Storico e calcoli**: estrazione notturna via API in BigQuery (fase 01), su cui girano segnali, analisi, semaforo e briefing.
- **Interfaccia web** in sola lettura e **MCP del Copilota** (piccolo, sola lettura) per portare briefing e diagnosi in chat.

## Fasi
Si lavora una fase alla volta, nell'ordine dei file in `fasi/`. Ogni fase ha obiettivo, attività, output e criteri di completamento. Non iniziare una fase finché i criteri della precedente non sono soddisfatti. Aggiornare lo stato in `fasi/STATO.md` a fine lavoro.

## Stack (proposta, da confermare in fase 00)
- Python 3.12, `google-ads`, `facebook-business`, `google-cloud-bigquery`, `pydantic`, `pyyaml`.
- Dati su BigQuery (un dataset per l'intero tool, tabelle partizionate per data e con `account_id`).
- Interfaccia: FastAPI + HTML/JS semplice, partendo dal mockup.
- MCP del Copilota (sola lettura): SDK Python ufficiale `mcp`. Per scrivere sulle piattaforme si usano gli MCP ufficiali.
- Hook di guardrail: script Python in `hooks/`.
- Hosting: Cloud Run + Cloud Scheduler (da confermare).

## Regole di lavoro
- Mai scrivere sulle piattaforme prima della fase 08. Fino ad allora gli strumenti di scrittura degli MCP ufficiali restano negati nelle impostazioni (`deny`).
- Segreti (developer token, token Meta, credenziali GCP) solo in Secret Manager o `.env` locale ignorato da git. Mai nel codice, mai nei log.
- Query BigQuery pesanti: dry run prima, con stima dei byte.
- Nessun dato personale (email, telefoni) nelle tabelle di analisi. Le liste Customer Match restano fuori dal tool.
- Nomi di tabelle, campi e codice in inglese; testi per l'advertiser in italiano.
- Testi per l'advertiser: frasi brevi, niente gergo non spiegato, sempre la struttura cosa / perché / come / non fare.
