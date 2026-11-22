---
name: copilota-advertiser
description: Copilota Advertiser SearchOn - dice all'advertiser cosa fare su Google Ads e Meta Ads, account per account, leggendo i dati dagli MCP ufficiali in sola lettura. Usala quando si chiede di controllare un account pilota, aggiornare i dati di un cliente dagli MCP, lanciare i Segnali, capire perché un account è rosso o preparare il ticket per il team analytics.
---

# Copilota Advertiser (prototipo in chat, fase 00b)

Il lavoro dell'advertiser è dare all'algoritmo **segnali** buoni, **creatività** diverse, **vincoli** giusti e una **misurazione** onesta. Non si pilota l'algoritmo a mano: niente micro-gestione di keyword, offerte o ad set.

Regole e soglie vivono solo in `config/regole.yaml` e `config/soglie.yaml`. Non scrivere soglie nel testo delle risposte se non leggendole da lì.

## Regole ferme
- **Sola lettura.** Fino alla fase 08 non si chiama nessuno strumento di scrittura degli MCP, anche se disponibile e anche se l'utente lo chiede: si scrive la modifica come istruzione per l'advertiser.
- Dati reali dei clienti solo in `data/<cliente>/` (esclusa da git). Mai dati personali.
- Se i Segnali sono **rossi**, per quell'account si produce solo il ticket: nessun'altra raccomandazione sulle campagne.
- **Senza qualità dei lead** (export CRM o conversioni offline) l'esito dice se tracciamento e impostazioni reggono, non se l'account porta clienti. Dirlo sempre.

## Procedura: aggiornare un cliente e lanciare i Segnali

1. Leggere `config/clienti/<cliente>.yaml`: id Google e Meta, perimetro, obiettivo.
2. Periodo: gli **ultimi 30 giorni completi** (fino a ieri). Basta per tutti i controlli.
3. Scaricare i dati con le chiamate di [riferimenti/segnali.md](riferimenti/segnali.md). Per ogni export:
   - se il client l'ha salvato su file perché troppo grande, usare quel file;
   - altrimenti scrivere il risultato JSON in un file temporaneo;
   - convertirlo con `python scripts/import_mcp_export.py <tipo> <file> <account_id> data/<cliente>`.
4. Aggiornare a mano in `data/<cliente>/`, solo con fatti verificati (campo vuoto = da verificare):
   - `accounts.csv`;
   - `tracking_status.csv`: Enhanced Conversions, CAPI, Consent Mode, conversione di ottimizzazione, ritorno della qualità dal CRM, data dell'ultimo caricamento offline, Customer Match;
   - `backend_daily.csv`: export CRM del cliente se c'è (formato in `docs/export_crm.md`), altrimenti solo intestazione.
5. Lanciare `python scripts/run_signals.py data/<cliente>`.
6. Prima di riportare un rosso, **cercare la causa** (vedi sotto). Non fermarsi al sintomo.
7. Riportare all'utente per account: esito, cosa è rosso e perché, cosa fare, cosa manca per un giudizio completo.

## Trovare la causa di un rosso
- **Conversioni crollate**: prima la cronologia delle modifiche (Meta: `ads_account_get_activity_logs` sull'id della campagna; Google: risorsa `change_event`). Pause, ad set sostituiti, budget e creatività spiegano più crolli del tracciamento. Poi lo spaccato per ad set / campagna, poi il tracciamento (Meta: `ads_get_dataset_stats` sull'evento ottimizzato; Google: conversioni per azione).
- **Qualità dal CRM ferma**: Google `offline_conversion_upload_conversion_action_summary` (stato e data dell'ultimo caricamento).
- **Conversioni non-lead**: conversioni per azione e categoria; indicare quali azioni togliere dalle principali.
- Attenzione: nella cronologia Meta il campo `campaign_id` dentro `extra_data` degli annunci può essere l'id dell'**ad set**.

## Procedura: creatività Meta (semaforo e mappa della diversità)

1. Servono `meta_ad_daily.csv` e `meta_campaigns.csv` aggiornati (procedura Segnali).
2. **Concept**: per gli annunci con spesa delle campagne a conversione, leggere `creative_id` (`ads_get_ad_entities`, level `ad`) e le creatività (`ads_get_creatives`: `object_type`, `video_id`, `product_set_id`, `title`, `body`). Proporre in `data/<cliente>/creative_concepts.csv`:
   - **concept** = cosa si promuove (le versioni datate dello stesso modello o offerta sono lo stesso concept);
   - **angolo** = il messaggio (offerta, problema da risolvere, prova sociale, servizio / garanzia, prova del prodotto…);
   - **formato** = statico, video, carosello, catalogo;
   - `confirmed=false` finché l'advertiser non conferma. Mostrare la proposta e chiedere conferma.
3. Lanciare `python scripts/run_creative.py data/<cliente>`; con `--al AAAA-MM-GG` si vede cosa avrebbe detto il tool in una data passata (per il confronto col senior).
4. Leggere il semaforo per concept (`troppo presto`, `ok`, `prepara il cambio`, `in ritardo`, `spento`, `dati insufficienti`) e la mappa angolo × formato. Concept diversi con lo stesso angolo e formato **non** sono diversità.
5. Con Segnali rossi le diagnosi creatività non vanno all'advertiser: solo il ticket.

## Formato delle istruzioni per l'advertiser
Per ogni azione: **cosa succede / perché / come fare / cosa non fare**, frasi brevi, niente gergo non spiegato. Il livello (`puoi_farlo`, `serve_senior`, `vietato`) si prende da `config/regole.yaml`; un'azione che lì non c'è non si propone.

## Ancora da fare in questa fase
Moduli Google, Meta (struttura, Advantage+ creative, esclusioni), brief creativi, Post-click, Misurazione, Briefing: procedure e riferimenti da aggiungere qui man mano che si costruiscono.
