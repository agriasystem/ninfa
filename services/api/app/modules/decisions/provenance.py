"""Run input provenance (Gate 23B): from WHICH booking import a `DecisionRun`'s freshness was
frozen at analysis time - never a dynamic "latest import" query made later, when Oggi is opened.

Provenance != coverage (`app.modules.decisions.coverage`): coverage answers "which of the four
user-facing domains did this run attempt"; provenance answers "from which input/source freshness
did this run's facts derive". A property can have more than one BOOKINGS `DataSource`, and a run
uses exactly one of them - provenance records THAT ONE, never a property-wide/domain-wide MAX
across every booking source the property happens to have.

The booking fact recorded is deliberately narrow: "the latest import that changed the bookings, for
the EXACT booking data source this run used, when it looked" - never "the file this run's numbers
came from" (canonical booking state is cumulative/upserted across many imports, so no single import
is "the" source of a run's facts) and never a judgement like CURRENT/STALE (no freshness threshold
exists in V1). A file that brought nothing new moves nothing here: analysing again after one is the
same run. `observation` says which observation of its day the run read: with
`BookingSnapshotRepository.list_for_snapshot_date(as_of_revision=...)` its input can be read back as
it was, whatever came later that day.

Labor and costs say the same of their own kind of data, when the run looked at them: which import
last changed it and, for labor, which files the evaluations read. The two are absent from the JSON
of a run that did not look at them, and from every run recorded before they existed.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    snapshot_local_date: date | None = None
    observation_revision: int | None = None

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
        payload: dict[str, Any] = {
            "data_source_id": str(self.data_source_id),
            "last_successful_import_job_id": (
                None if self.import_job_id is None else str(self.import_job_id)
            ),
            "last_successful_import_finished_at": (
                None if finished_at is None else finished_at.astimezone(UTC).isoformat()
            ),
        }
        if self.snapshot_local_date is not None and self.observation_revision is not None:
            payload["observation"] = {
                "snapshot_local_date": self.snapshot_local_date.isoformat(),
                "revision": self.observation_revision,
            }
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BookingProvenance":
        job_id = payload["last_successful_import_job_id"]
        finished_at = payload["last_successful_import_finished_at"]
        observation = payload.get("observation")
        return cls(
            data_source_id=UUID(payload["data_source_id"]),
            import_job_id=None if job_id is None else UUID(job_id),
            last_successful_import_finished_at=(
                None if finished_at is None else datetime.fromisoformat(finished_at)
            ),
            snapshot_local_date=(
                None
                if observation is None
                else date.fromisoformat(observation["snapshot_local_date"])
            ),
            observation_revision=None if observation is None else observation["revision"],
        )


@dataclass(frozen=True, slots=True)
class DomainProvenance:
    """Which import last changed a kind of data the run looked at (None: none is known), and which
    labor files its evaluations read (`snapshot_ids`, sorted; empty for costs)."""

    data_source_id: UUID | None
    import_job_id: UUID | None
    snapshot_ids: tuple[UUID, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "data_source_id": None if self.data_source_id is None else str(self.data_source_id),
            "import_job_id": None if self.import_job_id is None else str(self.import_job_id),
            "snapshot_ids": [str(snapshot_id) for snapshot_id in self.snapshot_ids],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DomainProvenance":
        source_id = payload["data_source_id"]
        job_id = payload["import_job_id"]
        return cls(
            data_source_id=None if source_id is None else UUID(source_id),
            import_job_id=None if job_id is None else UUID(job_id),
            snapshot_ids=tuple(UUID(snapshot_id) for snapshot_id in payload["snapshot_ids"]),
        )


@dataclass(frozen=True, slots=True)
class RunInputProvenance:
    """Exactly one booking provenance fact per run, and the labor and cost ones when the run looked
    at them."""

    bookings: BookingProvenance
    labor: DomainProvenance | None = None
    costs: DomainProvenance | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": PROVENANCE_VERSION,
            "bookings": self.bookings.to_json(),
        }
        if self.labor is not None:
            payload["labor"] = self.labor.to_json()
        if self.costs is not None:
            payload["costs"] = self.costs.to_json()
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "RunInputProvenance":
        if payload.get("version") != PROVENANCE_VERSION:
            raise ValueError(f"unsupported input_provenance version: {payload.get('version')!r}")
        labor = payload.get("labor")
        costs = payload.get("costs")
        return cls(
            bookings=BookingProvenance.from_json(payload["bookings"]),
            labor=None if labor is None else DomainProvenance.from_json(labor),
            costs=None if costs is None else DomainProvenance.from_json(costs),
        )


__all__ = ["PROVENANCE_VERSION", "BookingProvenance", "DomainProvenance", "RunInputProvenance"]
