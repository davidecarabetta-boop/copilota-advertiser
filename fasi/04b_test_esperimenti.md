# Fase 04b – Test A/B, lift ed esperimenti

## Perché
Senza test l'advertiser decide su numeri attribuiti dalla piattaforma e su impressioni. Il modulo dice **quando** testare, **cosa** testare, **come** impostare il test perché dia una risposta, **cosa non toccare** mentre gira e **come leggere** il risultato.

## Tipi di test gestiti
| Domanda | Test | Piattaforma |
|---|---|---|
| Quale creatività / concept / landing funziona meglio? | A/B test | Meta (A/B test), Google (esperimenti personalizzati, A/B Demand Gen) |
| Conviene la nuova strategia di offerta, AI Max, l'obiettivo a valore? | Esperimento a metà traffico | Google (esperimenti di campagna) |
| PMax porta vendite in più rispetto a quello che già ho? | Esperimento di uplift PMax | Google |
| Le campagne generano vendite che non avrei avuto comunque? | Conversion lift | Meta, Google (YouTube / Demand Gen dove disponibile) |
| Effetto complessivo dei media, anche offline | Geo-test (zone test vs controllo) | Fuori piattaforma, con il team analytics |
| Notorietà / ricordo | Brand lift | Meta, Google (YouTube) |

## 1. Quando proporre un test
- Una decisione importante è in sospeso (cambio di strategia, nuovo canale, budget in aumento) e i dati attribuiti non bastano a decidere.
- Il modulo Misurazione segnala risultati sospetti (brand in PMax, clienti esistenti su Meta).
- L'account non ha mai fatto un test di incrementalità ed è sopra le soglie minime.
- **Ammissibilità**: budget e volume di conversioni sufficienti per la durata (calcolo della minima differenza rilevabile con le soglie in `soglie.yaml → test`). Su Meta si usa anche la verifica di ammissibilità della piattaforma (`ads_experiment_check_eligibility`). Se il test non può dare una risposta, il tool lo dice e non lo propone.

## 2. Impostazione (scheda test)
Ogni test proposto ha una scheda fissa:
- **Ipotesi** in una frase ("I video UGC abbassano il CPA rispetto alle statiche di prodotto").
- **Metrica principale** (una sola) e metriche di controllo.
- **Variabile**: una sola cosa cambia tra le versioni.
- **Durata minima** e budget necessario calcolati, con la differenza minima che il test può rilevare.
- **Criterio di decisione** scritto prima di partire ("se il CPA della variante è almeno il 10% più basso con confidenza ≥ 90%, la adottiamo").

La creazione del test è un'azione `esperimenti_test` (serve il senior).

## 3. Durante il test
- L'oggetto in test entra automaticamente in **"Da non toccare"** fino alla fine: niente modifiche a budget, target, creatività, pubblico nelle campagne coinvolte.
- Gli hook della fase 08 bloccano le modifiche agli oggetti in test.
- Il tool controlla solo che il test stia ricevendo traffico bilanciato e segnala se rischia di non arrivare a risultato.
- Vietato chiudere in anticipo perché "una versione sta già vincendo".

## 4. Lettura del risultato
- Esito in italiano semplice: vince A / vince B / **nessuna differenza dimostrabile** (anche questo è un risultato).
- Confidenza e intervallo, non solo la differenza puntuale.
- Azione conseguente secondo il criterio scritto all'inizio, come attività nel briefing.
- Per i lift: incrementalità stimata e confronto con quanto attribuito dalla piattaforma (fattore di correzione da usare nelle valutazioni successive).

## 5. Registro dei test
Tabella `tests` con tutti i test di ogni cliente: ipotesi, impostazione, date, esito, decisione presa. Serve a non ripetere test già fatti e a costruire, nel tempo, i fattori di incrementalità per cliente e canale.

## Output
- Righe in `findings_daily` con `module = test` (proposte di test, avvisi durante, esiti).
- Scheda "Test" nell'interfaccia: in corso, proposti, conclusi.

## Fatto quando
Almeno un A/B test creativo e una proposta di lift sui clienti pilota sono stati impostati, seguiti e letti con il tool, e il senior conferma impostazione e lettura.
