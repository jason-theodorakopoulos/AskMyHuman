from io import StringIO
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_encoded_database_url_runs_offline_without_disclosing_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database_url = "postgresql://probe:dummy%40password%25@localhost/probe"
    monkeypatch.setenv("DATABASE_URL", database_url)
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)

    command.upgrade(config, "head", sql=True)

    assert "CREATE TABLE human_requests" in output.getvalue()
    assert config.get_main_option("sqlalchemy.url") == database_url.replace(
        "postgresql://", "postgresql+psycopg://"
    )
    captured = capsys.readouterr()
    assert "dummy" not in output.getvalue() + captured.out + captured.err


def test_initial_migration_creates_table_constraints_and_pending_index(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert "human_requests" in inspector.get_table_names()
        assert {column["name"] for column in inspector.get_columns("human_requests")} >= {
            "request_id",
            "subject_id",
            "application_id",
            "idempotency_key",
            "phone_number",
            "status",
            "outcome",
            "error_code",
            "error_message",
            "completed_at",
        }
        assert any(
            constraint["name"] == "uq_human_requests_subject_idempotency"
            for constraint in inspector.get_unique_constraints("human_requests")
        )
        pending_index = next(
            index
            for index in inspector.get_indexes("human_requests")
            if index["name"] == "uq_human_requests_one_pending"
        )
        assert pending_index["unique"] is True
        assert "status = 'pending'" in str(pending_index["dialect_options"])
    finally:
        engine.dispose()


def test_phone_number_migration_fails_legacy_pending_closed_and_preserves_terminal_history(
    database_url: str,
) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "20260916_0002")
    engine = create_engine(database_url)
    pending_id = uuid4()
    terminal_id = uuid4()
    try:
        with engine.begin() as connection:
            for request_id, status, outcome, completed_at in (
                (pending_id, "pending", None, None),
                (terminal_id, "expired", "no_answer", "now()"),
            ):
                connection.execute(
                    text(
                        f"""
                        INSERT INTO human_requests (
                            request_id, subject_id, application_id, idempotency_key,
                            request_hash, kind, prompt, status, outcome, created_at,
                            expires_at, completed_at, recognition_started
                        ) VALUES (
                            :request_id, :subject_id, 'application', :idempotency_key,
                            :request_hash, 'approval', 'Legacy request', :status, :outcome,
                            now(), now(), {completed_at or "NULL"}, false
                        )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "subject_id": str(request_id),
                        "idempotency_key": uuid4(),
                        "request_hash": "a" * 64,
                        "status": status,
                        "outcome": outcome,
                    },
                )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            pending = connection.execute(
                text(
                    "SELECT status, error_code, phone_number FROM human_requests "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": pending_id},
            ).one()
            terminal = connection.execute(
                text(
                    "SELECT status, outcome, phone_number FROM human_requests "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": terminal_id},
            ).one()
        assert pending == ("failed", "dependency_failure", None)
        assert terminal == ("expired", "no_answer", None)
    finally:
        command.upgrade(config, "head")
        engine.dispose()


@pytest.mark.parametrize("phone_number", [None, "555-555-0101"])
def test_database_rejects_pending_rows_without_valid_e164_destination(
    database_url: str,
    phone_number: str | None,
) -> None:
    engine = create_engine(database_url)
    try:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO human_requests (
                        request_id, subject_id, application_id, idempotency_key,
                        request_hash, kind, prompt, phone_number, status,
                        created_at, expires_at, recognition_started
                    ) VALUES (
                        :request_id, :subject_id, 'application', :idempotency_key,
                        :request_hash, 'approval', 'Request', :phone_number, 'pending',
                        now(), now(), false
                    )
                    """
                ),
                {
                    "request_id": uuid4(),
                    "subject_id": str(uuid4()),
                    "idempotency_key": uuid4(),
                    "request_hash": "a" * 64,
                    "phone_number": phone_number,
                },
            )
    finally:
        engine.dispose()
