"""dpi-eval-web: localhost web UI over run_batch for HDC student workers.

Imports only run_batch from the engine (spec hard constraint); never
imports dinglehopper.
"""

import argparse
import json
import logging
import os
import re
import secrets
import shutil
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from dpi_eval import derive, iiif, pages
from dpi_eval import sessions as sess
from dpi_eval.pairing import OCR_EXTENSIONS, discover_pairs
from dpi_eval.runner import run_batch

logger = logging.getLogger("dpi_eval.web")

RUN_ID = re.compile(r"run-\d{3,}")
HOST = "127.0.0.1"
PREFERRED_PORT = 8765


def _real_uploads(uploads: list[UploadFile]) -> list[UploadFile]:
    """Drop no-selection placeholders and hidden junk (.DS_Store etc.)."""
    kept = []
    for upload in uploads:
        if not upload.filename:
            continue
        if Path(upload.filename).name.startswith("."):
            continue
        kept.append(upload)
    return kept


def _collisions(uploads: list[UploadFile]) -> list[str]:
    """Original paths of uploads whose flattened basenames collide."""
    by_name: dict[str, list[str]] = {}
    for upload in uploads:
        by_name.setdefault(Path(upload.filename).name, []).append(upload.filename)
    return [
        path for paths in by_name.values() if len(paths) > 1 for path in paths
    ]


def _ocr_stem(filename: str) -> str:
    """Display name for an OCR file with no ground truth: strip whichever
    OCR_EXTENSIONS suffix it has, mirroring pairing.py's own stem logic
    (read-only use of its extension list, not a reimplementation of the
    matching algorithm)."""
    for ext in OCR_EXTENSIONS:
        if filename.endswith(ext):
            return filename[: -len(ext)]
    return filename


def _save(uploads: list[UploadFile], dest: Path) -> None:
    """Flatten to basenames — pairing.py expects flat directories."""
    dest.mkdir(parents=True, exist_ok=True)
    for upload in uploads:
        (dest / Path(upload.filename).name).write_bytes(upload.file.read())


class GradeValidationError(Exception):
    """A batch failed the shared validation pipeline before anything was
    written to disk. `message` mirrors the existing /grade wording;
    `details` mirrors the existing per-item list (e.g. colliding paths)."""

    def __init__(self, message: str, details: tuple[str, ...] = ()):
        super().__init__(message)
        self.message = message
        self.details = details


class _PathBuf:
    """Duck-types UploadFile.file's .read() for pre-read path bytes."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _PathUpload:
    """Duck-types UploadFile's `.filename` / `.file.read()` surface so a
    path-enumerated file can flow through the same `_real_uploads`,
    `_collisions`, and `_save` helpers /grade already uses — parity is
    structural, not a reimplementation."""

    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = _PathBuf(data)


def _enumerate_dir(dir_path: Path) -> list[_PathUpload]:
    """Recursively enumerate files under dir_path (files only).

    rglob semantics (pinned by test): a symlinked file is read through;
    a symlinked directory is listed as an entry but not descended into
    (its is_dir() is True, so it is skipped here, and rglob itself never
    walks into it). Every file's bytes are read now, before validation
    or any write, so a read failure anywhere in the tree fails the whole
    request with nothing partially graded.
    """
    items = []
    for path in sorted(dir_path.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(dir_path)
        items.append(_PathUpload(str(rel), path.read_bytes()))
    return items


def _grade_pipeline(
    gt_uploads: list, ocr_uploads: list, base_dir: Path
) -> Path:
    """Shared /grade + /grade-paths pipeline: drop hidden files, run the
    .gt.txt/empty-OCR/collision validations (same messages/order as the
    original /grade), then save flat and run the batch. Those checks
    raise GradeValidationError before any run directory is created — a
    validation failure never leaves a partial run behind.

    The pairing pre-check (F14) runs after the flat save, because it
    calls the engine's own pairing.discover_pairs, which matches files
    on disk — it can leave a run directory containing the saved (but
    ungraded) uploads behind when it rejects. It rejects only when
    discover_pairs finds zero pairs; a partial mismatch (some names pair,
    some don't) still proceeds to run_batch, which reports the unpaired
    names on the results page as it always has."""
    gt_kept = _real_uploads(gt_uploads)
    ocr_kept = _real_uploads(ocr_uploads)
    if not any(Path(u.filename).name.endswith(".gt.txt") for u in gt_kept):
        raise GradeValidationError(
            "The ground-truth folder has no .gt.txt files. Each "
            "transcription must be named after its OCR file, with "
            ".gt.txt in place of the extension — for example "
            "page_3.gt.txt grades page_3.xml."
        )
    if not ocr_kept:
        raise GradeValidationError(
            "The OCR folder is empty — pick the folder that holds "
            "the .hocr, .xml, or .txt files."
        )
    colliding = _collisions(gt_kept) + _collisions(ocr_kept)
    if colliding:
        raise GradeValidationError(
            "Two or more files would end up with the same name, so "
            "grading could silently use the wrong page. Flatten the "
            "folder or rename these files, then try again:",
            tuple(colliding),
        )

    run_dir = _next_run_dir(base_dir)
    _save(gt_kept, run_dir / "gt")
    _save(ocr_kept, run_dir / "ocr")

    pairs, missing_gt = discover_pairs(run_dir / "gt", run_dir / "ocr")
    if not pairs:
        orphan_ocr = sorted(Path(u.filename).name for u in ocr_kept)
        details = tuple(
            f"{stem} — no OCR file with the same name"
            for stem in sorted(missing_gt)
        ) + tuple(
            f"{_ocr_stem(name)} — no ground-truth file with the same name"
            for name in orphan_ocr
        )
        raise GradeValidationError(
            "None of the files matched up by name, so nothing would be "
            "graded. Each ground-truth file must be named after its OCR "
            "file, with .gt.txt in place of the extension — for example "
            "page_3.gt.txt grades page_3.xml. Fix these names, then try "
            "again:",
            details,
        )

    return _register(run_dir)


def _register(run_dir: Path) -> Path:
    """Run the engine over an already-populated run dir's gt/ocr folders
    and write result.json so the /runs/{id} results page can serve it."""
    result, code = run_batch(
        run_dir / "gt", run_dir / "ocr", run_dir / "reports"
    )
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "succeeded": result.succeeded,
                "failed": result.failed,
                "missing": result.missing,
                "exit_code": code,
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _run_and_register(gt_dir: Path, ocr_dir: Path, base_dir: Path) -> Path:
    """Copy two ready folders into a fresh run dir and register the run.
    Shared by the transcription grade-confirm route (later task)."""
    run_dir = _next_run_dir(base_dir)
    shutil.copytree(gt_dir, run_dir / "gt")
    shutil.copytree(ocr_dir, run_dir / "ocr")
    return _register(run_dir)


def _check_token(request: Request, form_token: str | None = None) -> None:
    """403 unless the caller supplies the per-launch token via the
    X-DPI-Eval-Token header or a form field; also 403 when unset."""
    token = os.environ.get("DPI_EVAL_TOKEN")
    supplied = request.headers.get("X-DPI-Eval-Token") or form_token
    if not token or not secrets.compare_digest(supplied or "", token):
        raise HTTPException(status_code=403)


def _next_run_dir(base_dir: Path) -> Path:
    while True:
        highest = 0
        for existing in base_dir.glob("run-*"):
            suffix = existing.name[len("run-") :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        run_dir = base_dir / f"run-{highest + 1:03d}"
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError:
            continue  # concurrent grader (desktop + CLI share the dir) won this name
        return run_dir


def _load_result(base_dir: Path, run_id: str) -> dict | None:
    if not RUN_ID.fullmatch(run_id):
        return None
    result_file = base_dir / run_id / "result.json"
    if not result_file.exists():
        return None
    return json.loads(result_file.read_text(encoding="utf-8"))


def _read_json(path: Path) -> dict | None:
    """Best-effort read of an engine-written JSON report for display."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("unreadable report JSON %s", path)
        return None


def create_app(
    base_dir: Path, *, expected_hosts: set[str] | None = None
) -> FastAPI:
    base_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="dpi-eval-web")
    app.mount("/files", StaticFiles(directory=base_dir), name="files")

    if expected_hosts:
        # DNS-rebinding guard (spec amendment 2026-07-18): reject any
        # request whose Host header isn't the loopback host:port this
        # server was bound to. Opt-in via expected_hosts so existing
        # callers (and TestClient's default "testserver" Host) are
        # unaffected unless a caller wires it up explicitly.
        @app.middleware("http")
        async def _host_guard(request: Request, call_next):
            if request.headers.get("host") not in expected_hosts:
                return JSONResponse(
                    {"error": "invalid host"}, status_code=403
                )
            return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def form() -> str:
        return pages.form_page(token=os.environ.get("DPI_EVAL_TOKEN"))

    @app.post("/grade")
    def grade(
        gt_files: list[UploadFile] = File(default=[]),
        ocr_files: list[UploadFile] = File(default=[]),
    ):
        try:
            run_dir = _grade_pipeline(gt_files, ocr_files, base_dir)
        except GradeValidationError as exc:
            return HTMLResponse(
                pages.error_page(exc.message, details=exc.details),
                status_code=400,
            )
        return RedirectResponse(f"/runs/{run_dir.name}", status_code=303)

    @app.post("/grade-paths")
    async def grade_paths(request: Request):
        _check_token(request)

        body = await request.json()
        gt_dir = Path(body["gt_dir"])
        ocr_dir = Path(body["ocr_dir"])
        for path in (gt_dir, ocr_dir):
            if not path.is_dir():
                return JSONResponse(
                    {"error": f"Not a readable directory: {path}"},
                    status_code=400,
                )

        try:
            gt_uploads = _enumerate_dir(gt_dir)
            ocr_uploads = _enumerate_dir(ocr_dir)
        except OSError as exc:
            return JSONResponse(
                {"error": f"Could not read files: {exc}"}, status_code=400
            )

        try:
            run_dir = _grade_pipeline(gt_uploads, ocr_uploads, base_dir)
        except GradeValidationError as exc:
            message = exc.message
            if exc.details:
                message = f"{message} {'; '.join(exc.details)}"
            return JSONResponse({"error": message}, status_code=400)

        return JSONResponse({"run_url": f"/runs/{run_dir.name}"})

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def results(run_id: str):
        record = _load_result(base_dir, run_id)
        if record is None:
            return HTMLResponse(
                pages.error_page("No such run."), status_code=404
            )
        reports_dir = base_dir / run_id / "reports"
        summary = _read_json(reports_dir / "summary.json")
        page_metrics = {}
        for stem in record["succeeded"]:
            metrics = _read_json(reports_dir / f"{stem}.json")
            if metrics is not None:
                page_metrics[stem] = metrics
        return pages.results_page(
            run_id,
            record["succeeded"],
            record["failed"],
            record["missing"],
            record["exit_code"],
            summary=summary,
            page_metrics=page_metrics,
        )

    @app.get("/runs/{run_id}/reports/{name}", response_class=HTMLResponse)
    def wrapped_report(run_id: str, name: str):
        record = _load_result(base_dir, run_id)
        if record is None or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            return HTMLResponse(pages.error_page("No such report."), status_code=404)
        report = base_dir / run_id / "reports" / f"{name}.html"
        if not report.is_file():
            return HTMLResponse(pages.error_page("No such report."), status_code=404)
        html = report.read_text(encoding="utf-8")
        body = (
            html.split("<body", 1)[-1].split(">", 1)[-1].rsplit("</body>", 1)[0]
            if "<body" in html
            else html
        )
        body = pages.transform_report_body(body)
        return pages.report_page(run_id, name, body)

    @app.get("/runs/{run_id}/download")
    def download(run_id: str):
        record = _load_result(base_dir, run_id)
        reports_dir = base_dir / run_id / "reports"
        if record is None or not reports_dir.is_dir():
            return HTMLResponse(
                pages.error_page("No reports for that run."), status_code=404
            )
        archive = shutil.make_archive(
            str(base_dir / run_id / f"dpi-eval-{run_id}-reports"),
            "zip",
            root_dir=reports_dir,
        )
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"dpi-eval-{run_id}-reports.zip",
        )

    trans_root = sess.transcriptions_root(base_dir)

    def _token() -> str:
        return os.environ.get("DPI_EVAL_TOKEN") or ""

    @app.get("/transcribe", response_class=HTMLResponse)
    def transcribe_home():
        return pages.transcribe_home_page(sess.list_sessions(trans_root), _token())

    @app.post("/transcribe/sessions", response_class=HTMLResponse)
    def transcribe_create(
        request: Request,
        token: str = Form(default=None),
        source_type: str = Form(...),
        folder: str = Form(default=""),
        manifest_url: str = Form(default=""),
        mode: str = Form(default="from_scratch"),
        draft_folder: str = Form(default=""),
        collection: str = Form(default=""),
    ):
        _check_token(request, token)
        drafts = Path(draft_folder) if draft_folder.strip() else None
        try:
            if source_type == "local":
                session = sess.create_local_session(
                    trans_root, Path(folder), mode, collection, drafts)
            else:
                records = iiif.parse_manifest(iiif.fetch_manifest(manifest_url))
                session = sess.create_iiif_session(
                    trans_root, manifest_url, records, mode, collection, drafts)
        except (sess.SessionError, iiif.IIIFError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return pages.selection_page(session, _token())

    @app.post("/transcribe/sessions/{sid}/confirm")
    def transcribe_confirm(
        sid: str, request: Request,
        token: str = Form(default=None),
        pages_selected: list[str] = Form(default=[], alias="pages"),
    ):
        _check_token(request, token)
        try:
            sess.confirm_session(trans_root, sid, [int(i) for i in pages_selected])
        except (sess.SessionError, ValueError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{sid}", status_code=303)

    @app.get("/transcribe/sessions/{sid}", response_class=HTMLResponse)
    def transcribe_session(sid: str):
        try:
            session = sess.load_session(trans_root, sid)
        except sess.SessionError:
            return HTMLResponse(pages.error_page("No such session."), status_code=404)
        problems = sess.reconcile(trans_root, session)
        return pages.session_page(session, problems, _token())

    def _next_pending(session, after_index):
        for page in session["pages"]:
            if page["source_index"] > after_index and page["status"] == "pending":
                return page["source_index"]
        return None

    @app.get("/transcribe/sessions/{sid}/pages/{n}", response_class=HTMLResponse)
    def editor(sid: str, n: int, notice: str = ""):
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=404)
        gt_file = sess.gt_path(trans_root, session, page)
        gt_text = gt_file.read_text(encoding="utf-8") if gt_file.exists() else ""
        draft = sess.draft_text(session, page) if session["mode"] == "corrected" else ""
        total = len(session["pages"])
        ordinal = [p["source_index"] for p in session["pages"]].index(n) + 1
        return pages.editor_page(session, page, draft, gt_text, _token(),
                                 position=f"Page {ordinal} of {total}",
                                 notice=notice)

    @app.post("/transcribe/sessions/{sid}/pages/{n}")
    async def editor_action(sid: str, n: int, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        action = form.get("action", "")
        try:
            if action == "save":
                session, changes = sess.save_page(
                    trans_root, sid, n, str(form.get("text", "")),
                    elapsed=int(form.get("elapsed") or 0),
                    active=int(form.get("active") or 0),
                    nonce=str(form.get("nonce") or ""))
                nxt = _next_pending(session, n)
                target = (f"/transcribe/sessions/{sid}/pages/{nxt}"
                          if nxt is not None else f"/transcribe/sessions/{sid}")
                if changes:
                    target += f"?notice={changes}+changes+applied+by+conventions+v{session['conventions_version']}"
                return RedirectResponse(target, status_code=303)
            if action == "no_text":
                sess.mark_no_text(trans_root, sid, n, str(form.get("reason") or ""))
            elif action == "flag":
                sess.set_flag(trans_root, sid, n,
                              form.get("flagged") is not None,
                              str(form.get("note") or ""))
            elif action in ("adopt", "discard"):
                sess.resolve_attention(trans_root, sid, n, action)
            else:
                return HTMLResponse(pages.error_page("Unknown action."), status_code=400)
        except (sess.SessionError, ValueError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{sid}", status_code=303)

    def _local_master(session, page) -> Path:
        return Path(session["source"]["path"]) / page["image_file"]

    @app.post("/transcribe/sessions/{sid}/grade/preview", response_class=HTMLResponse)
    async def grade_preview(sid: str, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        files: list[tuple[str, bytes]] = []
        ocr_folder = str(form.get("ocr_folder") or "").strip()
        if ocr_folder:
            folder = Path(ocr_folder)
            if not folder.is_dir():
                return HTMLResponse(
                    pages.error_page(f"Not a readable directory: {folder}"),
                    status_code=400)
            files = [(u.filename, u.file.read()) for u in _enumerate_dir(folder)]
        else:
            for upload in form.getlist("ocr_files"):
                if getattr(upload, "filename", None):
                    files.append((upload.filename, upload.file.read()))
        if not files:
            return HTMLResponse(
                pages.error_page("Pick the OCR folder or upload OCR files."),
                status_code=400)
        try:
            session = sess.load_session(trans_root, sid)
            alignment = sess.stage_ocr(trans_root, sid, files)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return pages.alignment_page(session, alignment, _token())

    @app.post("/transcribe/sessions/{sid}/grade/confirm")
    async def grade_confirm(sid: str, request: Request):
        form = await request.form()
        _check_token(request, form.get("token"))
        overrides = {
            key[len("override_"):]: str(value)
            for key, value in form.items() if key.startswith("override_")}
        try:
            gt_dir, ocr_dir = sess.stage_for_grade(trans_root, sid, overrides)
            run_dir = _run_and_register(gt_dir, ocr_dir, base_dir)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        finally:
            sess.clear_staging(trans_root, sid)
        return RedirectResponse(f"/runs/{run_dir.name}", status_code=303)

    @app.post("/transcribe/sessions/{sid}/clone")
    def clone_session(sid: str, request: Request, token: str = Form(default=None)):
        _check_token(request, token)
        try:
            source = sess.load_session(trans_root, sid)
            other_mode = "corrected" if source["mode"] == "from_scratch" else "from_scratch"
            selected = [p["source_index"] for p in source["pages"]]
            if source["source"]["type"] == "local":
                clone = sess.create_local_session(
                    trans_root, Path(source["source"]["path"]), other_mode,
                    source["collection"],
                    Path(source["draft_source"]) if source.get("draft_source") else None)
            else:
                records = iiif.parse_manifest(
                    iiif.fetch_manifest(source["source"]["manifest_url"]))
                clone = sess.create_iiif_session(
                    trans_root, source["source"]["manifest_url"], records,
                    other_mode, source["collection"])
            sess.confirm_session(trans_root, clone["id"], selected)
        except (sess.SessionError, iiif.IIIFError) as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return RedirectResponse(f"/transcribe/sessions/{clone['id']}", status_code=303)

    @app.post("/transcribe/sessions/{sid}/export")
    def export(sid: str, request: Request, token: str = Form(default=None)):
        _check_token(request, token)
        try:
            archive = sess.export_session(trans_root, sid)
        except sess.SessionError as exc:
            return HTMLResponse(pages.error_page(str(exc)), status_code=400)
        return FileResponse(archive, media_type="application/zip",
                            filename=archive.name)

    @app.get("/transcribe/sessions/{sid}/images/{n}/info.json")
    def image_info(sid: str, n: int, request: Request):
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
            width, height = derive.image_dims(_local_master(session, page))
        except derive.DeriveError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except (sess.SessionError, KeyError, OSError):
            return JSONResponse({"error": "no such image"}, status_code=404)
        base = f"http://{request.headers.get('host')}/transcribe/sessions/{sid}/images/{n}"
        return JSONResponse(
            derive.info_json(base, width, height),
            media_type='application/ld+json;profile="http://iiif.io/api/image/3/context.json"')

    @app.get("/transcribe/sessions/{sid}/images/{n}/{region}/{size}/{rotation}/{quality_fmt}")
    def image_request(sid: str, n: int, region: str, size: str,
                      rotation: str, quality_fmt: str):
        if "." not in quality_fmt:
            return JSONResponse({"error": "bad request"}, status_code=400)
        quality, fmt = quality_fmt.rsplit(".", 1)
        try:
            session = sess.load_session(trans_root, sid)
            page = sess.page_by_index(session, n)
            derive.parse_params(region, size, rotation, quality, fmt)
            cache = sess.session_dir(trans_root, sid) / "derivatives"
            out = derive.derive(_local_master(session, page), region, size, cache)
        except derive.DeriveError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except (sess.SessionError, KeyError, OSError):
            return JSONResponse({"error": "no such image"}, status_code=404)
        return FileResponse(out, media_type="image/jpeg")

    return app


def _pick_port(preferred: int = PREFERRED_PORT) -> int:
    """Prefer the bookmarkable port; fall back to an ephemeral one."""
    try:
        with socket.socket() as probe:
            probe.bind((HOST, preferred))
            return preferred
    except OSError:
        with socket.socket() as probe:
            probe.bind((HOST, 0))
            return probe.getsockname()[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dpi-eval-web")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab (a desktop shell provides the window)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not os.environ.get("DPI_EVAL_TOKEN"):
        # Browser mode: mint a per-launch token; forms embed it as a
        # hidden field (CSRF), matching the desktop shell's header token.
        os.environ["DPI_EVAL_TOKEN"] = secrets.token_urlsafe(24)
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    app = create_app(
        Path.home() / "dpi-eval-runs",
        expected_hosts={f"{HOST}:{port}", f"localhost:{port}"},
    )
    print(f"dpi-eval-web running at {url}", flush=True)
    print(
        "Done? Close the browser tab, then close this window (or press Ctrl+C).",
        flush=True,
    )
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
