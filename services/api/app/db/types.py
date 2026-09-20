"""Helpers to store Python enums as plain VARCHAR guarded by a named CHECK constraint.

PostgreSQL ENUM types are hard to evolve (values cannot be removed, ADD VALUE has transaction
restrictions). VARCHAR + CHECK is changed with an ordinary migration, which keeps V1 value sets
(roles, statuses, domains, ...) easy to extend.
"""

from enum import StrEnum

from sqlalchemy import Enum


def enum_column(enum_cls: type[StrEnum], length: int) -> Enum:
    """Column type storing the enum *values* (not names) as VARCHAR(length)."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        create_constraint=False,  # the CHECK is declared explicitly, with a stable name
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def values_check(column: str, enum_cls: type[StrEnum]) -> str:
    """SQL for `column IN ('A', 'B', ...)` built from the enum values."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"
