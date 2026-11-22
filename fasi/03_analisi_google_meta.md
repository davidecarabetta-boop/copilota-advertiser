# Fase 03 – Analisi Google Ads, Meta Ads e Creatività

## Obiettivo
Produrre **diagnosi strutturate** (non ancora testi per l'advertiser): ogni analizzatore restituisce righe con account, oggetto, problema, evidenze numeriche, proposta, livello dell'azione (da `regole.yaml`).

## Google Ads
- **Consolidamento**: campagne sotto `conversioni_min_mese_per_campagna`, raggruppabili (stessa tipologia/obiettivo) → proposta di accorpamento, Search in AI Max. La Search Brand resta separata.
- **Target di offerta**: confronto target vs effettivo 30g e quota di budget spesa. Target troppo alto se spende sotto soglia; troppo basso se sempre limitato dal budget con CPA ben sotto target.
- **PMax per canale**: quota spesa vs quota valore per canale.
- **Copertura asset**: asset group senza video verticali, con pochi titoli/immagini, asset con resa bassa.
- **Esclusioni**: nuovi termini negativi dai search terms (come guardrail, non come attività principale).

## Meta Ads
- **Struttura**: numero di campagne, ad set con budget troppo basso, quota spesa su Advantage+.
- **Semaforo affaticamento** per concept (soglie in `soglie.yaml`):
  - confronto con i primi 7 giorni dello stesso concept, non frequenza assoluta;
  - CPM in salita con CTR stabile = non affaticamento;
  - durata media dei concept calcolata sullo storico dell'account e usata per calibrare.
- **Miglioramenti Advantage+ creative**: stato di ciascuno vs linee guida del brand in `config/clienti/`.
- **Esclusioni**: clienti esistenti in prospecting, età del pubblico clienti.

## Creatività
- **Mappa della diversità**: matrice angolo × formato con conteggio di creatività attive; buchi evidenziati.
- **Risultati per concept**: quota spesa, ROAS/CPA, stato del semaforo.
- **Brief**: per ogni buco o concept in "prepara il cambio"/"in ritardo", un brief (cosa mantenere dai vincitori, cosa evitare dai perdenti, formato, durata). Generazione del testo con Claude a partire dai dati.

## Output
Tabella `findings_daily` con schema unico per tutti gli analizzatori:
`date, account_id, module, object_type, object_id, issue_code, evidence (JSON), proposal (JSON), action_key (da regole.yaml), priority`.

## Fatto quando
Su 2 settimane dei clienti pilota un senior valuta le diagnosi: almeno l'80% giudicate corrette e utili, nessuna pericolosa.
