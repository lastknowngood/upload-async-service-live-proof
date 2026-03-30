from __future__ import annotations

from datetime import UTC, datetime

from psycopg.rows import dict_row

from app.store import PostgresUploadStore


class FakeCursor:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row
        self.query: str | None = None
        self.parameters: tuple[object, ...] | None = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> None:
        self.query = query
        self.parameters = parameters

    def fetchone(self) -> dict[str, object]:
        return self._row


class FakeConnection:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row
        self.cursor_row_factory = None
        self.cursor_instance: FakeCursor | None = None

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self, *, row_factory=None):
        self.cursor_row_factory = row_factory
        self.cursor_instance = FakeCursor(self._row)
        return self.cursor_instance


def test_find_processing_hold_uses_dict_row_and_returns_upload_record(monkeypatch) -> None:
    now = datetime(2026, 3, 30, 20, 30, tzinfo=UTC)
    row = {
        'id': 'hold-upload',
        'filename': 'hold.txt',
        'content_type': 'text/plain',
        'source_payload': b'HOLD',
        'source_bytes_count': 4,
        'source_sha256': 'sha-hold',
        'status': 'processing',
        'attempt_count': 1,
        'available_at': now,
        'lease_expires_at': now,
        'proof_fail_once': False,
        'proof_fail_consumed': False,
        'proof_hold_state': 'armed',
        'artifact_state': 'pending',
        'artifact_key': 'uploads/hold-upload/artifact.json',
        'last_error_code': None,
        'created_at': now,
        'updated_at': now,
    }
    fake_connection = FakeConnection(row)
    store = PostgresUploadStore.__new__(PostgresUploadStore)
    store._database_url = 'postgresql://example.invalid/test'
    monkeypatch.setattr(store, '_connect', lambda: fake_connection)

    record = store.find_processing_hold()

    assert fake_connection.cursor_row_factory is dict_row
    assert fake_connection.cursor_instance is not None
    assert fake_connection.cursor_instance.query is not None
    assert 'WHERE status = \'processing\'' in fake_connection.cursor_instance.query
    assert fake_connection.cursor_instance.parameters is None
    assert record is not None
    assert record.upload_id == 'hold-upload'
    assert record.proof_hold_state == 'armed'
