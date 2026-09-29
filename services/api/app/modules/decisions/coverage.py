"""Analysis coverage (Gate 22): WHICH of the four user-facing analysis domains a `DecisionRun`
actually attempted, independent of what each domain's detectors concluded.

Coverage != outcome: a domain stays EVALUATED whether its detectors returned CLEAR, TRIGGERED,
INSUFFICIENT_DATA, NOT_APPLICABLE or SUPPRESSED_LOW_CONFIDENCE - this module only answers "did
NINFA even look here this run", never "what did it find". The four domains group the five
detector types the way an operator/hotel thinks about them, not the way the engine does:

    REVENUE       REV_PICKUP_LOW, REV_OCCUPANCY_RISK
    DISTRIBUTION  REV_OTA_DEPENDENCY
    COSTS         COST_CPOR_ANOMALY
    LABOR         LABOR_OVERSTAFFING

The production orchestrator (`app/cli/analysis.py`) is the ONE place that builds an
`AnalysisCoverage`, from the same decisions it already makes about which detectors to call -
never reconstructed afterward from `DecisionRun`'s own aggregate counts (Gate 22A's audit found
those counts are domain-blind and cannot be reverse-engineered into per-domain coverage).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

ANALYSIS_COVERAGE_VERSION = 1


class AnalysisDomain(StrEnum):
    REVENUE = "REVENUE"
    DISTRIBUTION = "DISTRIBUTION"
    COSTS = "COSTS"
    LABOR = "LABOR"


class DomainCoverageStatus(StrEnum):
    EVALUATED = "EVALUATED"
    SKIPPED = "SKIPPED"


class DomainSkipReason(StrEnum):
    """Deliberately one value in V1: every skip in this gate is a caller-side choice (an
    optional domain the operator did not request), never a runtime failure - a crashed detector
    never reaches here at all, because a failed analysis never calls `DecisionService.sync()`
    (Gate 21's fail-loud guarantee, unchanged)."""

    NOT_REQUESTED = "NOT_REQUESTED"


class CoverageSummary(StrEnum):
    """A derived, never-persisted view of an `AnalysisCoverage` (or its absence) - `AnalysisCoverage
    .summary` only ever returns FULL/PARTIAL; UNKNOWN exists solely for a run with no coverage
    recorded at all (`DecisionRun.analysis_coverage IS NULL`), which is never turned into a real
    `AnalysisCoverage` object."""

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DomainCoverage:
    domain: AnalysisDomain
    status: DomainCoverageStatus
    reason: DomainSkipReason | None = None

    def __post_init__(self) -> None:
        if self.status is DomainCoverageStatus.EVALUATED and self.reason is not None:
            raise ValueError("an EVALUATED domain must not carry a skip reason")
        if self.status is DomainCoverageStatus.SKIPPED and self.reason is None:
            raise ValueError("a SKIPPED domain must carry a reason")

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"domain": self.domain.value, "status": self.status.value}
        if self.reason is not None:
            payload["reason"] = self.reason.value
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "DomainCoverage":
        reason = payload.get("reason")
        return cls(
            domain=AnalysisDomain(payload["domain"]),
            status=DomainCoverageStatus(payload["status"]),
            reason=None if reason is None else DomainSkipReason(reason),
        )


@dataclass(frozen=True, slots=True)
class AnalysisCoverage:
    """Exactly one `DomainCoverage` per `AnalysisDomain`, no more, no fewer - a run that forgets
    to name a domain is a bug, not a valid "we don't know about that one" state (that state is
    `DecisionRun.analysis_coverage IS NULL` for the WHOLE run, handled entirely outside this type -
    see the module docstring)."""

    domains: tuple[DomainCoverage, ...]

    def __post_init__(self) -> None:
        named = tuple(item.domain for item in self.domains)
        if sorted(named, key=lambda d: d.value) != sorted(AnalysisDomain, key=lambda d: d.value):
            raise ValueError("AnalysisCoverage must name every AnalysisDomain exactly once")

    @property
    def summary(self) -> CoverageSummary:
        if all(item.status is DomainCoverageStatus.EVALUATED for item in self.domains):
            return CoverageSummary.FULL
        return CoverageSummary.PARTIAL

    def to_json(self) -> dict[str, Any]:
        return {
            "version": ANALYSIS_COVERAGE_VERSION,
            "domains": [item.to_json() for item in self.domains],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "AnalysisCoverage":
        if payload.get("version") != ANALYSIS_COVERAGE_VERSION:
            raise ValueError(f"unsupported analysis_coverage version: {payload.get('version')!r}")
        return cls(domains=tuple(DomainCoverage.from_json(item) for item in payload["domains"]))


__all__ = [
    "ANALYSIS_COVERAGE_VERSION",
    "AnalysisCoverage",
    "AnalysisDomain",
    "CoverageSummary",
    "DomainCoverage",
    "DomainCoverageStatus",
    "DomainSkipReason",
]
