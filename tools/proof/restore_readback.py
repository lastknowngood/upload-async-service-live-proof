import argparse
import json

from app.store import read_uploads_for_restore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--upload-id', action='append', default=[])
    parser.add_argument('--forbid-upload-id', action='append', default=[])
    parser.add_argument('--expect-status')
    parser.add_argument('--expect-attempt-count', type=int)
    parser.add_argument('--expect-source-sha256')
    parser.add_argument('--expect-artifact-state')
    parser.add_argument('--expect-proof-hold-state')
    args = parser.parse_args()

    uploads = read_uploads_for_restore(args.database_url, args.upload_id)
    payload = [upload.to_record().model_dump(mode='json') for upload in uploads]

    if len(uploads) != len(args.upload_id):
        print(json.dumps({'error': 'missing_uploads', 'uploads': payload}, indent=2))
        return 1

    forbidden = set(args.forbid_upload_id)
    present = {upload.upload_id for upload in uploads}
    if forbidden & present:
        print(json.dumps({'error': 'forbidden_upload_present', 'uploads': payload}, indent=2))
        return 1

    for upload in uploads:
        record = upload.to_record()
        if args.expect_status and record.status != args.expect_status:
            print(json.dumps({'error': 'unexpected_status', 'uploads': payload}, indent=2))
            return 1
        if (
            args.expect_attempt_count is not None
            and record.attempt_count != args.expect_attempt_count
        ):
            print(json.dumps({'error': 'unexpected_attempt_count', 'uploads': payload}, indent=2))
            return 1
        if args.expect_source_sha256 and record.source_sha256 != args.expect_source_sha256:
            print(json.dumps({'error': 'unexpected_source_sha256', 'uploads': payload}, indent=2))
            return 1
        if args.expect_artifact_state and record.artifact_state != args.expect_artifact_state:
            print(json.dumps({'error': 'unexpected_artifact_state', 'uploads': payload}, indent=2))
            return 1
        if (
            args.expect_proof_hold_state
            and record.proof_hold_state != args.expect_proof_hold_state
        ):
            print(
                json.dumps(
                    {'error': 'unexpected_proof_hold_state', 'uploads': payload},
                    indent=2,
                )
            )
            return 1

    print(json.dumps({'uploads': payload}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
