# Fase 05 – Briefing per l'advertiser

## Obiettivo
Trasformare `findings_daily` nella to-do dell'advertiser: poche attività, ordinate, scritte in modo che non serva capire l'analisi per eseguirle.

## Regole di composizione
- Ogni attività ha sempre: **titolo, leva, piattaforma, livello (puoi farlo / serve il senior), priorità, impatto stimato, cosa succede, perché, come fare (passi numerati), non fare**.
- Massimo 6 attività per account al giorno, ordinate per priorità e impatto.
- Se `gate = rosso`, una sola attività: aprire il ticket.
- Sezione fissa **"Da non toccare"**: campagne in apprendimento, oggetti in raffreddamento (da `regole.yaml`), decisioni prese con il cliente.
- Un'attività già proposta e non eseguita non si duplica: si aggiorna.

## Testi
- Generati con Claude a partire dal finding strutturato e da un prompt con esempi (i testi del mockup sono il riferimento di tono).
- Il modello **non inventa numeri**: usa solo quelli in `evidence`. Validazione automatica: ogni numero nel testo deve comparire nel finding.
- Italiano semplice, frasi brevi, termini tecnici spiegati la prima volta.

## Output
Tabella `tasks` (stato: aperta, fatta, scartata, in attesa del senior) con lo storico. Le azioni dell'advertiser vengono registrate.

## Fatto quando
Per 2 settimane gli advertiser dei clienti pilota lavorano dal briefing e il senior non trova istruzioni sbagliate.
