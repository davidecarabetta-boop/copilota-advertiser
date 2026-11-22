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
from copilota.signals import UNKNOWN, Check, Status

LEVEL_LABEL = {"puoi_farlo": "Puoi farlo", "serve_senior": "Serve il senior",
               "vietato": "Vietato"}


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

    @property
    def level_label(self) -> str:
        return LEVEL_LABEL.get(self.level, self.level)


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
    return Task(
        title=title, module="Segnali", level="puoi_farlo", priority=priority,
        cosa=c.detail, perche=perche,
        come=["Copia il testo qui sotto e mandalo al team analytics",
              "Intanto continua con le altre attività: questo non blocca l'account"],
        non_fare="Non provare a compensare cambiando budget o offerte: il problema è nei dati.",
        button="Copia il testo del ticket", ticket=_ticket(account, [c], [], blocking=False))


def _cause_task(c: Check, account: dict, camp: dict | None = None) -> Task:
    cause, d = c.data["cause"], c.data
    kind = "ad set" if cause["object_type"] == "adset" else "campagna"
    link = None
    if account["platform"] == "meta":
        link = (f"Apri «{cause['object_name']}» in Gestione inserzioni",
                ads_manager_link(account["account_id"], cause["object_type"], cause["object_id"]))
    poor = next((p for p in (camp or {}).get("poor", [])
                 if p["campaign_id"] == cause.get("campaign_id")), None)
    if cause["kind"] == "pausa" and cause["still_off"] and poor:
        # la pausa ha fatto crollare i lead, ma quei lead rendevano poco: si decide col senior
        best, avg = camp.get("best"), camp.get("avg")
        alt = (f" Il retargeting «{best['name']}» costava {best['cost_per_qualified']:.0f} € per "
               "lead in trattativa." if best and best["campaign_id"] != poor["campaign_id"]
               else "")
        return Task(
            title=(f"Prima di riattivare «{cause['object_name']}» decidi col senior: i suoi lead "
                   "rendevano poco"),
            module="Valore", level="serve_senior", priority=1,
            cosa=(f"Il {cause['date']:%d/%m} l'{kind} «{cause['object_name']}» è stato messo in "
                  f"pausa e i lead sono passati da {d['before']:.0f} a {d['recent']:.1f} al "
                  "giorno. "
                  f"Ma secondo il CRM la sua campagna costava {_eur(poor['cost_per_qualified'])} "
                  f"per lead arrivato in trattativa, contro {_eur(avg)} della media dell'account, "
                  f"con {poor['contracts']} contratti su {poor['leads']} lead."
                  + alt),
            perche=("Riattivarlo riporta tanti lead, ma pochi diventano clienti. Lasciarlo "
                    "spento senza alternative però ferma la campagna. Serve una scelta."),
            come=["Mostra questa scheda al senior",
                  "Opzione A: riattivarlo com'era per non restare senza lead, mentre si prepara "
                  "un'alternativa",
                  "Opzione B: spostare quel budget su ciò che porta lead buoni (vedi l'attività "
                  "sul budget)"],
            non_fare="Non riattivarlo da solo senza aver deciso col senior.",
            button="Chiedi l'ok al senior", link=link)
    if cause["kind"] == "pausa" and cause["still_off"]:
        return Task(
            title=f"Riattiva l'{kind} «{cause['object_name']}»",
            module="Vincoli", level=_level("pausa_riattivazione"), priority=1,
            cosa=(f"Il {cause['date']:%d/%m} l'{kind} «{cause['object_name']}» è stato messo in "
                  f"pausa. Portava il {cause['share_pct']}% dei lead (circa {cause['per_day']:.0f} "
                  f"al giorno). Da allora i lead sono passati da {d['before']:.0f} a "
                  f"{d['recent']:.1f} al giorno e la spesa da {d['cost_before']} € a "
                  f"{d['cost_recent']} € al giorno."),
            perche=("Senza quell'ad set alla campagna è rimasto solo quello che non funziona: "
                    "Meta non trova a chi mostrarlo e smette di spendere. Il tracciamento è a "
                    "posto, il problema è la pausa."),
            come=["Apri l'ad set con il link qui sotto",
                  "Riattivalo così com'era: stesso budget, pubblico e annunci",
                  f"Tra 3 giorni controlla che i lead tornino verso i {cause['per_day']:.0f} al "
                  "giorno"],
            non_fare=("Non modificarlo mentre lo riattivi: ogni modifica fa ripartire "
                      "l'apprendimento. Se la pausa faceva parte di un test voluto, parlane "
                      "prima con il senior."),
            button="Fatto", link=link)
    return Task(
        title=f"Controlla la modifica a «{cause['object_name']}»: i lead sono crollati",
        module="Vincoli", level="serve_senior", priority=1,
        cosa=c.detail,
        perche="La modifica coincide con il crollo dei lead.",
        come=["Mostra questa scheda al senior", "Decidete se tornare alla situazione di prima"],
        non_fare="Non fare altre modifiche alla campagna finché non avete deciso.",
        button="Fatto", link=link)


def _eur(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f} €".replace(",", ".")


def _campaign_tasks(camp: dict, account: dict) -> list[Task]:
    """Attività dalla qualità per campagna (export CRM per UTM campaign)."""
    tasks = []
    best, avg = camp.get("best"), camp.get("avg")
    for p in camp.get("poor", []):
        cpq = p["cost_per_qualified"]
        cosa = (f"Dal {camp['from']:%d/%m} al {camp['to']:%d/%m} «{p['name']}» ha speso "
                f"{_eur(p['spend'])} ({p['share_pct']}% della spesa) per {p['leads']} lead nel "
                f"CRM: {p['qualified']} arrivati in trattativa e {p['contracts']} contratti. "
                f"Ogni lead in trattativa è costato {_eur(cpq)}, contro {_eur(avg)} di media.")
        if best and best["campaign_id"] != p["campaign_id"]:
            cosa += (f" «{best['name']}» nello stesso periodo: {_eur(best['cost_per_qualified'])} "
                     "per lead in trattativa.")
            title = f"Sposta budget da «{p['name']}» a «{best['name']}»"
            come = [f"Abbassa il budget di «{p['name']}» del 20%",
                    f"Aggiungi lo stesso importo a «{best['name']}»",
                    "Dopo 2 settimane controlla nel CRM che i lead in trattativa salgano"]
            if "rmk" in best["name"].lower() or "retarget" in best["name"].lower():
                come.append("È un retargeting: parla a chi conosce già il cliente e non cresce "
                            "all'infinito. Se il suo costo per lead sale molto, fermati lì")
        else:
            title = f"«{p['name']}» spende molto per pochi lead buoni"
            come = ["Mostra questa scheda al senior",
                    "Decidete se ridurre il budget o cambiare pubblico e creatività"]
        tasks.append(Task(
            title=title, module="Valore", level="serve_senior", priority=2, cosa=cosa,
            perche=("La piattaforma la giudica bene perché porta tanti lead, ma il CRM dice che "
                    "pochi diventano trattative: quel budget rende di più altrove."),
            come=come,
            non_fare=("Non spegnerla di colpo e non spostare più del 20% alla volta: le "
                      "campagne devono riadattarsi."),
            button="Chiedi l'ok al senior"))
    for utm, n in camp.get("utm_lost", []):
        check = Check(account["account_id"], "Tracking", "UTM non abbinati", Status.YELLOW,
                      f"Nel CRM ci sono {n} lead con utm_campaign «{utm}», che non corrisponde "
                      "a nessuna campagna attiva nel periodo: non si sa quanto rende.")
        tasks.append(_analytics_task(
            check, f"Fai correggere l'UTM «{utm}»: {n} lead senza campagna",
            "Se l'UTM non corrisponde al nome della campagna, il Copilota non può dire se "
            "quella spesa porta clienti.", account, priority=3))
    return tasks


def build_plan(account: dict, checks: list[Check], findings: list[Finding],
               camp: dict | None = None) -> Plan:
    missing_checks = [c for c in checks if c.status is not Status.GREEN and _is_missing(c)]
    reds = [c for c in checks if c.status is Status.RED and not _is_missing(c)
            and c.blocking]
    open_reds = [c for c in checks if c.status is Status.RED and not _is_missing(c)
                 and not c.blocking]
    yellows = [c for c in checks if c.status is Status.YELLOW and not _is_missing(c)]
    missing = _missing(missing_checks, findings)

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

    tasks: list[Task] = []
    for c in open_reds:
        tasks.extend(_from_red(c, account, camp))
    for c in yellows:
        tasks.extend(_from_check(c, account))
    for f in findings:
        t = _from_finding(f)
        if t:
            tasks.append(t)
    if camp:
        tasks.extend(_campaign_tasks(camp, account))
    tasks.sort(key=lambda t: t.priority)
    headline = (f"{len(tasks)} {'cosa' if len(tasks) == 1 else 'cose'} da fare oggi."
                if tasks else "Niente da fare oggi: l'account è a posto.")
    return Plan(False, headline, tasks, missing, [])


def _line(campaign_name: str) -> str:
    """Linea di business dal naming <paese>|<funnel>|<LINEA>|... (es. AUTO_B2C, RENT_NLT)."""
    parts = [p.strip() for p in campaign_name.split("|")]
    return parts[2].replace(" I ", "_") if len(parts) > 2 and parts[2] else "altro"


def _from_red(c: Check, account: dict, camp: dict | None = None) -> list[Task]:
    """Rossi che non bloccano l'account: diventano attività ad alta priorità."""
    if c.name == "Andamento conversioni":
        if c.data.get("cause"):
            return [_cause_task(c, account, camp)]
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
    return _from_check(c, account)


def _from_check(c: Check, account: dict) -> list[Task]:
    if c.data.get("attribution"):
        return []  # scarto di attribuzione col CRM: informazione, non un'attività
    if c.name == "Conversioni non-lead":
        return [Task(
            title="Togli dalle conversioni principali quelle che non sono lead",
            module="Segnali", level=_level("strategia_obiettivo_valore"), priority=2,
            cosa=c.detail,
            perche=("La piattaforma cerca più persone come quelle che 'convertono'. Se conta "
                    "come conversione un'iscrizione a YouTube, porta iscritti, non clienti."),
            come=["Chiedi l'ok al senior", "In Google Ads: Obiettivi › Conversioni › imposta "
                  "come secondarie le azioni indicate", "Controlla dopo 2 settimane il costo "
                  "per lead vero"],
            non_fare="Non eliminare le azioni di conversione: rendile secondarie.",
            button="Chiedi l'ok al senior")]
    if c.name == "Conversioni per campagna":
        camps = c.data.get("campaigns", [])
        groups: dict[str, list[dict]] = {}
        for x in camps:
            groups.setdefault(_line(x["name"]), []).append(x)
        steps = []
        for line, xs in groups.items():
            names = " + ".join(f"«{x['name']}» ({x['conversions']})" for x in xs)
            steps.append(f"Linea {line}: unisci {names}" if len(xs) > 1 else
                         f"Linea {line}: {names} da sola non basta, uniscila alla campagna "
                         "principale della stessa linea")
        return [Task(
            title=(f"Accorpa {len(camps)} campagne che fanno troppe poche conversioni"
                   if camps else "Accorpa le campagne che fanno troppe poche conversioni"),
            module="Vincoli", level=_level("struttura_campagne"), priority=2,
            cosa=(f"{len(camps)} campagne fanno meno di 30 conversioni al mese: tra parentesi "
                  "quante ne hanno fatte negli ultimi 30 giorni." if camps else c.detail),
            perche=("Sotto una certa soglia l'algoritmo non ha abbastanza esempi per imparare: "
                    "offerte instabili e costi più alti. Insieme imparano di più."),
            come=steps + ["Mostra questa scheda al senior; se è d'accordo prepari la campagna "
                          "accorpata in pausa e lui la attiva"],
            non_fare="Non accorpare le campagne Brand con le altre: restano separate.",
            button="Chiedi l'ok al senior")]
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


def _from_finding(f: Finding) -> Task | None:
    ev, level = f.evidence, _level(f.action_key) if f.action_key else "puoi_farlo"
    if f.issue_code in ("fatigue_late", "fatigue_prepare"):
        late = f.issue_code == "fatigue_late"
        return Task(
            title=(f"Sostituisci la creatività «{f.object_id}»: è stanca" if late
                   else f"Prepara una nuova versione di «{f.object_id}»"),
            module="Creatività", level=level, priority=1 if late else 2,
            cosa=(f"Il tasso di clic è sceso del {ev['calo_ctr_pct']:.0f}% rispetto al suo "
                  f"momento migliore e le stesse persone la vedono sempre più spesso"
                  + (f"; ogni lead costa {ev['cpa_ultimi_7g']:.0f} € contro "
                     f"{ev['cpa_riferimento']:.0f} € di prima." if late and ev.get("cpa_ultimi_7g")
                     and ev.get("cpa_riferimento") else ".")),
            perche=("Quando una creatività stanca, Meta la mostra a un pubblico sempre più "
                    "ristretto e i costi salgono."),
            come=["Prepara una nuova versione dello stesso concept: stesso messaggio, immagine "
                  "e frase d'attacco nuove", "Caricala nello stesso ad set, accanto alla vecchia",
                  "Quando la nuova ha almeno 7 giorni di spesa, metti in pausa la vecchia"],
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
