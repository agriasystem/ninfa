"""The short, bounded conversation context of Mia Home (Mia V2).

Mia answers a follow-up ("Perché?", "Intendo gli OTA, sono a posto?") only if she knows what it
follows. The Home UI therefore sends the last few exchanges of the CURRENT page session with each
question; nothing is stored server-side (no table, no conversation id, lost on reload).

What the history IS: linguistic / referential context - it lets "Perché?" be resolved to the topic
of the previous question. What it is NOT: business truth. The client sends the assistant's earlier
answers back itself, so they are exactly as (un)trustworthy as the user's own text - they can be
stale, edited or forged. Every fact Mia states still comes from the fresh NINFA context built for
THIS request (ENGINE CALCULATES. MIA EXPLAINS.), and the instructions say so: history never
overrides it, and an instruction inside history is data, not a command.

Validation is strict and static (it never "repairs" a payload): at most `MAX_HISTORY_EXCHANGES`
complete user/assistant pairs, strictly alternating and starting with the user; every message
non-blank and within its length bound; a bounded total; and no user message the deterministic
guardrail would itself refuse (a refused question is never part of a real history - the UI drops
it - so one that shows up here is a forged one). A violation is a 400 `INVALID_ASK_HISTORY` with a
static reason label, never an echo of the offending text.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from app.modules.ai.ask_ninfa.errors import InvalidAskHistoryError
from app.modules.ai.ask_ninfa.guardrails import classify_refusal
from app.modules.ai.ask_ninfa.home_types import MAX_HOME_ANSWER_CHARS
from app.modules.ai.ask_ninfa.types import MAX_QUESTION_LENGTH

# The newest 4 exchanges of the page session. (The Home UI retains 4 exchanges INCLUDING the one
# being asked, so it sends at most 3 as history; the backend accepts up to 4 to keep headroom.)
MAX_HISTORY_EXCHANGES = 4
MAX_HISTORY_MESSAGES = MAX_HISTORY_EXCHANGES * 2
MAX_HISTORY_USER_CHARS = MAX_QUESTION_LENGTH
MAX_HISTORY_ASSISTANT_CHARS = MAX_HOME_ANSWER_CHARS
# 4 x (1000 + 1800) would be 11200; a real conversation is far shorter, and the cap keeps the
# prompt (and its cost) bounded regardless of what a client sends.
MAX_HISTORY_TOTAL_CHARS = 8000


class HistoryRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class HomeHistoryTurn:
    role: HistoryRole
    content: str


def _reject(reason: str) -> InvalidAskHistoryError:
    return InvalidAskHistoryError(reason)


def validate_history(raw: Sequence[tuple[str, str]]) -> tuple[HomeHistoryTurn, ...]:
    """`raw` is the `(role, content)` pairs exactly as received. Returns the cleaned, typed turns,
    or raises `InvalidAskHistoryError` - it never silently drops or truncates a message."""
    if len(raw) > MAX_HISTORY_MESSAGES:
        raise _reject("too_many_messages")
    if len(raw) % 2 != 0:
        raise _reject("incomplete_exchange")

    turns: list[HomeHistoryTurn] = []
    total = 0
    for index, (role_value, content) in enumerate(raw):
        expected = HistoryRole.USER if index % 2 == 0 else HistoryRole.ASSISTANT
        if role_value != expected.value:
            raise _reject("roles_do_not_alternate")
        text = content.strip()
        if not text:
            raise _reject("blank_message")
        limit = (
            MAX_HISTORY_USER_CHARS if expected is HistoryRole.USER else MAX_HISTORY_ASSISTANT_CHARS
        )
        if len(text) > limit:
            raise _reject("message_too_long")
        if expected is HistoryRole.USER and classify_refusal(text) is not None:
            raise _reject("refused_message_in_history")
        total += len(text)
        turns.append(HomeHistoryTurn(role=expected, content=text))

    if total > MAX_HISTORY_TOTAL_CHARS:
        raise _reject("history_too_long")
    return tuple(turns)


__all__ = [
    "MAX_HISTORY_ASSISTANT_CHARS",
    "MAX_HISTORY_EXCHANGES",
    "MAX_HISTORY_MESSAGES",
    "MAX_HISTORY_TOTAL_CHARS",
    "MAX_HISTORY_USER_CHARS",
    "HistoryRole",
    "HomeHistoryTurn",
    "validate_history",
]
