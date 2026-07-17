"""dpi-eval-web: localhost web UI over run_batch for HDC student workers.

Imports only run_batch from the engine (spec hard constraint); never
imports dinglehopper.
"""

import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from dpi_eval import pages
from dpi_eval.runner import run_batch

logger = logging.getLogger("dpi_eval.web")

RUN_ID = re.compile(r"run-\d{3,}")


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


def _save(uploads: list[UploadFile], dest: Path) -> None:
    """Flatten to basenames — pairing.py expects flat directories."""
    dest.mkdir(parents=True, exist_ok=True)
    for upload in uploads:
        (dest / Path(upload.filename).name).write_bytes(upload.file.read())


def _next_run_dir(base_dir: Path) -> Path:
    highest = 0
    for existing in base_dir.glob("run-*"):
        suffix = existing.name[len("run-") :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    run_dir = base_dir / f"run-{highest + 1:03d}"
    run_dir.mkdir(parents=True)
    return run_dir


def _load_result(base_dir: Path, run_id: str) -> dict | None:
    if not RUN_ID.fullmatch(run_id):
        return None
    result_file = base_dir / run_id / "result.json"
    if not result_file.exists():
        return None
    return json.loads(result_file.read_text(encoding="utf-8"))


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
            return HTMLResponse(pages.error_page("No such run."), status_code=404)
        return pages.results_page(
            run_id,
            record["succeeded"],
            record["failed"],
            record["missing"],
            record["exit_code"],
        )

    return app
