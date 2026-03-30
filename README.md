# upload-async-service-live-proof

Kleines separates Demo-Repo fuer einen generischen Upload-/Async-/Artefaktpfad
auf `coolify-01`.

## Charakter

- `lifecycle.mode: live`
- stateful
- PostgreSQL als durable source of truth
- s3-kompatibler Object Storage nur fuer abgeleitete Artefakte
- ein einzelner FastAPI-Prozess mit eingebettetem DB-polling Worker
- `operations.backup_class: stateful-logical-dump`
- geplanter Proof-Hostname: `upload.dental-school.education`
- Default-Endzustand des ersten Public-Proofs: Cleanup nach Evidence

## Aktueller Zustand

- das Repo existiert lokal als neues separates Demo-Repo
- die Runtime, die projektlokalen Proof-Helfer und der Deploy-Contract fuer den
  Upload-/Async-Fall sind angelegt
- es gibt aktuell keinen GitHub-Remote-Readback, keinen Bucket-Key-Readback und
  keine Host-Ressourcen aus diesem Repo
- es laeuft aktuell kein privater oder oeffentlicher Dienst aus diesem Repo auf
  `coolify-01`
- DNS, Object-Storage-Credentials und der generische Host-Dump-/Restore-Pfad
  fuer diesen Demo-Slug sind aktuell noch nicht bewiesen

## Lokale Entwicklung

Voraussetzungen:

- Python `3.12`
- `uv`
- optional Docker fuer PostgreSQL- und MinIO-Smoke-Checks

Schnellstart:

```powershell
uv sync
uv run pytest --cov=app
uv run ruff check .
uv run pyright
```

Optionaler lokaler Compose-Smoke:

```powershell
docker compose up -d postgres minio
$env:TEST_DATABASE_URL = 'postgresql://postgres:postgres@127.0.0.1:54329/upload_async_service_live_proof'
$env:TEST_OBJECT_STORAGE_ENDPOINT = 'http://127.0.0.1:9000'
$env:TEST_OBJECT_STORAGE_BUCKET = 'upload-async-local'
$env:TEST_OBJECT_STORAGE_ACCESS_KEY_ID = 'minioadmin'
$env:TEST_OBJECT_STORAGE_SECRET_ACCESS_KEY = 'minioadmin'
uv run pytest --cov=app -m "not integration or integration"
```

Project-Closeout:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File tools/repo/check-project-closeout.ps1
git status --short --ignored
```

## Laufzeitverhalten

- `POST /uploads` nimmt `multipart/form-data` mit Feld `file` an
- `POST /uploads` unterstuetzt nur bei `PROOF_MODE=true` die proof-only
  Form-Felder `proof_fail_once` und `proof_hold`
- `GET /uploads/{id}` read-backt den Jobzustand browserlos
- `GET /uploads/{id}/artifact` liefert das abgeleitete JSON-Artefakt
  app-proxied aus
- `POST /uploads/{id}/artifact/rematerialize` queued eine Artefakt-Neuerzeugung
- `POST /proof/terminate-worker` ist proof-only und beendet den Prozess nur,
  wenn bereits ein gehaltener Job in `processing` steht
- `GET /healthz` read-backt Status, Store, Artefakt-Backend und `build_revision`
- sichtbarer Root-Marker: `UPLOAD-ASYNC-SERVICE-LIVE-PROOF OK`

## Proof-Status

- lokaler Code- und Testpfad ist vorhanden
- private Host-Proofs, Object-Storage-Control-Path, DNS und Cleanup-Evidence
  fehlen noch
- dieses Repo ist aktuell nur lokale/private Planungs- und
  Implementierungsevidence
