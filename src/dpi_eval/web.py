"""dpi-eval-web: localhost web UI over run_batch for HDC student workers.

Imports only run_batch from the engine (spec hard constraint); never
imports dinglehopper.
"""

import argparse
import json
import logging
import re
import shutil
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dpi_eval import pages
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


def _save(uploads: list[UploadFile], dest: Path) -> None:
    """Flatten to basenames — pairing.py expects flat directories."""
    dest.mkdir(parents=True, exist_ok=True)
    for upload in uploads:
        (dest / Path(upload.filename).name).write_bytes(upload.file.read())


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


def create_app(base_dir: Path) -> FastAPI:
    base_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="dpi-eval-web")
    app.mount("/files", StaticFiles(directory=base_dir), name="files")

    @app.get("/", response_class=HTMLResponse)
    def form() -> str:
        return pages.form_page()

    @app.post("/grade")
    def grade(
        gt_files: list[UploadFile] = File(default=[]),
        ocr_files: list[UploadFile] = File(default=[]),
    ):
        gt_uploads = _real_uploads(gt_files)
        ocr_uploads = _real_uploads(ocr_files)
        if not any(
            Path(u.filename).name.endswith(".gt.txt") for u in gt_uploads
        ):
            return HTMLResponse(
                pages.error_page(
                    "The ground-truth folder has no .gt.txt files. Each "
                    "transcription must be named after its OCR file, with "
                    ".gt.txt in place of the extension — for example "
                    "page_3.gt.txt grades page_3.xml."
                ),
                status_code=400,
            )
        if not ocr_uploads:
            return HTMLResponse(
                pages.error_page(
                    "The OCR folder is empty — pick the folder that holds "
                    "the .hocr, .xml, or .txt files."
                ),
                status_code=400,
            )
        colliding = _collisions(gt_uploads) + _collisions(ocr_uploads)
        if colliding:
            return HTMLResponse(
                pages.error_page(
                    "Two or more files would end up with the same name, so "
                    "grading could silently use the wrong page. Flatten the "
                    "folder or rename these files, then try again:",
                    details=tuple(colliding),
                ),
                status_code=400,
            )
        run_dir = _next_run_dir(base_dir)
        _save(gt_uploads, run_dir / "gt")
        _save(ocr_uploads, run_dir / "ocr")
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
        return RedirectResponse(f"/runs/{run_dir.name}", status_code=303)

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
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    app = create_app(Path.home() / "dpi-eval-runs")
    print(f"dpi-eval-web running at {url}", flush=True)
    print(
        "Done? Close the browser tab, then close this window (or press Ctrl+C).",
        flush=True,
    )
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
