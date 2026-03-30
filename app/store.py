import hashlib
import os
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, cast

import psycopg
from psycopg.rows import dict_row

from .models import ArtifactState, ProofHoldState, StoredUpload, UploadRecord, UploadStatus

UPLOAD_SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS uploads (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    source_payload BYTEA NOT NULL,
    source_bytes_count INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_expires_at TIMESTAMPTZ NULL,
    proof_fail_once BOOLEAN NOT NULL DEFAULT false,
    proof_fail_consumed BOOLEAN NOT NULL DEFAULT false,
    proof_hold_state TEXT NOT NULL DEFAULT 'none',
    artifact_state TEXT NOT NULL DEFAULT 'pending',
    artifact_key TEXT NOT NULL,
    last_error_code TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
'''

UPLOAD_INDEX_SQL = '''
CREATE INDEX IF NOT EXISTS idx_uploads_claim
ON uploads (status, available_at, lease_expires_at, created_at);
'''


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def compute_sha256(source_payload: bytes) -> str:
    return hashlib.sha256(source_payload).hexdigest()


def build_artifact_key(upload_id: str) -> str:
    return f'uploads/{upload_id}/artifact.json'


def _row_to_upload(row: dict[str, object]) -> StoredUpload:
    return StoredUpload(
        upload_id=str(row['id']),
        filename=str(row['filename']),
        content_type=str(row['content_type']),
        source_payload=cast(bytes, row['source_payload']),
        source_bytes=int(cast(int, row['source_bytes_count'])),
        source_sha256=str(row['source_sha256']),
        status=cast(UploadStatus, row['status']),
        attempt_count=int(cast(int, row['attempt_count'])),
        available_at=cast(datetime, row['available_at']),
        lease_expires_at=cast(datetime | None, row['lease_expires_at']),
        proof_fail_once=bool(row['proof_fail_once']),
        proof_fail_consumed=bool(row['proof_fail_consumed']),
        proof_hold_state=cast(ProofHoldState, row['proof_hold_state']),
        artifact_state=cast(ArtifactState, row['artifact_state']),
        artifact_key=str(row['artifact_key']),
        last_error_code=cast(str | None, row['last_error_code']),
        created_at=cast(datetime, row['created_at']),
        updated_at=cast(datetime, row['updated_at']),
    )


class UploadStore:
    def create_upload(
        self,
        *,
        filename: str,
        content_type: str,
        source_payload: bytes,
        proof_fail_once: bool,
        proof_hold: bool,
    ) -> UploadRecord:
        raise NotImplementedError

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        raise NotImplementedError

    def claim_due_upload(
        self,
        *,
        now: datetime,
        lease_timeout_seconds: float,
    ) -> StoredUpload | None:
        raise NotImplementedError

    def mark_retry_wait(
        self,
        upload_id: str,
        *,
        now: datetime,
        retry_delay_seconds: float,
        error_code: str,
    ) -> UploadRecord | None:
        raise NotImplementedError

    def mark_completed(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        raise NotImplementedError

    def mark_artifact_missing(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        raise NotImplementedError

    def enqueue_rematerialize(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        raise NotImplementedError

    def find_processing_hold(self) -> UploadRecord | None:
        raise NotImplementedError

    def release_hold(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        raise NotImplementedError


class InMemoryUploadStore(UploadStore):
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, StoredUpload] = {}

    def create_upload(
        self,
        *,
        filename: str,
        content_type: str,
        source_payload: bytes,
        proof_fail_once: bool,
        proof_hold: bool,
    ) -> UploadRecord:
        now = utcnow()
        upload_id = str(uuid.uuid4())
        item = StoredUpload(
            upload_id=upload_id,
            filename=filename,
            content_type=content_type,
            source_payload=source_payload,
            source_bytes=len(source_payload),
            source_sha256=compute_sha256(source_payload),
            status='queued',
            attempt_count=0,
            available_at=now,
            lease_expires_at=None,
            proof_fail_once=proof_fail_once,
            proof_fail_consumed=False,
            proof_hold_state='armed' if proof_hold else 'none',
            artifact_state='pending',
            artifact_key=build_artifact_key(upload_id),
            last_error_code=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._items[upload_id] = item
        return item.to_record()

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            return None if item is None else item.to_record()

    def claim_due_upload(
        self,
        *,
        now: datetime,
        lease_timeout_seconds: float,
    ) -> StoredUpload | None:
        with self._lock:
            candidates = sorted(self._items.values(), key=lambda item: item.created_at)
            for item in candidates:
                due = item.status == 'queued'
                due = due or (item.status == 'retry_wait' and item.available_at <= now)
                due = due or (
                    item.status == 'processing'
                    and item.lease_expires_at is not None
                    and item.lease_expires_at <= now
                )
                if not due:
                    continue
                claimed = replace(
                    item,
                    status='processing',
                    attempt_count=item.attempt_count + 1,
                    lease_expires_at=now + timedelta(seconds=lease_timeout_seconds),
                    updated_at=now,
                )
                self._items[item.upload_id] = claimed
                return claimed
        return None

    def mark_retry_wait(
        self,
        upload_id: str,
        *,
        now: datetime,
        retry_delay_seconds: float,
        error_code: str,
    ) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None:
                return None
            updated = replace(
                item,
                status='retry_wait',
                available_at=now + timedelta(seconds=retry_delay_seconds),
                lease_expires_at=None,
                proof_fail_consumed=True,
                last_error_code=error_code,
                updated_at=now,
            )
            self._items[upload_id] = updated
            return updated.to_record()

    def mark_completed(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None:
                return None
            updated = replace(
                item,
                status='completed',
                lease_expires_at=None,
                artifact_state='present',
                last_error_code=None,
                updated_at=now,
            )
            self._items[upload_id] = updated
            return updated.to_record()

    def mark_artifact_missing(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None:
                return None
            updated = replace(item, artifact_state='missing', updated_at=now)
            self._items[upload_id] = updated
            return updated.to_record()

    def enqueue_rematerialize(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None:
                return None
            updated = replace(
                item,
                status='queued',
                available_at=now,
                lease_expires_at=None,
                artifact_state='rematerializing',
                last_error_code=None,
                updated_at=now,
            )
            self._items[upload_id] = updated
            return updated.to_record()

    def find_processing_hold(self) -> UploadRecord | None:
        with self._lock:
            candidates = sorted(self._items.values(), key=lambda item: item.created_at)
            for item in candidates:
                if item.status == 'processing' and item.proof_hold_state == 'armed':
                    return item.to_record()
        return None

    def release_hold(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None:
                return None
            updated = replace(item, proof_hold_state='released', updated_at=now)
            self._items[upload_id] = updated
            return updated.to_record()


class PostgresUploadStore(UploadStore):
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self.ensure_schema()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._database_url)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(UPLOAD_SCHEMA_SQL)
                cur.execute(UPLOAD_INDEX_SQL)
            conn.commit()

    def create_upload(
        self,
        *,
        filename: str,
        content_type: str,
        source_payload: bytes,
        proof_fail_once: bool,
        proof_hold: bool,
    ) -> UploadRecord:
        now = utcnow()
        upload_id = str(uuid.uuid4())
        artifact_key = build_artifact_key(upload_id)
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    '''
                    INSERT INTO uploads (
                        id,
                        filename,
                        content_type,
                        source_payload,
                        source_bytes_count,
                        source_sha256,
                        status,
                        attempt_count,
                        available_at,
                        lease_expires_at,
                        proof_fail_once,
                        proof_fail_consumed,
                        proof_hold_state,
                        artifact_state,
                        artifact_key,
                        last_error_code,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        'queued', 0, %s, NULL, %s, false, %s, 'pending', %s, NULL, %s, %s
                    )
                    RETURNING *
                    ''',
                    (
                        upload_id,
                        filename,
                        content_type,
                        source_payload,
                        len(source_payload),
                        compute_sha256(source_payload),
                        now,
                        proof_fail_once,
                        'armed' if proof_hold else 'none',
                        artifact_key,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError('create_upload returned no row')
        return _row_to_upload(row).to_record()

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute('SELECT * FROM uploads WHERE id = %s', (upload_id,))
                row = cur.fetchone()
        return None if row is None else _row_to_upload(cast(dict[str, object], row)).to_record()

    def claim_due_upload(
        self,
        *,
        now: datetime,
        lease_timeout_seconds: float,
    ) -> StoredUpload | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    '''
                    WITH candidate AS (
                        SELECT id
                        FROM uploads
                        WHERE
                            status = 'queued'
                            OR (status = 'retry_wait' AND available_at <= %s)
                            OR (
                                status = 'processing'
                                AND lease_expires_at IS NOT NULL
                                AND lease_expires_at <= %s
                            )
                        ORDER BY created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE uploads AS target
                    SET
                        status = 'processing',
                        attempt_count = target.attempt_count + 1,
                        lease_expires_at = %s,
                        updated_at = %s
                    FROM candidate
                    WHERE target.id = candidate.id
                    RETURNING target.*
                    ''',
                    (
                        now,
                        now,
                        now + timedelta(seconds=lease_timeout_seconds),
                        now,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return None if row is None else _row_to_upload(row)

    def mark_retry_wait(
        self,
        upload_id: str,
        *,
        now: datetime,
        retry_delay_seconds: float,
        error_code: str,
    ) -> UploadRecord | None:
        return self._update_returning(
            '''
            UPDATE uploads
            SET
                status = 'retry_wait',
                available_at = %s,
                lease_expires_at = NULL,
                proof_fail_consumed = true,
                last_error_code = %s,
                updated_at = %s
            WHERE id = %s
            RETURNING *
            ''',
            (now + timedelta(seconds=retry_delay_seconds), error_code, now, upload_id),
        )

    def mark_completed(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        return self._update_returning(
            '''
            UPDATE uploads
            SET
                status = 'completed',
                lease_expires_at = NULL,
                artifact_state = 'present',
                last_error_code = NULL,
                updated_at = %s
            WHERE id = %s
            RETURNING *
            ''',
            (now, upload_id),
        )

    def mark_artifact_missing(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        return self._update_returning(
            '''
            UPDATE uploads
            SET
                artifact_state = 'missing',
                updated_at = %s
            WHERE id = %s
            RETURNING *
            ''',
            (now, upload_id),
        )

    def enqueue_rematerialize(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        return self._update_returning(
            '''
            UPDATE uploads
            SET
                status = 'queued',
                available_at = %s,
                lease_expires_at = NULL,
                artifact_state = 'rematerializing',
                last_error_code = NULL,
                updated_at = %s
            WHERE id = %s
            RETURNING *
            ''',
            (now, now, upload_id),
        )

    def find_processing_hold(self) -> UploadRecord | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    '''
                    SELECT *
                    FROM uploads
                    WHERE status = 'processing' AND proof_hold_state = 'armed'
                    ORDER BY created_at ASC
                    LIMIT 1
                    '''
                )
                row = cur.fetchone()
        return None if row is None else _row_to_upload(cast(dict[str, object], row)).to_record()

    def release_hold(self, upload_id: str, *, now: datetime) -> UploadRecord | None:
        return self._update_returning(
            '''
            UPDATE uploads
            SET
                proof_hold_state = 'released',
                updated_at = %s
            WHERE id = %s
            RETURNING *
            ''',
            (now, upload_id),
        )

    def _update_returning(
        self,
        statement: str,
        parameters: tuple[object, ...],
    ) -> UploadRecord | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(cast(Any, statement), parameters)
                row = cur.fetchone()
            conn.commit()
        return None if row is None else _row_to_upload(row).to_record()


def build_default_store() -> UploadStore:
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL is required for default application startup.')
    return PostgresUploadStore(database_url)


def read_uploads_for_restore(database_url: str, upload_ids: Sequence[str]) -> list[StoredUpload]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                '''
                SELECT *
                FROM uploads
                WHERE id = ANY(%s)
                ORDER BY created_at ASC
                ''',
                (list(upload_ids),),
            )
            rows = cur.fetchall()
    return [_row_to_upload(row) for row in rows]
