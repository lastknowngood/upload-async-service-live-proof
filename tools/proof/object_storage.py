import argparse
import json
import os
from uuid import uuid4

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def build_client(args: argparse.Namespace):
    endpoint = args.endpoint or os.getenv('OBJECT_STORAGE_ENDPOINT')
    access_key_id = args.access_key_id or os.getenv('OBJECT_STORAGE_ACCESS_KEY_ID')
    secret_access_key = args.secret_access_key or os.getenv('OBJECT_STORAGE_SECRET_ACCESS_KEY')
    if not endpoint:
        raise SystemExit('OBJECT_STORAGE_ENDPOINT is required.')
    if not access_key_id:
        raise SystemExit('OBJECT_STORAGE_ACCESS_KEY_ID is required.')
    if not secret_access_key:
        raise SystemExit('OBJECT_STORAGE_SECRET_ACCESS_KEY is required.')
    return boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name='us-east-1',
        config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
    )


def require_bucket(args: argparse.Namespace) -> str:
    bucket = args.bucket or os.getenv('OBJECT_STORAGE_BUCKET')
    if not bucket:
        raise SystemExit('OBJECT_STORAGE_BUCKET is required.')
    return bucket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'command',
        choices=[
            'list-buckets',
            'head-bucket',
            'list-prefix',
            'delete-prefix',
            'roundtrip-prefix',
            'verify-auth-fails',
        ],
    )
    parser.add_argument('--endpoint')
    parser.add_argument('--bucket')
    parser.add_argument('--access-key-id')
    parser.add_argument('--secret-access-key')
    parser.add_argument('--prefix', default='')
    args = parser.parse_args()

    client = build_client(args)

    if args.command == 'list-buckets':
        response = client.list_buckets()
        buckets = [item['Name'] for item in response.get('Buckets', [])]
        print(json.dumps({'buckets': buckets}, indent=2))
        return 0

    bucket = require_bucket(args)

    if args.command == 'head-bucket':
        client.head_bucket(Bucket=bucket)
        print(json.dumps({'bucket': bucket, 'exists': True}))
        return 0

    if args.command == 'list-prefix':
        response = client.list_objects_v2(Bucket=bucket, Prefix=args.prefix)
        keys = [item['Key'] for item in response.get('Contents', [])]
        print(json.dumps({'bucket': bucket, 'prefix': args.prefix, 'keys': keys}, indent=2))
        return 0

    if args.command == 'delete-prefix':
        response = client.list_objects_v2(Bucket=bucket, Prefix=args.prefix)
        keys = [item['Key'] for item in response.get('Contents', [])]
        if keys:
            client.delete_objects(
                Bucket=bucket,
                Delete={'Objects': [{'Key': key} for key in keys], 'Quiet': True},
            )
        print(json.dumps({'bucket': bucket, 'prefix': args.prefix, 'deleted_count': len(keys)}))
        return 0

    if args.command == 'roundtrip-prefix':
        probe_key = f"{args.prefix.rstrip('/')}/probe-{uuid4().hex}.json" if args.prefix else (
            f"probe-{uuid4().hex}.json"
        )
        payload = b'{"probe":"ok"}\n'
        created = False
        try:
            client.put_object(
                Bucket=bucket,
                Key=probe_key,
                Body=payload,
                ContentType='application/json',
            )
            created = True
            fetched = client.get_object(Bucket=bucket, Key=probe_key)['Body'].read()
            response = client.list_objects_v2(Bucket=bucket, Prefix=args.prefix)
            keys = [item['Key'] for item in response.get('Contents', [])]
            print(
                json.dumps(
                    {
                        'bucket': bucket,
                        'prefix': args.prefix,
                        'probe_key': probe_key,
                        'roundtrip_ok': fetched == payload and probe_key in keys,
                    },
                    indent=2,
                )
            )
            return 0 if fetched == payload and probe_key in keys else 1
        finally:
            if created:
                client.delete_object(Bucket=bucket, Key=probe_key)

    try:
        client.list_objects_v2(Bucket=bucket, Prefix=args.prefix, MaxKeys=1)
    except ClientError as exc:
        print(
            json.dumps(
                {
                    'bucket': bucket,
                    'prefix': args.prefix,
                    'auth_failed': True,
                    'error_code': exc.response.get('Error', {}).get('Code'),
                }
            )
        )
        return 0

    print(
        json.dumps(
            {
                'bucket': bucket,
                'prefix': args.prefix,
                'auth_failed': False,
                'error': 'unexpected_success',
            }
        )
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
