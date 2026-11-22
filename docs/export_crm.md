# Export CRM per il Copilota

Serve a dire se le campagne portano **clienti**, non solo lead. Senza questo dato il Copilota sa solo se il tracciamento funziona.

## Cosa chiedere al cliente

Un file al giorno (o un accesso a una tabella aggiornata ogni giorno) con **solo conteggi**, nessun dato personale.

| Colonna | Esempio | Cosa contiene |
|---|---|---|
| `date` | 2026-11-21 | Giorno in cui il lead è **arrivato** (non quello in cui è stato qualificato) |
| `client` | RATTIX | Sigla del cliente, come in `config/clienti/` |
| `source` | google | Piattaforma da cui arriva il lead: `google`, `meta`, `altro` (da UTM o gclid / fbclid) |
| `leads` | 42 | Lead ricevuti quel giorno da quella piattaforma |
| `qualified_leads` | 18 | Di quei lead, quanti sono diventati **qualificati** (contattati e validi) fino a oggi |
| `contracts` | 3 | Di quei lead, quanti sono diventati **contratti** fino a oggi |

- I conteggi di `qualified_leads` e `contracts` vanno **ricalcolati ogni giorno sugli ultimi 90 giorni**: un lead di ottobre può diventare contratto a novembre.
- Un campo vuoto vuol dire "dato non disponibile", zero vuol dire zero.
- Formato: CSV UTF-8 con queste intestazioni, oppure tabella BigQuery con gli stessi campi.

## In parallelo: conversioni offline sulle piattaforme

L'export CRM dice a **noi** quanto valgono i lead. Le conversioni offline lo dicono **all'algoritmo**, che così cerca lead buoni e non lead qualsiasi. Servono entrambi:

- **Google Ads**: caricamento delle conversioni "lead qualificato" e "contratto" (es. integrazione Salesforce o import da gclid), da usare come conversioni principali.
- **Meta**: eventi dal CRM via Conversions API (es. `QualifiedLead`, `Purchase`/contratto) collegati ai lead.

Il Copilota confronta le due fonti: se la piattaforma riceve molti meno qualificati di quelli nel CRM, il caricamento va sistemato.
