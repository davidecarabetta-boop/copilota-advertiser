"""Traduce i controlli (Segnali) e le diagnosi (Creatività) nelle attività per l'advertiser.

Ogni attività segue il formato fisso del progetto: cosa succede / perché / come fare /
non fare, con il livello preso da config/regole.yaml. È il pezzo che l'advertiser legge:
niente gergo, niente numeri senza spiegazione.
"""

from dataclasses import dataclass, field

import yaml

from copilota.causes import ads_manager_link
from copilota.config import CONFIG_DIR
from copilota.creative import Finding
from copilota.rules import Condition, evaluate, is_brand, line_of, proposals, zone_of
from copilota.signals import UNKNOWN, Check, Status

LEVEL_LABEL = {"puoi_farlo": "Puoi farlo", "decide_specialist": "Decide lo specialist",
               "serve_senior": "Serve il senior", "vietato": "Vietato"}


@dataclass
class Task:
    title: str
    module: str
    level: str  # puoi_farlo | serve_senior
    priority: int
    cosa: str
    perche: str
    come: list[str]
    non_fare: str
    button: str
    ticket: str | None = None  # testo da copiare, se l'azione è aprire un ticket
    link: tuple[str, str] | None = None  # (etichetta, url) per aprire l'oggetto in piattaforma
    rule: str | None = None  # chiave della proposta in regole.yaml
    conditions: list[Condition] = field(default_factory=list)  # perché viene proposta
    verifica: str | None = None  # cosa controllare dopo, e quando

    @property
    def level_label(self) -> str:
        return LEVEL_LABEL.get(self.level, self.level)


@dataclass
class Waiting:
    """Una proposta che oggi non si può fare: quale e perché (condizioni non soddisfatte)."""

    title: str
    reasons: list[str]


@dataclass
class Missing:
    """Un dato che manca per dare un giudizio completo, con dove inserirlo."""

    title: str
    why: str
    page: str  # crm | concetti | tracciamento
    items: list[str] = field(default_factory=list)


@dataclass
class Plan:
    blocked: bool
    headline: str
    tasks: list[Task]
    missing: list[Missing]
    dont_touch: list[str]
    waiting: list[Waiting] = field(default_factory=list)


def _rule(key: str, values: dict, task: Task, waiting: list[Waiting]) -> list[Task]:
    """Propone `task` solo se la proposta `key` di regole.yaml è soddisfatta; altrimenti la
    mette in attesa con le condizioni che mancano."""
    ok, conds = evaluate(key, values)
    p = proposals()[key]
    if ok:
        task.rule, task.conditions = key, conds
        v = p.get("verifica")
        task.verifica = f"Dopo {v['dopo_giorni']} giorni: {v['cosa']}" if v else None
        return [task]
    reasons = [("non vale: " if not c.exclusion else "vale: ") + c.text for c in conds
               if (c.state is False and not c.exclusion) or (c.state is True and c.exclusion)]
    reasons += ["non verificabile con i dati: " + c.text for c in conds
                if c.state is None and not c.exclusion]
    waiting.append(Waiting(task.title, reasons))
    return []


def _level(action_key: str) -> str:
    regole = yaml.safe_load((CONFIG_DIR / "regole.yaml").read_text(encoding="utf-8"))
    return (regole.get("azioni", {}).get(action_key) or {}).get("livello", "serve_senior")


def _is_missing(c: Check) -> bool:
    return (UNKNOWN in c.detail or c.detail.startswith("Nessun lead dal CRM")
            or c.detail.startswith("Qualità dei lead non misurata")
            or c.name == "Stato del tracciamento")


TRACKING_PAGE_FIELDS = {
    "Enhanced Conversions": "Enhanced Conversions attive?",
    "CAPI": "Conversions API attiva e con che copertura?",
    "Consent Mode v2": "Consent Mode v2 attivo e tasso di consenso?",
    "Conversione di ottimizzazione": "La qualità dei lead torna dal CRM alla piattaforma?",
    "Customer Match": "Quando è stato aggiornato il pubblico clienti?",
    "Stato del tracciamento": "Stato del tracciamento dell'account",
}


def _ticket(account: dict, items: list[Check], also: list[Check], blocking: bool = True) -> str:
    where = f"{account['platform'].capitalize()} · {account['name']} ({account['account_id']})"
    intro = ("il Copilota ha bloccato l'account per questi problemi:" if blocking
             else "il Copilota ha trovato questo problema da sistemare:")
    lines = [f"Oggetto: [Copilota] Da sistemare - {where}", "", f"Ciao, {intro}", ""]
    lines += [f"- {c.name}: {c.detail}" for c in items]
    if also:
        lines += ["", "Da sistemare insieme, se possibile:"]
        lines += [f"- {c.name}: {c.detail}" for c in also]
    lines += ["", ("Finché non è risolto sull'account non facciamo modifiche. Grazie!" if blocking
                   else "Nel frattempo sulle campagne continuiamo a lavorare. Grazie!")]
    return "\n".join(lines)


def _analytics_task(c: Check, title: str, perche: str, account: dict,
                    priority: int = 2) -> Task:
    ok, conds = evaluate("ticket_analytics", {"problema_dati": True})
    return Task(
        title=title, module="Segnali", level="puoi_farlo", priority=priority,
        cosa=c.detail, perche=perche,
        come=["Copia il testo qui sotto e mandalo al team analytics",
              "Intanto continua con le altre attività: questo non blocca l'account"],
        non_fare="Non provare a compensare cambiando budget o offerte: il problema è nei dati.",
        button="Copia il testo del ticket", ticket=_ticket(account, [c], [], blocking=False),
        rule="ticket_analytics", conditions=conds,
        verifica="Dopo 7 giorni: il controllo torna verde")


def _quality_of(camp: dict | None, campaign_id: str) -> tuple[bool | None, dict | None]:
    """La campagna rispetta il KPI di costo per lead qualificato? (True / False / None se non
    c'è CRM o KPI) e la riga della campagna fuori KPI, se lo è."""
    if not camp:
        return None, None
    bad = next((o for o in camp.get("out", []) if o["campaign_id"] == campaign_id
                and any(x["metric"] == "costo per lead qualificato" for x in o["over"])), None)
    if bad:
        return False, bad
    ok = next((w for w in camp.get("within", []) if w["campaign_id"] == campaign_id
               and (w.get("kpi") or {}).get("cost_per_qualified")), None)
    return (True, None) if ok else (None, None)


def _cause_task(c: Check, account: dict, camp: dict | None, waiting: list[Waiting]
                ) -> list[Task]:
    cause, d = c.data["cause"], c.data
    kind = "ad set" if cause["object_type"] == "adset" else "campagna"
    link = None
    if account["platform"] == "meta":
        link = (f"Apri «{cause['object_name']}» in Gestione inserzioni",
                ads_manager_link(account["account_id"], cause["object_type"], cause["object_id"]))
    quality, bad = _quality_of(camp, cause.get("campaign_id", ""))
    days_ago = (cause.get("today") or cause["date"]) - cause["date"]
    values = {"portava_meta": cause["share_pct"] >= 50, "ancora_in_pausa": cause["still_off"],
              "crollo": True, "qualita_ok": quality, "pausa_vecchia": days_ago.days > 30}
    rule = proposals()["riattiva_oggetto"]
    what = (f"Il {cause['date']:%d/%m} l'{kind} «{cause['object_name']}» è stato messo in "
            f"pausa. Portava il {cause['share_pct']}% dei lead (circa {cause['per_day']:.0f} al "
            f"giorno). Da allora i lead sono passati da {d['before']:.0f} a {d['recent']:.1f} "
            f"al giorno e la spesa da {d['cost_before']} € a {d['cost_recent']} € al giorno.")
    if cause["kind"] == "pausa" and cause["still_off"] and quality is False:
        _, conds = evaluate("riattiva_oggetto", values)
        over = next(x for x in bad["over"] if x["metric"] == "costo per lead qualificato")
        return [Task(
            title=(f"Prima di riattivare «{cause['object_name']}» decidi col senior: i suoi lead "
                   "erano fuori KPI"),
            module="Valore", level="serve_senior", priority=1,
            cosa=(what + f" Ma secondo il CRM la sua campagna costava {_eur(over['value'])} per "
                  f"lead qualificato, contro un KPI dello specialist di {_eur(over['target'])}."),
            perche=rule["se_qualita_bassa"] + ".",
            come=["Mostra questa scheda al senior e allo specialist",
                  "Opzione A: riattivarlo com'era per non restare senza lead, e intanto "
                  "lavorare sulla qualità (lead qualificati dal CRM alla piattaforma, creatività)",
                  "Opzione B: lasciarlo spento; lo specialist decide dove va il budget"],
            non_fare="Non riattivarlo da solo senza la decisione del senior.",
            button="Chiedi l'ok al senior", link=link, rule="riattiva_oggetto",
            conditions=conds)]
    if cause["kind"] == "pausa":
        task = Task(
            title=f"Riattiva l'{kind} «{cause['object_name']}»",
            module="Vincoli", level=rule.get("livello") or _level("pausa_riattivazione"),
            priority=1, cosa=what,
            perche=rule["perche"],
            come=["Apri l'oggetto con il link qui sotto", *rule["procedura"]],
            non_fare=("Non modificarlo mentre lo riattivi: ogni modifica fa ripartire "
                      "l'apprendimento."),
            button="Fatto", link=link)
        if quality is None and values["portava_meta"] and cause["still_off"]:
            # qualità non verificabile (manca CRM o KPI): si propone, ma decide il senior
            values = {**values, "qualita_ok": True}
            task.level = "serve_senior"
            task.button = "Chiedi l'ok al senior"
            task.perche += " " + rule["se_qualita_non_verificabile"] + "."
            tasks = _rule("riattiva_oggetto", values, task, waiting)
            for t in tasks:
                for cond in t.conditions:
                    if cond.text == rule["proponi_se"][3]["testo"]:
                        cond.state = None
            return tasks
        return _rule("riattiva_oggetto", values, task, waiting)
    return [Task(
        title=f"Controlla la modifica a «{cause['object_name']}»: i lead sono crollati",
        module="Vincoli", level="serve_senior", priority=1,
        cosa=c.detail,
        perche="La modifica coincide con il crollo dei lead.",
        come=["Mostra questa scheda al senior", "Decidete se tornare alla situazione di prima"],
        non_fare="Non fare altre modifiche alla campagna finché non avete deciso.",
        button="Fatto", link=link)]


def _eur(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f} €".replace(",", ".")


def _campaign_tasks(camp: dict, account: dict, waiting: list[Waiting]) -> list[Task]:
    """Attività dal confronto delle campagne con i KPI dello specialist."""
    tasks: list[Task] = []
    rule = proposals()["campagna_fuori_kpi"]
    for o in camp.get("out", []):
        over = "; ".join(f"{x['metric']} {_eur(x['value'])} contro un KPI di {_eur(x['target'])}"
                         for x in o["over"])
        task = Task(
            title=f"«{o['name']}» è fuori KPI: segnalalo allo specialist",
            module="Valore", level=_level("budget_giornaliero"), priority=2,
            cosa=(f"Dal {camp['from']:%d/%m} al {camp['to']:%d/%m} ha speso {_eur(o['spend'])} "
                  f"({o['share_pct']}% della spesa) per {o['leads']} lead nel CRM, "
                  f"{o['qualified']} qualificati e {o['contracts']} contratti. {over[0].upper()}"
                  f"{over[1:]}."),
            perche=rule["perche"], come=rule["procedura"],
            non_fare="Non cambiare budget, target o campagna senza la decisione dello specialist.",
            button="Segnala allo specialist")
        tasks += _rule("campagna_fuori_kpi", {
            "kpi_presenti": True, "crm_maturo": True, "fuori_kpi": True,
            "abbastanza_lead": True, "pesa": True,
            "in_test": True if o.get("in_test") else (False if camp.get("status_known")
                                                     else None)}, task, waiting)
    vrule = proposals()["volume_sotto_kpi"]
    for v in camp.get("volume", []):
        task = Task(
            title=f"Lead {v['line']} sotto il volume richiesto: segnalalo allo specialist",
            module="Valore", level=_level("budget_giornaliero"), priority=2,
            cosa=(f"Negli ultimi 30 giorni la linea {v['line']} ha portato {v['leads']} lead "
                  f"(come li conta la piattaforma), contro {v['target']:.0f} richiesti dallo "
                  "specialist."),
            perche=vrule["perche"], come=vrule["procedura"],
            non_fare="Non alzare il budget da solo.", button="Segnala allo specialist")
        tasks += _rule("volume_sotto_kpi", {"kpi_presenti": True, "sotto_volume": True},
                       task, waiting)
    # Lead senza UTM (organico, diretto) o con l'UTM di una campagna chiusa o rinominata non
    # sono un errore: si mostrano nella pagina Campagne come informazione, non come attività.
    return tasks


def _data_problems(checks: list[Check]) -> list[Check]:
    """Problemi aperti su tracciamento, obiettivo e qualità: finché ci sono, le regole che
    richiedono Segnali verdi (strategia_obiettivo_valore) aspettano."""
    return [c for c in checks if c.status is Status.RED and c.group in
            ("Tracking", "Obiettivo", "Valore") and c.name != "Andamento conversioni"
            and not c.data.get("attribution")]


def build_plan(account: dict, checks: list[Check], findings: list[Finding],
               camp: dict | None = None) -> Plan:
    missing_checks = [c for c in checks if c.status is not Status.GREEN and _is_missing(c)]
    reds = [c for c in checks if c.status is Status.RED and not _is_missing(c)
            and c.blocking]
    open_reds = [c for c in checks if c.status is Status.RED and not _is_missing(c)
                 and not c.blocking]
    yellows = [c for c in checks if c.status is Status.YELLOW and not _is_missing(c)]
    missing = _missing(missing_checks, findings)
    if camp is not None and (camp.get("missing_kpi") or not camp.get("kpis")):
        lines = ", ".join(camp.get("missing_kpi") or []) or "tutte le linee"
        missing.insert(0, Missing(
            "Inserisci i KPI dello specialist",
            f"Senza KPI il Copilota non giudica il rendimento delle campagne ({lines}): "
            "costo per lead, per lead qualificato, per contratto, lead al mese e budget.",
            "kpi"))

    if reds:
        data_yellows = [c for c in yellows + open_reds
                        if c.group in ("Tracking", "Obiettivo", "Valore")
                        and not c.data.get("attribution")]
        task = Task(
            title="Apri il ticket al team analytics e non toccare l'account",
            module="Segnali", level="puoi_farlo", priority=1,
            cosa=" ".join(c.detail for c in reds),
            perche=("Finché i numeri non sono affidabili, la piattaforma impara da dati "
                    "sbagliati e ogni modifica alle campagne rischia di peggiorare le cose."),
            come=["Copia il testo del ticket qui sotto (è già pronto) e mandalo al team "
                  "analytics", "Aspetta la loro conferma prima di qualsiasi modifica",
                  "Quando è risolto, torna qui: le altre attività compariranno da sole"],
            non_fare=("Non cambiare budget, offerte, creatività o campagne su questo account "
                      "finché il ticket non è chiuso."),
            button="Copia il testo del ticket",
            ticket=_ticket(account, reds, data_yellows))
        return Plan(True, "Bloccato: prima va risolto un problema sui dati.", [task], missing,
                    ["Tutto l'account, finché il ticket non è chiuso"])

    waiting: list[Waiting] = []
    ctx = {"segnali_verdi": not _data_problems(checks)}
    tasks: list[Task] = []
    for c in open_reds:
        tasks.extend(_from_red(c, account, camp, waiting, ctx))
    for c in yellows:
        tasks.extend(_from_check(c, account, waiting, ctx))
    blocked = (camp or {}).get("blocked_ids")
    for f in findings:
        tasks.extend(_from_finding(f, waiting, blocked))
    if camp:
        tasks.extend(_campaign_tasks(camp, account, waiting))
    tasks.sort(key=lambda t: t.priority)
    headline = (f"{len(tasks)} {'cosa' if len(tasks) == 1 else 'cose'} da fare oggi."
                if tasks else "Niente da fare oggi: l'account è a posto.")
    return Plan(False, headline, tasks, missing, [], waiting)


def _from_red(c: Check, account: dict, camp: dict | None, waiting: list[Waiting],
              ctx: dict) -> list[Task]:
    """Rossi che non bloccano l'account: diventano attività ad alta priorità."""
    if c.name == "Andamento conversioni":
        if c.data.get("cause"):
            return _cause_task(c, account, camp, waiting)
        return [Task(
            title="I lead sono crollati: controlla la consegna delle campagne",
            module="Vincoli", level="serve_senior", priority=1, cosa=c.detail,
            perche=("Il tracciamento è a posto, quindi il calo viene dalle campagne: annunci "
                    "rifiutati, ad set in pausa, pubblico troppo stretto, budget."),
            come=["Apri la campagna a conversione e controlla stato e consegna di ad set e "
                  "annunci", "Mostra al senior cosa trovi prima di cambiare qualcosa"],
            non_fare="Non alzare il budget per compensare: se non consegna, non spende comunque.",
            button="Fatto")]
    if c.name == "Conversione di ottimizzazione":
        title = ("Fai ripartire il caricamento dei lead qualificati da Salesforce a Google"
                 if account["platform"] == "google"
                 else "Fai mandare a Meta i lead qualificati dal CRM")
        return [_analytics_task(
            c, title, "Senza sapere quali lead diventano clienti, la piattaforma cerca lead "
            "qualsiasi: tanti contatti, pochi contratti.", account, priority=1)]
    if c.name == "Qualità dei lead":
        return [Task(
            title="Sono calati i lead che diventano clienti: parlane con il senior",
            module="Valore", level="serve_senior", priority=1, cosa=c.detail,
            perche=("La piattaforma può portare più lead e meno clienti: conta il numero di "
                    "contratti, non il numero di contatti."),
            come=["Mostra questa scheda al senior",
                  "Guardate insieme cosa è cambiato nel periodo: creatività, pubblico, offerte"],
            non_fare="Non alzare il budget per avere più lead: peggioreresti il problema.",
            button="Fatto")]
    return _from_check(c, account, waiting, ctx)


def _merge_groups(camps: list[dict]) -> list[list[dict]]:
    """Gruppi di campagne davvero accorpabili: stessa linea, tipo, strategia e zona."""
    groups: dict[tuple, list[dict]] = {}
    for x in camps:
        if is_brand(x["name"]):
            continue
        key = (line_of(x["name"]), x.get("type"), x.get("bidding"), zone_of(x["name"]))
        groups.setdefault(key, []).append(x)
    return list(groups.values())


def _from_check(c: Check, account: dict, waiting: list[Waiting], ctx: dict) -> list[Task]:
    if c.data.get("attribution"):
        return []  # scarto di attribuzione col CRM: informazione, non un'attività
    if c.name == "Conversioni non-lead":
        task = Task(
            title="Rendi secondarie le conversioni che non sono lead",
            module="Segnali", level=_level("strategia_obiettivo_valore"), priority=2,
            cosa=c.detail, perche=proposals()["conversioni_secondarie"]["perche"],
            come=proposals()["conversioni_secondarie"]["procedura"],
            non_fare="Non eliminare le azioni di conversione: rendile secondarie.",
            button="Chiedi l'ok al senior")
        return _rule("conversioni_secondarie",
                     {"quota_non_lead": True, "segnali_verdi": ctx["segnali_verdi"],
                      "in_test": None}, task, waiting)
    if c.name == "Conversioni per campagna":
        tasks: list[Task] = []
        min_conv = c.data.get("min_conv", 30)
        groups = _merge_groups(c.data.get("campaigns", []))
        alone = [g[0] for g in groups if len(g) == 1]
        if alone:
            waiting.append(Waiting(
                f"Campagne con poche conversioni: {len(alone)}",
                ["non vale: " + proposals()["accorpa_campagne"]["proponi_se"][5]["testo"]
                 + ". Nessuna ha una campagna della stessa linea, tipo, strategia e zona con "
                 "cui accorparla: " + "; ".join(f"«{x['name']}» ({x['conversions']})"
                                                 for x in alone)
                 + ". Lasciale così o parlane col senior."]))
        for group in (g for g in groups if len(g) > 1):
            names = [x["name"] for x in group]
            keep = max(group, key=lambda x: x["conversions"])
            task = Task(
                title=f"Accorpa {len(group)} campagne: " + " + ".join(f"«{n}»" for n in names),
                module="Vincoli", level=_level("struttura_campagne"), priority=2,
                cosa=("Fanno " + ", ".join(f"{x['conversions']} ({x['name']})" for x in group)
                      + f" conversioni al mese, tutte sotto le {min_conv}. Stessa linea, stesso "
                      "tipo di campagna, stessa strategia e stessa zona: insieme imparano di "
                      "più."),
                perche=proposals()["accorpa_campagne"]["perche"],
                come=[f"Resta «{keep['name']}», che ha più conversioni",
                      *proposals()["accorpa_campagne"]["procedura"][1:]],
                non_fare="Non accorpare campagne Brand, di zone o tipi diversi.",
                button="Chiedi l'ok al senior")
            tasks += _rule("accorpa_campagne", {
                "sotto_soglia": True, "stessa_linea": True, "stesso_tipo": True,
                "stessa_strategia": True, "stessa_zona": True, "almeno_due": len(group) > 1,
                "brand": False, "in_test": None, "budget_cliente": None}, task, waiting)
        return tasks
    titles = {
        "Riconciliazione con CRM": ("Fai controllare perché la piattaforma e il CRM non "
                                    "tornano", "Se la piattaforma conta lead che il CRM non ha "
                                    "(o il contrario), impara su numeri sbagliati."),
        "Caricamento offline vs CRM": ("Fai sistemare il caricamento dei lead qualificati",
                                       "La piattaforma riceve solo una parte dei lead buoni: "
                                       "impara a cercarne di meno."),
        "Consent Mode v2": ("Fai controllare il calo del consenso ai cookie",
                            "Meno consenso vuol dire meno conversioni viste: la piattaforma "
                            "sembra andare peggio di come va."),
        "CAPI": ("Fai alzare la copertura della Conversions API",
                 "Senza CAPI Meta perde le conversioni bloccate dal browser e impara meno."),
        "Enhanced Conversions": ("Fai attivare le Enhanced Conversions",
                                 "Google vede meno conversioni di quelle reali."),
        "Customer Match": ("Fai aggiornare il pubblico clienti",
                           "Un pubblico vecchio non aiuta la piattaforma a distinguere clienti "
                           "nuovi e già acquisiti."),
        "Campagne a conversione": ("Nessuna campagna cerca lead: parlane con il senior",
                                   "Senza un obiettivo di conversione l'algoritmo porta clic o "
                                   "visualizzazioni, non contatti."),
    }
    if c.name in titles:
        title, perche = titles[c.name]
        return [_analytics_task(c, title, perche, account)]
    return []


def _from_finding(f: Finding, waiting: list[Waiting], blocked: set[str] | None = None
                  ) -> list[Task]:
    t = _finding_task(f)
    if t is None:
        return []
    if f.issue_code == "diversity_low":
        learning = None if blocked is None else f.object_id in blocked
        return _rule("nuove_creativita", {"diversita_bassa": True, "campagna_lead": True,
                                           "campagna_spenta": False,
                                           "in_apprendimento": learning}, t, waiting)
    if f.issue_code in ("fatigue_late", "fatigue_prepare"):
        cid = f.evidence.get("campagna_id")
        learning = None if blocked is None or cid is None else cid in blocked
        return _rule("rinnova_creativita", {"stanca": True, "oltre_7_giorni": True,
                                             "in_apprendimento": learning}, t, waiting)
    return [t]


def _finding_task(f: Finding) -> Task | None:
    ev, level = f.evidence, _level(f.action_key) if f.action_key else "puoi_farlo"
    if f.issue_code in ("fatigue_late", "fatigue_prepare"):
        late = f.issue_code == "fatigue_late"
        return Task(
            title=(f"Sostituisci la creatività «{f.object_id}»: è stanca" if late
                   else f"Prepara una nuova versione di «{f.object_id}»"),
            module="Creatività", level=level, priority=1 if late else 2,
            cosa=((f"Negli ultimi 7 giorni ogni persona l'ha vista in media "
                   f"{ev['frequenza_ultimi_7g']:.1f} volte, oltre il massimo di "
                   f"{ev['frequenza_oltre']:g}. Il tasso di clic è a {ev['ctr_ultimi_7g_pct']}% "
                   f"(picco {ev['ctr_picco_pct']}%).")
                  if ev.get("frequenza_oltre") else
                  f"Il tasso di clic è sceso del {ev['calo_ctr_pct']:.0f}% rispetto al suo "
                  f"momento migliore e le stesse persone la vedono sempre più spesso"
                  + (f"; ogni lead costa {ev['cpa_ultimi_7g']:.0f} € contro "
                     f"{ev['cpa_riferimento']:.0f} € di prima." if late and ev.get("cpa_ultimi_7g")
                     and ev.get("cpa_riferimento") else ".")),
            perche=proposals()["rinnova_creativita"]["perche"],
            come=proposals()["rinnova_creativita"]["procedura"],
            non_fare=("Non spegnere la vecchia prima che la nuova sia partita: perderesti "
                      "volume per giorni."),
            button="Fatto")
    if f.issue_code == "diversity_low":
        gaps = f.proposal.get("buchi") or []
        n_ang, n_fmt = len(ev["angoli"]), len(ev["formati"])
        return Task(
            title="Aggiungi creatività con messaggi e formati diversi",
            module="Creatività", level=level, priority=2,
            cosa=(f"Nella campagna «{ev['campagna']}» "
                  f"{'gira' if ev['concept_attivi'] == 1 else 'girano'} "
                  f"{ev['concept_attivi']} concept, "
                  f"con {n_ang} {'messaggio' if n_ang == 1 else 'messaggi'} "
                  f"e {n_fmt} {'formato' if n_fmt == 1 else 'formati'}."),
            perche=("Meta trova persone diverse solo con creatività davvero diverse. Cambiare "
                    "modello d'auto con lo stesso messaggio e lo stesso formato raggiunge "
                    "sempre lo stesso tipo di persone."),
            come=([f"Aggiungi: {g}" for g in gaps]
                  + ["Caricale nella stessa campagna, senza creare nuovi ad set"]),
            non_fare=("Non creare 10 varianti dello stesso visual cambiando solo colore o "
                      "modello: per Meta sono la stessa creatività."),
            button="Fatto")
    if f.issue_code == "concept_concentration":
        return Task(
            title=f"Quasi tutta la spesa va su «{f.object_id}»",
            module="Creatività", level=level, priority=3,
            cosa=f"Negli ultimi 7 giorni il {ev['quota_pct']:.0f}% della spesa è andato lì.",
            perche="Se quel concept si stanca, la campagna non ha alternative pronte.",
            come=["Affianca almeno due concept con un messaggio diverso"],
            non_fare="Non spegnere il concept che funziona.", button="Fatto")
    if f.issue_code == "no_active_concepts":
        return Task(
            title=f"La campagna «{ev['campagna']}» non ha creatività attive",
            module="Creatività", level="puoi_farlo", priority=1,
            cosa="Negli ultimi 7 giorni nessuna creatività ha speso.",
            perche="Una campagna senza creatività attive non porta lead.",
            come=["Controlla se è stata messa in pausa di proposito", "Se no, parlane col senior"],
            non_fare="Non riattivare vecchie creatività senza controllare perché erano ferme.",
            button="Fatto")
    return None


def _missing(checks: list[Check], findings: list[Finding]) -> list[Missing]:
    out: list[Missing] = []
    if any(c.name in ("Qualità dei lead", "Riconciliazione con CRM") for c in checks):
        out.append(Missing(
            "Carica l'export CRM",
            "Senza sapere quanti lead diventano clienti, il tool non può dire se l'account "
            "rende: vede solo se il tracciamento regge.", "crm"))
    track = [TRACKING_PAGE_FIELDS[c.name] for c in checks if c.name in TRACKING_PAGE_FIELDS]
    if track:
        out.append(Missing("Completa lo stato del tracciamento",
                           "Sono informazioni che dalle piattaforme non si leggono: le sa il "
                           "team analytics.", "tracciamento", track))
    if any(f.issue_code == "diversity_map" and f.evidence.get("concept_da_confermare")
           for f in findings):
        out.append(Missing("Conferma i concept creativi",
                           "Il tool ha raggruppato gli annunci leggendo i nomi: serve la tua "
                           "conferma per giudicare la diversità.", "concetti"))
    return out
