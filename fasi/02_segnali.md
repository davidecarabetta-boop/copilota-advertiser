# Fase 02 – Modulo Segnali (il cancello)

## Obiettivo
Per ogni account, un esito `verde / giallo / rosso` con l'elenco dei controlli. Se è rosso, tutti gli altri moduli producono solo l'istruzione "apri ticket".

## Controlli
| Gruppo | Controllo | Rosso se | Giallo se |
|---|---|---|---|
| Tracking | Enhanced Conversions / CAPI attivi, copertura CAPI | conversione principale assente da 24h | copertura CAPI < soglia |
| Tracking | Deduplica Pixel/CAPI (event_id) | piattaforma > backend oltre 2x | scarto > soglia |
| Tracking | Riconciliazione piattaforma vs backend | scarto > 30% | scarto > 10% |
| Tracking | Consent Mode v2 | assente | tasso di consenso in calo oltre soglia |
| Obiettivo | Conversione usata per ottimizzare | lead gen ottimizzata su invio modulo senza qualità dal CRM | conteggio senza valore in e-commerce |
| Valore | Fatturato o margine | – | e-commerce con margini molto diversi tra categorie e valore = fatturato |
| Valore | Obiettivo nuovi clienti | – | non attivo e quota clienti esistenti alta |
| First-party | Customer Match / pubblico clienti | – | più vecchio della soglia |
| Volume | Conversioni per campagna | – | campagne sotto la soglia mensile |

Le soglie vengono da `config/soglie.yaml`.

## Output
- Tabella `signals_daily` (account, controllo, esito, dettaglio in italiano).
- Funzione `gate(account) -> verde|giallo|rosso` usata da tutti i moduli e, più avanti, dal motore delle regole.
- Testo del ticket precompilato per il team analytics quando è rosso (con le prove numeriche).

## Fatto quando
Sui clienti pilota l'esito coincide con il giudizio di un analista senior su almeno 2 settimane di dati.
