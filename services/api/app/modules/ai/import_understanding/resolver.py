"""The optional AI step: at most TWO calls per file, never per row, and never the only reason for a
certainty.

    deterministic reading -> something still unresolved? -> one call -> checked
                                                              \\-> broke the rules? -> ONE more call
    any failure -> the deterministic reading goes on alone, exactly as if there were no model

`ImportUnderstandingProvider` is the one seam: a vendor adapter implements it (the only file that
imports a vendor SDK is `app.modules.ai.gateway.anthropic_provider`), a test implements it with a
fake. With no provider configured - the default - `resolve` returns immediately and Smart Import
behaves exactly as it does without any of this.
"""

import logging
from typing import Protocol

from app.modules.ai.import_understanding.prompt import (
    SYSTEM_INSTRUCTIONS,
    evidence_json,
    output_schema,
)
from app.modules.ai.import_understanding.types import (
    AiResolution,
    ImportUnderstandingRequest,
    ResolutionReason,
    UnderstandingEvidence,
    empty,
)
from app.modules.ai.import_understanding.validator import (
    FitOf,
    InvalidGuessError,
    check_guess,
    parse_guess,
)

logger = logging.getLogger(__name__)

MAX_CALLS = 2


class ImportUnderstandingUnavailableError(Exception):
    """A provider could not answer (timeout, transport, refusal, an answer that is not JSON...). The
    message is a static word, never anything from the request or the response."""


class ImportUnderstandingProvider(Protocol):
    """The ONE seam. A real implementation MUST bound its own time and MUST raise
    `ImportUnderstandingUnavailableError` - never let a raw SDK exception escape - and MUST NEVER
    log the request (it holds the cleaned evidence of a hotel's file)."""

    def suggest(self, request: ImportUnderstandingRequest) -> object:
        """The model's answer as parsed JSON (validated by the caller, never trusted)."""
        ...


def worth_asking(evidence: UnderstandingEvidence) -> bool:
    """Is there anything the model could add? A file whose columns are all placed, or locked as
    personal data, with no question to suggest an answer for, is not worth a call."""
    open_columns = [
        c
        for c in evidence.columns
        if c.assigned is None and c.pii is None and c.kind != "EMPTY" and c.values > 0
    ]
    return bool(open_columns or evidence.questions)


class ImportUnderstandingResolver:
    """Asks the provider (when there is one) and returns what survives every check."""

    def __init__(self, provider: ImportUnderstandingProvider | None) -> None:
        self._provider = provider

    @property
    def enabled(self) -> bool:
        return self._provider is not None

    def resolve(self, evidence: UnderstandingEvidence, fit_of: FitOf) -> AiResolution:
        if self._provider is None:
            return empty(ResolutionReason.OFF)
        if not worth_asking(evidence):
            return empty(ResolutionReason.NOT_NEEDED)
        schema = output_schema(evidence.fields)
        document = evidence_json(evidence)
        hints: tuple[str, ...] = ()
        calls = 0
        for attempt in range(1, MAX_CALLS + 1):
            calls = attempt
            request = ImportUnderstandingRequest(
                SYSTEM_INSTRUCTIONS, document, schema, attempt=attempt, retry_hints=hints
            )
            try:
                payload = self._provider.suggest(request)
            except ImportUnderstandingUnavailableError:
                return empty(ResolutionReason.UNAVAILABLE, calls)
            except (
                Exception
            ) as error:  # a provider must not raise anything else; fail closed anyway
                logger.warning(
                    "import understanding provider raised error_type=%s", type(error).__name__
                )
                return empty(ResolutionReason.UNAVAILABLE, calls)
            try:
                guess = parse_guess(payload, evidence)
            except InvalidGuessError as invalid:
                hints = invalid.codes
                continue
            checked = check_guess(guess, evidence, fit_of)
            return AiResolution(
                ResolutionReason.OK,
                calls,
                checked.domain,
                checked.columns,
                checked.answers,
                checked.rejected,
            )
        logger.info("import understanding answer ignored calls=%d codes=%s", calls, ",".join(hints))
        return empty(ResolutionReason.INVALID, calls)


__all__ = [
    "MAX_CALLS",
    "ImportUnderstandingProvider",
    "ImportUnderstandingResolver",
    "ImportUnderstandingUnavailableError",
    "worth_asking",
]
