"""Baseline: empty schema.

Gate 0 has no business tables. This revision only establishes the Alembic history so that
`alembic upgrade head` works end to end from day one.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
