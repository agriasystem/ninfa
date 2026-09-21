"""Revenue Decision Detection V1 (Gate 5): REV_PICKUP_LOW and REV_OCCUPANCY_RISK.

A DETECTOR produces a typed, immutable, auditable EVALUATION (a status plus the facts behind it).
It persists nothing: there is no Decision table yet, and nothing here is a recommendation, a
priority, a price or an alert. See docs/architecture/revenue-decisions-v1.md and ADR 0011.

    types         statuses, reason codes, thresholds, facts and the evaluation model
    errors        stable error codes for requests that cannot be answered at all
    pairing       historical curve pairs from the Gate 4 comparables (observed-first)
    statistics    median / P25 / P75 / IQR of the historical deltas (the Gate 4 algorithms)
    confidence    curve-pattern confidence and the final (conservative) confidence
    pattern       pairs + statistics + confidence, shared by both detectors
    precision     decision values vs displayed values: quotients, display rounding, canonical text
    impact        reference ADR and the revenue gap proxy (a gross exposure, NOT a loss)
    pickup        the REV_PICKUP_LOW detector
    occupancy     the REV_OCCUPANCY_RISK detector (with its minimal net-pickup projection)
    fingerprint   the deterministic SHA-256 of an evaluation, and the one place that builds it
    service       the read-only application service over the immutable Gate 3/4 data
"""
