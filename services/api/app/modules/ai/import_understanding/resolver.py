"""The optional AI step: at most TWO calls per file, never per row, and never the only reason for a
certainty.

    deterministic reading -> something still unresolved? -> egress gate -> one call -> checked
                                                       broke the rules? -> ONE more call (the last)
    any failure -> the deterministic reading goes on alone, exactly as if there were no model

`ImportUnderstandingProvider` is the one seam: a vendor adapter implements it (the only file that
imports a vendor SDK is `app.modules.ai.gateway.anthropic_provider`), a test implements it with a
fake. With no provider configured - the default - `resolve` returns immediately: nothing is read,
prepared or sent, no network library is touched, and Smart Import behaves exactly as it does
without any of this.

Before ANY call the evidence goes through the egress gate (`egress`): every free text is cleaned
again from scratch, the document is cut to a hard size limit, and its final text is read once more
for anything personal. A provider is handed text that has already been through all of it.
"""

import json
import logging
import time
from dataclasses import replace
from typing import Protocol

from app.modules.ai.import_understanding.egress import (
    MAX_RESPONSE_CHARS,
    EgressGuard,
    EgressTooLargeError,
    EgressViolationError,
    approx_tokens,
    fit_budget,
    prepare,
    verify,
)
from app.modules.ai.import_understanding.prompt import (
    PROMPT_VERSION,
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
# A second call is not made when the first one already took this long (a slow provider is a
# failing one): the deterministic reading goes on without waiting for it again.
RETRY_ONLY_BEFORE_SECONDS = 15.0


class ImportUnderstandingUnavailableError(Exception):
    """A provider could not answer (timeout, transport, refusal, an answer that is not JSON...). The
    message is a static word, never anything from the request or the response."""


class ImportUnderstandingProvider(Protocol):
    """The ONE seam. A real implementation MUST bound its own time and MUST raise
    `ImportUnderstandingUnavailableError` - never let a raw SDK exception escape - and MUST NEVER
    log the request (it holds the cleaned evidence of a hotel's file). It is handed evidence that
    the egress gate has already cleaned and verified: it is never asked to protect anything."""

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

    def resolve(
        self,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        guard: EgressGuard | None = None,
    ) -> AiResolution:
        if self._provider is None:
            return empty(ResolutionReason.OFF)
        resolution = self._resolve(evidence, fit_of, guard or EgressGuard())
        # the audit trail: what was decided and what it cost - counts and words, never content
        logger.info(
            "import_understanding resolution reason=%s calls=%d payload_chars=%d "
            "input_tokens~%d response_chars=%d output_tokens~%d reduced=%s redactions=%d "
            "suggested=%d rejected=%d prompt=%s",
            resolution.reason.value,
            resolution.calls,
            resolution.payload_chars,
            resolution.input_tokens,
            resolution.response_chars,
            resolution.output_tokens,
            resolution.reduced,
            resolution.redactions,
            len(resolution.columns) + len(resolution.answers),
            resolution.rejected,
            PROMPT_VERSION,
        )
        return resolution

    def _resolve(
        self, evidence: UnderstandingEvidence, fit_of: FitOf, guard: EgressGuard
    ) -> AiResolution:
        sent, redactions = prepare(evidence, guard)
        if not worth_asking(sent):
            return replace(empty(ResolutionReason.NOT_NEEDED), redactions=redactions)
        try:
            sent, reduced = fit_budget(sent)
        except EgressTooLargeError:
            logger.info("import understanding skipped: the evidence cannot be reduced to the limit")
            return replace(empty(ResolutionReason.TOO_LARGE), redactions=redactions)
        if not worth_asking(sent):
            return replace(empty(ResolutionReason.NOT_NEEDED), redactions=redactions, reduced=True)
        schema = output_schema(sent.fields)
        document = evidence_json(sent)
        try:
            verify(document, guard)
        except EgressViolationError as violation:
            # a bug upstream, caught here: the call is NOT made. Only stable codes are logged.
            logger.warning("import understanding blocked by the egress gate codes=%s", violation)
            return replace(empty(ResolutionReason.BLOCKED), redactions=redactions)
        return self._ask(sent, fit_of, schema, document, redactions=redactions, reduced=reduced)

    def _ask(
        self,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        schema: dict[str, object],
        document: str,
        *,
        redactions: int,
        reduced: bool,
    ) -> AiResolution:
        assert self._provider is not None
        hints: tuple[str, ...] = ()
        calls = 0
        spent_in = spent_out = response_chars = 0
        started = time.monotonic()

        def cost(reason: ResolutionReason) -> AiResolution:
            return replace(
                empty(reason, calls),
                payload_chars=len(document),
                input_tokens=spent_in,
                response_chars=response_chars,
                output_tokens=spent_out,
                reduced=reduced,
                redactions=redactions,
            )

        for attempt in range(1, MAX_CALLS + 1):
            if attempt > 1 and time.monotonic() - started >= RETRY_ONLY_BEFORE_SECONDS:
                break
            calls = attempt
            request = ImportUnderstandingRequest(
                SYSTEM_INSTRUCTIONS, document, schema, attempt=attempt, retry_hints=hints
            )
            spent_in += approx_tokens(
                len(SYSTEM_INSTRUCTIONS) + len(document) + len(str(schema)) + sum(map(len, hints))
            )
            try:
                payload = self._provider.suggest(request)
            except ImportUnderstandingUnavailableError:
                return cost(ResolutionReason.UNAVAILABLE)
            except (
                Exception
            ) as error:  # a provider must not raise anything else; fail closed anyway
                logger.warning(
                    "import understanding provider raised error_type=%s", type(error).__name__
                )
                return cost(ResolutionReason.UNAVAILABLE)
            size = _weight(payload)
            response_chars += size
            spent_out += approx_tokens(size)
            if size > MAX_RESPONSE_CHARS:
                hints = ("TOO_LARGE",)  # an answer this heavy is not read at all
                continue
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
                payload_chars=len(document),
                input_tokens=spent_in,
                response_chars=response_chars,
                output_tokens=spent_out,
                reduced=reduced,
                redactions=redactions,
            )
        logger.info("import understanding answer ignored calls=%d codes=%s", calls, ",".join(hints))
        return cost(ResolutionReason.INVALID)


def _weight(payload: object) -> int:
    """The size of an answer in characters (one that cannot even be written out is too heavy)."""
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return MAX_RESPONSE_CHARS + 1


__all__ = [
    "MAX_CALLS",
    "ImportUnderstandingProvider",
    "ImportUnderstandingResolver",
    "ImportUnderstandingUnavailableError",
    "worth_asking",
]
