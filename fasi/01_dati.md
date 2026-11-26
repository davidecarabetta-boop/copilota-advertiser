# Fase 01 – Estrazione dati in BigQuery

## Obiettivo
Ogni notte i dati di Google Ads e Meta degli account configurati arrivano in BigQuery, in tabelle stabili su cui lavorano tutti i moduli.

## Attività
1. **Google Ads (GAQL)**, giornaliero per data:
   - `campaign`: tipo (Search, PMax, Demand Gen…), stato, strategia di offerta, target, budget, stato di apprendimento, metriche, impression share persa (budget/rank).
   - `ad_group`, `ad_group_ad` (RSA, resa asset), `asset_group` e `asset_group_asset` (copertura per tipo di asset).
   - Canali PMax (report per canale), search terms / search term insights di PMax e AI Max.
   - Conversioni per azione di conversione (per capire su cosa si ottimizza), nuovi clienti vs esistenti dove disponibile.
2. **Meta (Insights API)**, giornaliero per data:
   - `campaign`, `adset` (obiettivo, ottimizzazione, budget, stato di apprendimento), `ad`, `creative` (con le impostazioni di Advantage+ creative).
   - Metriche per annuncio: spesa, impression, copertura, frequenza, CPM, CTR, hook rate e hold rate (video), conversioni e valore.
   - Copertura incrementale: copertura cumulata per finestre, per calcolare la "copertura nuova".
   - Stato di consegna (incluso l'avviso di affaticamento creatività dove esposto).
3. **Raggruppamento in concept**: tabella `creative_concepts` che assegna ogni annuncio/asset a un concept, con angolo e formato. All'inizio si compila a mano o con regole sul nome; più avanti classificazione automatica con Claude sull'anteprima.
4. **Qualità dei lead, due fonti** (senza, l'account non è giudicabile sul rendimento):
   - **Export CRM** del cliente (`backend_daily`): lead, lead qualificati e contratti per giorno di arrivo e piattaforma, solo conteggi. Specifica in `docs/export_crm.md`.
   - **Conversioni offline sulle piattaforme** (`offline_conversions_daily`): quello che l'algoritmo riceve. Google: azioni di categoria `QUALIFIED_LEAD` / `CONVERTED_LEAD` per data di conversione, più lo stato dei caricamenti (`offline_conversion_upload_conversion_action_summary`). Meta: eventi server dal CRM sul dataset.
   - Il modulo Segnali usa l'export CRM se c'è, altrimenti le offline, e confronta le due fonti.
5. **Post-click** (per la fase 03b):
   - export GA4 in BigQuery del cliente: funnel del traffico a pagamento per piattaforma, campagna, landing page e dispositivo (solo aggregati);
   - URL finali e testi degli annunci (Google e Meta);
   - crawl leggero delle landing page attive: testo, prezzo, stato HTTP, catena di redirect, screenshot;
   - Core Web Vitals delle landing (CrUX / PageSpeed API);
   - feed prodotti (Merchant Center, catalogo Meta) per prezzo e disponibilità.
6. **Test** (per la fase 04b): elenco di esperimenti Google e test Meta con stato e configurazione.
7. **Orchestrazione**: job notturno (Cloud Run Job + Scheduler), idempotente, con backfill di 90 giorni.

## Tabelle (nomi indicativi)
`ga_campaign_daily`, `ga_asset_group_daily`, `ga_pmax_channel_daily`, `ga_search_terms`, `meta_ad_daily`, `meta_adset_daily`, `meta_reach_windows`, `creative_concepts`, `backend_daily`, `accounts`.

## Attenzione
- Rate limit di entrambe le API: batch e retry con backoff.
- Date nel fuso dell'account.
- Dry run delle query di trasformazione prima di schedularle.

## Fatto quando
Dopo 3 notti consecutive le tabelle sono complete e i totali di spesa coincidono con l'interfaccia delle piattaforme (scarto < 1%).
