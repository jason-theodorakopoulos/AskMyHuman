"""Persist the caller-supplied human phone number."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260917_0003"
down_revision: str | None = "20260916_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE human_requests ADD COLUMN phone_number text")
    op.execute(
        """
        UPDATE human_requests
        SET status = 'failed',
            error_code = 'dependency_failure',
            error_message = 'Legacy request cannot resume without a destination.',
            completed_at = now()
        WHERE status = 'pending'
        """
    )
    op.execute(
        """
        ALTER TABLE human_requests
        ADD CONSTRAINT ck_human_requests_phone_number CHECK (
            (status <> 'pending' OR phone_number IS NOT NULL)
            AND (phone_number IS NULL OR phone_number ~ '^[+][1-9][0-9]{1,14}$')
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE human_requests DROP CONSTRAINT ck_human_requests_phone_number")
    op.execute("ALTER TABLE human_requests DROP COLUMN phone_number")
