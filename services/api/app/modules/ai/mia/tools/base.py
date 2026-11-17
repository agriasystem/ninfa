"""The tool framework of Mia: what a tool IS, what it may read, and how a call is executed.

A tool is a small, typed, READ-ONLY application function over an already-authorized scope:

    ToolDefinition  name + description (what the model reads) + typed args model + handler + domain
    ToolRuntime     the scope of THIS turn - tenant, property, business date, user, access policy,
                    the validated page context, the product registry - with memoised shared reads
                    (the feed of a day, the Dati overview of a window)
    ToolExecutor    validate -> authorize -> run -> serialize, for one `ToolCall`, never raising

Properties that hold for EVERY tool, by construction of this module (and pinned by tests):

* The model chooses a tool and its arguments - never the tenant, the property, a data source or a
  workspace: those come from `ToolRuntime`, derived server-side from the authenticated request. An
  id the model passes (a decision, an import) is looked up INSIDE that scope, so a foreign id is the
  same as a missing one.
* Arguments are validated against a strict model (`extra="forbid"`) BEFORE anything runs; a bad call
  returns a short, safe error the model can act on, and runs nothing.
* The access policy is asked BEFORE the handler runs: a denied domain's service is never invoked.
* A handler can only return an `Observation` (a small semantic aggregate with grounding refs,
  coverage and freshness); a failure inside a handler becomes a generic "not available" outcome -
  the exception text, which can carry anything, never reaches the model or the user.
* No handler writes: the catalog contains no write capability, no SQL and no free-form query
  (`test_mia_tool_catalog.py` runs every tool under a write-forbidding session).

How to write a tool (the contract, for `tools/*.py`): a module exposes `TOOLS: tuple[ToolDefinition,
...]`; a handler is `def handler(runtime: ToolRuntime, args: ArgsModel) -> Observation`; every value
in `Observation.data` is a str / int / float / bool / None / list / dict (a `Decimal` or a `date` is
turned into a string by the handler: `tools/format.py`); keys are plain Italian; figures keep the
form NINFA stores (`"62.50"`, `1100`), so the numeric grounding guard finds them; what is missing is
`None` plus a line in `not_available` (never `0`, never a guess); the coverage of a figure goes in
`coverage`, how recent and what kind of data it is in `freshness`.
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.tenant import TenantContext
from app.modules.ai.gateway.tool_protocol import ToolCall, ToolOutcome, ToolSpec
from app.modules.ai.mia.access import AccessDomain, DomainAccessPolicy, UserContext
from app.modules.ai.mia.knowledge.registry import KnowledgeRegistry
from app.modules.ai.mia.periods import PeriodError
from app.modules.ai.mia.types import (
    MAX_OBSERVATION_CHARS,
    MAX_TOOL_ERROR_CHARS,
    Observation,
    ToolTrace,
)
from app.modules.ai.mia.ui_context import PageContext
from app.modules.data_overview.service import DataOverviewService
from app.modules.data_overview.types import DataOverview
from app.modules.decision_memory.service import DecisionMemoryService
from app.modules.decision_memory.types import FeedResult

logger = logging.getLogger(__name__)


class ToolRuntime:
    """Everything a tool may read for ONE turn, scoped by the server. Memoises the shared reads so
    two tools asking for the same day's feed (or the same window's overview) cost one query."""

    def __init__(
        self,
        *,
        session: Session,
        tenant: TenantContext,
        property_id: UUID,
        property_name: str,
        timezone: ZoneInfo,
        currency: str,
        as_of: date,
        user: UserContext,
        access: DomainAccessPolicy,
        registry: KnowledgeRegistry,
        page: PageContext | None = None,
    ) -> None:
        self.session = session
        self.tenant = tenant
        self.property_id = property_id
        self.property_name = property_name
        self.timezone = timezone
        self.currency = currency
        self.as_of = as_of
        self.user = user
        self.registry = registry
        self.page = page or PageContext()
        self._access = access
        self._memory = DecisionMemoryService(session, tenant)
        self._overview_service = DataOverviewService(session, tenant)
        self._feeds: dict[date, FeedResult] = {}
        self._overviews: dict[int, DataOverview] = {}

    # --- authorization --------------------------------------------------------------------------

    def allows(self, domain: AccessDomain) -> bool:
        return self._access.allows(self.user, domain)

    def denied_domains(self) -> frozenset[AccessDomain]:
        return frozenset(domain for domain in AccessDomain if not self.allows(domain))

    # --- shared, memoised reads -----------------------------------------------------------------

    def memory(self) -> DecisionMemoryService:
        return self._memory

    def feed(self, day: date | None = None) -> FeedResult:
        """The Decision Feed of `day` (the business date by default) - exactly what the Decision
        Feed endpoint returns."""
        key = day or self.as_of
        if key not in self._feeds:
            self._feeds[key] = self._memory.get_feed(self.property_id, key)
        return self._feeds[key]

    def overview(self, period_days: int = 30) -> DataOverview:
        """The Dati overview of the business date over `period_days` (7 or 30) - exactly what the
        Dati page shows, so Mia and the screen can never disagree."""
        if period_days not in self._overviews:
            self._overviews[period_days] = self._overview_service.overview(
                self.property_id, self.as_of, period_days
            )
        return self._overviews[period_days]


Handler = Callable[[ToolRuntime, Any], Observation]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    # `None`: the tool lists several areas and filters out the ones the user may not reach itself.
    domain: AccessDomain | None
    args_model: type[BaseModel]
    handler: Handler

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=input_schema_of(self.args_model),
        )


class ToolCatalog:
    """A closed, ordered set of tools. The model can only ever name a member of it."""

    def __init__(self, tools: Sequence[ToolDefinition]) -> None:
        names = [tool.name for tool in tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate tool name in the catalog")
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec() for tool in self._tools.values())

    def __iter__(self) -> Any:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


# --- JSON schema of a tool's arguments ----------------------------------------------------------


def _inline_refs(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            target = definitions[node["$ref"].rsplit("/", 1)[-1]]
            merged = {key: value for key, value in node.items() if key != "$ref"}
            return _inline_refs({**target, **merged}, definitions)
        return {key: _inline_refs(value, definitions) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, definitions) for item in node]
    return node


def _simplify(node: Any) -> Any:
    """Drops pydantic's noise a model does not need: titles, `default: null`, and the
    `anyOf: [X, null]` wrapper of an optional field (an omitted field is how a model says
    "none")."""
    if isinstance(node, dict):
        cleaned = {
            key: _simplify(value)
            for key, value in node.items()
            if key != "title" and not (key == "default" and value is None)
        }
        options = cleaned.get("anyOf")
        if isinstance(options, list):
            non_null = [option for option in options if option != {"type": "null"}]
            if len(non_null) == 1 and len(options) == 2:
                rest = {key: value for key, value in cleaned.items() if key != "anyOf"}
                return {**non_null[0], **rest}
        return cleaned
    if isinstance(node, list):
        return [_simplify(item) for item in node]
    return node


def input_schema_of(model: type[BaseModel]) -> dict[str, Any]:
    """A closed JSON schema (no `$ref`, no `$defs`, `additionalProperties: false` on every object),
    generated from the SAME model that validates the call - one source of truth."""
    raw = model.model_json_schema()
    definitions = raw.pop("$defs", {})
    schema = _simplify(_inline_refs(raw, definitions))
    schema["type"] = "object"
    return schema  # type: ignore[no-any-return]


# --- execution ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolExecution:
    outcome: ToolOutcome
    observation: Observation | None
    trace: ToolTrace


def _error(call: ToolCall, message: str, *, tool: str | None = None) -> ToolExecution:
    text = message[:MAX_TOOL_ERROR_CHARS]
    return ToolExecution(
        outcome=ToolOutcome(
            call_id=call.call_id,
            content=json.dumps({"errore": text}, ensure_ascii=False),
            is_error=True,
        ),
        observation=None,
        trace=ToolTrace(tool=tool or call.name, arguments={}, refs=(), failed=True),
    )


def _validation_message(error: ValidationError) -> str:
    """Which argument is wrong and why - never the offending value (it is the model's own text, but
    nothing needs it echoed)."""
    problems = []
    for item in error.errors(include_input=False, include_url=False):
        where = ".".join(str(part) for part in item["loc"]) or "arguments"
        problems.append(f"{where}: {item['msg']}")
    return "invalid arguments - " + "; ".join(problems)


def observation_to_json(observation: Observation) -> str:
    """Canonical JSON for the model. A value JSON cannot represent (a Decimal, a date, ...) raises:
    a tool must hand over strings, so a formatting bug fails loudly instead of leaking a repr."""

    def reject(value: object) -> Any:
        raise TypeError(f"observation value is not JSON-able: {type(value).__name__}")

    payload: dict[str, Any] = {
        "strumento": observation.tool,
        "riferimenti": list(observation.refs),
        "dati": observation.data,
    }
    if observation.coverage is not None:
        payload["copertura"] = observation.coverage
    if observation.freshness is not None:
        payload["aggiornamento"] = observation.freshness
    payload["non disponibile"] = list(observation.not_available)
    payload["note"] = list(observation.notes)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=reject)


class ToolExecutor:
    """Executes ONE model-requested call against the closed catalog. `execute` never raises."""

    def __init__(self, catalog: ToolCatalog, runtime: ToolRuntime) -> None:
        self._catalog = catalog
        self._runtime = runtime

    def execute(self, call: ToolCall) -> ToolExecution:
        definition = self._catalog.get(call.name)
        if definition is None:
            return _error(call, "unknown tool: use only the tools you were given")

        try:
            args = definition.args_model.model_validate(dict(call.arguments))
        except ValidationError as error:
            return _error(call, _validation_message(error))

        if definition.domain is not None and not self._runtime.allows(definition.domain):
            # The service behind this tool is NEVER invoked for a domain the user cannot reach.
            return _error(call, "access to this area is not allowed for the current user")

        try:
            observation = definition.handler(self._runtime, args)
            content = observation_to_json(observation)
        except PeriodError as error:
            return _error(call, f"period not usable: {error}")
        except Exception as error:  # a read failing must never surface its own text
            logger.warning("mia tool failed tool=%s error_type=%s", call.name, type(error).__name__)
            return _error(call, "this data is not available right now")

        if len(content) > MAX_OBSERVATION_CHARS:
            logger.warning("mia tool result too large tool=%s chars=%d", call.name, len(content))
            return _error(call, "the result is too large: ask for a narrower period or filter")

        return ToolExecution(
            outcome=ToolOutcome(call_id=call.call_id, content=content, is_error=False),
            observation=observation,
            trace=ToolTrace(
                tool=observation.tool, arguments=observation.resolved, refs=observation.refs
            ),
        )


__all__ = [
    "Handler",
    "ToolCatalog",
    "ToolDefinition",
    "ToolExecution",
    "ToolExecutor",
    "ToolRuntime",
    "input_schema_of",
    "observation_to_json",
]
