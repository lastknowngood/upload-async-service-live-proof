from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.models import StoredUpload

TOOL_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'proof' / 'restore_readback.py'


def load_tool_module():
    spec = importlib.util.spec_from_file_location('restore_readback_tool', TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f'failed to load tool module from {TOOL_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_upload(
    upload_id: str,
    *,
    attempt_count: int,
    proof_hold_state: Literal['none', 'armed', 'released'],
    source_sha256: str,
) -> StoredUpload:
    now = datetime(2026, 3, 30, 12, 0, tzinfo=UTC)
    return StoredUpload(
        upload_id=upload_id,
        filename=f'{upload_id}.txt',
        content_type='text/plain',
        source_payload=upload_id.encode('utf-8'),
        source_bytes=len(upload_id),
        source_sha256=source_sha256,
        status='completed',
        attempt_count=attempt_count,
        available_at=now,
        lease_expires_at=None,
        proof_fail_once=False,
        proof_fail_consumed=False,
        proof_hold_state=proof_hold_state,
        artifact_state='present',
        artifact_key=f'proof/{upload_id}.json',
        last_error_code=None,
        created_at=now,
        updated_at=now,
    )


def test_expect_spec_file_supports_per_upload_expectations_and_forbidden_ids(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    tool = load_tool_module()
    uploads = {
        'A': build_upload('A', attempt_count=1, proof_hold_state='none', source_sha256='sha-A'),
        'B': build_upload('B', attempt_count=2, proof_hold_state='none', source_sha256='sha-B'),
        'C': build_upload('C', attempt_count=2, proof_hold_state='released', source_sha256='sha-C'),
    }

    def fake_read_uploads_for_restore(database_url: str, upload_ids: list[str]):
        assert database_url == 'postgresql://restore-db'
        assert upload_ids == ['A', 'B', 'C', 'D']
        return [uploads[upload_id] for upload_id in upload_ids if upload_id in uploads]

    spec_path = tmp_path / 'restore-spec.json'
    spec_path.write_text(
        json.dumps(
            {
                'expect_uploads': [
                    {
                        'upload_id': 'A',
                        'status': 'completed',
                        'attempt_count': 1,
                        'source_sha256': 'sha-A',
                        'artifact_state': 'present',
                        'proof_hold_state': 'none',
                    },
                    {
                        'upload_id': 'B',
                        'status': 'completed',
                        'attempt_count': 2,
                        'source_sha256': 'sha-B',
                        'artifact_state': 'present',
                        'proof_hold_state': 'none',
                    },
                    {
                        'upload_id': 'C',
                        'status': 'completed',
                        'attempt_count': 2,
                        'source_sha256': 'sha-C',
                        'artifact_state': 'present',
                        'proof_hold_state': 'released',
                    },
                ],
                'forbid_upload_ids': ['D'],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(tool, 'read_uploads_for_restore', fake_read_uploads_for_restore)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'restore_readback.py',
            '--database-url',
            'postgresql://restore-db',
            '--expect-spec-file',
            str(spec_path),
        ],
    )

    assert tool.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert [item['upload_id'] for item in payload['uploads']] == ['A', 'B', 'C']


def test_expect_spec_file_fails_when_forbidden_upload_is_present(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    tool = load_tool_module()

    def fake_read_uploads_for_restore(database_url: str, upload_ids: list[str]):
        assert upload_ids == ['A', 'D']
        return [
            build_upload('A', attempt_count=1, proof_hold_state='none', source_sha256='sha-A'),
            build_upload('D', attempt_count=1, proof_hold_state='none', source_sha256='sha-D'),
        ]

    spec_path = tmp_path / 'restore-spec.json'
    spec_path.write_text(
        json.dumps(
            {
                'expect_uploads': [
                    {
                        'upload_id': 'A',
                        'status': 'completed',
                        'attempt_count': 1,
                        'source_sha256': 'sha-A',
                        'artifact_state': 'present',
                        'proof_hold_state': 'none',
                    }
                ],
                'forbid_upload_ids': ['D'],
            }
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(tool, 'read_uploads_for_restore', fake_read_uploads_for_restore)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'restore_readback.py',
            '--database-url',
            'postgresql://restore-db',
            '--expect-spec-file',
            str(spec_path),
        ],
    )

    assert tool.main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload['error'] == 'forbidden_upload_present'
