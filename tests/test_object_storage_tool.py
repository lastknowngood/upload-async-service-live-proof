from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

TOOL_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'proof' / 'object_storage.py'


def load_tool_module():
    spec = importlib.util.spec_from_file_location('object_storage_tool', TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f'failed to load tool module from {TOOL_PATH}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeS3Client:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def list_buckets(self) -> dict[str, object]:
        return {'Buckets': [{'Name': 'alpha'}, {'Name': 'beta'}]}

    def head_bucket(self, *, Bucket: str) -> None:
        return None

    def list_objects_v2(
        self,
        *,
        Bucket: str,
        Prefix: str = '',
        MaxKeys: int | None = None,
    ) -> dict[str, object]:
        matching = [key for key in sorted(self._objects) if key.startswith(Prefix)]
        if MaxKeys is not None:
            matching = matching[:MaxKeys]
        return {'Contents': [{'Key': key} for key in matching]}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self._objects[Key] = Body

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, object]:
        return {'Body': io.BytesIO(self._objects[Key])}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self._objects.pop(Key, None)

    def delete_objects(self, *, Bucket: str, Delete: dict[str, list[dict[str, str]]]) -> None:
        for item in Delete['Objects']:
            self._objects.pop(item['Key'], None)


def test_list_buckets_does_not_require_bucket(monkeypatch, capsys) -> None:
    tool = load_tool_module()
    monkeypatch.setattr(tool, 'build_client', lambda args: FakeS3Client())
    monkeypatch.setattr(
        sys,
        'argv',
        ['object_storage.py', 'list-buckets', '--endpoint', 'https://example.invalid'],
    )

    assert tool.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {'buckets': ['alpha', 'beta']}


def test_roundtrip_prefix_self_cleans(monkeypatch, capsys) -> None:
    tool = load_tool_module()
    client = FakeS3Client()
    monkeypatch.setattr(tool, 'build_client', lambda args: client)
    monkeypatch.setattr(
        sys,
        'argv',
        [
            'object_storage.py',
            'roundtrip-prefix',
            '--endpoint',
            'https://example.invalid',
            '--bucket',
            'proof-bucket',
            '--access-key-id',
            'key',
            '--secret-access-key',
            'secret',
            '--prefix',
            'proof/run-1/',
        ],
    )

    assert tool.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['bucket'] == 'proof-bucket'
    assert payload['prefix'] == 'proof/run-1/'
    assert payload['probe_key'].startswith('proof/run-1/probe-')
    assert payload['roundtrip_ok'] is True
    assert client.list_objects_v2(Bucket='proof-bucket', Prefix='').get('Contents', []) == []
