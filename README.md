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

- das Repo ist lokal vorhanden und oeffentlich auf GitHub publiziert:
  - `https://github.com/lastknowngood/upload-async-service-live-proof`
- die bisher publizierten Proof-Refs sind:
  - `proof/upload-async-service-live-proof-private-20260330-r1`
  - `proof/upload-async-service-live-proof-private-20260330-r2`
- die Runtime, die projektlokalen Proof-Helfer und der Deploy-Contract fuer den
  Upload-/Async-Fall sind angelegt
- der aktuelle Contract ist bewusst auf einen privaten Proof-Block ausgerichtet:
  - `exposure.mode: private`
  - kein Public-DNS- oder TLS-Claim in diesem Arbeitsstand
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
- ein erster privater Host-Lauf wurde gestartet und fail-closed wieder
  entfernt:
  - `r1` wurde in Coolify exakt importiert
  - private Readiness sowie Upload `A` und `B` waren browserlos gruen
  - der Hold-/Worker-Terminierungsfall fuer `C` deckte einen echten
    Postgres-Store-Defekt auf
  - der Defekt ist lokal behoben, regression-getestet und als
    `abff105 fix: tighten private proof helpers` auf `main` und `r2`
    publiziert
  - `r2` wurde in Coolify ebenfalls exakt importiert
  - die neue Version wurde aber weder per Rolling Update noch per bounded cold
    redeploy aktiv; Coolify brach den Deploy vor Aktivierung wieder ab
- aktuell gibt es bewusst keinen aktiven App-Object-Storage-Key und keine
  Host-Ressourcen aus diesem Repo
- es laeuft aktuell kein privater oder oeffentlicher Dienst aus diesem Repo auf
  `coolify-01`
- `upload.dental-school.education` hat aktuell oeffentlich weder `A` noch
  `AAAA`
- der generische Host-Dump-/Restore-Pfad fuer diesen Demo-Slug ist im Host-Repo
  vorbereitet, blieb in diesem roten privaten Lauf aber unbenutzt

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
- der aktuelle Projekt-Contract ist bewusst auf einen privaten Host-Block
  eingefroren; ein spaeterer Public-Proof braucht danach einen eigenen
  Contract-Nachzug
- dedizierte Object-Storage-Boundary ist vorhanden:
  - Projekt `upload-async-service-live-proof`
  - Bucket `schwedler-upload-async-proof`
  - kein aktiver App-Key retained
- spaeteres Host-Wiring braucht trotzdem wieder einen **neuen** Demo-Key und
  muss mit genau diesem Key die volle Isolation im selben Block erneut
  beweisen
- ein erster privater Host-Lauf wurde bereits teilweise bewiesen:
  - private Readiness
  - Upload Success
  - `proof_fail_once`
- der aktuelle offene Blocker ist jetzt enger:
  - die Folgeversion `r2` wird zwar exakt importiert, aber auf diesem
    Coolify-Stand vor Aktivierung der neuen Version wieder entfernt
- aktueller Steady State nach dem roten Lauf:
  - kein App-Key retained
  - kein App-/DB-Ressourcensatz retained
  - kein Dump-Pfad
  - kein Public-DNS
