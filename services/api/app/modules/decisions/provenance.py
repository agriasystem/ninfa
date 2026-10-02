"""Run input provenance (Gate 23B): from WHICH booking import a `DecisionRun`'s freshness was
frozen at analysis time - never a dynamic "latest import" query made later, when Oggi is opened.

Provenance != coverage (`app.modules.decisions.coverage`): coverage answers "which of the four
user-facing domains did this run attempt"; provenance answers "from which input/source freshness
did this run's facts derive". A property can have more than one BOOKINGS `DataSource`, and a run
uses exactly one of them - provenance records THAT ONE, never a property-wide/domain-wide MAX
across every booking source the property happens to have.

V1 is BOOKINGS only (Gate 23B's own P0 scope - no cost/labor provenance yet). The fact recorded is
deliberately narrow: "the latest SUCCEEDED import known, for the EXACT booking data source this
run used, at analysis time" - never "the file this run's numbers came from" (canonical booking
state is cumulative/upserted across many imports, so no single import is "the" source of a run's
facts) and never a judgement like CURRENT/STALE (no freshness threshold exists in V1).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

PROVENANCE_VERSION = 1


@dataclass(frozen=True, slots=True)
class BookingProvenance:
    """The exact BOOKINGS `DataSource` a run used, and the latest SUCCEEDED `ImportJob` known
    for that exact source at analysis time - frozen forever once persisted, never re-derived
    afterward.

    `import_job_id`/`last_successful_import_finished_at` are both `None` together when no
    SUCCEEDED import of this source existed yet at analysis time: the SOURCE identity is still
    known, but its freshness fact is UNKNOWN - never a fabricated timestamp.
    """

    data_source_id: UUID
    import_job_id: UUID | None
    last_successful_import_finished_at: datetime | None

    def __post_init__(self) -> None:
        if (self.import_job_id is None) != (self.last_successful_import_finished_at is None):
            raise ValueError(
                "import_job_id and last_successful_import_finished_at must be both set or both None"
            )
        if (
            self.last_successful_import_finished_at is not None
            and self.last_successful_import_finished_at.tzinfo is None
        ):
            raise ValueError("last_successful_import_finished_at must be timezone-aware")

    def to_json(self) -> dict[str, Any]:
        finished_at = self.last_successful_import_finished_at
        return {
            "data_source_id": str(self.data_source_id),
            "last_successful_import_job_id": (
                None if self.import_job_id is None else str(self.import_job_id)
            ),
            "last_successful_import_finished_at": (
                None if finished_at is None else finished_at.astimezone(UTC).isoformat()
            ),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BookingProvenance":
        job_id = payload["last_successful_import_job_id"]
        finished_at = payload["last_successful_import_finished_at"]
        return cls(
            data_source_id=UUID(payload["data_source_id"]),
            import_job_id=None if job_id is None else UUID(job_id),
            last_successful_import_finished_at=(
                None if finished_at is None else datetime.fromisoformat(finished_at)
            ),
        )


@dataclass(frozen=True, slots=True)
class RunInputProvenance:
    """Exactly one booking provenance fact per run, in V1 - no cost/labor provenance exists yet
    (Gate 23B's own P0 scope is BOOKINGS only)."""

    bookings: BookingProvenance

    def to_json(self) -> dict[str, Any]:
        return {"version": PROVENANCE_VERSION, "bookings": self.bookings.to_json()}

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "RunInputProvenance":
        if payload.get("version") != PROVENANCE_VERSION:
            raise ValueError(f"unsupported input_provenance version: {payload.get('version')!r}")
        return cls(bookings=BookingProvenance.from_json(payload["bookings"]))


__all__ = ["PROVENANCE_VERSION", "BookingProvenance", "RunInputProvenance"]
