import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .build_info import get_build_revision
from .models import HealthzRecord, UploadRecord
from .object_store import ArtifactStore, build_default_artifact_store
from .store import UploadStore, build_default_store, utcnow

MARKER = 'UPLOAD-ASYNC-SERVICE-LIVE-PROOF OK'
RETRY_ERROR_CODE = 'proof_fail_once'


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    return int(value.strip())


def parse_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    return float(value.strip())


class BackgroundWorker:
    def __init__(
        self,
        *,
        store: UploadStore,
        artifact_store: ArtifactStore,
        poll_interval_seconds: float,
        lease_timeout_seconds: float,
        retry_delay_seconds: float,
        build_revision: str,
        proof_mode: bool,
        terminator: Callable[[], None],
    ) -> None:
        self._store = store
        self._artifact_store = artifact_store
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_timeout_seconds = lease_timeout_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._build_revision = build_revision
        self._proof_mode = proof_mode
        self._terminator = terminator
        self._stop_event = threading.Event()
        self._terminate_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name='upload-async-worker', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self._poll_interval_seconds * 4))

    def request_termination(self) -> None:
        self._terminate_requested.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.process_once()
            self._stop_event.wait(self._poll_interval_seconds)

    def process_once(self) -> None:
        upload = self._store.claim_due_upload(
            now=utcnow(),
            lease_timeout_seconds=self._lease_timeout_seconds,
        )
        if upload is None:
            if self._terminate_requested.is_set():
                self._terminate_requested.clear()
                self._terminator()
                self._stop_event.set()
            return
        if upload.proof_hold_state == 'armed' and self._proof_mode:
            if self._terminate_requested.is_set():
                self._terminate_requested.clear()
                self._terminator()
                self._stop_event.set()
            return
        if upload.proof_fail_once and not upload.proof_fail_consumed:
            self._store.mark_retry_wait(
                upload.upload_id,
                now=utcnow(),
                retry_delay_seconds=self._retry_delay_seconds,
                error_code=RETRY_ERROR_CODE,
            )
            return
        artifact_document = upload.build_artifact_document(
            build_revision=self._build_revision,
            generated_at=datetime.now(timezone.utc),
        )
        self._artifact_store.put_json(upload.artifact_key, artifact_document)
        self._store.mark_completed(upload.upload_id, now=utcnow())


def default_terminator() -> None:
    os._exit(95)


def create_app(
    *,
    store_factory: Callable[[], UploadStore] | None = None,
    artifact_store_factory: Callable[[], ArtifactStore] | None = None,
    terminator: Callable[[], None] | None = None,
    proof_mode: bool | None = None,
    poll_interval_seconds: float | None = None,
    lease_timeout_seconds: float | None = None,
    retry_delay_seconds: float = 0.2,
    upload_max_bytes: int | None = None,
) -> FastAPI:
    store = (store_factory or build_default_store)()
    artifact_store = (artifact_store_factory or build_default_artifact_store)()
    selected_proof_mode = proof_mode if proof_mode is not None else parse_bool(
        os.getenv('PROOF_MODE'),
        default=False,
    )
    selected_poll_interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else parse_float(os.getenv('WORKER_POLL_INTERVAL_SECONDS'), default=0.2)
    )
    selected_lease_timeout = (
        lease_timeout_seconds
        if lease_timeout_seconds is not None
        else parse_float(os.getenv('LEASE_TIMEOUT_SECONDS'), default=2.0)
    )
    selected_upload_max_bytes = (
        upload_max_bytes
        if upload_max_bytes is not None
        else parse_int(os.getenv('UPLOAD_MAX_BYTES'), default=262144)
    )
    build_revision = get_build_revision()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker = BackgroundWorker(
            store=store,
            artifact_store=artifact_store,
            poll_interval_seconds=selected_poll_interval,
            lease_timeout_seconds=selected_lease_timeout,
            retry_delay_seconds=retry_delay_seconds,
            build_revision=build_revision,
            proof_mode=selected_proof_mode,
            terminator=terminator or default_terminator,
        )
        app.state.worker = worker
        worker.start()
        yield
        worker.stop()

    app = FastAPI(title='upload-async-service-live-proof', lifespan=lifespan)

    @app.middleware('http')
    async def add_anti_indexing_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['X-Robots-Tag'] = (
            'noindex, nofollow, noarchive, noimageindex, nosnippet'
        )
        return response

    @app.get('/healthz')
    def healthz() -> HealthzRecord:
        return HealthzRecord(
            status='ok',
            project='upload-async-service-live-proof',
            store=store.__class__.__name__,
            artifact_store=artifact_store.__class__.__name__,
            build_revision=build_revision,
            proof_mode=selected_proof_mode,
        )

    @app.get('/robots.txt', response_class=PlainTextResponse)
    def robots_txt() -> PlainTextResponse:
        return PlainTextResponse('User-agent: *\nDisallow: /\n')

    @app.get('/', response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(
            f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="robots" content="noindex,nofollow,noarchive,noimageindex,nosnippet">
    <title>upload-async-service-live-proof</title>
  </head>
  <body>
    <main>
      <h1>{MARKER}</h1>
      <p>Durable source of truth: PostgreSQL</p>
      <p>Derived artifacts: app-proxied object storage JSON</p>
      <p>Proof mode: {str(selected_proof_mode).lower()}</p>
    </main>
  </body>
</html>'''
        )

    @app.post('/uploads', response_model=UploadRecord, status_code=201)
    async def create_upload(
        file: UploadFile = File(...),
        proof_fail_once: bool = Form(False),
        proof_hold: bool = Form(False),
    ) -> UploadRecord:
        if (proof_fail_once or proof_hold) and not selected_proof_mode:
            raise HTTPException(status_code=403, detail='proof_mode_disabled')
        payload = await file.read()
        if len(payload) > selected_upload_max_bytes:
            raise HTTPException(status_code=413, detail='upload_too_large')
        return store.create_upload(
            filename=file.filename or 'upload.bin',
            content_type=file.content_type or 'application/octet-stream',
            source_payload=payload,
            proof_fail_once=proof_fail_once,
            proof_hold=proof_hold,
        )

    @app.get('/uploads/{upload_id}', response_model=UploadRecord)
    def get_upload(upload_id: str) -> UploadRecord:
        upload = store.get_upload(upload_id)
        if upload is None:
            raise HTTPException(status_code=404, detail='upload_not_found')
        return upload

    @app.get('/uploads/{upload_id}/artifact')
    def get_artifact(upload_id: str) -> Response:
        upload = store.get_upload(upload_id)
        if upload is None:
            raise HTTPException(status_code=404, detail='upload_not_found')
        if upload.artifact_key is None:
            return JSONResponse(
                status_code=409,
                content={'detail': {'error': 'artifact_missing', 'upload_id': upload_id}},
            )
        try:
            payload = artifact_store.get_json(upload.artifact_key)
        except FileNotFoundError:
            store.mark_artifact_missing(upload_id, now=utcnow())
            return JSONResponse(
                status_code=409,
                content={'detail': {'error': 'artifact_missing', 'upload_id': upload_id}},
            )
        return JSONResponse(payload)

    @app.post('/uploads/{upload_id}/artifact/rematerialize')
    def rematerialize_artifact(upload_id: str) -> Response:
        upload = store.get_upload(upload_id)
        if upload is None:
            raise HTTPException(status_code=404, detail='upload_not_found')
        if upload.artifact_key and artifact_store.exists(upload.artifact_key):
            raise HTTPException(status_code=409, detail='artifact_present')
        queued = store.enqueue_rematerialize(upload_id, now=utcnow())
        if queued is None:
            raise HTTPException(status_code=404, detail='upload_not_found')
        return JSONResponse(status_code=202, content=queued.model_dump(mode='json'))

    @app.post('/proof/terminate-worker')
    def terminate_worker() -> Response:
        if not selected_proof_mode:
            raise HTTPException(status_code=403, detail='proof_mode_disabled')
        held_upload = store.find_processing_hold()
        if held_upload is None:
            raise HTTPException(status_code=409, detail='no_processing_hold')
        store.release_hold(held_upload.upload_id, now=utcnow())
        app.state.worker.request_termination()
        return JSONResponse(
            status_code=202,
            content={'status': 'termination_requested', 'upload_id': held_upload.upload_id},
        )

    return app
