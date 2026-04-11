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

Klarstellung: `lifecycle.mode: live` beschreibt hier die Proof-/Deploy-Contract-Klasse. Ob aus diesem Repo aktuell ein Dienst, DNS oder Host-Ressourcen retained sind, steht in den folgenden Bulletpoints und in den `notes` des Deploy-Contracts.

- das Repo ist lokal vorhanden und oeffentlich auf GitHub publiziert:
  - `https://github.com/lastknowngood/upload-async-service-live-proof`
- die bisher publizierten Proof-Refs sind:
  - `proof/upload-async-service-live-proof-private-20260330-r1`
  - `proof/upload-async-service-live-proof-private-20260330-r2`
  - `proof/upload-async-service-live-proof-private-20260331-r3`
- `r3` zeigt direkt auf
  `abff105c4cb0743e9d758a6812d63c8490233a22`
- die Runtime, die projektlokalen Proof-Helfer und der Deploy-Contract fuer den
  Upload-/Async-Fall sind angelegt
- der erste volle private und kurze oeffentliche Proof auf `r3` ist
  erfolgreich gelaufen:
  - exakter Import beim privaten Create und beim same-ref Redeploy
  - browserloser Hold-/Worker-Terminierungsfall, Retry und Rematerialisierung
  - Dump, `host-restic-data-backup-run`, Restore in sauberes Ziel,
    Restore-Cutover und Rematerialisierung aus Restore-Daten
  - proof-only Oberflaeche vor der public Runde mit `PROOF_MODE=false`
    geschlossen
  - kurzer Public-Proof auf `https://upload.dental-school.education`
    erfolgreich
  - danach same-day fail-closed Cleanup erfolgreich
- ein dediziertes Hetzner-Object-Storage-Projekt
  `upload-async-service-live-proof` ist angelegt
- der dedizierte retained Bucket `schwedler-upload-async-proof` existiert in
  `hel1`
- ein proof-scoped S3-Key wurde einmalig erzeugt, lokal ausserhalb von Git
  gesichert, gegen genau dieses dedizierte Projekt verifiziert und danach
  wieder widerrufen
- der verifizierte Befund dazu ist:
  - Hetzner-S3-Credentials sind projektweit pro Object-Storage-Projekt gueltig
  - mit dem dedizierten Projekt zeigte `list_buckets` nur
    `schwedler-upload-async-proof`
  - derselbe Key bekam gegen `schwedler-coolify-bkp` nur `AccessDenied`
- der alte Shared-Proof-Bucket `schwedler-coolify-app-proof` im Projekt
  `Backups` ist entfernt
- aktuell gibt es bewusst keinen aktiven App-Object-Storage-Key und keine
  Host-Ressourcen aus diesem Repo
- es laeuft aktuell kein privater oder oeffentlicher Dienst aus diesem Repo auf
  `coolify-01`
- `upload.dental-school.education` hat aktuell oeffentlich weder `A` noch
  `AAAA`
- der generische Host-Dump-/Restore-Pfad fuer diesen Demo-Slug ist jetzt real
  genutzt und fail-closed wieder aufgeraeumt

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
- oeffentliches GitHub-Repo und Proof-Ref sind vorhanden
- der aktuelle Projekt-Contract ist jetzt auf den erfolgreichen `r3`-Proof
  ausgerichtet:
  - `exposure.mode: public`
  - Proof-Hostname `upload.dental-school.education`
- dedizierte Object-Storage-Boundary ist vorhanden:
  - Projekt `upload-async-service-live-proof`
  - Bucket `schwedler-upload-async-proof`
  - kein aktiver App-Key retained
- spaeteres Host-Wiring braucht trotzdem wieder einen **neuen** Demo-Key und
  muss mit genau diesem Key die volle Isolation im selben Block erneut
  beweisen
- privater `r3`-Beweis erfolgreich:
  - private Readiness
  - `proof_fail_once`
  - `proof_hold` plus `POST /proof/terminate-worker`
  - Dump, Offsite-Aufnahme, Restore, Restore-Cutover und Rematerialisierung
- kurzer Public-Proof erfolgreich:
  - `HTTPS 200`
  - Upload
  - Status-/Artefakt-Readback
  - Anti-Indexing
- aktueller Steady State nach erfolgreichem Cleanup:
  - kein App-Key retained
  - kein App-/DB-Ressourcensatz retained
  - kein Dump-Pfad
  - kein Public-DNS
