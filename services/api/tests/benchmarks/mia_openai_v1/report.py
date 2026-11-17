"""The report of a run: a JSON document and a Markdown one. Honest about what it is.

It never prints a model's text unless asked (`show_text`): a failing scenario is listed with the
NAMES
of the checks it failed, which is what is needed to find it and nothing about the hotel."""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from tests.benchmarks.mia_openai_v1.harness import ScenarioOutcome
from tests.benchmarks.mia_openai_v1.scoring import (
    GATES,
    KNOWN_GAPS,
    ZERO_COUNTERS,
    Aggregate,
)

FAMILIES = ("simple_product", "data_aware", "multi_tool")
LIMITS = (
    "The rubric is deterministic (words, tools, figures, counters): it is not a model-as-judge and "
    "it cannot tell a correct answer that is phrased in an unexpected way from a wrong one that is "
    "not caught by a pattern. A pass is evidence, a fail is a lead to read.",
    "A live run covers the sample it was asked for, not the whole corpus: the rates carry the "
    "uncertainty of the sample size (a handful of turns per category).",
    "The worlds are synthetic hotels; real exports will differ. Real-hotel validation is a "
    "separate "
    "gate.",
    "Zero counters count what the checks can see: a leak the patterns do not recognise (a person's "
    "NAME inside a file name, for instance) is reported as a known gap, not as a zero.",
)


@dataclass
class Price:
    """Dollars per MILLION tokens, typed by the operator from the provider's published pricing. The
    evaluation never knows a price by itself: with none, the report says cost unavailable."""

    model: str
    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_million + output_tokens * self.output_per_million
        ) / 1_000_000


def parse_price(spec: str) -> Price:
    """`MODEL=IN:OUT` (dollars per million tokens)."""
    model, _, rest = spec.partition("=")
    low, _, high = rest.partition(":")
    return Price(model.strip(), float(low), float(high))


@dataclass
class TurnStats:
    scenario: str
    category: str
    family: str
    model_calls: int
    tool_calls: int
    reasoning: tuple[str, ...]
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    provider_latency_ms: int
    elapsed_ms: int
    status: str
    corrected: bool
    failure_kind: str | None


def turn_stats(outcomes: list[ScenarioOutcome]) -> list[TurnStats]:
    rows: list[TurnStats] = []
    for outcome in outcomes:
        for turn in outcome.turns:
            m = turn.metrics
            rows.append(
                TurnStats(
                    outcome.scenario.id,
                    outcome.scenario.category,
                    outcome.scenario.family,
                    m.model_calls,
                    m.tool_calls,
                    m.reasoning,
                    m.input_tokens,
                    m.output_tokens,
                    m.reasoning_tokens,
                    m.provider_latency_ms,
                    m.elapsed_ms,
                    turn.run.result.status.value,
                    m.corrected,
                    m.failure_kind,
                )
            )
    return rows


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))]


def performance(rows: list[TurnStats], price: Price | None) -> dict[str, Any]:
    by_family: dict[str, list[TurnStats]] = defaultdict(list)
    for row in rows:
        by_family[row.family].append(row)
    out: dict[str, Any] = {}
    for family in (*FAMILIES, "all"):
        group = rows if family == "all" else by_family.get(family, [])
        if not group:
            continue
        calls = [r.model_calls for r in group]
        entry: dict[str, Any] = {
            "turns": len(group),
            "model_calls_mean": round(statistics.fmean(calls), 2),
            "tool_calls_mean": round(statistics.fmean(r.tool_calls for r in group), 2),
            "input_tokens_mean": int(statistics.fmean(r.input_tokens for r in group)),
            "output_tokens_mean": int(statistics.fmean(r.output_tokens for r in group)),
            "reasoning_tokens_mean": int(statistics.fmean(r.reasoning_tokens for r in group)),
            "latency_ms_p50": _percentile([r.provider_latency_ms for r in group], 0.5),
            "latency_ms_p95": _percentile([r.provider_latency_ms for r in group], 0.95),
            "elapsed_ms_p95": _percentile([r.elapsed_ms for r in group], 0.95),
        }
        if price is not None:
            total = sum(price.cost(r.input_tokens, r.output_tokens) for r in group)
            entry["cost_per_turn_usd"] = round(total / len(group), 5)
            entry["cost_total_usd"] = round(total, 4)
        else:
            entry["cost_per_turn_usd"] = None
        out[family] = entry
    return out


def project(
    rows: list[TurnStats], turns: int, price: Price | None, assumed_output: int
) -> dict[str, Any]:
    """The cost of `turns` turns, from the measured (or oracle-estimated) tokens per call: the
    lead's
    tool for deciding how much to spend BEFORE spending it."""
    if not rows:
        return {"turns": turns, "cost_usd": None}
    calls = statistics.fmean(r.model_calls for r in rows)
    input_per_turn = statistics.fmean(r.input_tokens for r in rows)
    measured_output = statistics.fmean(r.output_tokens for r in rows)
    output_per_turn = measured_output if measured_output > calls * 200 else calls * assumed_output
    result: dict[str, Any] = {
        "turns": turns,
        "model_calls_per_turn": round(calls, 2),
        "input_tokens_per_turn": int(input_per_turn),
        "output_tokens_per_turn": int(output_per_turn),
        "total_input_tokens": int(input_per_turn * turns),
        "total_output_tokens": int(output_per_turn * turns),
    }
    result["cost_usd"] = (
        None
        if price is None
        else round(price.cost(int(input_per_turn * turns), int(output_per_turn * turns)), 2)
    )
    return result


@dataclass
class RunReport:
    mode: str
    model: str
    aggregate: Aggregate
    outcomes: list[ScenarioOutcome]
    rows: list[TurnStats]
    price: Price | None = None
    scenarios_run: int = 0
    scenarios_selected: int = 0
    calls_made: int = 0
    calls_cached: int = 0
    budget_exhausted: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.aggregate.tripped:
            return 2
        if self.aggregate.gate_failures():
            return 1
        return 0

    def to_json(self) -> dict[str, Any]:
        agg = self.aggregate
        return {
            "mode": self.mode,
            "model": self.model,
            "scenarios_selected": self.scenarios_selected,
            "scenarios_run": self.scenarios_run,
            "turns": agg.turns,
            "budget_exhausted": self.budget_exhausted,
            "provider_calls": {"made": self.calls_made, "from_cache": self.calls_cached},
            "zero_counters": {
                name: {"count": agg.counters[name], "turns": agg.counter_turns[name]}
                for name in ZERO_COUNTERS
            },
            "known_gaps": dict(agg.gaps),
            "rates": {
                m: {"passed": p, "applicable": n, "rate": None if n == 0 else round(p / n, 4)}
                for m, (p, n) in agg.rates.items()
            },
            "multi_turn_reference_accuracy": {
                "passed": agg.follow_up[0],
                "applicable": agg.follow_up[1],
            },
            "gates": GATES,
            "gate_failures": {
                k: {"rate": round(r, 4), "bar": b} for k, (r, b) in agg.gate_failures().items()
            },
            "by_category": {
                c: {m: {"passed": p, "applicable": n} for m, (p, n) in d.items() if n}
                for c, d in agg.by_category.items()
            },
            "unavailable_turns": agg.unavailable,
            "performance": performance(self.rows, self.price),
            "failing": [
                {"scenario": s, "turn": i, "checks": checks} for s, i, checks in agg.failing
            ],
            "limits": list(LIMITS),
            "notes": self.notes,
            "exit_code": self.exit_code,
        }


def _pct(passed: int, total: int) -> str:
    return "n/a" if total == 0 else f"{100 * passed / total:.1f}% ({passed}/{total})"


def markdown(report: RunReport, *, show_text: bool = False) -> str:
    agg = report.aggregate
    out: list[str] = []
    add = out.append
    add(f"# Mia evaluation - {report.mode} run ({report.model})\n")
    add(
        f"{report.scenarios_run} of {report.scenarios_selected} scenarios, {agg.turns} turns. "
        f"Provider calls made: {report.calls_made}; replayed from cache: {report.calls_cached}."
    )
    if report.budget_exhausted:
        add("\n**The call budget was spent: the run stopped early.**")
    for note in report.notes:
        add(f"\n> {note}")
    add("\n## Zero counters (each must be 0)\n")
    add("| Counter | Count | Where |\n|---|---|---|")
    for name in ZERO_COUNTERS:
        count = agg.counters[name]
        where = ", ".join(agg.counter_turns[name][:6]) or "-"
        add(f"| {name} | {'**' + str(count) + ' - FAILS THE RUN**' if count else '0'} | {where} |")
    add("\n### Known gaps (reported, not gated)\n")
    for name in KNOWN_GAPS:
        count = agg.gaps[name]
        add(f"- `{name}`: {'**' + str(count) + ' request(s) carried it**' if count else '0'}")
    add("\n## Quality metrics\n")
    add("| Metric | Rate | Bar | |\n|---|---|---|---|")
    for metric, bar in GATES.items():
        if metric == "multi_turn_reference_accuracy":
            passed, total = agg.follow_up
        else:
            passed, total = agg.rates.get(metric, (0, 0))
        ok = "" if total == 0 else ("ok" if passed / total >= bar else "**BELOW BAR**")
        add(f"| {metric} | {_pct(passed, total)} | {bar:.0%} | {ok} |")
    add("\n## By category\n")
    metrics = [m for m in GATES if m != "multi_turn_reference_accuracy"]
    add("| Category | " + " | ".join(metrics) + " |")
    add("|---|" + "---|" * len(metrics))
    for category, data in sorted(agg.by_category.items()):
        cells = [_pct(*data[m]) if data[m][1] else "-" for m in metrics]
        add(f"| {category} | " + " | ".join(cells) + " |")
    add("\n## Performance\n")
    perf = performance(report.rows, report.price)
    add(
        "| Family | Turns | Model calls | Tool calls | Input tok | Output tok | p50 ms | p95 ms | "
        "Cost/turn |\n|---|---|---|---|---|---|---|---|---|"
    )
    for family, e in perf.items():
        cost = e["cost_per_turn_usd"]
        add(
            f"| {family} | {e['turns']} | {e['model_calls_mean']} | {e['tool_calls_mean']} | "
            f"{e['input_tokens_mean']} | {e['output_tokens_mean']} | {e['latency_ms_p50']} | "
            f"{e['latency_ms_p95']} | {'cost unavailable' if cost is None else f'${cost}'} |"
        )
    if report.price is None:
        add("\nNo price was given (`--price MODEL=IN:OUT`): cost is unavailable, never invented.")
    add("\n## Failing turns\n")
    if not agg.failing:
        add("None.")
    for scenario, index, checks in agg.failing[:80]:
        add(f"- `{scenario}` turn {index}: {', '.join(checks)}")
    if len(agg.failing) > 80:
        add(f"- ... and {len(agg.failing) - 80} more (see the JSON)")
    if show_text:
        add("\n## Texts (requested)\n")
        for outcome in report.outcomes:
            for turn in outcome.turns:
                if turn.score.failed_checks or turn.score.tripped_counters:
                    add(f"### {outcome.scenario.id} #{turn.run.index}\n")
                    add(f"Q: {turn.run.message}\n\nA: {turn.run.result.answer}\n")
    add("\n## Limits of this evaluation\n")
    for limit in LIMITS:
        add(f"- {limit}")
    return "\n".join(out) + "\n"


__all__ = [
    "FAMILIES",
    "LIMITS",
    "Price",
    "RunReport",
    "TurnStats",
    "markdown",
    "parse_price",
    "performance",
    "project",
    "turn_stats",
]
