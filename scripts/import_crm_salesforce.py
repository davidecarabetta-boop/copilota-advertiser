"""Converte l'export Salesforce dei lead (tabella HTML con estensione .xls) in
data/<cliente>/backend_daily.csv: solo conteggi per giorno e piattaforma, nessun dato personale.

Le regole (fasi che valgono come qualificato / contratto, UTM -> piattaforma, esclusioni)
stanno in config/clienti/<cliente>.yaml, sezione `crm`.

Uso: python -I scripts/import_crm_salesforce.py <cliente> <export.xls>
"""

import sys
from collections import defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote_plus

import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
from copilota.data import write_table  # noqa: E402


class _Table(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] = []
        self._in = False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._in, self._cell = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._in = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._in:
            self._cell.append(data)


def normalize_campaign(utm: str) -> str:
    """'IT_ita+|+MF+|+AUTO+I+B2C' -> 'IT_ita | MF | AUTO I B2C' (spazi singoli)."""
    return " ".join(unquote_plus(utm or "").split())


def aggregate(rows: list[dict], cfg: dict, client: str, by_campaign: bool = False) -> list[dict]:
    src_map = {s.lower(): p for p, ss in cfg["sorgenti"].items() for s in ss}
    excl = cfg.get("escludi") or {}
    qual, won = set(cfg["fasi_qualificato"]), set(cfg["fasi_contratto"])
    agg: dict[tuple, dict] = defaultdict(lambda: {"leads": 0, "qualified_leads": 0,
                                                  "contracts": 0})
    for r in rows:
        if r.get("Where", "") in excl.get("where", []):
            continue
        if any(r.get("UTM Campaign", "").startswith(p)
               for p in excl.get("utm_campaign_inizia_con", [])):
            continue
        source = src_map.get(r.get("UTM Source", "").strip().lower(), "altro")
        day = datetime.strptime(r[cfg["colonna_data"]], "%d/%m/%Y").date()
        if by_campaign:
            camp = normalize_campaign(r.get("UTM Campaign", ""))
            if source == "altro" or not camp:
                continue
            a = agg[(day, source, camp)]
        else:
            a = agg[(day, source)]
        a["leads"] += 1
        stage = r[cfg["colonna_fase"]]
        a["qualified_leads"] += stage in qual
        a["contracts"] += stage in won
    if by_campaign:
        return [{"date": d, "client": client, "source": s, "utm_campaign": c, **v}
                for (d, s, c), v in sorted(agg.items())]
    return [{"date": d, "client": client, "source": s, **v} for (d, s), v in sorted(agg.items())]


def main() -> None:
    client, path = sys.argv[1], Path(sys.argv[2])
    cfg = yaml.safe_load((ROOT / "config" / "clienti" / f"{client}.yaml")
                         .read_text(encoding="utf-8"))
    t = _Table()
    t.feed(path.read_text(encoding="latin-1"))
    header = t.rows[0]
    rows = [dict(zip(header, r, strict=False)) for r in t.rows[1:]]
    out = aggregate(rows, cfg["crm"], cfg["cliente"])
    write_table(ROOT / "data" / client, "backend_daily", out)
    per_camp = aggregate(rows, cfg["crm"], cfg["cliente"], by_campaign=True)
    write_table(ROOT / "data" / client, "backend_campaign_daily", per_camp)
    print(f"backend_campaign_daily.csv: {len(per_camp)} righe, "
          f"{len({r['utm_campaign'] for r in per_camp})} campagne")
    tot = defaultdict(lambda: [0, 0, 0])
    for r in out:
        t3 = tot[r["source"]]
        t3[0] += r["leads"]
        t3[1] += r["qualified_leads"]
        t3[2] += r["contracts"]
    print(f"backend_daily.csv: {len(out)} righe ({out[0]['date']} -> {out[-1]['date']})")
    for s, (n, q, c) in sorted(tot.items()):
        print(f"  {s}: {n} lead, {q} qualificati ({q / n:.0%}), {c} contratti ({c / n:.1%})")


if __name__ == "__main__":
    main()
