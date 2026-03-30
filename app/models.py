from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

UploadStatus = Literal['queued', 'processing', 'retry_wait', 'completed', 'failed']
ArtifactState = Literal['pending', 'present', 'missing', 'rematerializing']
ProofHoldState = Literal['none', 'armed', 'released']


class UploadRecord(BaseModel):
    upload_id: str
    status: UploadStatus
    attempt_count: int
    lease_expires_at: datetime | None
    proof_hold_state: ProofHoldState
    source_bytes: int
    source_sha256: str
    artifact_state: ArtifactState
    artifact_key: str | None
    last_error_code: str | None
    updated_at: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HealthzRecord(BaseModel):
    status: str
    project: str
    store: str
    artifact_store: str
    build_revision: str
    proof_mode: bool


@dataclass(slots=True)
class StoredUpload:
    upload_id: str
    filename: str
    content_type: str
    source_payload: bytes
    source_bytes: int
    source_sha256: str
    status: UploadStatus
    attempt_count: int
    available_at: datetime
    lease_expires_at: datetime | None
    proof_fail_once: bool
    proof_fail_consumed: bool
    proof_hold_state: ProofHoldState
    artifact_state: ArtifactState
    artifact_key: str
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime

    def to_record(self) -> UploadRecord:
        return UploadRecord(
            upload_id=self.upload_id,
            status=self.status,
            attempt_count=self.attempt_count,
            lease_expires_at=self.lease_expires_at,
            proof_hold_state=self.proof_hold_state,
            source_bytes=self.source_bytes,
            source_sha256=self.source_sha256,
            artifact_state=self.artifact_state,
            artifact_key=self.artifact_key,
            last_error_code=self.last_error_code,
            updated_at=self.updated_at,
            created_at=self.created_at,
        )

    def build_artifact_document(
        self,
        build_revision: str,
        generated_at: datetime,
    ) -> dict[str, Any]:
        return {
            'upload_id': self.upload_id,
            'source_sha256': self.source_sha256,
            'source_bytes': self.source_bytes,
            'attempt_count': self.attempt_count,
            'proof_hold_state': self.proof_hold_state,
            'build_revision': build_revision,
            'generated_at': generated_at.isoformat(),
        }
