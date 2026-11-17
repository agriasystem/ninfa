"""A small notation for writing scenarios: one line per question, the oracle next to the rubric."""

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from tests.benchmarks.mia_openai_v1.model import Call, Oracle, Rubric, Scenario, Turn

DATA_TOOLS = frozenset(
    {
        "get_occupancy_revenue",
        "get_pickup",
        "compare_windows",
        "get_distribution",
        "get_channel_breakdown",
        "get_cost_metrics",
        "get_cpor",
        "get_staff_metrics",
        "get_today_summary",
        "list_decisions",
        "explain_decision",
        "get_data_status",
        "get_import_status",
        "get_source_learning_status",
        "get_connected_sources",
        "get_room_inventory",
        "get_property_profile",
        "get_current_property_context",
    }
)
PRODUCT_TOOLS = frozenset(
    {"search_ninfa_knowledge", "get_page_help", "get_feature_explanation", "get_ninfa_glossary"}
)


def C(name: str, **arguments: Any) -> Call:  # noqa: N802
    return (name, arguments)


def _rounds(calls: Sequence[Any]) -> tuple[tuple[Call, ...], ...]:
    if not calls:
        return ()
    if isinstance(calls[0], tuple) and calls[0] and isinstance(calls[0][0], str):
        return (tuple(calls),)
    return tuple(tuple(r) for r in calls)


def T(  # noqa: N802
    message: str,
    calls: Sequence[Any],
    answer: str,
    *,
    mention: Sequence[Sequence[str]] = (),
    tools: Sequence[Iterable[str]] | None = None,
    status: str = "ANSWERED",
    expect: Sequence[str] | None = None,
    ui: Mapping[str, Any] | None = None,
    limitations: Sequence[str] = (),
    max_calls: int | None = None,
    **rubric: Any,
) -> Turn:
    rounds = _rounds(calls)
    names = [name for r in rounds for name, _ in r]
    if tools is None:
        distinct = sorted(set(names))
        if len(distinct) > 2:
            raise ValueError(f"a multi-tool turn needs explicit `tools=` alternatives: {message!r}")
        tool_sets: tuple[frozenset[str], ...] = (frozenset(distinct),) if distinct else ()
    else:
        tool_sets = tuple(frozenset(s) for s in tools)
    statuses = frozenset(expect if expect is not None else {status})
    base = Rubric(
        expect_status=statuses,
        expected_tools_any=tool_sets,
        must_mention=tuple(tuple(g) for g in mention),
        max_tool_calls=max_calls if max_calls is not None else max(2, len(names) + 1),
        **{
            **{k: v for k, v in rubric.items() if k not in ("forbidden", "not_")},
            **(
                {"forbidden_tools": frozenset(rubric["forbidden"])} if "forbidden" in rubric else {}
            ),
            **({"must_not_mention": tuple(rubric["not_"])} if "not_" in rubric else {}),
        },
    )
    return Turn(
        message=message,
        rubric=base,
        oracle=Oracle(rounds, answer, status, tuple(limitations)),
        ui_context=ui,
    )


def S(id_: str, category: str, world: str, *turns: Turn, tags: Sequence[str] = ()) -> Scenario:  # noqa: N802
    return Scenario(id_, category, world, tuple(turns), frozenset(tags))


def numbered(prefix: str) -> Callable[[], str]:
    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"{prefix}-{counter[0]:03d}"

    return next_id


__all__ = ["C", "DATA_TOOLS", "PRODUCT_TOOLS", "S", "T", "numbered"]
