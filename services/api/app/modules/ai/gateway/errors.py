"""Framework-free provider errors - `AskNinfaService` catches these, never lets a raw SDK/transport
exception (or its message, which may embed request/response bodies) reach a caller."""


class LanguageModelUnavailableError(Exception):
    """Raised by a `LanguageModelProvider` on timeout, transport failure, or - for
    `UnconfiguredLanguageModelProvider`, this gate's only production implementation - simply
    because no real provider is configured yet. `AskNinfaService` catches this (and any other
    provider-raised exception, as defense in depth) and turns it into `AskStatus.UNAVAILABLE`,
    never a leaked stack trace or provider error body."""


class ToolProviderUnavailableError(LanguageModelUnavailableError):
    """The same failure as above, with ONE stable word saying why (`kind`: a `FailureKind` value
    such as `TIMEOUT` or `QUOTA`) and the call's own latency - what Mia's observability keeps. Never
    the
    vendor's message: it can hold anything, a key included."""

    def __init__(self, message: str, kind: str = "PROVIDER_ERROR", latency_ms: int = 0) -> None:
        super().__init__(message)
        self.kind = kind
        self.latency_ms = latency_ms


__all__ = ["LanguageModelUnavailableError", "ToolProviderUnavailableError"]
