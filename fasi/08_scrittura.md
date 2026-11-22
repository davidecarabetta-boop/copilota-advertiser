# Fase 08 – Scrittura tramite MCP ufficiali, con guardrail negli hook

## Obiettivo
Permettere agli advertiser di eseguire dalla chat le modifiche consentite usando gli MCP ufficiali Google Ads e Meta Ads, con le regole di `config/regole.yaml` applicate da **hook `PreToolUse` di Claude Code** che l'utente non può togliere.

## Prerequisiti
- Fasi 05 e 07 stabili da almeno 1 mese.
- Elenco completo in `regole.yaml → strumenti_mcp` di tutti gli strumenti di scrittura dei due MCP, con l'azione a cui corrispondono.
- Possibilità di distribuire **impostazioni gestite** (managed settings) di Claude Code ai PC degli advertiser.

## Perimetro di sicurezza
- Gli hook funzionano **solo in Claude Code**. Per gli advertiser i connettori Google Ads e Meta Ads in scrittura non vanno abilitati su claude.ai web o desktop chat, dove gli hook non esistono.
- Le impostazioni gestite contengono: gli hook, le regole `deny` sugli strumenti vietati e il divieto di disattivare gli hook.
- Ogni strumento di scrittura **non mappato** in `strumenti_mcp` è bloccato per default (nuovi strumenti aggiunti dalle piattaforme compresi).

## Hook `PreToolUse` (`hooks/guardrail.py`)
Riceve nome e argomenti dello strumento MCP e risponde consenti / blocca con un motivo in italiano che Claude mostra all'advertiser. Controlli, leggendo `regole.yaml` e `soglie.yaml`:
1. strumento mappato a un'azione e azione non `vietato`;
2. ruolo dell'utente (advertiser / senior) rispetto al livello dell'azione;
3. Segnali dell'account non rossi (letti dal Copilota);
4. oggetto non in apprendimento (lettura con l'MCP o dal Copilota);
5. raffreddamento rispettato (dal log);
6. variazione entro il limite percentuale: l'hook legge il valore attuale prima di consentire;
7. limite giornaliero di modifiche per account;
8. valore uguale alla proposta del Copilota per quell'oggetto (niente valori liberi);
9. linee guida del brand del cliente.

Azioni `serve_senior` chieste da un advertiser: blocco + creazione della richiesta nella coda di approvazione. Il senior la esegue dalla sua sessione, e l'hook ricontrolla tutto.

Avviso Meta: se la modifica può far ripartire l'apprendimento, l'hook risponde con una richiesta di conferma esplicita.

## Hook `PostToolUse` (`hooks/log.py`)
Scrive in `change_log`: utente, account, strumento, argomenti, valore prima (letto dal PreToolUse), valore dopo, finding di origine, esito. Da qui:
- **Annulla** entro 7 giorni: il Copilota propone la modifica inversa, che ripassa dagli hook.
- Report settimanale per il senior delle modifiche fatte.

## Test
Un test automatico per ogni regola di `regole.yaml` che dimostra il blocco, più un test per uno strumento non mappato.

## Rilascio graduale
1. Solo livello `puoi_farlo`, solo account pilota, solo Meta o solo Google (quello con l'MCP più completo).
2. Coda di approvazione per il senior.
3. Estensione a tutti gli account.

## Fatto quando
Un mese di uso senza modifiche annullate per errore e tutti i test di blocco verdi.
