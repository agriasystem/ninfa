"""The closed catalog Mia's model can name: its shape, and the promise that no tool writes.

There is no `execute_sql`, no table or column argument, no tenant, workspace, property or user
argument, no write verb in a name: the model chooses WHAT to look at and never WHERE. Every tool is
run for real, in a world with data, under a database that raises on any INSERT, UPDATE or DELETE -
so "read-only" is a property of the code, not a sentence in a document."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from app.modules.ai.mia.tools.catalog import build_tool_catalog
from app.modules.ai.mia.types import MAX_OBSERVATION_CHARS
from app.modules.data_sources.understanding_types import QuestionKind
from app.modules.decision_memory.service import DecisionMemoryService
from tests.mia_decision_support import seed_five_decisions, world_for
from tests.mia_support import MiaWorld
from tests.support import BookingFactory

AS_OF = date(2026, 8, 1)

EXPECTED_TOOLS = {
    # product support
    "search_ninfa_knowledge",
    "get_page_help",
    "get_feature_explanation",
    "get_ninfa_glossary",
    # what the person is looking at
    "get_current_property_context",
    "get_data_status",
    # Oggi and Decisioni
    "get_today_summary",
    "list_decisions",
    "explain_decision",
    # revenue and bookings
    "get_occupancy_revenue",
    "get_pickup",
    "compare_windows",
    # distribution
    "get_distribution",
    "get_channel_breakdown",
    # costs
    "get_cost_metrics",
    "get_cpor",
    # staff
    "get_staff_metrics",
    # imports
    "get_import_status",
    "explain_import_question",
    "get_source_learning_status",
    # the structure
    "get_property_profile",
    "get_room_inventory",
    "get_connected_sources",
}
WRITE_VERBS = (
    "set_",
    "create_",
    "update_",
    "delete_",
    "remove_",
    "write_",
    "save_",
    "send_",
    "execute_",
    "run_",
    "apply_",
    "approve_",
    "cancel_",
    "forget_",
    "import_",
    "upload_",
    "sync_",
    "refresh_",
)
FORBIDDEN_ARGUMENTS = {
    "workspace_id",
    "tenant_id",
    "tenant",
    "property_id",
    "user_id",
    "data_source_id",
    "sql",
    "table",
    "column",
    "where",
    "url",
}


def _sample_arguments(decision_id: str) -> dict[str, dict[str, Any]]:
    return {
        "search_ninfa_knowledge": {"query": "pickup"},
        "get_feature_explanation": {"entry_id": "nav.dati"},
        "explain_decision": {"decision_id": decision_id},
        "explain_import_question": {"kind": next(iter(QuestionKind)).value},
    }


@contextmanager
def _writes_forbidden(engine: Engine) -> Iterator[list[str]]:
    seen: list[str] = []

    def guard(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
        if head in {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "DROP", "ALTER", "CREATE"}:
            seen.append(statement[:80])
            raise AssertionError(f"a Mia tool wrote to the database: {statement[:80]}")

    event.listen(engine, "before_cursor_execute", guard)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", guard)


def test_the_catalog_is_exactly_the_closed_set_of_tools() -> None:
    catalog = build_tool_catalog()

    assert set(catalog.names) == EXPECTED_TOOLS
    assert len(catalog) == len(EXPECTED_TOOLS)


def test_no_tool_name_says_write_or_run_something() -> None:
    for name in build_tool_catalog().names:
        assert name.startswith(("get_", "list_", "explain_", "search_", "compare_")), name
        assert not name.startswith(WRITE_VERBS), name


def test_every_tool_is_described_for_the_model_and_its_arguments_are_closed() -> None:
    for tool in build_tool_catalog():
        spec = tool.spec()
        schema = dict(spec.input_schema)
        assert len(spec.description) >= 60, tool.name
        assert schema["type"] == "object" and schema.get("additionalProperties") is False, tool.name
        assert "$ref" not in json.dumps(schema) and "$defs" not in schema, tool.name
        properties = set(schema.get("properties", {}))
        assert properties.isdisjoint(FORBIDDEN_ARGUMENTS), (tool.name, properties)


def test_the_model_never_names_where_to_look() -> None:
    """Only `explain_decision` and `get_import_status` take an id at all, and each is looked up
    inside the person's own property: a foreign id is the same as a missing one."""
    with_ids = {
        tool.name
        for tool in build_tool_catalog()
        if any(key.endswith("_id") for key in tool.spec().input_schema.get("properties", {}))
    }

    assert with_ids == {"explain_decision", "get_import_status", "get_feature_explanation"}


def test_the_catalog_fits_in_a_prompt() -> None:
    size = sum(
        len(json.dumps(dict(t.spec().input_schema), ensure_ascii=False)) + len(t.spec().description)
        for t in build_tool_catalog()
    )

    assert size < 24000, size  # roughly 8k tokens: a static prefix the provider can cache


@pytest.fixture
def world(factory: BookingFactory, db_session: Session) -> MiaWorld:
    tenant = factory.tenant()
    seed_five_decisions(factory, db_session, tenant, as_of=AS_OF)
    return world_for(factory, db_session, tenant)


def test_every_tool_runs_read_only_and_answers_within_the_size_cap(
    world: MiaWorld, db_engine: Engine
) -> None:
    feed = DecisionMemoryService(world.session, world.runtime().tenant).get_feed(
        world.at.tenant.property.id, AS_OF
    )
    decision_id = str(feed.items[0].decision.id)
    samples = _sample_arguments(decision_id)
    outcomes: dict[str, bool] = {}

    with _writes_forbidden(db_engine) as writes:
        for tool in build_tool_catalog():
            execution = world.call(tool.name, samples.get(tool.name, {}))
            outcomes[tool.name] = not execution.outcome.is_error
            assert len(execution.outcome.content) <= MAX_OBSERVATION_CHARS, tool.name
            json.loads(execution.outcome.content)  # always valid JSON for the model

    assert writes == []
    # a world with data answers the data tools (a tool may legitimately say "not available" in its
    # observation, but it is an observation, not a failure)
    for name in ("get_data_status", "get_today_summary", "list_decisions", "explain_decision"):
        assert outcomes[name], name
    assert sum(outcomes.values()) >= 18


def test_a_tool_never_takes_the_scope_from_its_arguments(world: MiaWorld) -> None:
    for tool in build_tool_catalog():
        for forbidden in ("property_id", "workspace_id", "user_id", "sql"):
            execution = world.call(tool.name, {forbidden: str(uuid4())})
            assert execution.outcome.is_error, (tool.name, forbidden)
            assert "invalid arguments" in execution.outcome.content


def test_every_observation_names_its_refs_and_keeps_coverage_apart_from_the_figures(
    world: MiaWorld,
) -> None:
    for name in (
        "get_occupancy_revenue",
        "get_pickup",
        "get_distribution",
        "get_cost_metrics",
        "get_staff_metrics",
    ):
        payload = world.ok(name)

        assert payload["riferimenti"], name
        assert "copertura" in payload, name  # first-class, never buried in a note
        assert "aggiornamento" in payload, name
