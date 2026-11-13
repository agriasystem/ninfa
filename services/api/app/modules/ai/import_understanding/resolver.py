"""The optional AI step: at most TWO calls per file, never per row, and never the only reason for a
certainty.

    deterministic reading -> something still unresolved? -> egress gate -> one call -> checked
                                                       broke the rules? -> ONE more call (the last)
    any failure -> the deterministic reading goes on alone, exactly as if there were no model

`ImportUnderstandingProvider` is the one seam: a vendor adapter implements it (the only files that
import a vendor SDK are the adapters in `app.modules.ai.gateway`), a test implements it with a
fake. With no provider configured - the default - `resolve` returns immediately: nothing is read,
prepared or sent, no network library is touched, and Smart Import behaves exactly as it does
without any of this.

Before ANY call the evidence goes through the egress gate (`egress`): every free text is cleaned
again from scratch, the document is cut to a hard size limit, and its final text is read once more
for anything personal. A provider is handed text that has already been through all of it.

A provider speaks one of two closed shapes (`provider.contract`): the original three-key answer
("legacy") or the richer `semantic-v1` interpretation. Whatever it speaks, what comes back goes
through the SAME checks (`validator`): the richer shape only adds things to compare and to count.
"""

import json
import logging
import time
from collections.abc import Callable
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
from app.modules.ai.import_understanding.interpretation import (
    SCHEMA_VERSION,
    InterpretationSummary,
    SemanticInterpretation,
    contract_model,
    interpretation_from,
    to_payload,
)
from app.modules.ai.import_understanding.prompt import (
    PROMPT_VERSION,
    SEMANTIC_INSTRUCTIONS,
    SEMANTIC_PROMPT_VERSION,
    SYSTEM_INSTRUCTIONS,
    evidence_json,
    output_schema,
)
from app.modules.ai.import_understanding.types import (
    AiMode,
    AiResolution,
    AiTrace,
    FailureKind,
    ImportUnderstandingRequest,
    LevelCounts,
    ProviderAnswer,
    ProviderUsage,
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
LEGACY_CONTRACT = "legacy"


class ImportUnderstandingUnavailableError(Exception):
    """A provider could not answer (timeout, transport, refusal, an answer that is not JSON...). The
    message is a static word, never anything from the request or the response. `kind` says why, as
    one stable word, and `usage` what the call cost when the adapter knows."""

    def __init__(
        self,
        message: str = "",
        kind: FailureKind = FailureKind.PROVIDER_ERROR,
        usage: ProviderUsage | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.usage = usage


class ImportUnderstandingProvider(Protocol):
    """The ONE seam. A real implementation MUST bound its own time and MUST raise
    `ImportUnderstandingUnavailableError` - never let a raw SDK exception escape - and MUST NEVER
    log the request (it holds the cleaned evidence of a hotel's file). It is handed evidence that
    the egress gate has already cleaned and verified: it is never asked to protect anything.

    A provider that speaks the richer shape has a class attribute `contract = "semantic-v1"`, and
    may return a `ProviderAnswer` (the answer with what the call cost) instead of the bare answer.
    """

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
    """Asks the provider (when there is one) and returns what survives every check.

    `mode` says what the caller does with the result (see `AiMode`); the resolver itself asks the
    same way in SHADOW and in ASSIST. `corroborate` says that a column the model named AND the
    file's own values prove may be taken as confirmed (see `understanding_ai.corroborate`); without
    it the model's reading is only ever a suggestion to confirm. `observer` receives every audit
    record (the benchmark and the shadow report use it; production only logs)."""

    def __init__(
        self,
        provider: ImportUnderstandingProvider | None,
        mode: AiMode = AiMode.ASSIST,
        *,
        corroborate: bool = False,
        observer: Callable[[AiTrace], None] | None = None,
        provider_name: str = "",
        model: str = "",
    ) -> None:
        self._provider = provider
        self._mode = mode
        self._corroborate = corroborate
        self._observer = observer
        self._provider_name = provider_name or (
            type(provider).__name__ if provider is not None else ""
        )
        self._model = model or str(getattr(provider, "model", "") or "")

    @property
    def enabled(self) -> bool:
        return self._provider is not None and self._mode != AiMode.OFF

    @property
    def mode(self) -> AiMode:
        return self._mode

    @property
    def corroborates(self) -> bool:
        return self._corroborate and self._mode == AiMode.ASSIST

    def resolve(
        self,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        guard: EgressGuard | None = None,
    ) -> AiResolution:
        if self._provider is None or self._mode == AiMode.OFF:
            return empty(ResolutionReason.OFF)
        resolution = self._resolve(evidence, fit_of, guard or EgressGuard())
        # the audit trail: what was decided and what it cost - counts and words, never content
        logger.info(
            "import_understanding resolution mode=%s reason=%s failure=%s calls=%d "
            "payload_chars=%d input_tokens~%d response_chars=%d output_tokens~%d "
            "reduced=%s redactions=%d "
            "suggested=%d rejected=%d prompt=%s",
            self._mode.value,
            resolution.reason.value,
            resolution.failure.value if resolution.failure else "-",
            resolution.calls,
            resolution.payload_chars,
            resolution.input_tokens,
            resolution.response_chars,
            resolution.output_tokens,
            resolution.reduced,
            resolution.redactions,
            len(resolution.columns) + len(resolution.answers),
            resolution.rejected,
            self._prompt_version(),
        )
        return resolution

    # --- the audit record ----------------------------------------------------------------------

    def _prompt_version(self) -> str:
        return SEMANTIC_PROMPT_VERSION if self._contract() != LEGACY_CONTRACT else PROMPT_VERSION

    def _contract(self) -> str:
        return str(getattr(self._provider, "contract", LEGACY_CONTRACT))

    def trace_of(
        self,
        resolution: AiResolution,
        *,
        before: LevelCounts = LevelCounts(),  # noqa: B008 - an immutable value
        after: LevelCounts = LevelCounts(),  # noqa: B008
        questions_before: int = 0,
        questions_after: int = 0,
        suggested: int = 0,
        promoted: int = 0,
        source_learning_conflicts: int = 0,
    ) -> AiTrace:
        """The record of one use of the model. `before` / `after` / the counts are filled by the one
        who applied the resolution (the resolver does not know the proposal)."""
        known = [u for u in resolution.usages if u.input_tokens is not None]
        exact_in = sum(u.input_tokens or 0 for u in known) if known else None
        exact_out = sum(u.output_tokens or 0 for u in known) if known else None
        model = next((u.model for u in reversed(resolution.usages) if u.model), self._model)
        summary = resolution.interpretation
        return AiTrace(
            mode=self._mode.value,
            provider=self._provider_name,
            model=model,
            prompt_version=self._prompt_version(),
            schema_version=SCHEMA_VERSION if self._contract() != LEGACY_CONTRACT else "legacy",
            outcome=resolution.reason.value,
            calls=resolution.calls,
            retries=sum(u.retries for u in resolution.usages),
            latency_ms=sum(u.latency_ms for u in resolution.usages),
            input_tokens=exact_in,
            output_tokens=exact_out,
            request_ids=tuple(u.request_id for u in resolution.usages if u.request_id),
            fallback_reason=resolution.failure.value if resolution.failure else None,
            status=summary.status if summary else None,
            before=before,
            after=after,
            questions_before=questions_before,
            questions_after=questions_after,
            suggested=suggested,
            promoted=promoted,
            agreements=len(summary.agreements) if summary else 0,
            conflicts=len(summary.conflicts) if summary else 0,
            source_learning_conflicts=source_learning_conflicts,
        )

    def record(self, trace: AiTrace) -> None:
        """One audit line (counts, words and ids) and, when somebody listens, the record itself."""
        logger.info(
            "import_understanding trace mode=%s provider=%s model=%s prompt=%s schema=%s "
            "outcome=%s fallback=%s status=%s calls=%d retries=%d latency_ms=%d in=%s out=%s "
            "request_ids=%s open_before=%d open_after=%d questions=%d->%d suggested=%d "
            "promoted=%d agreements=%d conflicts=%d source_learning_conflicts=%d",
            trace.mode,
            trace.provider,
            trace.model,
            trace.prompt_version,
            trace.schema_version,
            trace.outcome,
            trace.fallback_reason or "-",
            trace.status or "-",
            trace.calls,
            trace.retries,
            trace.latency_ms,
            trace.input_tokens,
            trace.output_tokens,
            ",".join(trace.request_ids) or "-",
            trace.before.open,
            trace.after.open,
            trace.questions_before,
            trace.questions_after,
            trace.suggested,
            trace.promoted,
            trace.agreements,
            trace.conflicts,
            trace.source_learning_conflicts,
        )
        if self._observer is not None:
            try:
                self._observer(trace)
            except Exception:  # an observer must never be able to stop an import
                logger.warning("import_understanding observer raised", exc_info=False)

    # --- the call ------------------------------------------------------------------------------

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
            return replace(
                empty(ResolutionReason.TOO_LARGE, failure=FailureKind.REQUEST_TOO_LARGE),
                redactions=redactions,
            )
        if not worth_asking(sent):
            return replace(empty(ResolutionReason.NOT_NEEDED), redactions=redactions, reduced=True)
        document = evidence_json(sent)
        try:
            verify(document, guard)
        except EgressViolationError as violation:
            # a bug upstream, caught here: the call is NOT made. Only stable codes are logged.
            logger.warning("import understanding blocked by the egress gate codes=%s", violation)
            return replace(empty(ResolutionReason.BLOCKED), redactions=redactions)
        if self._contract() == LEGACY_CONTRACT:
            instructions = SYSTEM_INSTRUCTIONS
            schema: dict[str, object] = output_schema(sent.fields)
        else:
            instructions = SEMANTIC_INSTRUCTIONS
            schema = contract_model(sent.fields).model_json_schema()
        return self._ask(
            sent,
            fit_of,
            schema,
            document,
            instructions,
            redactions=redactions,
            reduced=reduced,
        )

    def _ask(
        self,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        schema: dict[str, object],
        document: str,
        instructions: str,
        *,
        redactions: int,
        reduced: bool,
    ) -> AiResolution:
        assert self._provider is not None
        contract = self._contract()
        hints: tuple[str, ...] = ()
        calls = 0
        spent_in = spent_out = response_chars = 0
        usages: list[ProviderUsage] = []
        started = time.monotonic()

        def cost(reason: ResolutionReason, failure: FailureKind | None) -> AiResolution:
            return replace(
                empty(reason, calls, failure),
                payload_chars=len(document),
                input_tokens=spent_in,
                response_chars=response_chars,
                output_tokens=spent_out,
                reduced=reduced,
                redactions=redactions,
                usages=tuple(usages),
            )

        failure: FailureKind | None = FailureKind.SCHEMA
        for attempt in range(1, MAX_CALLS + 1):
            if attempt > 1 and time.monotonic() - started >= RETRY_ONLY_BEFORE_SECONDS:
                break
            calls = attempt
            request = ImportUnderstandingRequest(
                instructions,
                document,
                schema,
                attempt=attempt,
                retry_hints=hints,
                contract=contract,
            )
            spent_in += approx_tokens(
                len(instructions) + len(document) + len(str(schema)) + sum(map(len, hints))
            )
            try:
                answer = self._provider.suggest(request)
            except ImportUnderstandingUnavailableError as unavailable:
                if unavailable.usage is not None:
                    usages.append(unavailable.usage)
                return cost(ResolutionReason.UNAVAILABLE, unavailable.kind)
            except (
                Exception
            ) as error:  # a provider must not raise anything else; fail closed anyway
                logger.warning(
                    "import understanding provider raised error_type=%s", type(error).__name__
                )
                return cost(ResolutionReason.UNAVAILABLE, FailureKind.PROVIDER_ERROR)
            payload: object = answer
            if isinstance(answer, ProviderAnswer):
                payload = answer.payload
                usages.append(answer.usage)
            size = _weight(payload)
            response_chars += size
            spent_out += approx_tokens(size)
            if size > MAX_RESPONSE_CHARS:
                hints = ("TOO_LARGE",)  # an answer this heavy is not read at all
                failure = FailureKind.SCHEMA
                continue
            summary: InterpretationSummary | None = None
            if contract != LEGACY_CONTRACT:
                interpretation = interpretation_from(payload, evidence.fields)
                if interpretation is None:
                    hints = ("SHAPE",)
                    failure = FailureKind.SCHEMA
                    continue
                payload, summary = to_payload(interpretation, evidence)
            try:
                guess = parse_guess(payload, evidence)
            except InvalidGuessError as invalid:
                hints = invalid.codes
                failure = FailureKind.SCHEMA
                continue
            checked = check_guess(guess, evidence, fit_of)
            # the model answered with opaque ids: back to the ones this side knows
            answers = {evidence.aliases.get(q, q): choice for q, choice in checked.answers.items()}
            columns = dict(checked.columns)
            domain = checked.domain
            if summary is not None:
                # a column the model finds ambiguous is nobody's to settle but the person's; and a
                # model that says its own reading is not to be used is believed
                columns = {i: f for i, f in columns.items() if i not in summary.ambiguous}
                if summary.stands_down:
                    columns, answers, domain = {}, {}, None
            return AiResolution(
                ResolutionReason.OK,
                calls,
                domain,
                columns,
                answers,
                checked.rejected,
                payload_chars=len(document),
                input_tokens=spent_in,
                response_chars=response_chars,
                output_tokens=spent_out,
                reduced=reduced,
                redactions=redactions,
                interpretation=summary,
                usages=tuple(usages),
            )
        logger.info("import understanding answer ignored calls=%d codes=%s", calls, ",".join(hints))
        return cost(ResolutionReason.INVALID, failure)


class ReplayResolver(ImportUnderstandingResolver):
    """Hands back ONE resolution that was already obtained, as an ASSIST resolver would apply it.

    SHADOW needs to know what ASSIST would have done with the model's reading. Rather than a second
    implementation of "applying" (which could drift from the real one), the service reads the file
    a second time through the real code with this resolver in place of the real one: no second
    call to a model, the same checks, the same outcome ASSIST would have produced. Nothing it
    produces is ever returned to a person."""

    def __init__(self, resolution: AiResolution) -> None:
        super().__init__(None, AiMode.ASSIST, corroborate=True)
        self._replayed = resolution

    @property
    def enabled(self) -> bool:
        return True

    def resolve(
        self,
        evidence: UnderstandingEvidence,
        fit_of: FitOf,
        guard: EgressGuard | None = None,
    ) -> AiResolution:
        return self._replayed

    def record(self, trace: AiTrace) -> None:
        return None


def _weight(payload: object) -> int:
    """The size of an answer in characters (one that cannot even be written out is too heavy)."""
    if isinstance(payload, SemanticInterpretation):
        return len(payload.model_dump_json())
    try:
        return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    except (TypeError, ValueError):
        return MAX_RESPONSE_CHARS + 1


__all__ = [
    "LEGACY_CONTRACT",
    "MAX_CALLS",
    "ImportUnderstandingProvider",
    "ImportUnderstandingResolver",
    "ImportUnderstandingUnavailableError",
    "ReplayResolver",
    "worth_asking",
]
