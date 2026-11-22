"""Copilota Advertiser in locale: Segnali e Creatività per cliente, più gli input a mano
(export CRM, concept creativi, stato del tracciamento).

Sola lettura verso le piattaforme: scrive solo i CSV in data/<cliente>/.
Avvio: .venv/Scripts/python -m uvicorn copilota.web.app:app --host 127.0.0.1 --port 8000
"""

from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from copilota.config import CONFIG_DIR, load_thresholds
from copilota.creative import analyze_account
from copilota.data import CsvSource, parse_rows, write_table
from copilota.signals import (
    META_CONV_OBJECTIVES,
    Status,
    check_account,
    gate,
    quality_measured,
    ticket_text,
)

DATA_ROOT = Path(__file__).parent.parent.parent.parent / "data"
HERE = Path(__file__).parent

app = FastAPI(title="Copilota Advertiser (locale)")
templates = Jinja2Templates(directory=HERE / "templates")

ISSUE_LABELS = {
    "fatigue_late": "Creatività in ritardo",
    "fatigue_prepare": "Prepara il cambio",
    "diversity_low": "Diversità bassa",
    "concept_concentration": "Spesa concentrata su un concept",
    "no_active_concepts": "Nessun concept attivo",
}
TRACKING_BOOL = ["enhanced_conversions", "capi_active", "consent_mode_v2", "crm_quality_feedback"]
TRACKING_NUM = ["capi_coverage_pct", "consent_rate_pct", "consent_rate_prev_pct"]
TRACKING_DATE = ["crm_last_upload", "customer_match_updated"]


def data_root() -> Path:
    return app.state.data_root if hasattr(app.state, "data_root") else DATA_ROOT


def clients() -> list[str]:
    return sorted(p.name for p in data_root().iterdir() if (p / "accounts.csv").exists())


def client_dir(slug: str) -> Path:
    if slug not in clients():  # anche protezione da percorsi arbitrari
        raise HTTPException(404, "Cliente non trovato")
    return data_root() / slug


def target_cpa(client: str) -> float | None:
    f = CONFIG_DIR / "clienti" / f"{client.lower()}.yaml"
    if not f.exists():
        return None
    return ((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("target") or {}).get("cpa")


def last_date(source: CsvSource) -> date | None:
    dates = [r["date"] for t in ("ga_campaign_daily", "meta_ad_daily") for r in _safe(source, t)]
    return max(dates, default=None)


class AsOfSource:
    """Vista dei dati come se oggi fosse `as_of`: scarta le righe giornaliere successive."""

    def __init__(self, source: CsvSource, as_of: date):
        self.source, self.as_of = source, as_of

    def read(self, table: str) -> list:
        return [r for r in self.source.read(table) if r.get("date", self.as_of) <= self.as_of]


def _safe(source: CsvSource, table: str) -> list:
    try:
        return source.read(table)
    except FileNotFoundError:
        return []


def account_view(source: CsvSource, account: dict, as_of: date | None) -> dict:
    th = load_thresholds(account["client"])
    checks = check_account(source, account, th)
    esito = gate(checks)
    view = {
        "account": account,
        "checks": sorted(checks, key=lambda c: -c.status.rank),
        "gate": esito,
        "quality": quality_measured(source, account),
        "ticket": ticket_text(account, checks) if esito is Status.RED else None,
        "findings": [],
    }
    if account["platform"] == "meta":
        fs = analyze_account(source, account, th, as_of, target_cpa(account["client"]))
        view["map"] = [f for f in fs if f.issue_code == "diversity_map"]
        view["findings"] = sorted((f for f in fs if f.issue_code != "diversity_map"),
                                  key=lambda f: f.priority)
    return view


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    rows = []
    for slug in clients():
        source = CsvSource(data_root() / slug)
        accounts = []
        for a in source.read("accounts"):
            checks = check_account(source, a, load_thresholds(a["client"]))
            accounts.append({"a": a, "gate": gate(checks),
                             "quality": quality_measured(source, a)})
        rows.append({"slug": slug, "accounts": accounts, "updated": last_date(source)})
    return templates.TemplateResponse(request, "home.html", {"clients": rows})


@app.get("/c/{slug}", response_class=HTMLResponse)
def client_page(request: Request, slug: str, al: str | None = None, msg: str | None = None):
    source = CsvSource(client_dir(slug))
    updated = last_date(source)
    as_of = date.fromisoformat(al) if al else None
    view_source = AsOfSource(source, as_of) if as_of else source
    views = [account_view(view_source, a, as_of) for a in source.read("accounts")]
    return templates.TemplateResponse(request, "client.html", {
        "slug": slug, "views": views, "updated": as_of or updated, "al": al, "msg": msg,
        "labels": ISSUE_LABELS, "clients": clients(),
    })


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
    return templates.TemplateResponse(request, "crm.html", {
        "slug": slug, "summary": dict(summary), "period": period, "err": err,
        "clients": clients(),
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
    return templates.TemplateResponse(request, "concepts.html", {
        "slug": slug, "ads": _concept_rows(source), "clients": clients(),
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
    return templates.TemplateResponse(request, "tracking.html", {
        "slug": slug, "items": items, "clients": clients(),
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
