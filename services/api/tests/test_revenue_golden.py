"""Golden revenue decisions: "MASSERIA NINFA DEMO".

The full chain, end to end, through the real services:

    BOOKINGS (golden + addendum + history + the revenue bookings, imported by the import service;
              the stays that are OBSERVED are imported day by day, as they became known)
      -> SNAPSHOTS (observed and reconstructed by the snapshot services)
      -> EXPECTED BASELINES (the Expected service)
      -> REVENUE EVALUATIONS (the Revenue Decision service)     STOP: no decision is stored.

The expected result (`masseria_ninfa_revenue_v1.expected.json`) was computed independently of the
application code (tests/fixtures/revenue/generate_masseria_revenue_expected.py, standard library
only, exact fractions), including the snapshot values themselves.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from fractions import Fraction
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.modules.bookings.service import BookingImportService
from app.modules.ingestion.models import ImportJobStatus
from app.modules.intelligence.expected.models import BookingExpectedBaseline
from app.modules.intelligence.revenue.service import RevenueDecisionService
from app.modules.intelligence.revenue.types import (
    EvaluationStatus,
    OccupancyFacts,
    PickupFacts,
    RevenueDecisionEvaluation,
    RevenueSignals,
)
from app.modules.snapshots.models import BookingSnapshot
from app.modules.snapshots.observed import ObservedSnapshotService
from app.modules.snapshots.reconstruction import BookingSnapshotReconstructionService
from app.modules.snapshots.repository import RoomInventoryRepository
from tests.booking_support import FIXTURES
from tests.snapshot_support import FixedClock
from tests.support import BookingFactory
from tests.test_expected_golden import (
    EXPECTED as GATE_4_EXPECTED,
)
from tests.test_expected_golden import (
    Golden,
    calculate_all,
    import_bookings,
    materialise_snapshots,
)

FIXTURE_DIR = FIXTURES.parent / "revenue"
REVENUE_CSV = FIXTURE_DIR / "masseria_ninfa_bookings_revenue_v1.csv"
EXPECTED = json.loads((FIXTURE_DIR / "masseria_ninfa_revenue_v1.expected.json").read_text("utf-8"))
TARGETS = {t["name"]: t for t in EXPECTED["targets"]}
RECONSTRUCTION_CLOCK = datetime.fromisoformat(EXPECTED["reconstruction_clock"])
OBSERVED_STAYS = {date.fromisoformat(d) for d in EXPECTED["observed_stays"]}
HEADER = [
    "Codice Prenotazione",
    "Data Prenotazione",
    "Arrivo",
    "Partenza",
    "Stato",
    "Camere",
    "Ospiti",
    "Importo Camera",
    "Importo Totale",
    "Canale",
    "Commissione",
    "Tipologia Camera",
    "Data Cancellazione",
    "Ospite",
    "Telefono",
]
CANCELLED = "Annullato"


# --- building the world ----------------------------------------------------------------------


def parse_day(text: str) -> date:
    day, month, year = text.split(" ")[0].split("/")
    return date(int(year), int(month), int(day))


def as_of(row: dict[str, str], day: date) -> dict[str, str] | None:
    """The booking as the application knew it at the end of `day`, or None if not yet made."""
    if parse_day(row["Data Prenotazione"]) > day:
        return None
    if row["Stato"] == CANCELLED and parse_day(row["Data Cancellazione"]) > day:
        return {**row, "Stato": "Confermato", "Data Cancellazione": ""}
    return row


def csv_bytes(rows: list[dict[str, str]]) -> bytes:
    lines = [";".join(HEADER)] + [";".join(row[name] for name in HEADER) for row in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")


@dataclass
class World:
    golden: Golden
    imported: dict[str, tuple[str, str]]
    files: int = 0

    def send(self, rows: list[dict[str, str]]) -> None:
        """Import the rows that are new or changed since the last import (one file)."""
        changed = [r for r in rows if self.imported.get(r["Codice Prenotazione"]) != state_of(r)]
        if not changed:
            return
        self.files += 1
        service = BookingImportService(self.golden.session, self.golden.context)
        result = service.import_file(
            self.golden.source.id,
            filename=f"revenue-{self.files:03d}.csv",
            content=csv_bytes(changed),
        )
        assert (result.status, result.rows_valid, result.rows_invalid) == (
            ImportJobStatus.SUCCEEDED,
            len(changed),
            0,
        )
        for row in changed:
            self.imported[row["Codice Prenotazione"]] = state_of(row)


def state_of(row: dict[str, str]) -> tuple[str, str]:
    return (row["Stato"], row["Data Cancellazione"])


def read_revenue_rows() -> list[dict[str, str]]:
    with REVENUE_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def observe(golden: Golden, day: date, stay: date) -> None:
    clock = FixedClock(
        datetime.combine(day, time(EXPECTED["observation_clock_hour_utc"]), tzinfo=UTC)
    )
    ObservedSnapshotService(golden.session, golden.context, clock=clock).take_snapshot(
        property_id=golden.prop.id,
        data_source_id=golden.source.id,
        stay_date_start=stay,
        stay_date_end=stay,
    )


def extend_with_revenue(golden: Golden) -> None:
    """The revenue timeline: inventory, day-by-day imports and observations, reconstructions."""
    inventory = RoomInventoryRepository(golden.session, golden.context)
    for stay, rooms in EXPECTED["inventory"].items():
        inventory.set_for_date(golden.prop.id, date.fromisoformat(stay), rooms_available=rooms)

    rows = read_revenue_rows()
    world = World(golden, imported={})
    settled = [r for r in rows if parse_day(r["Arrivo"]) not in OBSERVED_STAYS]
    world.send(settled)  # the stays that are only ever reconstructed: final state at once
    observed_rows = [r for r in rows if parse_day(r["Arrivo"]) in OBSERVED_STAYS]

    specs = EXPECTED["snapshots"]
    observed_days = sorted({s["snapshot_date"] for s in specs if s["kind"] == "OBSERVED"})
    for day_text in observed_days:
        day = date.fromisoformat(day_text)
        world.send([v for r in observed_rows if (v := as_of(r, day)) is not None])
        for spec in specs:
            if spec["kind"] == "OBSERVED" and spec["snapshot_date"] == day_text:
                observe(golden, day, date.fromisoformat(spec["stay_date"]))
    world.send(observed_rows)  # what happened after the last observation

    clock = FixedClock(RECONSTRUCTION_CLOCK)
    for spec in specs:
        if spec["kind"] == "RECONSTRUCTED":
            day, stay = (
                date.fromisoformat(spec["snapshot_date"]),
                date.fromisoformat(spec["stay_date"]),
            )
            BookingSnapshotReconstructionService(
                golden.session, golden.context, clock=clock
            ).reconstruct(
                property_id=golden.prop.id,
                data_source_id=golden.source.id,
                snapshot_date_start=day,
                snapshot_date_end=day,
                stay_date_start=stay,
                stay_date_end=stay,
            )


def build(session: Session, factory: BookingFactory) -> Golden:
    golden = import_bookings(session, factory)  # Gate 2 / 3 / 4 bookings, real import service
    materialise_snapshots(golden)  # Gate 3 / 4 snapshots, real snapshot services
    calculate_all(golden)  # Gate 4 baselines, real Expected service
    extend_with_revenue(golden)  # Gate 5 timeline
    for target in EXPECTED["targets"]:
        golden.service().calculate_for_target(
            property_id=golden.prop.id,
            data_source_id=golden.source.id,
            target_snapshot_id=target_snapshot(golden, target).id,
        )
    return golden


def target_snapshot(golden: Golden, target: dict[str, Any]) -> BookingSnapshot:
    row = golden.snapshots().get_for_stay_date(
        golden.source.id,
        date.fromisoformat(target["snapshot_date"]),
        date.fromisoformat(target["stay_date"]),
    )
    assert row is not None, target["name"]
    return row


def revenue(golden: Golden) -> RevenueDecisionService:
    return RevenueDecisionService(golden.session, golden.context)


def evaluate_all(golden: Golden) -> dict[str, RevenueSignals]:
    return {
        name: revenue(golden).evaluate_revenue_signals(target_snapshot(golden, target).id)
        for name, target in TARGETS.items()
    }


def text(value: object) -> str | None:
    return None if value is None else format(value, ".2f")


def count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- comparison helpers ----------------------------------------------------------------------


def check_exact(actual: Decimal | None, expected: str | None, label: str) -> None:
    """A DECISION value against the independent exact fraction ("numerator/denominator").

    The application keeps 50 significant digits, so it agrees with the fraction far beyond 1e-40
    even when the value is a repeating decimal (140/3 = 46.666...).
    """
    if expected is None:
        assert actual is None, label
        return
    assert actual is not None, label
    assert abs(Fraction(actual) - Fraction(expected)) < Fraction(1, 10**40), label


def check_pattern(actual: Any, expected: dict[str, Any] | None, label: str) -> None:
    assert actual is not None, label
    assert expected is not None, label
    for key in (
        "pair_count",
        "observed_pair_count",
        "approximate_pair_count",
        "rejected_uncertain_count",
        "missing_endpoint_count",
        "excluded_future_count",
    ):
        assert getattr(actual, key) == expected[key], (label, key)
    assert text(actual.median) == expected["median"], label
    if expected["median"] is not None:
        assert (text(actual.p25), text(actual.p75), text(actual.iqr)) == (
            expected["p25"],
            expected["p75"],
            expected["iqr"],
        ), label
        assert text(actual.pattern_confidence) == expected["pattern_confidence"], label
        assert [p.stay_date.isoformat() for p in actual.pairs] == expected["stay_dates"], label


def check_common(evaluation: RevenueDecisionEvaluation, target: dict[str, Any], key: str) -> None:
    expected = target[key]
    label = f"{target['name']} {key}"
    assert evaluation.decision_type.value == expected["decision_type"], label
    assert evaluation.status.value == expected["status"], label
    assert [c.value for c in evaluation.reason_codes] == expected["reasons"], label
    assert text(evaluation.confidence_score) == expected["confidence"], label
    assert text(evaluation.revenue_gap_proxy) == expected["proxy"], label
    assert text(evaluation.reference_adr) == target["reference_adr"], label
    assert evaluation.reference_adr_source.value == target["reference_adr_source"], label
    assert evaluation.rules_version == EXPECTED["rules_version"], label
    assert evaluation.pattern_version == EXPECTED["pattern_version"], label
    assert evaluation.lead_time_days == target["lead_time_days"], label
    assert evaluation.stay_date.isoformat() == target["stay_date"], label
    assert evaluation.snapshot_local_date.isoformat() == target["snapshot_date"], label


def check_pickup(evaluation: RevenueDecisionEvaluation, target: dict[str, Any]) -> None:
    check_common(evaluation, target, "pickup")
    expected = target["pickup"]
    facts = evaluation.facts
    assert isinstance(facts, PickupFacts)
    label = f"{target['name']} pickup"
    assert facts.remaining_capacity == expected.get("remaining_capacity"), label
    assert facts.actual_pickup == expected.get("actual_pickup"), label
    for key in ("expected_pickup", "delta_rooms", "missing_rooms", "delta_percent"):
        assert text(getattr(facts, key)) == expected.get(key), (label, key)
    check_exact(facts.delta_percent_exact, expected.get("delta_percent_exact"), label)
    if "pattern" in expected:
        check_pattern(facts.pattern, expected["pattern"], label)
    else:
        assert facts.pattern is None, label


def check_occupancy(evaluation: RevenueDecisionEvaluation, target: dict[str, Any]) -> None:
    check_common(evaluation, target, "occupancy")
    expected = target["occupancy"]
    facts = evaluation.facts
    assert isinstance(facts, OccupancyFacts)
    label = f"{target['name']} occupancy"
    for key in (
        "expected_remaining_net_pickup",
        "raw_forecast_rooms",
        "forecast_rooms",
        "expected_final_rooms",
        "forecast_occupancy",
        "expected_final_occupancy",
        "occupancy_gap_pp",
        "room_shortfall",
    ):
        assert text(getattr(facts, key)) == expected.get(key), (label, key)
    for key in (
        "forecast_occupancy_exact",
        "expected_final_occupancy_exact",
        "occupancy_gap_pp_exact",
    ):
        check_exact(getattr(facts, key), expected.get(key), f"{label} {key}")
    if "pattern" in expected:
        check_pattern(facts.pattern, expected["pattern"], label)
    else:
        assert facts.pattern is None, label


# --- the golden world contains what it must --------------------------------------------------


def test_the_snapshots_of_the_revenue_world_match_the_independent_calculation(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    counts = EXPECTED["counts"]
    stored = {
        (s.snapshot_local_date, s.stay_date): s for s in db_session.scalars(select(BookingSnapshot))
    }
    lines = []
    observed = 0
    for spec in EXPECTED["snapshots"]:
        key = (date.fromisoformat(spec["snapshot_date"]), date.fromisoformat(spec["stay_date"]))
        snapshot = stored[key]
        assert snapshot.origin.value == (
            "OBSERVED" if spec["kind"] == "OBSERVED" else "RECONSTRUCTED_APPROXIMATE"
        ), key
        observed += snapshot.origin.value == "OBSERVED"
        lines.append(
            f"{key[0]}|{key[1]}|{snapshot.origin.value}|{snapshot.rooms_on_books}|{snapshot.uncertain_rooms}"
        )
    assert len(lines) == counts["snapshots"]
    assert observed == counts["observed_snapshots"]
    assert (
        hashlib.sha256("\n".join(sorted(lines)).encode("ascii")).hexdigest()
        == EXPECTED["snapshot_grid_sha256"]
    )
    assert golden.prop.slug == "masseria-ninfa"


def test_the_earlier_golden_worlds_are_still_intact_inside_the_extended_one(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    gate4 = {t["name"]: t for t in GATE_4_EXPECTED["targets"]}
    for name in ("A", "B", "C", "D"):
        target = gate4[name]
        stored = golden.expected().get_for_target_snapshot(
            golden.snapshots()
            .get_for_stay_date(
                golden.source.id,
                date.fromisoformat(target["snapshot_date"]),
                date.fromisoformat(target["stay_date"]),
            )
            .id  # type: ignore[union-attr]
        )
        assert stored is not None
        assert stored.status.value == target["status"]
        assert text(stored.expected_rooms_on_books) == target["expected"]
        assert text(stored.confidence_score) == target["confidence_score"]


def test_every_baseline_matches_the_independent_expected_result(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    for name, target in TARGETS.items():
        expected = target["baseline"]
        baseline = golden.expected().get_for_target_snapshot(target_snapshot(golden, target).id)
        assert baseline is not None, name
        assert baseline.status.value == expected["status"], name
        assert text(baseline.expected_rooms_on_books) == expected.get("expected"), name
        assert (
            text(baseline.expected_lower),
            text(baseline.expected_upper),
            text(baseline.iqr),
        ) == (
            expected.get("lower"),
            expected.get("upper"),
            expected.get("iqr"),
        ), name
        assert (
            baseline.sample_size,
            baseline.observed_sample_size,
            baseline.reconstructed_sample_size,
            baseline.rejected_uncertain_count,
        ) == (
            expected["sample_size"],
            expected["observed_sample_size"],
            expected["reconstructed_sample_size"],
            expected["rejected_uncertain_count"],
        ), name
        assert text(baseline.confidence_score) == expected["confidence"], name
        snapshots = {s.id: s for s in db_session.scalars(select(BookingSnapshot))}
        actual = [
            {
                "rank": c.recency_rank,
                "stay_date": snapshots[c.snapshot_id].stay_date.isoformat(),
                "snapshot_date": snapshots[c.snapshot_id].snapshot_local_date.isoformat(),
                "origin": c.origin.value,
                "rooms_on_books": c.rooms_on_books,
            }
            for c in golden.expected().list_comparables(baseline.id)
        ]
        assert actual == expected["comparables"], name


# --- the revenue evaluations -----------------------------------------------------------------


def test_every_evaluation_matches_the_independently_computed_result(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)

    signals = evaluate_all(golden)

    for name, target in TARGETS.items():
        check_pickup(signals[name].pickup_low, target)
        check_occupancy(signals[name].occupancy_risk, target)
        baseline = golden.expected().get_for_target_snapshot(target_snapshot(golden, target).id)
        assert baseline is not None
        for evaluation in (signals[name].pickup_low, signals[name].occupancy_risk):
            assert evaluation.workspace_id == golden.context.workspace_id
            assert evaluation.property_id == golden.prop.id
            assert evaluation.data_source_id == golden.source.id
            assert evaluation.target_snapshot_id == target_snapshot(golden, target).id
            assert evaluation.target_baseline_id == baseline.id
            assert len(evaluation.calculation_fingerprint) == 64


def test_the_golden_world_covers_every_required_case(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    signals = evaluate_all(golden)

    def pickup(name: str) -> RevenueDecisionEvaluation:
        return signals[name].pickup_low

    def occupancy(name: str) -> RevenueDecisionEvaluation:
        return signals[name].occupancy_risk

    status = EvaluationStatus
    # 1 pickup TRIGGERED, 2 pickup CLEAR, 3 pickup SUPPRESSED, 4 pickup INSUFFICIENT_DATA
    assert pickup("A").status == status.TRIGGERED
    assert pickup("B").status == status.CLEAR
    assert pickup("C").status == status.SUPPRESSED_LOW_CONFIDENCE
    assert pickup("G").status == status.INSUFFICIENT_DATA
    # 5 near sold out, 6 expected pickup <= 0
    assert (
        pickup("E").status == status.NOT_APPLICABLE
        and pickup("E").reason_codes[0].value == "PICKUP_NEAR_SOLD_OUT"
    )
    assert pickup("F").status == status.NOT_APPLICABLE
    assert pickup("F").reason_codes[0].value == "PICKUP_EXPECTATION_NON_POSITIVE"
    # 7 occupancy TRIGGERED by the gap, 8 by the room shortfall, 9 CLEAR, 10 SUPPRESSED,
    # 11 INSUFFICIENT_DATA, 12 inventory missing
    a, f = occupancy("A"), occupancy("F")
    assert a.status == status.TRIGGERED and a.reason_codes[0].value == "TRIGGER_OCCUPANCY_GAP"
    assert f.status == status.TRIGGERED and f.reason_codes[0].value == "TRIGGER_ROOM_SHORTFALL"
    assert occupancy("B").status == status.CLEAR and occupancy("E").status == status.CLEAR
    assert occupancy("C").status == status.SUPPRESSED_LOW_CONFIDENCE
    assert occupancy("D").status == status.INSUFFICIENT_DATA
    assert occupancy("G").status == status.NOT_APPLICABLE
    assert occupancy("G").reason_codes[0].value == "OCCUPANCY_INVENTORY_UNKNOWN"
    # all five statuses appear, for both detectors
    assert {s.pickup_low.status for s in signals.values()} == set(status)
    assert {s.occupancy_risk.status for s in signals.values()} == set(status)
    # the exact boundary: A sits ON the 10-point gap with only 2 missing rooms
    a_facts = a.facts
    assert isinstance(a_facts, OccupancyFacts)
    assert (text(a_facts.occupancy_gap_pp), text(a_facts.room_shortfall)) == ("10.00", "2.00")
    assert a_facts.gap_condition is True and a_facts.shortfall_condition is False
    # F: 3 rooms of 60 is only 5 points: the rooms alone trigger
    f_facts = f.facts
    assert isinstance(f_facts, OccupancyFacts)
    assert (text(f_facts.occupancy_gap_pp), text(f_facts.room_shortfall)) == ("5.00", "3.00")
    assert f_facts.gap_condition is False and f_facts.shortfall_condition is True
    # C: an empty target has no ADR: the historical median prices the gap; and 105 % is not clamped
    c = occupancy("C")
    assert c.reference_adr_source.value == "HISTORICAL_COMPARABLE_MEDIAN_ADR"
    assert c.revenue_gap_proxy is not None
    c_facts = c.facts
    assert isinstance(c_facts, OccupancyFacts)
    assert text(c_facts.expected_final_occupancy) == "105.00"


def test_historical_cancellations_lower_the_remaining_net_pickup(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    facts = revenue(golden).evaluate_occupancy_risk(target_snapshot(golden, TARGETS["A"]).id).facts
    assert isinstance(facts, OccupancyFacts)
    assert facts.pattern is not None

    remaining = {pair.stay_date.isoformat(): pair.delta for pair in facts.pattern.pairs}
    assert remaining["2026-09-07"] == -2  # 3 rooms cancelled after the anchor, 1 made
    assert min(remaining.values()) < 0 < max(remaining.values())
    assert text(facts.expected_remaining_net_pickup) == "2.00"  # the median still carries it


# --- explainability --------------------------------------------------------------------------


def test_a_triggered_pickup_exposes_everything_behind_it(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    evaluation = revenue(golden).evaluate_pickup_low(target_snapshot(golden, TARGETS["A"]).id)
    facts = evaluation.facts
    assert isinstance(facts, PickupFacts)

    assert (facts.actual_pickup, text(facts.expected_pickup)) == (7, "10.00")
    assert (text(facts.missing_rooms), text(facts.delta_percent)) == ("3.00", "-30.00")
    assert facts.pattern is not None and len(facts.pattern.pairs) == 6
    assert text(evaluation.confidence_score) == "79.29"
    assert text(evaluation.revenue_gap_proxy) == "387.99"  # 3 missing rooms x ADR 129.33
    assert facts.thresholds.max_delta_percent == Decimal("-20")
    assert facts.thresholds.min_missing_rooms == Decimal("2")
    assert facts.thresholds.min_confidence == Decimal("50")
    # every pair says which snapshots it used, and the evidence lists them all
    ids = {evaluation.target_snapshot_id, facts.prior_snapshot_id}
    for pair in facts.pattern.pairs:
        ids |= {pair.anchor_snapshot_id, pair.other_snapshot_id}
    assert set(evaluation.evidence_snapshot_ids) == ids
    assert len(evaluation.evidence_snapshot_ids) == 2 + 2 * 6


def test_a_triggered_occupancy_risk_exposes_everything_behind_it(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    evaluation = revenue(golden).evaluate_occupancy_risk(target_snapshot(golden, TARGETS["F"]).id)
    facts = evaluation.facts
    assert isinstance(facts, OccupancyFacts)

    assert (facts.current_rooms_on_books, facts.rooms_available) == (20, 60)
    assert text(facts.expected_remaining_net_pickup) == "8.00"
    assert (text(facts.forecast_rooms), text(facts.expected_final_rooms)) == ("28.00", "31.00")
    assert (text(facts.forecast_occupancy), text(facts.expected_final_occupancy)) == (
        "46.67",
        "51.67",
    )
    assert (text(facts.room_shortfall), text(facts.occupancy_gap_pp)) == ("3.00", "5.00")
    assert facts.pattern is not None and facts.pattern.pair_count == 5
    assert (facts.pattern.observed_pair_count, facts.pattern.approximate_pair_count) == (2, 3)
    assert text(evaluation.confidence_score) == "68.27"
    assert text(evaluation.revenue_gap_proxy) == "360.00"  # 3 rooms x ADR 120.00
    assert facts.thresholds.min_confidence == Decimal("55")


def test_the_decision_values_are_exact_and_the_displayed_ones_are_rounded_from_them(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    evaluation = revenue(golden).evaluate_occupancy_risk(target_snapshot(golden, TARGETS["F"]).id)
    facts = evaluation.facts
    assert isinstance(facts, OccupancyFacts)

    # 28 rooms of 60 is 46.666...: the DECISION value keeps every digit, the display one is rounded
    assert facts.forecast_occupancy_exact is not None and facts.forecast_occupancy is not None
    assert facts.forecast_occupancy_exact != facts.forecast_occupancy
    assert text(facts.forecast_occupancy) == "46.67"
    assert abs(Fraction(facts.forecast_occupancy_exact) - Fraction(140, 3)) < Fraction(1, 10**40)
    assert facts.occupancy_gap_pp_exact == Decimal(5)  # 3 rooms / 60 * 100, exact
    payload = facts.payload()
    canonical = facts.canonical_payload()
    assert payload["forecast_occupancy"] == "46.67"
    assert "forecast_occupancy" not in canonical  # display-only figures are never hashed
    assert canonical["forecast_occupancy_exact"].startswith("46.666666666666666666")


def test_the_payload_of_every_evaluation_is_plain_data_without_prose(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    for signals in evaluate_all(golden).values():
        for evaluation in (signals.pickup_low, signals.occupancy_risk):
            payload = json.dumps(evaluation.facts.payload())
            assert json.loads(payload) == evaluation.facts.payload()
            for word in ("recommend", "should", "consider", "increase", "lower your"):
                assert word not in payload.lower()


# --- anti-leakage, in the real world ---------------------------------------------------------


def test_the_distractors_exist_and_are_never_used(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    stored = {
        (s.snapshot_local_date, s.stay_date): s for s in db_session.scalars(select(BookingSnapshot))
    }
    a = TARGETS["A"]
    signals = revenue(golden).evaluate_revenue_signals(target_snapshot(golden, a).id)
    used = {
        pair.stay_date
        for evaluation in (signals.pickup_low, signals.occupancy_risk)
        if evaluation.facts.pattern is not None
        for pair in evaluation.facts.pattern.pairs
    }

    out_of_season, future, wrong_lead_6 = date(2026, 2, 2), date(2026, 10, 12), date(2026, 9, 15)
    assert (date(2026, 1, 26), out_of_season) in stored  # same weekday and lead, another season
    assert (date(2026, 10, 5), future) in stored  # a stay AFTER the target, seen after its day
    assert (wrong_lead_6, date(2026, 9, 21)) in stored  # right stay date, wrong lead time
    assert not used & {out_of_season, future}
    # the final of the week before the target was observed on the target's own snapshot day: it
    # exists (and is wild: 30 rooms) but is not yet known, so no remaining pair uses it
    week_before = date(2026, 9, 28)
    assert stored[(week_before, week_before)].rooms_on_books == 30
    occupancy_pattern = signals.occupancy_risk.facts.pattern
    assert occupancy_pattern is not None
    assert week_before not in [pair.stay_date for pair in occupancy_pattern.pairs]
    assert occupancy_pattern.excluded_future_count == 1
    # ... while its pickup pair (all snapshots before the target day) is used
    pickup_pattern = signals.pickup_low.facts.pattern
    assert pickup_pattern is not None
    assert week_before in [pair.stay_date for pair in pickup_pattern.pairs]


# --- P: read-only ----------------------------------------------------------------------------


def test_the_evaluation_phase_writes_nothing(db_session: Session, factory: BookingFactory) -> None:
    golden = build(db_session, factory)
    tables = {mapper.class_.__tablename__: mapper.class_ for mapper in Base.registry.mappers}
    before = {name: count(db_session, model) for name, model in tables.items()}
    fingerprints_before = {
        b.id: b.comparable_fingerprint for b in db_session.scalars(select(BookingExpectedBaseline))
    }

    evaluate_all(golden)

    assert {name: count(db_session, model) for name, model in tables.items()} == before
    assert {
        b.id: b.comparable_fingerprint for b in db_session.scalars(select(BookingExpectedBaseline))
    } == fingerprints_before
    assert not [name for name in tables if "decision" in name]


def test_a_second_evaluation_is_identical_and_the_batch_agrees_with_the_single_calls(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    first = evaluate_all(golden)
    second = evaluate_all(golden)
    assert first == second
    for name, target in TARGETS.items():
        stay = date.fromisoformat(target["stay_date"])
        (batched,) = revenue(golden).evaluate_snapshot_date(
            property_id=golden.prop.id,
            data_source_id=golden.source.id,
            snapshot_local_date=date.fromisoformat(target["snapshot_date"]),
            stay_date_start=stay,
            stay_date_end=stay,
        )
        assert batched == first[name]


def test_fictional_guest_data_never_reaches_an_evaluation(
    db_session: Session, factory: BookingFactory
) -> None:
    golden = build(db_session, factory)
    dump = json.dumps(
        [
            [e.facts.payload(), [str(i) for i in e.evidence_snapshot_ids], e.reason_codes]
            for s in evaluate_all(golden).values()
            for e in (s.pickup_low, s.occupancy_risk)
        ],
        default=str,
    )
    for guest in ("Ospite Ricavi", "Ospite Storico", "+39 000 80", "Camera Doppia"):
        assert guest not in dump


def test_the_generator_is_independent_of_the_application_code() -> None:
    source = (FIXTURE_DIR / "generate_masseria_revenue_expected.py").read_text(encoding="utf-8")

    assert "from app" not in source and "import app" not in source
    assert "import decimal" not in source and "from decimal" not in source  # exact fractions
    assert "from fractions import Fraction" in source


def test_the_revenue_bookings_are_synthetic() -> None:
    text_ = REVENUE_CSV.read_text(encoding="utf-8")
    assert "Ospite Ricavi 0001" in text_ and "+39 000 8000001" in text_
    assert len(read_revenue_rows()) == EXPECTED["counts"]["revenue_bookings"]
