"""Create the human requests coordination table."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260915_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE human_requests (
            request_id uuid PRIMARY KEY,
            subject_id text NOT NULL,
            application_id text NOT NULL,
            idempotency_key uuid NOT NULL,
            request_hash char(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
            kind text NOT NULL CHECK (kind IN ('approval', 'input')),
            prompt text NOT NULL CHECK (length(prompt) BETWEEN 1 AND 2000),
            status text NOT NULL CHECK (status IN ('pending', 'responded', 'expired', 'failed')),
            outcome text,
            answer text CHECK (answer IS NULL OR length(answer) BETWEEN 1 AND 4000),
            error_code text CHECK (
                error_code IS NULL OR error_code IN ('dependency_failure', 'internal')
            ),
            error_message text CHECK (
                error_message IS NULL OR length(error_message) BETWEEN 1 AND 500
            ),
            acs_call_connection_id text,
            created_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            completed_at timestamptz,
            CONSTRAINT uq_human_requests_subject_idempotency
                UNIQUE (subject_id, idempotency_key),
            CONSTRAINT ck_human_requests_lifecycle CHECK (
                (status = 'pending' AND outcome IS NULL AND answer IS NULL
                    AND error_code IS NULL AND error_message IS NULL AND completed_at IS NULL)
                OR
                (status = 'responded' AND completed_at IS NOT NULL AND (
                    (outcome IN ('approved', 'rejected') AND answer IS NULL)
                    OR (outcome = 'answered' AND answer IS NOT NULL)
                ) AND error_code IS NULL AND error_message IS NULL)
                OR
                (status = 'expired' AND completed_at IS NOT NULL
                    AND outcome IN (
                        'no_answer', 'busy', 'declined', 'disconnected',
                        'cancelled', 'deadline_exceeded'
                    ) AND answer IS NULL AND error_code IS NULL AND error_message IS NULL)
                OR
                (status = 'failed' AND completed_at IS NOT NULL AND outcome IS NULL
                    AND answer IS NULL AND error_code IS NOT NULL AND error_message IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_human_requests_one_pending
        ON human_requests ((status))
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE human_requests")
