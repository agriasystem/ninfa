"""OTA Dependency Detection V1 (Gate 9): REV_OTA_DEPENDENCY.

A DETECTOR produces a typed, immutable, auditable EVALUATION (a status plus the facts behind it).
It persists nothing: there is no Decision table yet, and nothing here is a recommendation, a
priority, a commission model or a channel-performance judgement. See
docs/architecture/ota-dependency-v1.md and ADR 0015.

REV_OTA_DEPENDENCY measures ONE thing: how CONCENTRATED the property's next 30 days of room-night
business already on the books is on OTA channels, and whether that concentration is structurally
high or is rising sharply versus comparable history. It never judges whether a channel performs
well, converts, is profitable or should be closed.

    types         statuses, reason codes, thresholds, the channel/period facts, the evaluation
    channels      the read-only, conservative channel classifier (no fuzzy matching, no writes)
    temporal      Gate 3's own booking-certainty-window rule, re-exported (not reimplemented)
    precision     decision values vs displayed values (the Gate 5 rules, re-exported)
    metrics       one 30-day period's channel-mix room-night (and optional revenue) totals
    selection     historical comparable 30-day periods (730-day lookback, season window, 5..24)
    statistics    median / P25 / P75 / IQR / upper fence of the OTA shares, full-precision Decimal
    confidence    baseline confidence, target quality and the final (conservative) confidence
    detector      the REV_OTA_DEPENDENCY rule: channel mix + comparables -> a sealed evaluation
    fingerprint   the deterministic SHA-256 of an evaluation
    errors        stable error codes for requests that cannot be answered at all
    repository    set-based, read-only access to bookings, channels and snapshots
    service       the read-only application service over the immutable Gate 2/3 data
"""
