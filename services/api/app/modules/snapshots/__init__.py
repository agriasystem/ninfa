"""Gate 3: room inventory and the daily "on the books" snapshots derived from canonical bookings.

Two things are stored here and they are never the same thing:

* an OBSERVATION: what the canonical bookings said when NINFA looked at them (`OBSERVED`);
* a RECONSTRUCTION: what NINFA can infer *today* about an earlier day (`RECONSTRUCTED_APPROXIMATE`).

See docs/architecture/booking-snapshots-v1.md and ADR 0009.
"""
