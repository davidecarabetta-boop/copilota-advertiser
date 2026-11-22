"""Hook PreToolUse: blocca gli strumenti di scrittura degli MCP Meta Ads e Google Ads.

Valido fino alla fase 08 (poi sostituito da guardrail.py, che applica config/regole.yaml).
Funziona per nome dello strumento, quindi non dipende dall'id del connettore sul singolo PC.
Logica "fail closed": sul connettore Meta passano solo gli strumenti noti di lettura;
uno strumento nuovo è bloccato finché non viene aggiunto qui.

Uscita 2 = strumento bloccato (stderr va a Claude come motivo).
"""

import json
import re
import sys

# Strumenti Meta Ads (prefisso ads_) ammessi: solo lettura.
META_READ = re.compile(
    r"^ads_("
    r"get_.*"
    r"|account_get_activity_logs"
    r"|insights_.*"
    r"|library_search"
    r"|permission_list_.*"
    r"|catalog_get_.*"
    r"|catalog_list_.*"
    r"|catalog_event_source_get.*"
    r"|experiment_list_tests"
    r"|experiment_check_eligibility"
    r"|experiment_(abtest|lift)_get_test"
    r"|pixel_(event|parameter)_read"
    r")$"
)

# Verbi di scrittura riconosciuti su qualsiasi altro MCP pubblicitario (es. Google Ads).
WRITE_VERB = re.compile(
    r"(^|_)(create|update|delete|remove|mutate|activate|pause|duplicate|upload|apply)(_|$)"
)
GOOGLE_READ = {
    "customers_list_accessible_customers",
    "metadata_get_resource_metadata",
    "search_search",
}


def is_blocked(tool_name: str) -> bool:
    if not tool_name.startswith("mcp__"):
        return False
    server, tool = tool_name.split("__", 2)[1:]
    if server.startswith("ccd_"):  # strumenti interni dell'app Claude (sidebar, sessioni)
        return False
    if tool.startswith("ads_") or tool == "offer_report":
        return tool != "offer_report" and not META_READ.match(tool)
    if tool in GOOGLE_READ:
        return False
    # Gli id dei connettori sono opachi (UUID): si blocca ogni verbo di scrittura MCP.
    return bool(WRITE_VERB.search(tool))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    name = payload.get("tool_name", "")
    if is_blocked(name):
        print(
            f"Bloccato: '{name}' modifica la piattaforma pubblicitaria. "
            "Nel Copilota le scritture sono disabilitate fino alla fase 08.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
