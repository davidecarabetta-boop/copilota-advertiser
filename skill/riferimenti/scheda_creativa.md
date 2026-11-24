# Scheda creativa: chiamate MCP e regole di compilazione

Campi, controlli e limiti stanno in `config/scheda_creativa.yaml`: leggerlo prima di compilare.
Le schede vanno in `data/<cliente>/schede_creative/<creative_id>.yaml`, le immagini in
`data/<cliente>/schede_creative/img/` (cartella esclusa da git).

## 1. Quali creatività
Annunci con spesa delle campagne a conversione in `meta_ad_daily.csv` (ultimi 30 giorni).
Si fanno solo le **immagini statiche**. Catalogo dinamico (l'immagine cambia per utente) e video
(Meta dà solo miniature da 160 px) non si schedano.

## 2. Dall'annuncio all'immagine
1. `ads_get_ad_entities` (level `ad`, `object_ids` degli annunci, campo `creative_id`).
2. `ads_get_creatives` con `creative_ids` e `fields: [id, name, object_type, body, title, call_to_action_type, image_hash, product_set_id, video_id, asset_feed_spec]`.
   - `product_set_id` o `template_data` → catalogo: saltare.
   - `video_id` → video: saltare.
   - **Attenzione**: le creatività con `asset_feed_spec` hanno **più immagini**, una per posizionamento (1:1, 9:16, 1.91:1…). Si scheda quella del feed: la quadrata (larghezza = altezza, dal passo 3); se non c'è, la prima della lista. Non abbinare mai un'immagine a una creatività dal nome del file o dal modello raffigurato: versioni diverse dello stesso modello hanno prezzi diversi.
   - Il testo principale sta in `asset_feed_spec.bodies` (più varianti) o in `body`; i titoli in `asset_feed_spec.titles` o `title`. Servono per il controllo `testo_coerente`.
3. `ads_get_ad_images` con `hashes` e `fields: [hash, name, width, height, url]`.
4. Scaricare l'immagine dall'`url` in `img/<hash>.jpg`. Gli URL scadono: scaricare subito.

## 3. Compilare la scheda
Guardare l'immagine (Read del file) e compilare:
- `campi`: solo valori ammessi dal config. Se nessun valore va bene, scriverlo all'utente invece di inventarne uno.
- `testi`: trascrivere titolo, offerta, claim, CTA dell'immagine e il primo testo principale.
- `punti_forti`: 2–3 frasi su cosa funziona, ognuna con il perché.
- `controlli`: tutti quelli del config. Esito `ok`, `attenzione` o `problema`; per ogni esito diverso da `ok` una nota di una frase che dice **cosa si vede** nell'immagine, non un consiglio generico.
- `test`: al massimo 3, ognuno cambia **un solo** elemento (es. prezzo → rata; claim → fatto concreto). Con l'ipotesi in una frase.
- `confermata: false`. La conferma la dà l'advertiser o il senior.

Regole di scrittura: frasi brevi, niente gergo, niente giudizi sul gusto ("brutta", "vecchia"). Si giudica se l'immagine fa il suo lavoro: farsi notare, farsi capire, dare un motivo per cliccare.
I controlli legali (`condizioni`) si segnalano come "da verificare", non si danno pareri legali.

## 4. Numeri
Non scriverli nella scheda: l'app li calcola da `meta_ad_daily` per gli `ad_ids` della scheda e li confronta con la media della campagna. Nella risposta in chat ricordare che i numeri dicono cosa è successo, non perché, e che modello, pubblico e periodo pesano quanto la grafica.

## Esempio
```yaml
creative_id: "1424298183231130"
nome: Citroën C3 Aircross - 26 Ottobre
ad_ids: ["52596724665557"]
immagine: img/62528bcb1d18af3d83624fe1a322dbc8.jpg
compilata_il: 2026-11-24
confermata: false
campi: {leva: prezzo_modello, soggetto: prodotto_singolo, formato: "1:1", palette: colorata,
        densita_testo: media, prezzo_in_immagine: true, condizioni_in_immagine: false,
        cta_in_immagine: true}
testi: {titolo: Citroen C3 Aircross, offerta: A partire da 12.334 €, claim: Look inconfondibile,
        cta: Approfittane ora}
punti_forti:
  - Il prezzo nel bollino fucsia è l'elemento più visibile e si legge anche in miniatura.
controlli:
  - {id: tipo_di_offerta, esito: problema, nota: Non dice se l'auto è nuova, km 0 o usata.}
test:
  - {cambia: Aggiungere "Km 0" o "Usato garantito" sopra il prezzo, ipotesi: Chi clicca sa già cosa compra e il lead è più qualificato.}
```
