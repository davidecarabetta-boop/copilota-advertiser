# Pipeline del Copilota (dagli appunti del 2026-11-07, decisa il 2026-11-23)

Un ciclo continuo con lo specialist sempre nel mezzo. Le cose base si fanno sempre; il resto lo
decide lo specialist, con l'aiuto dell'AI.

```
Fotografia ─► Selezione ─► Diagnosi (MCP) ─► Proposta ─► OK specialist ─► Applicazione ─► Verifica
     ▲                                                                                      │
     └──────────────────────────── 7–14 giorni dopo, si guarda il risultato ◄──────────────┘
```

## 1. Fotografia
Una riga per campagna con spesa, conversioni, CPA/ROAS, target, budget pianificato e pacing.
- **Fonte**: Ads Guardian (warehouse), quando sarà agganciato. Fino ad allora la costruisce il
  Copilota dai dati che ha (MCP, KPI dello specialist). Regola fissa (decisa il 2026-11-26): ogni
  campo che Ads Guardian ha si prende da lì, sempre; il Copilota riempie solo i campi mancanti e
  lo scrive in `target_source` o in una colonna di fonte. Il resto della pipeline legge solo la
  tabella `campaign_snapshot`, quindi cambiare la fonte non cambia niente a valle.
- **Finestra assestata**: CPA e ROAS si calcolano escludendo gli ultimi 7 giorni, che non sono
  ancora consolidati (conversioni in ritardo).
- Per molti account si legge dal warehouse, non dalle API: sono lente e Meta ha limiti di
  chiamate. Gli MCP si usano solo nella diagnosi, sulle campagne selezionate.

### Schema di `campaign_snapshot`
| Campo | Cosa contiene |
|---|---|
| `account_id`, `platform`, `campaign_id`, `campaign_name` | identità |
| `campaign_type`, `line`, `funnel` | tipo (Search, PMax, Demand Gen, Meta lead…), linea e fase dal naming |
| `date_from`, `date_to` | finestra assestata (fine = 7 giorni prima di oggi) |
| `spend`, `conversions`, `conversions_value` | nella finestra |
| `cpa`, `roas` | calcolati |
| `target_cpa`, `target_roas`, `target_source` | target e da dove viene (Ads Guardian, KPI specialist, piattaforma) |
| `budget_daily`, `budget_planned_month`, `pacing_pct` | budget in piattaforma, pianificato, quota spesa rispetto al previsto |
| `lost_is_budget_pct`, `lost_is_rank_pct` | quota impressioni persa per budget e per ranking (Search, PMax dove esposto) |
| `bid_status` | stato della strategia: in apprendimento, limitata dal budget… |

Accanto alla fotografia restano i dati del Copilota: qualità dal CRM per campagna, cronologia
delle modifiche, creatività, apprendimento e test.

## 2. Selezione
- **Sotto target**: CPA sopra il target (o ROAS sotto) oltre la tolleranza, ordinate per
  **impatto = spesa × scostamento dal target**. Si guarda prima dove si perdono più soldi.
- **Opportunità di scala**: campagne in target che non spendono il budget o perdono quota per
  budget. Lì più budget porta più risultati allo stesso costo.
- Solo queste vanno in diagnosi: il resto non si tocca.

## 3. Diagnosi
Sulle campagne selezionate, con gli MCP. Cosa si controlla dipende dal **tipo di campagna**
(`config/diagnosi.yaml`): i controlli base si fanno sempre, gli altri li chiede lo specialist.
Esempi: strategia e target in piattaforma, quote perse per budget e per ranking, termini di
ricerca, frequenza e stanchezza delle creatività su Meta, qualità dei lead dal CRM, cronologia
delle modifiche.

## 4. Proposta
Per ogni campagna: **cosa cambiare, perché, effetto atteso**, nel formato delle regole
(`config/regole.yaml`). Il budget segue le proposte di Ads Guardian; offerte, creatività e
keyword sono azioni per lo specialist.

## 5. Approvazione, applicazione, verifica
- Lo specialist approva, scarta o chiede altre analisi.
- **Dopo l'ok la modifica la applica Claude via MCP** (decisione 2026-11-23): richiede hook di
  guardrail, anteprima prima/dopo, registro e annullamento. È la fase 08 anticipata e va fatta
  come passo a sé, prima di qualsiasi scrittura.
- Ogni modifica va nel **registro** con la data e quanto tempo serve per vedere il risultato
  (7–14 giorni). Il Copilota continua a monitorare e alla data confronta prima e dopo.
