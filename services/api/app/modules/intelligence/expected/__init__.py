"""Expected Engine V1 (Gate 4): what rooms-on-books level was *normally* seen for comparable stays.

EXPECTED, not a forecast: "historically, for comparable stay dates, at this distance from the
stay, the typical level was N rooms". It says nothing about how a stay will end and it never
raises an alert or a decision. See docs/architecture/expected-engine-v1.md and ADR 0010.

Layout (pure functions first, persistence last):

    seasonality   calendar rules: weekday, +-42 day season (year ignored), 730-day horizon
    selection     which stored snapshots are comparable, observed-first, quality filtering
    statistics    median, P25/P75 (linear interpolation) and IQR in Decimal
    confidence    baseline confidence 0-100 from sample, provenance and stability
    calculator    the whole calculation for a (stay date, lead time) target + the fingerprint
    models / repository / service   the persistent, immutable baseline and its comparables
"""
