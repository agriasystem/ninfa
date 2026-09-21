"""Cost CPOR Anomaly Detection V1 (Gate 7): COST_CPOR_ANOMALY.

A DETECTOR produces a typed, immutable, auditable EVALUATION (a status plus the facts behind it).
It persists nothing: there is no Decision table yet, and nothing here is a recommendation, a
priority, a saving or an alert. See docs/architecture/cost-cpor-anomaly-v1.md and ADR 0013.

CPOR (cost per occupied room) of ONE category and ONE currency in ONE calendar month is

    net category cost of the month  /  occupied-room-night PROXY of the same month

the numerator is the signed sum of the canonical Gate 6 invoice lines attributed to the month by
their invoice date; the denominator is the sum of the lead-time-0 `rooms_on_books` of the Gate 3
snapshots of an explicit BOOKINGS data source. It is an operating proxy, NOT a certified actual
occupancy.

    types         statuses, reason codes, thresholds, the period metric and the evaluation model
    errors        stable error codes for requests that cannot be answered at all
    precision     decision values vs displayed values (the Gate 5 rules, one implementation)
    periods       the calendar month, month arithmetic, the circular season distance
    occupancy     the lead-time-0 occupied-room-night denominator (complete or not, never zero)
    aggregation   the cost side of a period and the assembly of a CostPeriodMetric
    selection     historical comparable months (36 months, season window, 5..12, observed-first)
    statistics    median / P25 / P75 / IQR / upper fence of the CPORs, full-precision Decimal
    confidence    baseline confidence, target quality and the final (conservative) confidence
    detector      the COST_CPOR_ANOMALY rule: metric + comparables -> a sealed evaluation
    fingerprint   the deterministic SHA-256 of a metric and of an evaluation
    service       the read-only application service over the immutable Gate 3 / Gate 6 data
"""
