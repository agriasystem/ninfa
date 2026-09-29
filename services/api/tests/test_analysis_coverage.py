"""app.modules.decisions.coverage: the Gate 22 typed analysis-coverage domain model, in isolation
from persistence (see test_decision_coverage_persistence.py for the DecisionService/DecisionRun
level) and from the CLI (see test_pilot_analysis_cli.py)."""

import pytest

from app.modules.decisions.coverage import (
    AnalysisCoverage,
    AnalysisDomain,
    CoverageSummary,
    DomainCoverage,
    DomainCoverageStatus,
    DomainSkipReason,
)

EVALUATED = DomainCoverageStatus.EVALUATED
SKIPPED = DomainCoverageStatus.SKIPPED
NOT_REQUESTED = DomainSkipReason.NOT_REQUESTED


def _full() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, EVALUATED),
            DomainCoverage(AnalysisDomain.LABOR, EVALUATED),
        )
    )


def _booking_only() -> AnalysisCoverage:
    return AnalysisCoverage(
        domains=(
            DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
            DomainCoverage(AnalysisDomain.DISTRIBUTION, EVALUATED),
            DomainCoverage(AnalysisDomain.COSTS, SKIPPED, NOT_REQUESTED),
            DomainCoverage(AnalysisDomain.LABOR, SKIPPED, NOT_REQUESTED),
        )
    )


def test_evaluated_domain_rejects_a_reason() -> None:
    with pytest.raises(ValueError, match="EVALUATED"):
        DomainCoverage(AnalysisDomain.REVENUE, EVALUATED, NOT_REQUESTED)


def test_skipped_domain_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="SKIPPED"):
        DomainCoverage(AnalysisDomain.COSTS, SKIPPED)


def test_coverage_requires_every_domain_named_exactly_once() -> None:
    with pytest.raises(ValueError, match="every AnalysisDomain"):
        AnalysisCoverage(
            domains=(
                DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
                DomainCoverage(AnalysisDomain.DISTRIBUTION, EVALUATED),
                DomainCoverage(AnalysisDomain.COSTS, EVALUATED),
            )
        )


def test_coverage_rejects_a_duplicated_domain() -> None:
    with pytest.raises(ValueError, match="every AnalysisDomain"):
        AnalysisCoverage(
            domains=(
                DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
                DomainCoverage(AnalysisDomain.REVENUE, EVALUATED),
                DomainCoverage(AnalysisDomain.COSTS, EVALUATED),
                DomainCoverage(AnalysisDomain.LABOR, EVALUATED),
            )
        )


def test_all_evaluated_summary_is_full() -> None:
    assert _full().summary is CoverageSummary.FULL


def test_any_skipped_domain_summary_is_partial() -> None:
    assert _booking_only().summary is CoverageSummary.PARTIAL


def test_evaluated_outcome_is_independent_of_what_was_found() -> None:
    """Coverage != outcome (the audit's own point): a domain being EVALUATED has nothing to do
    with what its detectors concluded - this type carries no outcome/status field at all, on
    purpose, so there is nothing here that COULD couple the two."""
    coverage = _full()
    assert {d.domain for d in coverage.domains} == set(AnalysisDomain)
    for domain_coverage in coverage.domains:
        assert domain_coverage.status is EVALUATED
        assert domain_coverage.reason is None


def test_to_json_round_trips_through_from_json() -> None:
    original = _booking_only()
    restored = AnalysisCoverage.from_json(original.to_json())
    assert restored == original


def test_to_json_shape_matches_the_documented_contract() -> None:
    payload = _booking_only().to_json()
    assert payload["version"] == 1
    costs = next(d for d in payload["domains"] if d["domain"] == "COSTS")
    assert costs == {"domain": "COSTS", "status": "SKIPPED", "reason": "NOT_REQUESTED"}
    revenue = next(d for d in payload["domains"] if d["domain"] == "REVENUE")
    assert revenue == {"domain": "REVENUE", "status": "EVALUATED"}  # no "reason" key at all


def test_from_json_rejects_an_unknown_version() -> None:
    with pytest.raises(ValueError, match="version"):
        AnalysisCoverage.from_json({"version": 99, "domains": []})
