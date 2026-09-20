"""Bookings: canonical booking model and the file-based booking import (CSV / XLSX).

Pipeline (see docs/architecture/booking-data-v1.md):
source file -> parse -> map -> normalise -> validate -> stage -> atomic canonical upsert.
No metrics, snapshots or decisions live here: those start in later gates.
"""
