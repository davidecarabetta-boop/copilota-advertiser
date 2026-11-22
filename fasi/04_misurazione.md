# Fase 04 – Misurazione incrementale (leggera)

## Obiettivo
Avvisare quando il risultato dichiarato dalla piattaforma è probabilmente gonfiato, e proporre quando fare un test.

## Controlli
- **Brand in PMax**: quota di conversioni da ricerche brand (search term insights). Sopra soglia → proposta brand exclusion + confronto per 2 settimane.
- **Clienti esistenti su Meta**: quota vendite da clienti già acquisiti in prospecting. Sopra soglia → esclusione del pubblico clienti (richiede lista aggiornata dal team analytics).
- **Attribuzione**: finestra usata su Meta, confronto con la vista incrementale dove disponibile.
- **Test**: se l'account ha budget e volumi sufficienti e non ha mai fatto un test di incrementalità, proposta di conversion lift (Meta) o esperimento/geo-test (Google).

## Output
Righe in `findings_daily` con `module = misurazione`.

## Fatto quando
I controlli girano sui clienti pilota e le proposte di test sono validate da un senior.
