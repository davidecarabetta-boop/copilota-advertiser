# Fase 00b – Prototipo in chat con gli MCP ufficiali

Parte subito dopo la 00 e gira in parallelo alla 01. Nessuna infrastruttura: Claude Code + connettori ufficiali Google Ads e Meta Ads + skill.

## Obiettivo
Validare sui clienti pilota **la logica** del Copilota (segnali, analisi, semaforo creatività, mappa della diversità, briefing) e calibrare `config/soglie.yaml`, prima di costruire pipeline e interfaccia.

## Prerequisiti
- Connettori ufficiali Google Ads e Meta Ads collegati in Claude Code con un utente che ha accesso agli account pilota.
- **Verificare** quali strumenti espone oggi il connettore Google Ads: se ha strumenti di scrittura, elencarli in `config/regole.yaml` → `strumenti_mcp`.
- **Scritture bloccate:** in questa fase tutti gli strumenti di scrittura dei due MCP sono negati con regole `deny` nelle impostazioni di Claude Code (gestite dall'organizzazione per gli advertiser, `.claude/settings.json` di progetto per lo sviluppo).

## Attività
1. **Skill `copilota-advertiser`** (`skill/SKILL.md`), anticipata dalla fase 07:
   - le 4 leve e il principio "non piloti l'algoritmo";
   - per ogni modulo, quali dati leggere dagli MCP (query GAQL di riferimento, chiamate Meta) e come interpretarli secondo `config/soglie.yaml`;
   - semaforo creatività e mappa della diversità;
   - formato fisso dell'attività: cosa succede / perché / come fare / non fare, livello da `regole.yaml`;
   - mai proporre azioni fuori da `regole.yaml`; con Segnali rossi solo il ticket.
2. **Query e chiamate di riferimento** in `skill/riferimenti/`: le GAQL per campagne, PMax per canale, asset group, search terms; le chiamate Meta per insights per annuncio, copertura, stato di consegna, impostazioni Advantage+ creative.
3. **Concept**: finché non esiste la tabella `creative_concepts`, la skill raggruppa le creatività per concept leggendo nome e anteprima, e chiede conferma all'advertiser.
4. **Prova sui pilota**: 2-3 settimane di briefing generati in chat, confrontati con il giudizio del senior. Annotare in `fasi/STATO.md` errori, soglie corrette, analisi inutili o mancanti.

## Limiti noti (motivo per cui poi serve la fase 01)
- Nessuno storico salvato: ogni analisi rilegge i dati, è lenta e costa token.
- Risultati non sempre identici tra un'esecuzione e l'altra.
- Il semaforo sui primi 7 giorni del concept richiede di rileggere molte settimane di dati.

## Fatto quando
- Il senior approva il briefing generato in chat per almeno 2 settimane di fila sui clienti pilota.
- `config/soglie.yaml` aggiornato con i valori calibrati.
- Elenco degli strumenti di scrittura dei due MCP completo in `regole.yaml`.
