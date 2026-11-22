# Fase 00 – Setup, accessi e decisioni aperte

## Obiettivo
Avere accessi API funzionanti in sola lettura su almeno 1 account Google Ads e 1 account Meta di prova, e chiudere le decisioni aperte.

## Decisioni da chiudere (con Davide)
- [ ] Stack confermato (vedi CLAUDE.md) e hosting (Cloud Run? altro?).
- [ ] Progetto GCP e dataset BigQuery del tool.
- [ ] Account pilota: 1-2 clienti con Google + Meta e volumi sufficienti.
- [ ] Tool creativo: ha un'API o accetta input strutturato (JSON, CSV)? Formato del brief.
- [ ] Chi sono gli utenti (advertiser) e i senior che approvano; come si autenticano (Google Workspace SSO?).
- [ ] Soglie in `config/regole.yaml` e `config/soglie.yaml` validate.

## Attività
1. **MCP ufficiali** (per la fase 00b e, dalla 08, per scrivere)
   - Collegare in Claude Code i connettori Google Ads e Meta Ads con un utente che vede gli account pilota.
   - Elencare gli strumenti esposti da ciascuno, separando lettura e scrittura. Verificare in particolare se il connettore Google Ads scrive.
   - Negare con `deny` tutti gli strumenti di scrittura in `.claude/settings.json` di progetto.
2. **Google Ads API, solo lettura** (estrazione notturna della fase 01)
   - Developer token dell'MCC SearchOn: Basic basta per sviluppo; per leggere gli account dei clienti in produzione serve Standard, quindi avviare la richiesta presto.
   - Client OAuth in GCP, refresh token di un utente di servizio con accesso all'MCC.
   - Test: `customers:listAccessibleCustomers` e una query GAQL su `campaign` per l'account pilota.
3. **Meta Marketing API, solo lettura**
   - App Meta di SearchOn collegata al Business Manager, utente di sistema con `ads_read`. Il permesso `ads_management` e l'App Review non servono: le scritture passano dall'MCP ufficiale.
   - Test: lettura di campagne e insights dell'account pilota.
4. **GCP**: service account per BigQuery, Secret Manager per i token.
5. **Impostazioni gestite di Claude Code**: verificare come distribuirle ai PC degli advertiser (serve per bloccare le scritture ora e per gli hook in fase 08).
6. **Repo**: struttura cartelle, `pyproject.toml`, `.env.example`, lint e test minimi.

## Struttura proposta del repo
```
config/            regole.yaml, soglie.yaml, clienti/<cliente>.yaml
src/copilota/
  ingest/          google.py, meta.py           (fase 01)
  checks/          segnali.py                   (fase 02)
  analysis/        google.py, meta.py, creative.py, measurement.py (fasi 03-04)
  briefing/        tasks.py, text.py            (fase 05)
  rules/           engine.py                    (fase 08, usato dagli hook)
  web/             app FastAPI                  (fase 06)
  mcp/             MCP del Copilota, sola lettura (fase 07)
hooks/             guardrail.py, log.py         (fase 08)
skill/             SKILL.md, riferimenti/       (fase 00b, aggiornata in 07)
fasi/              questi file
docs/              mockup.html
```

## Output
- Accessi funzionanti, segreti in Secret Manager o `.env` locale.
- `config/clienti/<cliente>.yaml` per i clienti pilota (id account Google e Meta, target, linee guida brand, durata media dei concept se nota).
- Decisioni aperte chiuse e annotate in `fasi/STATO.md`.

## Fatto quando
Uno script di test legge campagne e metriche di ieri dall'account pilota su entrambe le piattaforme.
