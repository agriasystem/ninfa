"""Framework-free provider errors - `AskNinfaService` catches these, never lets a raw SDK/transport
exception (or its message, which may embed request/response bodies) reach a caller."""


class LanguageModelUnavailableError(Exception):
    """Raised by a `LanguageModelProvider` on timeout, transport failure, or - for
    `UnconfiguredLanguageModelProvider`, this gate's only production implementation - simply
    because no real provider is configured yet. `AskNinfaService` catches this (and any other
    provider-raised exception, as defense in depth) and turns it into `AskStatus.UNAVAILABLE`,
    never a leaked stack trace or provider error body."""


__all__ = ["LanguageModelUnavailableError"]
