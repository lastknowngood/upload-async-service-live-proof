import os
from threading import Event
from time import monotonic, sleep

import boto3
import pytest
from botocore.client import Config
from fastapi.testclient import TestClient

from app.main import MARKER, create_app
from app.object_store import InMemoryArtifactStore, S3ArtifactStore
from app.store import InMemoryUploadStore, PostgresUploadStore

TEST_DATABASE_URL = os.getenv('TEST_DATABASE_URL')
TEST_OBJECT_STORAGE_ENDPOINT = os.getenv('TEST_OBJECT_STORAGE_ENDPOINT')
TEST_OBJECT_STORAGE_BUCKET = os.getenv('TEST_OBJECT_STORAGE_BUCKET')
TEST_OBJECT_STORAGE_ACCESS_KEY_ID = os.getenv('TEST_OBJECT_STORAGE_ACCESS_KEY_ID')
TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY = os.getenv('TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY')


def wait_for_status(
    client: TestClient,
    upload_id: str,
    expected_status: str,
    *,
    timeout_seconds: float = 3.0,
) -> dict[str, object]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        response = client.get(f'/uploads/{upload_id}')
        assert response.status_code == 200
        payload = response.json()
        if payload['status'] == expected_status:
            return payload
        sleep(0.02)
    raise AssertionError(f'upload {upload_id} did not reach {expected_status!r} in time')


def create_test_client(
    *,
    store: InMemoryUploadStore | PostgresUploadStore | None = None,
    artifact_store: InMemoryArtifactStore | S3ArtifactStore | None = None,
    proof_mode: bool = True,
    terminator_event: Event | None = None,
) -> TestClient:
    store_instance = store or InMemoryUploadStore()
    artifact_instance = artifact_store or InMemoryArtifactStore()
    terminated = terminator_event or Event()

    def terminate() -> None:
        terminated.set()

    return TestClient(
        create_app(
            store_factory=lambda: store_instance,
            artifact_store_factory=lambda: artifact_instance,
            proof_mode=proof_mode,
            poll_interval_seconds=0.02,
            lease_timeout_seconds=0.08,
            retry_delay_seconds=0.05,
            upload_max_bytes=262144,
            terminator=terminate,
        )
    )


def test_upload_flow_in_memory() -> None:
    with create_test_client() as client:
        health = client.get('/healthz')
        assert health.status_code == 200
        assert health.json()['store'] == 'InMemoryUploadStore'
        assert health.json()['artifact_store'] == 'InMemoryArtifactStore'
        assert health.json()['build_revision'] == 'development'
        assert health.json()['proof_mode'] is True
        assert (
            health.headers['x-robots-tag']
            == 'noindex, nofollow, noarchive, noimageindex, nosnippet'
        )

        index = client.get('/')
        assert index.status_code == 200
        assert MARKER in index.text
        assert (
            index.headers['x-robots-tag']
            == 'noindex, nofollow, noarchive, noimageindex, nosnippet'
        )

        robots = client.get('/robots.txt')
        assert robots.status_code == 200
        assert robots.text == 'User-agent: *\nDisallow: /\n'

        created = client.post(
            '/uploads',
            files={'file': ('alpha.txt', b'ALPHA\n', 'text/plain')},
        )
        assert created.status_code == 201
        upload_id = created.json()['upload_id']

        completed = wait_for_status(client, upload_id, 'completed')
        assert completed['artifact_state'] == 'present'
        assert completed['source_bytes'] == 6
        assert completed['attempt_count'] == 1

        artifact = client.get(f'/uploads/{upload_id}/artifact')
        assert artifact.status_code == 200
        assert artifact.json()['upload_id'] == upload_id
        assert artifact.json()['source_bytes'] == 6


def test_fail_once_hold_and_rematerialize_in_memory() -> None:
    store = InMemoryUploadStore()
    artifact_store = InMemoryArtifactStore()
    terminated = Event()

    with create_test_client(
        store=store,
        artifact_store=artifact_store,
        terminator_event=terminated,
    ) as client:
        fail_once = client.post(
            '/uploads',
            data={'proof_fail_once': 'true'},
            files={'file': ('retry.txt', b'RETRY', 'text/plain')},
        )
        assert fail_once.status_code == 201
        fail_once_id = fail_once.json()['upload_id']
        completed_retry = wait_for_status(client, fail_once_id, 'completed')
        assert completed_retry['attempt_count'] == 2

        held = client.post(
            '/uploads',
            data={'proof_hold': 'true'},
            files={'file': ('hold.txt', b'HOLD', 'text/plain')},
        )
        assert held.status_code == 201
        held_id = held.json()['upload_id']

        processing = wait_for_status(client, held_id, 'processing')
        assert processing['proof_hold_state'] == 'armed'

        terminate = client.post('/proof/terminate-worker')
        assert terminate.status_code == 202
        assert terminate.json()['upload_id'] == held_id

        deadline = monotonic() + 2.0
        while monotonic() < deadline and not terminated.is_set():
            sleep(0.02)
        assert terminated.is_set()

    with create_test_client(store=store, artifact_store=artifact_store) as restarted:
        completed_hold = wait_for_status(restarted, held_id, 'completed')
        assert completed_hold['proof_hold_state'] == 'released'
        assert completed_hold['attempt_count'] == 2

        artifact_store.delete_key(str(completed_hold['artifact_key']))
        rematerialize = restarted.post(f'/uploads/{held_id}/artifact/rematerialize')
        assert rematerialize.status_code == 202
        rematerialized = wait_for_status(restarted, held_id, 'completed')
        assert rematerialized['artifact_state'] == 'present'

        artifact = restarted.get(f'/uploads/{held_id}/artifact')
        assert artifact.status_code == 200
        assert artifact.json()['proof_hold_state'] == 'released'


@pytest.mark.integration
@pytest.mark.skipif(
    not all(
        [
            TEST_DATABASE_URL,
            TEST_OBJECT_STORAGE_ENDPOINT,
            TEST_OBJECT_STORAGE_BUCKET,
            TEST_OBJECT_STORAGE_ACCESS_KEY_ID,
            TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY,
        ]
    ),
    reason='Integration environment for PostgreSQL and object storage is not configured',
)
def test_upload_flow_with_postgres_and_s3() -> None:
    assert TEST_DATABASE_URL is not None
    assert TEST_OBJECT_STORAGE_ENDPOINT is not None
    assert TEST_OBJECT_STORAGE_BUCKET is not None
    assert TEST_OBJECT_STORAGE_ACCESS_KEY_ID is not None
    assert TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY is not None

    s3_client = boto3.client(
        's3',
        endpoint_url=TEST_OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=TEST_OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY,
        region_name='us-east-1',
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    )
    buckets = [bucket['Name'] for bucket in s3_client.list_buckets().get('Buckets', [])]
    if TEST_OBJECT_STORAGE_BUCKET not in buckets:
        s3_client.create_bucket(Bucket=TEST_OBJECT_STORAGE_BUCKET)

    prefix = 'integration'
    existing = s3_client.list_objects_v2(Bucket=TEST_OBJECT_STORAGE_BUCKET, Prefix=prefix)
    for item in existing.get('Contents', []):
        s3_client.delete_object(Bucket=TEST_OBJECT_STORAGE_BUCKET, Key=item['Key'])

    store = PostgresUploadStore(TEST_DATABASE_URL)
    artifact_store = S3ArtifactStore(
        endpoint_url=TEST_OBJECT_STORAGE_ENDPOINT,
        bucket=TEST_OBJECT_STORAGE_BUCKET,
        access_key_id=TEST_OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_access_key=TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY,
        prefix=prefix,
    )

    with create_test_client(store=store, artifact_store=artifact_store) as client:
        created = client.post(
            '/uploads',
            files={'file': ('integration.txt', b'POSTGRES+S3', 'text/plain')},
        )
        assert created.status_code == 201
        upload_id = created.json()['upload_id']

        completed = wait_for_status(client, upload_id, 'completed')
        assert completed['artifact_state'] == 'present'

        artifact = client.get(f'/uploads/{upload_id}/artifact')
        assert artifact.status_code == 200
        assert artifact.json()['upload_id'] == upload_id
