"""The only production `LanguageModelProvider` this gate ships.

No vendor SDK, no network call, no API key, no config flag to flip - Gate 18 makes the system
PROVIDER-READY (the protocol boundary, the fail-closed wiring, the API contract) rather than
PROVIDER-CONNECTED. A real vendor was explicitly out of scope for this gate (see ADR 0024, "why no
vendor selected in this Gate") - a future gate adds a real implementation of `LanguageModelProvider`
here (or alongside it) and swaps the FastAPI dependency default; `AskNinfaService` and the `/ask`
route do not change at all when that happens.
"""

from app.modules.ai.gateway.errors import LanguageModelUnavailableError
from app.modules.ai.gateway.protocol import LanguageModelAnswer, LanguageModelRequest


class UnconfiguredLanguageModelProvider:
    """Always raises - there is nothing to configure yet, so "unconfigured" is not a state this
    class checks for, it is the only state it can ever be in."""

    def generate(self, request: LanguageModelRequest) -> LanguageModelAnswer:
        raise LanguageModelUnavailableError("no language model provider is configured")


__all__ = ["UnconfiguredLanguageModelProvider"]
