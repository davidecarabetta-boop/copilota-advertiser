# Chiamate di riferimento per i Segnali

Periodo di esempio: `2026-10-23` → `2026-11-21` (ultimi 30 giorni completi). Sostituire con le date correnti.
Tutte le chiamate sono in sola lettura.

## Google Ads (`search_search`, customer_id senza trattini)

### Campagne per giorno → `import_mcp_export.py google`
- resource: `campaign`
- fields: `segments.date`, `campaign.id`, `campaign.name`, `campaign.advertising_channel_type`, `campaign.status`, `campaign.bidding_strategy_type`, `campaign_budget.amount_micros`, `metrics.cost_micros`, `metrics.impressions`, `metrics.clicks`, `metrics.conversions`, `metrics.conversions_value`
- conditions: `segments.date BETWEEN '<da>' AND '<a>'`, `metrics.impressions > 0`

### Conversioni per azione, totale del periodo → `google_actions`
- resource: `customer`
- fields: `segments.conversion_action_name`, `segments.conversion_action_category`, `metrics.conversions`
- conditions: periodo, `metrics.conversions > 0`

### Conversioni offline per giorno → `google_offline`
- resource: `customer`
- fields: `segments.date`, `segments.conversion_action_name`, `segments.conversion_action_category`, `metrics.all_conversions_by_conversion_date`
- conditions: periodo, `segments.conversion_action_category IN ('QUALIFIED_LEAD', 'CONVERTED_LEAD', 'IMPORTED_LEAD')`
- Nessuna riga = nessun caricamento nel periodo: annotarlo in `tracking_status.csv` (`crm_last_upload`).

### Stato dei caricamenti offline (per `tracking_status.csv`)
- resource: `offline_conversion_upload_conversion_action_summary`
- fields: `...conversion_action_name`, `...status`, `...total_event_count`, `...successful_event_count`, `...last_upload_date_time`
- `NO_RECENT_UPLOAD` = il CRM non manda più la qualità.

### Impostazioni dell'account (per `tracking_status.csv`)
- resource: `customer`
- fields: `customer.conversion_tracking_setting.enhanced_conversions_for_leads_enabled`, `customer.conversion_tracking_setting.accepted_customer_data_terms`, `customer.time_zone`, `customer.currency_code`

### Azioni di conversione attive (quali sono principali)
- resource: `conversion_action`
- fields: `conversion_action.name`, `conversion_action.type`, `conversion_action.category`, `conversion_action.primary_for_goal`, `conversion_action.origin`
- conditions: `conversion_action.status = 'ENABLED'`

## Meta Ads (ad_account_id senza `act_`)

Prima di usare un campo in `fields`, verificarlo con `ads_get_field_context`.

### Annunci per giorno → `import_mcp_export.py meta`
- `ads_get_ad_entities`: level `ad`, `time_increment` `"1"`, `time_range` del periodo
- fields: `id`, `name`, `campaign_id`, `adset_id`, `amount_spent`, `impressions`, `reach`, `frequency`, `link_click`, `lead`
- filtering: `amount_spent GREATER_THAN 0`; limit 500

### Campagne con obiettivo → `meta_campaigns`
- `ads_get_ad_entities`: level `campaign`, `object_ids` = campagne viste negli annunci
- fields: `id`, `name`, `objective`, `effective_status`, `start_time`, `stop_time`

### Creatività degli annunci (per `creative_concepts.csv`)
- `ads_get_ad_entities`: level `ad`, `object_ids` = annunci con spesa, fields `id`, `name`, `creative_id`, `effective_status`
- `ads_get_creatives`: `creative_ids` (max 100), fields `id`, `name`, `object_type`, `video_id`, `product_set_id`, `title`, `body`, `call_to_action_type`
- `video_id` presente = video; `product_set_id` presente = catalogo; `child_attachments` (da chiedere) = carosello; altrimenti statico.

### Eventi del dataset (tracciamento e eventi dal CRM)
- `ads_get_datasets` con l'account → id del pixel; `ads_get_dataset_stats`: aggregation `event`, granularity `day`, tempi Unix in secondi (massimo 28 giorni).
- Evento ottimizzato stabile = tracciamento sano. Nessun evento server dal CRM (es. `QualifiedLead`) = Meta non riceve la qualità.

### Cronologia delle modifiche (causa dei crolli)
- `ads_account_get_activity_logs`: `object_id` = campagna, `start_time` / `end_time` ISO, limit 200. Se si arriva a 200 voci, ripetere su un intervallo più corto.
- `ads_get_errors` sulla campagna per blocchi di consegna.
