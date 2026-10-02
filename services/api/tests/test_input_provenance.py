"""app.modules.decisions.provenance: the Gate 23B typed run-input-provenance domain model, in
isolation from persistence (see test_decision_provenance_persistence.py for the DecisionService/
DecisionRun level) and from the CLI (see test_pilot_analysis_provenance_cli.py)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.decisions.provenance import BookingProvenance, RunInputProvenance

DATA_SOURCE_ID = uuid4()
IMPORT_JOB_ID = uuid4()
FINISHED_AT = datetime(2026, 9, 29, 9, 15, tzinfo=UTC)


def _known() -> RunInputProvenance:
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=DATA_SOURCE_ID,
            import_job_id=IMPORT_JOB_ID,
            last_successful_import_finished_at=FINISHED_AT,
        )
    )


def _unknown() -> RunInputProvenance:
    """Source identity known, but no SUCCEEDED import exists yet - freshness UNKNOWN, never a
    fabricated timestamp (see the module's own docstring)."""
    return RunInputProvenance(
        bookings=BookingProvenance(
            data_source_id=DATA_SOURCE_ID,
            import_job_id=None,
            last_successful_import_finished_at=None,
        )
    )


# --- 1/2: typed round trip, booking source + import job + finished_at -------------------------


def test_known_provenance_round_trips_through_from_json() -> None:
    original = _known()
    restored = RunInputProvenance.from_json(original.to_json())
    assert restored == original


def test_to_json_shape_matches_the_documented_contract() -> None:
    payload = _known().to_json()
    assert payload == {
        "version": 1,
        "bookings": {
            "data_source_id": str(DATA_SOURCE_ID),
            "last_successful_import_job_id": str(IMPORT_JOB_ID),
            "last_successful_import_finished_at": "2026-09-29T09:15:00+00:00",
        },
    }


def test_finished_at_is_canonicalised_to_utc() -> None:
    """A non-UTC but equivalent instant must serialise identically - the fingerprint (Gate 23B's
    own replay guarantee) must never depend on which offset the DB/session happened to hand
    back."""
    from datetime import timedelta, timezone

    cet = timezone(timedelta(hours=1))
    local = BookingProvenance(
        data_source_id=DATA_SOURCE_ID,
        import_job_id=IMPORT_JOB_ID,
        last_successful_import_finished_at=FINISHED_AT.astimezone(cet),
    )
    utc = BookingProvenance(
        data_source_id=DATA_SOURCE_ID,
        import_job_id=IMPORT_JOB_ID,
        last_successful_import_finished_at=FINISHED_AT,
    )
    assert local.to_json() == utc.to_json()


# --- 3: unknown freshness allowed ---------------------------------------------------------------


def test_unknown_freshness_round_trips() -> None:
    original = _unknown()
    restored = RunInputProvenance.from_json(original.to_json())
    assert restored == original
    assert restored.bookings.import_job_id is None
    assert restored.bookings.last_successful_import_finished_at is None
    # the source identity itself is still known, even though freshness is not
    assert restored.bookings.data_source_id == DATA_SOURCE_ID


def test_unknown_freshness_shape_has_explicit_nulls_not_missing_keys() -> None:
    payload = _unknown().to_json()
    assert payload["bookings"]["last_successful_import_job_id"] is None
    assert payload["bookings"]["last_successful_import_finished_at"] is None


# --- booking provenance invariants --------------------------------------------------------------


def test_import_job_id_and_finished_at_must_be_both_set_or_both_none() -> None:
    with pytest.raises(ValueError, match="both set or both None"):
        BookingProvenance(
            data_source_id=DATA_SOURCE_ID,
            import_job_id=IMPORT_JOB_ID,
            last_successful_import_finished_at=None,
        )
    with pytest.raises(ValueError, match="both set or both None"):
        BookingProvenance(
            data_source_id=DATA_SOURCE_ID,
            import_job_id=None,
            last_successful_import_finished_at=FINISHED_AT,
        )


def test_finished_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        BookingProvenance(
            data_source_id=DATA_SOURCE_ID,
            import_job_id=IMPORT_JOB_ID,
            last_successful_import_finished_at=datetime(2026, 9, 29, 9, 15),  # naive
        )


# --- 4: malformed JSON rejected safely -----------------------------------------------------------


def test_from_json_rejects_an_unknown_version() -> None:
    with pytest.raises(ValueError, match="version"):
        RunInputProvenance.from_json({"version": 99, "bookings": _known().to_json()["bookings"]})


def test_from_json_rejects_a_missing_version() -> None:
    with pytest.raises(ValueError, match="version"):
        RunInputProvenance.from_json({"bookings": _known().to_json()["bookings"]})


# --- 5: version handling explicit -----------------------------------------------------------------


def test_to_json_always_carries_the_current_version() -> None:
    assert _known().to_json()["version"] == 1
    assert _unknown().to_json()["version"] == 1
