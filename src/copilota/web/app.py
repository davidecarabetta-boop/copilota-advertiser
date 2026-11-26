"""Copilota Advertiser in locale.

Per ogni account la pagina principale è "Cosa fare oggi": attività pronte nel formato
cosa succede / perché / come fare / non fare. I controlli tecnici stanno nelle schede
Segnali e Creatività. I dati che le piattaforme non danno (export CRM, concept creativi,
stato del tracciamento) si inseriscono a mano.

Sola lettura verso le piattaforme: scrive solo i CSV in data/<cliente>/.
Avvio: .venv/Scripts/python -m uvicorn copilota.web.app:app --host 127.0.0.1 --port 8000
"""

import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from copilota import apply, brief, creative_review, profile, register
from copilota.campaigns import campaign_quality, judge, read_kpis, volume_check
from copilota.config import CONFIG_DIR, load_thresholds
from copilota.creative import analyze_account
from copilota.data import CsvSource, parse_rows, write_table
from copilota.diagnosis import diagnose
from copilota.selection import select
from copilota.signals import META_CONV_OBJECTIVES, check_account, lead_quality, quality_measured
from copilota.tasks import build_plan

DATA_ROOT = Path(__file__).parent.parent.parent.parent / "data"
HERE = Path(__file__).parent

app = FastAPI(title="Copilota Advertiser (locale)")
templates = Jinja2Templates(directory=HERE / "templates")

TRACKING_BOOL = ["enhanced_conversions", "capi_active", "consent_mode_v2", "crm_quality_feedback"]
TRACKING_NUM = ["capi_coverage_pct", "consent_rate_pct", "consent_rate_prev_pct"]
TRACKING_DATE = ["crm_last_upload", "customer_match_updated"]
SEMAFORO_CLASS = {"in ritardo": "bad", "prepara il cambio": "warn", "ok": "ok"}


def data_root() -> Path:
    return app.state.data_root if hasattr(app.state, "data_root") else DATA_ROOT


def clients() -> list[str]:
    return sorted(p.name for p in data_root().iterdir() if (p / "accounts.csv").exists())


def client_dir(slug: str) -> Path:
    if slug not in clients():  # anche protezione da percorsi arbitrari
        raise HTTPException(404, "Cliente non trovato")
    return data_root() / slug


def client_label(slug: str) -> str:
    return "Dati di prova" if slug == "sample" else slug.upper()


def target_cpa(client: str) -> float | None:
    f = CONFIG_DIR / "clienti" / f"{client.lower()}.yaml"
    if not f.exists():
        return None
    return ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("target") or {}).get("cpa")


def _safe(source, table: str) -> list:
    try:
        return source.read(table)
    except FileNotFoundError:
        return []


def last_date(source) -> date | None:
    dates = [r["date"] for t in ("ga_campaign_daily", "meta_ad_daily") for r in _safe(source, t)]
    return max(dates, default=None)


class AsOfSource:
    """Vista dei dati come se oggi fosse `as_of`: scarta le righe giornaliere successive."""

    def __init__(self, source: CsvSource, as_of: date):
        self.source, self.as_of = source, as_of

    def read(self, table: str) -> list:
        return [r for r in self.source.read(table) if r.get("date", self.as_of) <= self.as_of]


def kpis(source, account: dict, today: date | None) -> dict:
    """Spesa, lead e costo per lead degli ultimi 30 giorni, più la qualità se misurata."""
    google = account["platform"] == "google"
    table, cost, conv = (("ga_campaign_daily", "cost", "conversions") if google
                         else ("meta_ad_daily", "spend", "leads"))
    rows = [r for r in _safe(source, table) if r["account_id"] == account["account_id"]]
    if not rows:
        return {}
    today = today or max(r["date"] for r in rows)
    rows = [r for r in rows if today - timedelta(days=29) <= r["date"] <= today]
    spend, leads = sum(r[cost] for r in rows), sum(r[conv] for r in rows)
    lq = lead_quality(source, account, today, load_thresholds(account["client"]))
    return {"spend": spend, "leads": leads, "cpl": spend / leads if leads else None,
            "quality": lq["recent"] if lq else None}


def evaluate(source, account: dict, as_of: date | None) -> dict:
    th = load_thresholds(account["client"])
    checks = check_account(source, account, th)
    findings = (analyze_account(source, account, th, as_of, target_cpa(account["client"]))
                if account["platform"] == "meta" else [])
    cq = campaign_quality(source, account)
    kpis = read_kpis(source)
    status = [s for s in _safe(source, "object_status")
              if s["account_id"] == account["account_id"]]
    blocked_ids = {s["campaign_id"] or s["object_id"] for s in status
                   if s["learning"] or s["in_test"]}
    camp = {"blocked_ids": blocked_ids} if status else None
    if cq:
        camp = {**judge(cq, th, kpis, account["platform"], blocked_ids),
                "from": cq["from"], "to": cq["to"], "status_known": bool(status),
                "blocked_ids": blocked_ids if status else None,
                "volume": volume_check(source, account, th, kpis)}
    plan = build_plan(account, checks, findings, camp)
    today = as_of or date.today()
    all_log = _safe(source, "change_log")
    log = [e for e in all_log if e["account_id"] == account["account_id"]]
    sel = select(source, account, th, kpis)
    if sel.get("available"):
        for group in ("below", "scale", "no_target"):
            for c in sel[group]:
                c["diagnosis"] = diagnose(source, c, th, cq, findings)
    return {"checks": checks, "findings": findings, "campaigns": cq, "camp": camp,
            "plan": plan, "quality": quality_measured(source, account), "selection": sel,
            "todo": _todo(plan, status, log, today, all_log)}


WHO = {"decide_specialist": "Specialist", "serve_senior": "Senior"}


def _entry(e: dict, log: list, today: date) -> dict:
    """Voce del registro pronta per la pagina: numeri di partenza, data di verifica, azioni."""
    import json

    try:
        base = json.loads(e["baseline"]) if e["baseline"] else []
    except ValueError:
        base = []
    kind = e["kind"]
    actions = [a for a, (src, _) in register.AZIONI.items() if e["status"] in src]
    if kind == "decisione":
        actions = [a for a in actions if a in ("approva", "scarta")]
    elif kind == "verifica":
        actions = [a for a in actions if a in ("verificata", "scarta")]
    elif kind == "preparazione":
        actions = []  # la prepara Claude
    elif e["decides"] == "Advertiser":  # la fa e decide l'advertiser: niente "approva"
        actions = [a for a in actions if a not in ("approva",)
                   and not (a == "verificata" and e["status"] == "proposta")]
    else:
        actions = [a for a in actions if a != "fatta"
                   and not (a == "verificata" and e["status"] == "proposta")]
    return {**e, "baseline_rows": base if isinstance(base, list) else [base],
            "check": register.check_date(e), "is_due": e in register.due(log, today),
            "label": register.STATO_LABEL.get(e["status"], e["status"]), "actions": actions,
            "done": register.is_done(e)}


def _todo(plan, status: list, log: list, today: date, all_log: list | None = None) -> dict:
    """Tutto quello che c'è da fare sull'account, diviso per chi deve agire.

    - mine: tocca all'advertiser (attività "puoi farlo", passi da eseguire, risultati da
      verificare)
    - decide: aspetta la decisione dello specialist o del senior
    - later: passi che aspettano un altro passo, una data o la fine di un blocco
    - hold: in corso, da non toccare (apprendimento, test, blocchi, modifiche appena fatte)
    - closed: chiusi (verificati, scartati, decisioni prese, materiali preparati)
    """
    all_log = all_log if all_log is not None else log
    entries = [_entry(e, log, today) for e in log]
    # per decidere da quando si può eseguire contano anche i blocchi già decisi che partono
    # più avanti (es. "niente modifiche durante la promo")
    blocks = [b for b in all_log if b["kind"] == "da_non_toccare"
              and b["status"] not in ("scartata", "verificata")
              and (b["until"] is None or b["until"] >= today)]

    def blocked_until(e: dict) -> date | None:
        """Fine del blocco di un'altra voce sulle stesse campagne (non della stessa pipeline)."""
        ids = set(e["campaign_id"].split("|")) - {""}
        dates = [b["until"] for b in blocks if b["id"] != e["id"] and b["until"]
                 and (not e["pipeline"] or b["pipeline"] != e["pipeline"])
                 and ids & set(b["campaign_id"].split("|"))]
        return max(dates) + timedelta(days=1) if dates else None  # "fino al" è compreso

    def who_acts(e: dict) -> str:
        if e["status"] == "approvata" or e["is_due"]:
            return "Tu"
        if e["executor"] == "Claude":
            return "Claude"
        if e["decides"] == "Advertiser":
            return "Tu"
        return e["decides"]

    # un'attività del Copilota sullo stesso oggetto di un passo aperto del registro sparisce:
    # il passo del registro (deciso con più dati, es. da un brief) la sostituisce
    open_titles = " ".join(e["title"] for e in entries
                           if e["status"] in ("proposta", "approvata"))
    tasks = [t for t in plan.tasks if not (
        t.rule == "riattiva_oggetto"
        and any(f"«{n}»" in open_titles for n in re.findall(r"«([^»]+)»", t.title)))]
    mine: list[dict] = [{"task": t} for t in tasks if t.level == "puoi_farlo"]
    decide: dict[str, list] = {"Specialist": [], "Senior": []}
    for t in tasks:
        if t.level in WHO:
            decide[WHO[t.level]].append({"task": t})
    later = []
    for e in entries:
        if e["kind"] == "da_non_toccare" or e["done"] and not e["is_due"]:
            continue
        if not (e["is_due"] or e["status"] in ("proposta", "approvata")):
            continue
        who = who_acts(e)
        e["who"] = who
        e["waits"] = register.blockers(e, all_log)
        # una decisione si può prendere subito; è l'esecuzione che aspetta la fine del blocco
        dates = [d for d in (e["start"] if e["start"] and e["start"] > today else None,
                             blocked_until(e) if e["kind"] == "modifica" and who == "Tu"
                             else None) if d]
        e["after"] = max(dates) if dates else None
        if e["waits"] or e["after"] or who == "Claude":
            later.append(e)
        elif who == "Tu":
            mine.append({"entry": e})
        else:
            decide.setdefault(who, []).append({"entry": e})
    hold = [{"what": d, "why": "", "until": None} for d in plan.dont_touch]
    for s in status:
        if s["learning"] or s["in_test"]:
            hold.append({"what": s["object_name"],
                         "why": "È in un test." if s["in_test"] else "È in apprendimento: "
                         "ogni modifica lo fa ripartire.", "until": s["until"]})
    for e in register.dont_touch(log, today):
        hold.append({"what": e["campaign_name"], "why": e["why"], "until": e["until"]})
    for e in entries:
        if e["status"] == "applicata" and e["kind"] == "modifica" and not e["is_due"]:
            hold.append({"what": e["campaign_name"],
                         "why": f"Modifica appena fatta: «{e['title']}». Si guarda il risultato "
                                "prima di cambiare altro.", "until": e["check"]})
    closed = [e for e in entries if e["status"] in ("verificata", "scartata")
              or (e["done"] and e["kind"] in ("decisione", "preparazione"))]
    n_decide = sum(len(v) for v in decide.values())
    return {"mine": mine, "decide": {k: v for k, v in decide.items() if v}, "hold": hold,
            "later": later, "closed": closed, "count": len(mine) + n_decide,
            "n_mine": len(mine),
            "n_decide": n_decide}


SEV_OF_PRIORITY = {1: "critico", 2: "attenzione", 3: "info"}
PLATFORM_LABEL = {"google": "Google Ads", "meta": "Meta Ads"}
WHO_LABEL = {"Tu": "Tocca a te", "Specialist": "Specialist", "Senior": "Senior",
             "Regola": "Regola"}


def _uid(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", "-".join(parts))


def client_board(slug: str, as_of: date | None = None) -> dict:
    """Tutto il lavoro di un cliente, account per account, come elenco unico.

    Ogni voce ha: gruppo (mine | decide | hold | later), chi agisce, gravità e il contenuto
    per la scheda di dettaglio (attività del Copilota, proposta del registro o blocco).
    """
    source = CsvSource(client_dir(slug))
    view = AsOfSource(source, as_of) if as_of else source
    today = as_of or date.today()
    accounts, items, blocked = [], [], []
    for a in source.read("accounts"):
        ev = evaluate(view, a, as_of)
        plan, todo = ev["plan"], ev["todo"]
        acc = a["account_id"]
        accounts.append({"a": a, "plan": plan, "todo": todo})
        if plan.blocked:
            blocked.append({"a": a, "headline": plan.headline})

        def add(group: str, who: str, kind: str, obj, sev: str, uid: str, sub: str,
                right: str, a=a) -> None:
            items.append({"uid": uid, "group": group, "who": who, "kind": kind, "obj": obj,
                          "sev": sev, "a": a, "sub": sub, "right": right})

        def add_x(x: dict, group: str, who: str, n: int, acc=acc, a=a) -> None:
            if "task" in x:
                t = x["task"]
                add(group, who, "task", t, SEV_OF_PRIORITY.get(t.priority, "info"),
                    _uid("t", acc, group, str(n)), f"{PLATFORM_LABEL[a['platform']]} · "
                    f"{a['name']} · {t.module}", WHO_LABEL.get(who, who))
            else:
                e = x["entry"]
                sev = ("critico" if e["is_due"] else "info" if group == "later"
                       else "attenzione")
                days = (today - e["created"]).days
                waits = e.get("waits") or []
                right = (f"dopo il passo {waits[0]['step']}" if waits and waits[0]["step"]
                         else "dopo un altro passo" if waits else
                         f"dal {e['after']:%d/%m}" if e.get("after") else
                         "lo prepara Claude" if e.get("who") == "Claude" else
                         "da verificare" if e["is_due"] else
                         "oggi" if days == 0 else
                         f"{days} {'giorno' if days == 1 else 'giorni'}")
                sub = f"{PLATFORM_LABEL[a['platform']]} · {e['campaign_name']}"
                e["apply"] = apply.build(e, client_label(slug), a["name"])
                if e["pipeline"]:
                    sub = f"{e['pipeline']} · passo {e['step']} · " + sub
                add(group, who, "entry", e, sev, _uid("r", e["id"]), sub, right)

        if plan.blocked:
            for n, t in enumerate(plan.tasks):
                add_x({"task": t}, "mine", "Tu", n)
        else:
            for n, x in enumerate(todo["mine"]):
                add_x(x, "mine", "Tu", n)
            for who, xs in todo["decide"].items():
                for n, x in enumerate(xs):
                    add_x(x, "decide", who, n)
            for n, e in enumerate(todo["later"]):
                add_x({"entry": e}, "later", e.get("who") or "Tu", n)
        for n, h in enumerate(todo["hold"]):
            add("hold", "", "hold", h, "info", _uid("h", acc, str(n)),
                f"{PLATFORM_LABEL[a['platform']]} · {a['name']}",
                f"fino al {h['until']:%d/%m}" if h["until"] else "in corso")
    sev_rank = {"critico": 0, "attenzione": 1, "info": 2}
    group_rank = {"mine": 0, "decide": 1, "later": 2, "hold": 3}
    order = {a["a"]["account_id"]: i for i, a in enumerate(accounts)}
    items.sort(key=lambda i: (order[i["a"]["account_id"]], group_rank[i["group"]],
                              sev_rank[i["sev"]]))
    open_items = [i for i in items if i["group"] in ("mine", "decide")]
    busy = {i["a"]["account_id"] for i in open_items}
    return {"source": source, "accounts": accounts, "items": items, "blocked": blocked,
            "stats": {"open": len(open_items),
                      "mine": sum(i["group"] == "mine" for i in items),
                      "decide": sum(i["group"] == "decide" for i in items),
                      "hold": sum(i["group"] in ("hold", "later") for i in items),
                      "quiet": len(accounts) - len(busy), "accounts": len(accounts)}}


def _data_dates(source) -> str:
    """Riga di stato: fino a quando arrivano i dati di ogni fonte."""
    parts = []
    for table, label in (("ga_campaign_daily", "Google"), ("meta_ad_daily", "Meta"),
                         ("backend_daily", "CRM")):
        rows = _safe(source, table)
        if rows:
            parts.append(f"{label} al {max(r['date'] for r in rows):%d/%m}")
    return " · ".join(parts)


def nav_context(slug: str | None, board: dict | None = None) -> dict:
    ctx: dict = {"nav_clients": [(s, client_label(s)) for s in clients()]}
    if not slug:
        return ctx
    board = board or client_board(slug)
    ctx.update(nav_count=board["stats"]["open"],
               nav_missing=sum(len(a["plan"].missing) > 0 for a in board["accounts"]) or None,
               nav_has_meta=any(a["a"]["platform"] == "meta" for a in board["accounts"]))
    return ctx


def page(request: Request, template: str, ctx: dict, nav: str | None = None,
         board: dict | None = None):
    slug = ctx.get("slug")
    return templates.TemplateResponse(request, template, {
        **nav_context(slug, board), **ctx, "nav": nav,
    })


@app.get("/")
def home():
    found = clients()
    if not found:
        return HTMLResponse("<p>Nessun cliente in data/.</p>")
    first = next((s for s in found if s != "sample"), found[0])
    return RedirectResponse(f"/c/{first}", status_code=303)


@app.get("/c/{slug}", response_class=HTMLResponse)
def todo_page(request: Request, slug: str, account: str = "", item: str = "",
              al: str | None = None, msg: str | None = None):
    as_of = date.fromisoformat(al) if al else None
    board = client_board(slug, as_of)
    return page(request, "todo.html", {
        "slug": slug, "client": client_label(slug), "board": board, "account": account,
        "item": item, "al": al, "msg": msg, "dates": _data_dates(board["source"]),
        "nav_account": account,
    }, nav="dafare", board=board)


def _account_view(request: Request, slug: str, account: str, view: str,
                  al: str | None, msg: str | None):
    source = CsvSource(client_dir(slug))
    accs = source.read("accounts")
    if view == "creativita":
        accs = [a for a in accs if a["platform"] == "meta"] or accs
    acc = next((a for a in accs if a["account_id"] == account), accs[0])
    as_of = date.fromisoformat(al) if al else None
    view_source = AsOfSource(source, as_of) if as_of else source
    ev = evaluate(view_source, acc, as_of)
    return page(request, "account.html", {
        "slug": slug, "client": client_label(slug), "account": acc, "accounts": accs,
        "tab": view, "al": al, "msg": msg, "updated": as_of or last_date(source),
        "dates": _data_dates(source), "kpi": kpis(view_source, acc, as_of), **ev,
        "maps": [f for f in ev["findings"] if f.issue_code == "diversity_map"],
        "reviews": (creative_review.build(view_source, client_dir(slug), acc["account_id"])
                    if view == "creativita" and acc["platform"] == "meta" else None),
        "semaforo_class": SEMAFORO_CLASS, "nav_account": account,
        "checks_sorted": sorted(ev["checks"], key=lambda c: -c.status.rank),
    }, nav=view)


@app.get("/c/{slug}/campagne", response_class=HTMLResponse)
def campaigns_page(request: Request, slug: str, account: str = "", al: str | None = None,
                   msg: str | None = None):
    return _account_view(request, slug, account, "campagne", al, msg)


@app.get("/c/{slug}/business", response_class=HTMLResponse)
def business_page(request: Request, slug: str, account: str = "", al: str | None = None,
                  msg: str | None = None):
    """Livello business: le campagne giudicate sul CRM contro i KPI dello specialist."""
    return _account_view(request, slug, account, "business", al, msg)


@app.get("/c/{slug}/creativita", response_class=HTMLResponse)
def creative_page(request: Request, slug: str, account: str = "", al: str | None = None,
                  msg: str | None = None):
    return _account_view(request, slug, account, "creativita", al, msg)


@app.get("/c/{slug}/schede/{name}")
def review_image(slug: str, name: str):
    """Immagine di una scheda creativa (data/<cliente>/schede_creative/img/<name>)."""
    folder = (client_dir(slug) / creative_review.FOLDER / "img").resolve()
    f = (folder / name).resolve()
    if f.parent != folder or not f.is_file():
        raise HTTPException(404, "Immagine non trovata")
    return FileResponse(f)


@app.get("/c/{slug}/dati", response_class=HTMLResponse)
def data_page(request: Request, slug: str, account: str = "", al: str | None = None,
              msg: str | None = None):
    return _account_view(request, slug, account, "dati", al, msg)


@app.get("/c/{slug}/scheda", response_class=HTMLResponse)
def profile_page(request: Request, slug: str):
    folder = client_dir(slug)
    source = CsvSource(folder)
    return page(request, "profile.html", {
        "slug": slug, "client": client_label(slug), "p": profile.build(source, folder),
        "dates": _data_dates(source),
    }, nav="scheda")


@app.get("/c/{slug}/brief", response_class=HTMLResponse)
def brief_page(request: Request, slug: str, id: str = "", msg: str | None = None):
    folder = client_dir(slug)
    source = CsvSource(folder)
    briefs = brief.load(folder)
    b = next((x for x in briefs if x["id"] == id), briefs[0] if briefs else None)
    ctx: dict = {"slug": slug, "client": client_label(slug), "briefs": briefs, "b": b,
                 "msg": msg}
    if b:
        today = date.today()
        res = brief.check(source, b, today)
        log = _safe(source, "change_log")
        created = {e["id"]: e for e in log if e["pipeline"] == b["id"]}
        steps = [{**s, **(created.get(s["id"]) or {})} for s in res["steps"]]
        by_id = {s["id"]: s for s in steps}
        for s in steps:
            s["done"] = register.is_done(s)
            s["label"] = register.STATO_LABEL.get(s["status"], s["status"])
            s["deps"] = [by_id[d] for d in (s["depends"] or "").split("|") if d in by_id]
        ctx.update(res=res, steps=steps, created=bool(created), today=today)
    return page(request, "brief.html", ctx, nav="brief")


@app.post("/c/{slug}/brief/{brief_id}/pipeline")
def brief_pipeline(slug: str, brief_id: str):
    """Scrive nel registro i passi proposti per il brief: da qui entrano in «Da fare»."""
    folder = client_dir(slug)
    b = next((x for x in brief.load(folder) if x["id"] == brief_id), None)
    if b is None:
        raise HTTPException(404, "Brief non trovato")
    res = brief.check(CsvSource(folder), b, date.today())
    n = brief.create_pipeline(folder, res["steps"])
    msg = (f"Pipeline creata: {n} passi nel registro e in «Da fare»" if n
           else "La pipeline c'era già")
    return RedirectResponse(f"/c/{slug}/brief?id={quote(brief_id)}&msg={quote(msg)}",
                            status_code=303)


@app.get("/a/{slug}/{account_id}")
def account_redirect(slug: str, account_id: str, tab: str = "oggi", al: str | None = None):
    """Vecchi indirizzi per account: portano alle pagine del cliente filtrate."""
    if account_id not in {a["account_id"] for a in CsvSource(client_dir(slug)).read("accounts")}:
        raise HTTPException(404, "Account non trovato")
    path = {"oggi": "", "registro": "", "campagne": "/campagne", "guardare": "/campagne",
            "creativita": "/creativita", "dati": "/dati", "segnali": "/dati"}.get(tab, "")
    q = f"?account={quote(account_id)}" + (f"&al={al}" if al else "")
    return RedirectResponse(f"/c/{slug}{path}{q}", status_code=303)


@app.post("/a/{slug}/{account_id}/registro/{entry_id}")
def register_action(slug: str, account_id: str, entry_id: str, action: str = Form(...),
                    note: str = Form(""), result: str = Form("")):
    """Decisione o avanzamento di una voce del registro. Non scrive sulle piattaforme."""
    folder = client_dir(slug)
    if action not in register.AZIONI:
        raise HTTPException(400, "Azione non valida")
    entry = next((e for e in register.read(folder) if e["id"] == entry_id), None)
    if entry is None or entry["account_id"] != account_id:
        raise HTTPException(404, "Voce non trovata")
    if action == "verificata" and not result.strip():
        msg = "Per chiudere la verifica scrivi il risultato"
    else:
        try:
            e = register.apply_action(folder, entry_id, action, date.today(), note.strip(),
                                      result.strip())
            msg = f"«{e['title']}»: {register.STATO_LABEL[e['status']].lower()}"
        except ValueError as err:
            msg = str(err)
    return RedirectResponse(f"/c/{slug}?item={_uid('r', entry_id)}&msg={quote(msg)}",
                            status_code=303)


# ---------- Export CRM ----------

@app.get("/c/{slug}/crm", response_class=HTMLResponse)
def crm_form(request: Request, slug: str, err: str | None = None):
    source = CsvSource(client_dir(slug))
    rows = _safe(source, "backend_daily")
    summary = defaultdict(lambda: {"giorni": 0, "leads": 0, "qualified": 0, "contracts": 0})
    for r in rows:
        s = summary[r["source"]]
        s["giorni"] += 1
        s["leads"] += r["leads"]
        s["qualified"] += r["qualified_leads"] or 0
        s["contracts"] += r["contracts"] or 0
    period = (min(r["date"] for r in rows), max(r["date"] for r in rows)) if rows else None
    return page(request, "crm.html", {
        "slug": slug, "client": client_label(slug), "summary": dict(summary),
        "period": period, "err": err,
    })


@app.post("/c/{slug}/crm")
async def crm_upload(slug: str, file: UploadFile | None = None, text: str = Form("")):
    folder = client_dir(slug)
    content = text
    if file is not None and file.filename:
        content = (await file.read()).decode("utf-8-sig")
    client = CsvSource(folder).read("accounts")[0]["client"]
    try:
        rows = parse_rows("backend_daily", content)
        if not rows:
            raise ValueError("Il file non contiene righe")
        wrong = {r["client"] for r in rows} - {client}
        if wrong:
            raise ValueError(f"Righe di un altro cliente: {', '.join(sorted(wrong))}")
    except ValueError as e:
        return RedirectResponse(f"/c/{slug}/crm?err={e}", status_code=303)
    write_table(folder, "backend_daily", rows)
    return RedirectResponse(f"/c/{slug}?msg=Export CRM caricato: {len(rows)} righe",
                            status_code=303)


# ---------- Concept creativi ----------

def _concept_rows(source: CsvSource) -> list[dict]:
    """Annunci con spesa delle campagne Meta a conversione, con il concept attuale o proposto."""
    campaigns = {c["campaign_id"]: c for c in _safe(source, "meta_campaigns")}
    current = {c["ad_id"]: c for c in _safe(source, "creative_concepts")}
    ads: dict[str, dict] = {}
    for r in _safe(source, "meta_ad_daily"):
        c = campaigns.get(r["campaign_id"])
        if c is not None and c["objective"] not in META_CONV_OBJECTIVES:
            continue
        ad = ads.setdefault(r["ad_id"], {"ad_id": r["ad_id"], "ad_name": r["ad_name"],
                                         "campaign": c["campaign_name"] if c else r["campaign_id"],
                                         "spend": 0.0, "last": r["date"]})
        ad["spend"] += r["spend"]
        ad["last"] = max(ad["last"], r["date"])
    for ad in ads.values():
        cur = current.get(ad["ad_id"])
        guess = ad["ad_name"].split(" - ")[0].strip()
        ad.update(concept=cur["concept"] if cur else guess,
                  angle=cur["angle"] if cur else "",
                  format=cur["format"] if cur else "",
                  confirmed=bool(cur and cur["confirmed"]), proposed=cur is None)
    return sorted(ads.values(), key=lambda a: (a["campaign"], a["concept"], a["ad_name"]))


@app.get("/c/{slug}/concetti", response_class=HTMLResponse)
def concepts_form(request: Request, slug: str):
    source = CsvSource(client_dir(slug))
    return page(request, "concepts.html", {
        "slug": slug, "client": client_label(slug), "ads": _concept_rows(source),
        "formats": ["statico", "video", "carosello", "catalogo"],
    })


@app.post("/c/{slug}/concetti")
async def concepts_save(request: Request, slug: str):
    folder = client_dir(slug)
    form = await request.form()
    confirmed = set(form.getlist("confirmed"))
    rows = []
    for ad_id, concept, angle, fmt in zip(form.getlist("ad_id"), form.getlist("concept"),
                                          form.getlist("angle"), form.getlist("format"),
                                          strict=True):
        if concept.strip():
            rows.append({"ad_id": ad_id, "concept": concept.strip(), "angle": angle.strip(),
                         "format": fmt.strip(), "confirmed": ad_id in confirmed})
    write_table(folder, "creative_concepts", rows)
    return RedirectResponse(f"/c/{slug}?msg=Concept salvati: {len(rows)} annunci",
                            status_code=303)


# ---------- Stato del tracciamento ----------

@app.get("/c/{slug}/tracciamento", response_class=HTMLResponse)
def tracking_form(request: Request, slug: str):
    source = CsvSource(client_dir(slug))
    current = {t["account_id"]: t for t in _safe(source, "tracking_status")}
    items = [{"a": a, "t": current.get(a["account_id"], {})} for a in source.read("accounts")]
    return page(request, "tracking.html", {
        "slug": slug, "client": client_label(slug), "items": items,
    })


@app.post("/c/{slug}/tracciamento")
async def tracking_save(request: Request, slug: str):
    folder = client_dir(slug)
    form = await request.form()
    rows = []
    for a in CsvSource(folder).read("accounts"):
        acc = a["account_id"]

        def val(name: str, acc: str = acc) -> str:
            return str(form.get(f"{acc}__{name}", "")).strip()

        row: dict = {"account_id": acc, "optimization_event": val("optimization_event")}
        for k in TRACKING_BOOL:
            row[k] = {"si": True, "no": False}.get(val(k))
        for k in TRACKING_NUM:
            row[k] = float(val(k).replace(",", ".")) if val(k) else None
        for k in TRACKING_DATE:
            row[k] = date.fromisoformat(val(k)) if val(k) else None
        rows.append(row)
    write_table(folder, "tracking_status", rows)
    return RedirectResponse(f"/c/{slug}?msg=Stato del tracciamento salvato", status_code=303)


# ---------- Regole di lavoro ----------

@app.get("/regole", response_class=HTMLResponse)
def rules_page(request: Request):
    regole = yaml.safe_load((CONFIG_DIR / "regole.yaml").read_text(encoding="utf-8"))
    return page(request, "rules.html", {"proposte": regole["proposte"],
                                        "azioni": regole["azioni"]}, nav="regole")


# ---------- KPI dello specialist ----------

KPI_FIELDS = ["target_cpa", "cost_per_lead", "cost_per_qualified", "cost_per_contract",
              "leads_per_month", "monthly_budget"]


def _lines_in_data(source) -> list[tuple[str, str]]:
    """Coppie (piattaforma, linea) presenti nelle campagne del cliente."""
    from copilota.rules import line_of

    found = set()
    for r in _safe(source, "ga_campaign_daily"):
        found.add(("google", line_of(r["campaign_name"])))
    for c in _safe(source, "meta_campaigns"):
        found.add(("meta", line_of(c["campaign_name"])))
    return sorted(x for x in found if x[1] != "?")


@app.get("/c/{slug}/kpi", response_class=HTMLResponse)
def kpi_form(request: Request, slug: str):
    source = CsvSource(client_dir(slug))
    current = read_kpis(source)
    pairs = sorted(set(_lines_in_data(source)) | set(current))
    rows = [{"platform": p, "line": line, **(current.get((p, line)) or {})} for p, line in pairs]
    return page(request, "kpi.html", {"slug": slug, "client": client_label(slug), "rows": rows},
                nav="kpi")


@app.post("/c/{slug}/kpi")
async def kpi_save(request: Request, slug: str):
    folder = client_dir(slug)
    form = await request.form()
    rows = []
    for key in form.getlist("key"):
        platform, line = key.split("|", 1)

        def num(field: str, key: str = key) -> float | None:
            v = str(form.get(f"{key}__{field}", "")).strip().replace(",", ".")
            return float(v) if v else None

        values = {f: num(f) for f in KPI_FIELDS}
        if any(v is not None for v in values.values()):
            rows.append({"platform": platform, "line": line, **values})
    write_table(folder, "kpi", rows)
    return RedirectResponse(f"/c/{slug}?msg=KPI salvati: {len(rows)} linee", status_code=303)
