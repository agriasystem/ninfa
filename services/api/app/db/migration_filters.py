"""Alembic object filter shared by env.py and the model/migration drift test."""

from typing import Any

# Tables created and versioned by third-party schemas (Procrastinate, see migration 0002).
EXTERNALLY_MANAGED_PREFIXES = ("procrastinate_",)


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Ignore objects that are not described by our ORM metadata."""
    if type_ == "table" and name is not None:
        return not name.startswith(EXTERNALLY_MANAGED_PREFIXES)
    return True
