import argparse
import json

from app.store import read_uploads_for_restore


def load_expectations(args: argparse.Namespace) -> tuple[list[dict[str, object]], list[str]]:
    if args.expect_spec_file:
        with open(args.expect_spec_file, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
        expect_uploads = payload.get('expect_uploads', [])
        forbid_upload_ids = payload.get('forbid_upload_ids', [])
        if not isinstance(expect_uploads, list) or not isinstance(forbid_upload_ids, list):
            raise SystemExit(
                'expect spec must contain list fields `expect_uploads` and '
                '`forbid_upload_ids`.'
            )
        normalized_expect_uploads: list[dict[str, object]] = []
        for item in expect_uploads:
            if not isinstance(item, dict) or not isinstance(item.get('upload_id'), str):
                raise SystemExit('each expected upload must be an object with string `upload_id`.')
            normalized_expect_uploads.append(item)
        normalized_forbidden = [item for item in forbid_upload_ids if isinstance(item, str)]
        if len(normalized_forbidden) != len(forbid_upload_ids):
            raise SystemExit('each forbidden upload id must be a string.')
        return normalized_expect_uploads, normalized_forbidden

    expected_uploads = [{'upload_id': upload_id} for upload_id in args.upload_id]
    return expected_uploads, list(args.forbid_upload_id)


def apply_legacy_expectations(
    expected_uploads: list[dict[str, object]],
    args: argparse.Namespace,
) -> list[dict[str, object]]:
    if args.expect_spec_file:
        return expected_uploads

    for item in expected_uploads:
        if args.expect_status:
            item['status'] = args.expect_status
        if args.expect_attempt_count is not None:
            item['attempt_count'] = args.expect_attempt_count
        if args.expect_source_sha256:
            item['source_sha256'] = args.expect_source_sha256
        if args.expect_artifact_state:
            item['artifact_state'] = args.expect_artifact_state
        if args.expect_proof_hold_state:
            item['proof_hold_state'] = args.expect_proof_hold_state

    return expected_uploads


def normalize_upload_ids(
    expected_uploads: list[dict[str, object]],
    forbidden: list[str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for upload_id in [*(item['upload_id'] for item in expected_uploads), *forbidden]:
        if upload_id not in seen:
            ordered.append(upload_id)
            seen.add(upload_id)
    return ordered


def validate_expected_uploads(
    expected_uploads: list[dict[str, object]],
    payload: list[dict[str, object]],
) -> int:
    payload_by_id = {item['upload_id']: item for item in payload}

    missing_uploads = [
        item['upload_id'] for item in expected_uploads if item['upload_id'] not in payload_by_id
    ]
    if missing_uploads:
        print(
            json.dumps(
                {
                    'error': 'missing_uploads',
                    'missing_upload_ids': missing_uploads,
                    'uploads': payload,
                },
                indent=2,
            )
        )
        return 1

    forbidden_ids = {item['upload_id'] for item in expected_uploads}
    extra_uploads = [
        item['upload_id'] for item in payload if item['upload_id'] not in forbidden_ids
    ]
    if extra_uploads:
        print(
            json.dumps(
                {
                    'error': 'unexpected_uploads',
                    'unexpected_upload_ids': extra_uploads,
                    'uploads': payload,
                },
                indent=2,
            )
        )
        return 1

    for expected in expected_uploads:
        actual = payload_by_id[expected['upload_id']]
        for field in (
            'status',
            'attempt_count',
            'source_sha256',
            'artifact_state',
            'proof_hold_state',
        ):
            if field in expected and actual.get(field) != expected[field]:
                print(
                    json.dumps(
                        {
                            'error': f'unexpected_{field}',
                            'upload_id': expected['upload_id'],
                            'expected': expected[field],
                            'actual': actual.get(field),
                            'uploads': payload,
                        },
                        indent=2,
                    )
                )
                return 1

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--upload-id', action='append', default=[])
    parser.add_argument('--forbid-upload-id', action='append', default=[])
    parser.add_argument('--expect-spec-file')
    parser.add_argument('--expect-status')
    parser.add_argument('--expect-attempt-count', type=int)
    parser.add_argument('--expect-source-sha256')
    parser.add_argument('--expect-artifact-state')
    parser.add_argument('--expect-proof-hold-state')
    args = parser.parse_args()

    expected_uploads, forbidden_upload_ids = load_expectations(args)
    expected_uploads = apply_legacy_expectations(expected_uploads, args)
    upload_ids = normalize_upload_ids(expected_uploads, forbidden_upload_ids)

    uploads = read_uploads_for_restore(args.database_url, upload_ids)
    payload = [upload.to_record().model_dump(mode='json') for upload in uploads]

    forbidden = set(forbidden_upload_ids)
    present = {upload.upload_id for upload in uploads}
    if forbidden & present:
        print(json.dumps({'error': 'forbidden_upload_present', 'uploads': payload}, indent=2))
        return 1

    validation = validate_expected_uploads(expected_uploads, payload)
    if validation != 0:
        return validation

    print(json.dumps({'uploads': payload}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
