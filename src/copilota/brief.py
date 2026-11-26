"""Brief dell'advertiser → controllo → pipeline.

L'advertiser scrive cosa vorrebbe fare (data/<cliente>/briefs/<id>.yaml). Il Copilota lo
confronta con la scheda cliente, le regole di lavoro e lo stato degli account, e per ogni
richiesta dice: si fa così / si fa ma diversamente / non ora / sconsigliata, con il perché.
Poi propone la pipeline: passi in ordine, ognuno con chi lo esegue (Claude, Advertiser,
Specialist, Senior), chi decide, da cosa dipende, da quando si può fare e quando si verifica.
La pipeline si scrive nel registro solo quando qualcuno la conferma.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import yaml

from copilota import register
from copilota.campaigns import campaign_quality, read_kpis
from copilota.config import load_thresholds
from copilota.data import DataSource, Row
from copilota.rules import is_brand, line_of, proposals
from copilota.signals import Status, check_account

ESITO = {  # esito -> (etichetta, gravità per la grafica)
    "ok": ("Si fa così", "ok"),
    "modificata": ("Si fa, ma diversamente", "attenzione"),
    "non_ora": ("Non ora", "critico"),
    "sconsigliata": ("Sconsigliata", "critico"),
    "attenzione": ("Da sapere prima di partire", "attenzione"),
}


@dataclass
class Outcome:
    esito: str
    titolo: str
    motivi: list[str]
    proposta: str = ""
    req: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return ESITO[self.esito][0]

    @property
    def sev(self) -> str:
        return ESITO[self.esito][1]


def _safe(source: DataSource, table: str) -> list[Row]:
    try:
        return source.read(table)
    except FileNotFoundError:
        return []


def _eur(v: float | None) -> str:
    return "—" if v is None else f"{v:,.0f} €".replace(",", ".")


def load(folder: Path) -> list[dict]:
    d = Path(folder) / "briefs"
    if not d.exists():
        return []
    return [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.yaml"))]


class _Ctx:
    """Lo stato del cliente che serve per controllare un brief."""

    def __init__(self, source: DataSource, today: date):
        self.today = today
        self.accounts = source.read("accounts")
        self.by_platform = {a["platform"]: a for a in self.accounts}
        self.th = load_thresholds(self.accounts[0]["client"])
        self.snap = _safe(source, "campaign_snapshot")
        self.kpis = read_kpis(source)
        self.log = _safe(source, "change_log")
        self.blocks = register.dont_touch(self.log, today)
        self.learning = [s for s in _safe(source, "object_status") if s["learning"]]
        self.checks = {a["account_id"]: check_account(source, a, self.th) for a in self.accounts}
        self.quality: dict[str, Row] = {}
        for a in self.accounts:
            q = campaign_quality(source, a)
            for r in (q or {}).get("rows", []):
                self.quality[r["campaign_id"]] = {**r, "platform": a["platform"]}

    def block_of(self, campaign_id: str, pipeline: str = "") -> Row | None:
        return next((b for b in self.blocks if campaign_id in b["campaign_id"].split("|")
                     and b.get("pipeline") != pipeline), None)

    def same_kind(self, platform: str, line: str, ctype: str) -> list[Row]:
        """Campagne attive della stessa piattaforma, linea e tipo (niente brand)."""
        return [s for s in self.snap if s["platform"] == platform and s["campaign_type"] == ctype
                and line_of(s["campaign_name"]) == line and not is_brand(s["campaign_name"])
                and s["spend"] > 0]

    def snap_by_name(self, name: str) -> Row | None:
        return next((s for s in self.snap if s["campaign_name"].strip() == name.strip()), None)

    def q(self, campaign_id: str) -> Row | None:
        r = self.quality.get(campaign_id)
        return r if r and r["leads"] >= self.th["campagne"]["lead_min"] else None


class _Steps:
    """Costruisce i passi della pipeline come voci del registro."""

    def __init__(self, brief: dict, ctx: _Ctx):
        self.brief, self.ctx, self.items = brief, ctx, []

    def add(self, key: str, *, title: str, why: str, executor: str, decides: str,
            kind: str = "modifica", platform: str = "", campaigns: list[Row] | None = None,
            expected: str = "", depends: list[str] | None = None, start: date | None = None,
            check_after_days: int | None = None, until: date | None = None,
            prepared: bool = False) -> str:
        campaigns = campaigns or []
        acc = self.ctx.by_platform.get(platform, self.ctx.accounts[0])
        n = len(self.items) + 1
        sid = f"{self.brief['id']}-{n:02d}"
        self.items.append({
            "key": key, "id": sid, "created": self.ctx.today, "account_id": acc["account_id"],
            "platform": platform or acc["platform"],
            "campaign_id": "|".join(c["campaign_id"] for c in campaigns),
            "campaign_name": " + ".join(c["campaign_name"].split("|")[-1].strip()
                                        for c in campaigns) or "Tutta la promo",
            "kind": kind, "title": title, "why": why, "expected": expected,
            "decides": decides, "status": "applicata" if prepared else "proposta",
            "decided": self.ctx.today if prepared else None,
            "applied": self.ctx.today if prepared else None,
            "check_after_days": check_after_days, "until": until,
            "baseline": ("[" + ",".join(register.baseline_from_snapshot(c) for c in campaigns
                                        if "date_from" in c) + "]") if campaigns else "",
            "result": "", "note": "Preparato da Claude: vedi i materiali nel brief." if prepared
            else "", "pipeline": self.brief["id"], "step": n,
            "depends": "|".join(self.id_of(d) for d in depends or [] if self.id_of(d)),
            "executor": executor, "start": start,
        })
        return key

    def id_of(self, key: str) -> str:
        return next((s["id"] for s in self.items if s["key"] == key), "")


def check(source: DataSource, brief: dict, today: date) -> dict:
    ctx = _Ctx(source, today)
    steps = _Steps(brief, ctx)
    line = brief["linea"]
    start = date.fromisoformat(str(brief["periodo"]["dal"]))
    end = date.fromisoformat(str(brief["periodo"]["al"]))
    platforms = sorted({r["piattaforma"] for r in brief.get("richieste", [])})
    prereq: list[Outcome] = []
    mat = brief.get("materiali_claude") or {}

    # ---------- Prima di partire ----------
    missing = [p for p in platforms if (p, line) not in ctx.kpis]
    if missing:
        prereq.append(Outcome("attenzione", f"Mancano i KPI {line} dello specialist",
                              ["Senza KPI a fine promo non si può dire se è andata bene: "
                               "si vedrebbero solo i lead, non quanto costano quelli buoni."],
                              "Primo passo: lo specialist fissa costo per lead in trattativa e "
                              "per contratto."))
        steps.add("kpi", title=f"Fissa i KPI {line} per "
                  f"{' e '.join({'google': 'Google', 'meta': 'Meta'}[m] for m in missing)}",
                  why="Servono per giudicare la promo e le campagne a fine periodo.",
                  executor="Specialist", decides="Specialist", kind="decisione",
                  platform=missing[0])
    for a in ctx.accounts:
        if a["platform"] not in platforms:
            continue
        for c in ctx.checks[a["account_id"]]:
            if c.status is Status.RED and c.blocking:
                prereq.append(Outcome("non_ora", f"{a['name']} è bloccato", [c.detail],
                                      "Finché il ticket non è chiuso, niente promo qui."))
            elif c.status is Status.RED and c.name == "Conversione di ottimizzazione":
                prereq.append(Outcome(
                    "attenzione", f"{a['name']}: la piattaforma non sa quali lead sono buoni",
                    [c.detail, "Durante la promo il volume sale: senza questo segnale "
                     "l'algoritmo cerca più lead qualsiasi, non più clienti."],
                    "Il ticket è già in «Da fare»: va mandato oggi, la promo non lo aspetta."))
    days = (start - today).days
    prereq.append(Outcome(
        "attenzione", f"Mancano {days} giorni all'inizio",
        [f"La promo va dal {start:%d/%m} al {end:%d/%m} ({(end - start).days + 1} giorni). "
         "Una campagna nuova impara in circa 7 giorni: metà promo passerebbe a imparare.",
         "I materiali del cliente arrivano il 25/11: i testi si preparano prima, con i "
         "segnaposto."],
        "Si lavora sulle campagne che hanno già i dati."))

    prep_google = steps.add(
        "prep_google", title=(mat.get("google") or {}).get("titolo", "Testi Black Friday per "
                                                                    "Google"),
        why="Testi pronti prima dell'offerta, con i segnaposto da completare.",
        executor="Claude", decides="Advertiser", kind="preparazione", platform="google",
        prepared=bool(mat.get("google"))) if "google" in platforms else None
    prep_meta = steps.add(
        "prep_meta", title=(mat.get("meta") or {}).get("titolo", "Brief creativo per Meta"),
        why="Tre messaggi e due formati, da passare a chi fa le creatività.",
        executor="Claude", decides="Advertiser", kind="preparazione", platform="meta",
        prepared=bool(mat.get("meta"))) if "meta" in platforms else None

    # ---------- Le richieste ----------
    results: list[Outcome] = []
    step_pct = ctx.th["selezione"]["passo_budget_pct"]
    lost_min = ctx.th["selezione"]["quota_persa_budget_min_pct"]
    promo_campaigns: list[Row] = []
    budget_mod = None
    for r in brief.get("richieste", []):
        p = r["piattaforma"]
        if r["tipo"] == "nuova_campagna" and p == "google":
            same = sorted(ctx.same_kind("google", line, r["campagna_tipo"]),
                          key=lambda s: -s["spend"])
            if not same:
                results.append(Outcome("ok", r["cosa"], ["Non c'è una campagna simile."],
                                       req=r))
                continue
            host = next((s for s in same if "promo" in s["campaign_name"].lower()), same[0])
            block = ctx.block_of(host["campaign_id"], brief["id"])
            why = [f"Ci sono già {len(same)} PMax {line} attive: "
                   + ", ".join(f"«{s['campaign_name'].split('|')[-1]}»" for s in same)
                   + ". Una terza si dividerebbe gli stessi dati e le stesse ricerche "
                   "(regola: consolidare, non frazionare).",
                   "Una PMax nuova impara per circa 7 giorni: con 12 giorni di promo, "
                   "metà se ne va così."]
            hname = host["campaign_name"].split("|")[-1]
            proposta = f"Un asset group «Black Friday» dentro «{hname}», che ha già i dati."
            if block:
                why.append(f"Ma «{host['campaign_name'].split('|')[-1]}» è da non toccare fino "
                           f"al {block['until']:%d/%m}: {block['why']}")
                proposta += " Durante il blocco serve l'ok del senior; se dice no, su Google la "\
                            "promo passa dalla Search Pronta consegna."
                d = steps.add("pmax_ok", title=f"Eccezione al blocco: asset group Black Friday "
                              f"in «{host['campaign_name'].split('|')[-1]}»?",
                              why=why[-1] + " Un asset group nuovo è una modifica.",
                              expected="Sì: l'offerta entra nella PMax che ha già i dati. No: "
                              "si resta sulla Search.",
                              executor="Senior", decides="Senior", kind="decisione",
                              platform="google", campaigns=[host])
                deps = [d, prep_google]
            else:
                deps = [prep_google]
            steps.add("pmax_ag", title=f"Aggiungi l'asset group Black Friday in "
                      f"«{host['campaign_name'].split('|')[-1]}»",
                      why="Testi e immagini dal passo di Claude, offerta dal cliente.",
                      expected="Più impressioni sulle ricerche di offerta, nella campagna che "
                      "ha già i dati.", executor="Advertiser", decides="Advertiser",
                      platform="google", campaigns=[host], depends=deps, start=start,
                      check_after_days=7)
            promo_campaigns.append(host)
            results.append(Outcome("modificata", r["cosa"], why, proposta, r))

        elif r["tipo"] == "budget_su":
            s = ctx.snap_by_name(r["campagna"])
            if s is None:
                results.append(Outcome("non_ora", r["cosa"], ["Campagna non trovata nella "
                                       "fotografia."], req=r))
                continue
            name = s["campaign_name"].split("|")[-1]
            cur, asked = s["budget_daily"] or 0, r["euro_al_giorno"]
            step_eur = round(cur * step_pct / 100)
            q = ctx.q(s["campaign_id"])
            why = [f"Oggi {_eur(cur)} al giorno; perde il {s['lost_is_budget_pct']:.0f}% delle "
                   "impressioni per budget" + (" (sopra la soglia: c'è spazio)."
                                               if (s["lost_is_budget_pct"] or 0) >= lost_min
                                               else ".")]
            if q:
                why.append(f"Dal CRM costa {_eur(q['cost_per_qualified'])} per lead in "
                           f"trattativa: tra le migliori dell'account.")
            if asked > step_eur:
                why.append(f"+{_eur(asked)} al giorno è +{asked / cur * 100:.0f}%: la regola "
                           f"è al massimo +{step_pct}% per volta, poi si guarda il risultato.")
            why.append("Il budget lo decide lo specialist.")
            dec = steps.add(
                "budget", title=f"Budget Black Friday: «{name}» da {_eur(cur)} a "
                f"{_eur(cur + step_eur)} al giorno (+{step_pct}%)",
                why=" ".join(why), expected=f"Circa +{step_pct}% di conversioni se il costo "
                "resta uguale. Il resto del budget extra si decide dopo i primi giorni.",
                executor="Specialist", decides="Specialist", kind="decisione",
                platform=p, campaigns=[s])
            budget_mod = steps.add(
                "budget_set", title=f"Porta «{name}» a {_eur(cur + step_eur)} al giorno",
                why="Decisione dello specialist.", executor="Advertiser",
                decides="Advertiser", platform=p, campaigns=[s], depends=[dec], start=start,
                check_after_days=4)
            if prep_google:
                steps.add("promo_ext", title=f"Aggiungi l'estensione promozione Black Friday a "
                          f"«{name}»", why="Testo dal passo di Claude; date 26/11–7/12.",
                          executor="Advertiser", decides="Advertiser", platform=p,
                          campaigns=[s], depends=[prep_google], start=start)
            steps.add("budget_check", title=f"Primi giorni di «{name}»: secondo passo di "
                      f"budget?", why=f"Se il costo per conversione regge, altro "
                      f"+{step_pct}% ({_eur(cur + 2 * step_eur)} al giorno); se sale, si resta.",
                      executor="Specialist", decides="Specialist", kind="verifica",
                      platform=p, campaigns=[s], depends=[budget_mod],
                      start=start + timedelta(days=4))
            promo_campaigns.append(s)
            results.append(Outcome(
                "modificata" if asked > step_eur else "ok", r["cosa"], why,
                f"+{step_pct}% dal {start:%d/%m} ({_eur(cur)} → {_eur(cur + step_eur)}), "
                "poi si decide sul risultato.", r))

        elif r["tipo"] == "nuova_campagna" and p == "meta":
            leads = [s for s in ctx.snap if s["platform"] == "meta"
                     and s["campaign_type"] == r["campagna_tipo"]
                     and line_of(s["campaign_name"]) == line and s["spend"] > 0]
            judged = sorted((s for s in leads if ctx.q(s["campaign_id"])),
                            key=lambda s: ctx.q(s["campaign_id"])["cost_per_qualified"])
            best = judged[0] if judged else (leads[0] if leads else None)
            if best is None:
                results.append(Outcome("ok", r["cosa"], ["Non c'è una campagna lead simile."],
                                       req=r))
                continue
            why = [f"Ci sono già {len(leads)} campagne lead {line}: una nuova parte da zero e "
                   "impara per circa 7 giorni, metà promo."]
            for s in judged:
                qq = ctx.q(s["campaign_id"])
                why.append(f"«{s['campaign_name'].split('|')[-1].strip()}»: "
                           f"{_eur(qq['cost_per_qualified'])} per lead in trattativa.")
            learning = [x for x in ctx.learning if any(
                x["campaign_id"] == s["campaign_id"] for s in leads)]
            if learning:
                why.append("Ad set in apprendimento, da non toccare: "
                           + ", ".join(f"«{x['object_name']}»" for x in learning) + ".")
            why.append("Dove mettere il budget extra lo decide lo specialist.")
            bname = best["campaign_name"].split("|")[-1].strip()
            steps.add("meta_ads", title=f"Carica le creatività Black Friday in «{bname}»",
                      why="Nella campagna lead che rende di più, senza aprirne una nuova.",
                      expected="Lead dalla promo da subito, senza ripartire da zero.",
                      executor="Advertiser", decides="Advertiser", platform="meta",
                      campaigns=[best], depends=[prep_meta] if prep_meta else [],
                      start=start, check_after_days=7)
            extra = _eur(brief["budget_extra"]["meta"])
            steps.add("meta_budget", title=f"Budget Meta della promo ({extra}): quanto e su "
                      "quale campagna",
                      why=" ".join(why[1:]), executor="Specialist", decides="Specialist",
                      kind="decisione", platform="meta", campaigns=judged or [best])
            promo_campaigns.append(best)
            results.append(Outcome("modificata", r["cosa"], why,
                                   f"Niente campagna nuova: creatività Black Friday in «{bname}»"
                                   ", con tre messaggi e due formati.", r))

        elif r["tipo"] == "riattiva":
            rule = proposals()["riattiva_oggetto"]
            lead = next((s for s in ctx.snap if s["platform"] == p
                         and s["campaign_name"].strip().endswith("| LEAD")), None)
            qq = ctx.q(lead["campaign_id"]) if lead else None
            why = [f"Riattivare lo decide il senior ({rule['perche'].rstrip('.')})."]
            if qq:
                why.append(f"Portava volume, ma la sua campagna «LEAD» costa "
                           f"{_eur(qq['cost_per_qualified'])} per lead in trattativa: "
                           f"{rule['se_qualita_bassa'].rstrip('.')}.")
            why.append("Per la promo il volume arriva meglio dalle creatività nuove nella "
                       "campagna che rende di più.")
            steps.add("reactivate", title=f"Riattivare «{r['oggetto']}»? Il Copilota consiglia "
                      "di no", why=" ".join(why), executor="Senior", decides="Senior",
                      kind="decisione", platform=p, campaigns=[lead] if lead else [])
            results.append(Outcome("sconsigliata", r["cosa"], why,
                                   "Decide il senior. Consiglio: lasciarlo spento.", r))

    # ---------- Durante e dopo ----------
    if promo_campaigns:
        steps.add("freeze", title="Durante la promo: niente cambi di struttura, target o "
                  "offerte", why="Ogni modifica a metà promo rende illeggibile il risultato.",
                  executor="", decides="Regola", kind="da_non_toccare",
                  campaigns=promo_campaigns, start=start, until=end)
    if budget_mod:
        steps.add("budget_back", title="Fine promo: budget di partenza e via l'estensione "
                  "promozione", why="La promo finisce il " + f"{end:%d/%m}.",
                  executor="Advertiser", decides="Advertiser", platform="google",
                  campaigns=[ctx.snap_by_name(r["campagna"]) for r in brief["richieste"]
                             if r["tipo"] == "budget_su"],
                  depends=[budget_mod], start=end + timedelta(days=1))
    mature = end + timedelta(days=ctx.th["segnali"]["qualita_giorni_maturazione"])
    steps.add("result", title="Risultato della promo dal CRM: lead in trattativa e contratti",
              why=f"I lead dal {start:%d/%m} al {end:%d/%m} hanno bisogno di "
              f"{ctx.th['segnali']['qualita_giorni_maturazione']} giorni per essere lavorati.",
              expected="Costo per lead in trattativa e per contratto contro i KPI.",
              executor="Specialist", decides="Specialist", kind="verifica",
              depends=[k for k in ("kpi",) if steps.id_of(k)], start=mature)

    counts = {k: sum(o.esito == k for o in results) for k in ESITO}
    parts = [(counts["ok"], "si fa così", "si fanno così"),
             (counts["modificata"], "si fa diversamente", "si fanno diversamente"),
             (counts["non_ora"], "non ora", "non ora"),
             (counts["sconsigliata"], "è sconsigliata", "sono sconsigliate")]
    summary = (f"{len(results)} richieste: "
               + ", ".join(f"{n} {one if n == 1 else many}" for n, one, many in parts if n)
               + ".")
    for s in steps.items:
        s.pop("key")
    return {"prereq": prereq, "results": results, "steps": steps.items, "summary": summary,
            "start": start, "end": end}


def create_pipeline(folder: Path, steps: list[Row]) -> int:
    """Scrive i passi nel registro. Se la pipeline c'è già, non fa niente."""
    log = register.read(folder)
    ids = {e["id"] for e in log}
    new = [s for s in steps if s["id"] not in ids]
    if new:
        from copilota.data import write_table
        write_table(folder, "change_log", log + new)
    return len(new)
