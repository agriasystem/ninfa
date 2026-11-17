"""The trusted, per-turn application facts handed to the model as DATA (never as instructions).

Built by the server from values it already holds - the business date, the calendar around it, the
asking user's role and first name - so the model never has to do calendar arithmetic and never has
to be told who is asking by the user's own text. It deliberately carries NO business fact (no
decision, no number about the property, not even the property's name: those come from tools, which
are authorized and observed).
"""

import json
from datetime import date

from app.modules.ai.mia.periods import reference_calendar
from app.modules.ai.mia.tools.base import ToolRuntime
from app.modules.ai.mia.types import MAX_TOOL_CALLS_PER_TURN, MAX_TOOL_ROUNDS
from app.modules.tenancy.models import MembershipRole

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
_ROLE_LABELS = {
    MembershipRole.OWNER: "proprietario",
    MembershipRole.ADMIN: "amministratore",
    MembershipRole.MEMBER: "collaboratore",
}


def first_name_of(display_name: str | None) -> str | None:
    """ "Luisa Ferrante" -> "Luisa": the user is addressed by first name, as the Home does."""
    if display_name is None:
        return None
    parts = display_name.strip().split()
    return parts[0][:40] if parts else None


def business_day(as_of: date) -> str:
    return f"{as_of.isoformat()}, {_WEEKDAYS[as_of.weekday()]}"


def build_turn_context(runtime: ToolRuntime) -> str:
    payload = {
        "data di riferimento (oggi)": business_day(runtime.as_of),
        "calendario": reference_calendar(runtime.as_of),
        "utente": {
            "nome": first_name_of(runtime.user.display_name),
            "ruolo": _ROLE_LABELS[runtime.user.role],
        },
        "limiti per domanda": {
            "chiamate agli strumenti": MAX_TOOL_CALLS_PER_TURN,
            "round di strumenti": MAX_TOOL_ROUNDS,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


__all__ = ["build_turn_context", "business_day", "first_name_of"]
