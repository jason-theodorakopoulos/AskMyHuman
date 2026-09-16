"""Add a durable once-only recognition claim."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0002"
down_revision: str | None = "20260915_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE human_requests ADD COLUMN recognition_started boolean NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE human_requests DROP COLUMN recognition_started")
