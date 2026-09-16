from io import StringIO

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


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
