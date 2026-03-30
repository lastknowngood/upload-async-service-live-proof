import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


class ArtifactStore:
    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_json(self, key: str) -> dict[str, Any]:
        raise NotImplementedError

    def delete_key(self, key: str) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def list_prefix(self, prefix: str) -> Sequence[str]:
        raise NotImplementedError


@dataclass
class InMemoryArtifactStore(ArtifactStore):
    _items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self._items[key] = json.loads(json.dumps(payload))

    def get_json(self, key: str) -> dict[str, Any]:
        if key not in self._items:
            raise FileNotFoundError(key)
        return json.loads(json.dumps(self._items[key]))

    def delete_key(self, key: str) -> None:
        self._items.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self._items

    def list_prefix(self, prefix: str) -> Sequence[str]:
        return sorted(key for key in self._items if key.startswith(prefix))


class S3ArtifactStore(ArtifactStore):
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = '',
        region_name: str = 'us-east-1',
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip('/')
        self._client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
        )

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode('utf-8')
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._full_key(key),
            Body=body,
            ContentType='application/json',
        )

    def get_json(self, key: str) -> dict[str, Any]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') in {'404', 'NoSuchKey', 'NotFound'}:
                raise FileNotFoundError(key) from exc
            raise
        body = response['Body'].read()
        return json.loads(body.decode('utf-8'))

    def delete_key(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._full_key(key))

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
            return True
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') in {'404', 'NoSuchKey', 'NotFound'}:
                return False
            raise

    def list_prefix(self, prefix: str) -> Sequence[str]:
        full_prefix = self._full_key(prefix).rstrip('/')
        paginator = self._client.get_paginator('list_objects_v2')
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for item in page.get('Contents', []):
                keys.append(self._strip_prefix(item['Key']))
        return sorted(keys)

    def _full_key(self, key: str) -> str:
        clean = key.lstrip('/')
        if not self._prefix:
            return clean
        return f'{self._prefix}/{clean}'

    def _strip_prefix(self, key: str) -> str:
        if not self._prefix:
            return key
        prefix = f'{self._prefix}/'
        if key.startswith(prefix):
            return key[len(prefix) :]
        return key


def build_default_artifact_store() -> ArtifactStore:
    endpoint = os.getenv('OBJECT_STORAGE_ENDPOINT')
    bucket = os.getenv('OBJECT_STORAGE_BUCKET')
    access_key_id = os.getenv('OBJECT_STORAGE_ACCESS_KEY_ID')
    secret_access_key = os.getenv('OBJECT_STORAGE_SECRET_ACCESS_KEY')
    prefix = os.getenv('OBJECT_STORAGE_PREFIX', '')

    if not endpoint:
        raise RuntimeError('OBJECT_STORAGE_ENDPOINT is required.')
    if not bucket:
        raise RuntimeError('OBJECT_STORAGE_BUCKET is required.')
    if not access_key_id:
        raise RuntimeError('OBJECT_STORAGE_ACCESS_KEY_ID is required.')
    if not secret_access_key:
        raise RuntimeError('OBJECT_STORAGE_SECRET_ACCESS_KEY is required.')

    return S3ArtifactStore(
        endpoint_url=endpoint,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        prefix=prefix,
    )
