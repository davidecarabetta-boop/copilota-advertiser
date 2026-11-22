# Fase 03b – Post-click: pertinenza annuncio ↔ landing page e problemi del sito

## Perché
Un annuncio può funzionare bene (CTR alto, CPC giusto) e portare comunque poche conversioni perché il problema è **dopo il clic**: landing page non coerente con l'annuncio, pagina lenta, errori, funnel del sito che perde utenti. In questi casi l'advertiser non deve toccare le campagne: deve segnalare il problema a chi gestisce sito e CRO.

## 1. Diagnosi a quadranti (per campagna, asset group, ad set, concept)
CTR e tasso di conversione post-click confrontati con la mediana dell'account (soglie in `soglie.yaml → post_click`):

| CTR | Conv. rate | Diagnosi | Chi agisce |
|---|---|---|---|
| Alto | Basso | **Problema post-click**: landing page, coerenza del messaggio o sito | Team sito / CRO (ticket) |
| Basso | Alto | Annuncio o creatività poco attraenti, la pagina funziona | Advertiser (creatività) |
| Basso | Basso | Pubblico, offerta o segnali sbagliati | Advertiser + senior |
| Alto | Alto | Funziona: candidato a più budget | Senior |

## 2. Pertinenza annuncio ↔ landing page
Per ogni coppia annuncio/asset group/ad set → URL finale:
- **Coerenza del messaggio**: Claude legge il testo dell'annuncio (titoli, descrizioni, testo Meta) e la landing page e verifica che offerta, prodotto, prezzo, promozione e call to action corrispondano. Esito: coerente / parziale / incoerente, con l'esempio concreto ("l'annuncio dice −30%, la pagina non mostra sconti").
- **Pagina giusta**: annunci di prodotto che portano alla home o a una categoria generica.
- **Prezzo e disponibilità**: feed Merchant Center / catalogo Meta vs pagina prodotto (prezzo diverso, prodotto esaurito).
- **Errori**: 404, redirect a catena, parametri UTM / gclid persi nel redirect.
- **Segnali di piattaforma**: componente "esperienza sulla pagina di destinazione" del Quality Score (Google); rapporto visualizzazioni della landing page / clic sul link (Meta). Un rapporto basso indica pagina lenta o abbandoni prima del caricamento.

## 3. Problemi del sito / CRO (dati GA4 in BigQuery)
Per il traffico a pagamento, separato per piattaforma, campagna e dispositivo:
- **Funnel**: sessione → vista prodotto / pagina servizio → carrello / inizio modulo → checkout / invio → acquisto / lead. Individua lo step con la perdita anomala rispetto allo storico o al traffico organico.
- **Mobile vs desktop**: conversione mobile molto sotto desktop con traffico prevalentemente mobile (tipico Meta).
- **Velocità**: Core Web Vitals delle landing page (CrUX / PageSpeed API), soprattutto LCP e INP su mobile.
- **Engagement**: sessioni con engagement basso o uscita immediata dalle landing a pagamento.
- **Lead gen**: abbandono del modulo per campo, se tracciato.
- **Cambiamenti**: calo improvviso del tasso di conversione con CTR stabile → verificare rilasci del sito, checkout, metodi di pagamento, consenso.

## Output
- Righe in `findings_daily` con `module = post_click`.
- Nel briefing: attività di tipo **"Non toccare le campagne: il problema è sul sito"**, con il ticket precompilato per il team sito/CRO (pagina, step del funnel, numeri, confronto, screenshot della pagina).
- Proposte all'advertiser solo quando l'azione è sua: cambiare URL finale verso una pagina più pertinente (`cambio_url_finale`, serve il senior), allineare il testo dell'annuncio all'offerta reale.

## Dati necessari (aggiunti alla fase 01)
Export GA4 in BigQuery del cliente, URL finali e testi degli annunci, crawl leggero delle landing page (testo + screenshot), CrUX/PageSpeed API, feed prodotti.

## Fatto quando
Sui clienti pilota il senior conferma almeno 3 casi in cui il tool ha attribuito correttamente il problema al sito invece che alle campagne, e nessun caso in cui ha mandato l'advertiser a modificare campagne sane.
