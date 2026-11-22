# Fase 09 – Integrazione con il tool creativo

Può partire in parallelo alla fase 06, appena chiarito come il tool creativo riceve input.

## Obiettivo
Dal brief del Copilota alle creatività caricate in test, con il minimo lavoro manuale.

## Attività
1. Definire il formato del brief (JSON) condiviso: cliente, piattaforma, campagna/asset group di destinazione, concept, angolo, formato e durata, cosa mantenere, cosa evitare, vincoli del brand.
2. Invio del brief al tool creativo (API o file, secondo quanto deciso in fase 00).
3. Ritorno delle creatività generate con il riferimento al brief, per assegnarle automaticamente al concept in `creative_concepts`.
4. Revisione umana delle creatività prima del caricamento.
5. Caricamento sulla piattaforma: fino alla fase 08 è manuale; dopo, azione `aggiunta_creativita_asset` (livello `puoi_farlo`).

## Fatto quando
Un brief di un cliente pilota arriva al tool creativo e le creatività tornano collegate al concept giusto senza passaggi manuali di copia.
