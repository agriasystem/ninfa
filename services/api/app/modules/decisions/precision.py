"""Canonical, non-lossy text of a `Decimal`: RE-EXPORTED, not copied, from the Priority Engine's
own (itself re-exported from Gate 5's `revenue.precision`).

The Decision Layer never computes a score: it persists the exact `Decimal` values a detector or
the Priority Engine already produced. Reusing the same `canonical_text` keeps a fingerprint
comparison meaningful across gates (the same value always serialises to the same text, whichever
module hashes it) and means this gate cannot silently drift from the calculation it is recording.
"""

from app.modules.intelligence.priority.precision import canonical_text

__all__ = ["canonical_text"]
