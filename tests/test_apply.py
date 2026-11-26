import json

from copilota import apply

PC = {"campaign_id": "23977245050", "campaign": "IT_ita|LF|AUTO_B2C|GOO|SEA|Pronta_Consegna"}


def entry(**kw):
    e = {"id": "BF-2026-07", "account_id": "3107401529", "platform": "google",
         "campaign_id": "23977245050", "campaign_name": "Pronta_Consegna", "kind": "modifica",
         "title": "Porta «Pronta_Consegna» a 180 € al giorno", "why": "Promo Black Friday.",
         "expected": "", "decides": "Advertiser", "status": "proposta",
         "change": json.dumps([{**PC, "type": "budget_daily", "from": 150, "to": 180}])}
    return {**e, **kw}


def test_editor_paste_for_budget():
    text, note = apply.editor_paste(entry())
    assert text.split("\n") == ["Campaign\tBudget", f"{PC['campaign']}\t180"]
    assert "Modifiche multiple" in note


def test_editor_not_for_meta_or_free_text():
    assert apply.editor_paste(entry(platform="meta"))[0] is None
    free = json.dumps([{**PC, "type": "altro", "text": "aggiungi l'estensione promozione"}])
    assert apply.editor_paste(entry(change=free))[0] is None
    assert apply.editor_paste(entry(change=""))[0] is None


def test_prompt_has_checks_and_stops_without_write_tool():
    p = apply.mcp_prompt(entry(), "RATTIX", "Rattix (Italia)")
    assert "BF-2026-07" in p and "Google Ads 3107401529" in p
    assert "budget giornaliero da 150 a 180" in p
    assert "anteprima" in p and "ok esplicito" in p and "fase 08" in p
    assert "Non toccare altro" in p


def test_ready_only_when_decided():
    assert apply.build(entry(), "RATTIX", "Rattix")["ready"]
    waiting = apply.build(entry(decides="Specialist"), "RATTIX", "Rattix")
    assert not waiting["ready"] and "Specialist" in waiting["why_not"]
    assert apply.build(entry(decides="Specialist", status="approvata"), "R", "R")["ready"]
    blocked = apply.build(entry(waits=[{"step": 6, "title": "Budget"}]), "R", "R")
    assert not blocked["ready"]
    assert apply.build(entry(kind="da_non_toccare"), "R", "R") is None
    assert apply.build(entry(status="applicata"), "R", "R") is None
