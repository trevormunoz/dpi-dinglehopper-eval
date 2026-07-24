"""Transcription session lifecycle. Files-first: a session is a directory
holding session.json (all metadata) and gt/ (pure normalized text only).

Engine fence: this module never imports dinglehopper. Grading goes
through staged, status-filtered copies (stage_for_grade, Task 7) — the
engine's pairing never reads raw gt/ or session state.
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from dpi_eval.adapter import sniff_format
from dpi_eval.alignment import align
from dpi_eval.conventions import CONVENTIONS_VERSION
from dpi_eval.iiif import CanvasRecord, make_stem

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"}
_ALTO_PAGE_MARKERS = (b"<alto", b"<PcGts")


class SessionError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def transcriptions_root(base_dir: Path) -> Path:
    root = base_dir / "transcriptions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_dir(root: Path, session_id: str) -> Path:
    if not re.fullmatch(r"s-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", session_id):
        raise SessionError("No such session.")
    return root / session_id


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"s-{stamp}-{secrets.token_hex(2)}"


def save_session(root: Path, session: dict) -> None:
    target = session_dir(root, session["id"]) / "session.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_session(root: Path, session_id: str) -> dict:
    path = session_dir(root, session_id) / "session.json"
    if not path.exists():
        raise SessionError("No such session.")
    return json.loads(path.read_text(encoding="utf-8"))


def list_sessions(root: Path) -> list[dict]:
    sessions = []
    for path in sorted(root.glob("s-*/session.json"), reverse=True):
        try:
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sessions


def detect_draft_format(path: Path) -> str:
    """hOCR and plain text are usable draft formats; ALTO/PAGE are
    rejected — the editor has no dinglehopper downstream to parse them
    (adapter passes XML through by design). Root-element sniff wins over
    extension, so hOCR delivered as .xml still passes."""
    if sniff_format(path) == "hocr":
        return "hocr"
    head = path.read_bytes()[:4096]
    if any(marker in head for marker in _ALTO_PAGE_MARKERS):
        return "rejected"
    return "txt" if path.suffix.lower() == ".txt" else "rejected"


def _page_record(stem: str, index: int) -> dict:
    return {
        "stem": stem, "status": "pending", "no_text_reason": None,
        "flagged": False, "note": "", "canvas_id": None, "image_url": None,
        "image_service": None, "label": "", "source_index": index,
        "seconds_elapsed": 0, "seconds_active": 0, "saved_at": None,
        "last_nonce": None, "draft_file": None,
    }


def _validate_drafts(pages: list[dict], draft_source: Path, by: str) -> None:
    files = [p.name for p in sorted(draft_source.iterdir()) if p.is_file()]
    for name in files:
        candidate = draft_source / name
        if candidate.suffix.lower() in (".hocr", ".xml", ".txt"):
            if detect_draft_format(candidate) == "rejected":
                raise SessionError(
                    f"Draft file {name} is ALTO/PAGE XML, which the editor "
                    "cannot display as text. Correction drafts must be hOCR "
                    "or plain .txt in v1."
                )
    result = align(pages, files, by=by)
    for page in pages:
        page["draft_file"] = result["matched"].get(page["stem"])


def _base_session(mode: str, collection: str, source: dict) -> dict:
    if mode not in ("from_scratch", "corrected"):
        raise SessionError(f"Unknown mode: {mode}")
    return {
        "id": new_session_id(), "created": _now(), "state": "draft",
        "mode": mode, "collection": collection.strip(),
        "source": source, "conventions_version": CONVENTIONS_VERSION,
        "draft_source": None, "pages": [],
    }


def create_local_session(
    root: Path, folder: Path, mode: str, collection: str,
    draft_source: Path | None,
) -> dict:
    if not folder.is_dir():
        raise SessionError(f"Not a readable folder: {folder}")
    images = sorted(
        p for p in folder.iterdir()
        if p.is_file() and not p.name.startswith(".")
        and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise SessionError("That folder contains no page images.")
    stems = [p.stem for p in images]
    if len(stems) != len(set(stems)):
        raise SessionError(
            "Two images in that folder share a name and differ only by "
            "extension — rename one; page stems must be unique.")
    session = _base_session(mode, collection, {"type": "local", "path": str(folder)})
    session["pages"] = [_page_record(p.stem, i) for i, p in enumerate(images)]
    for page, path in zip(session["pages"], images):
        page["image_file"] = path.name
    if mode == "corrected":
        if draft_source is None or not draft_source.is_dir():
            raise SessionError("Correction mode needs a draft folder.")
        session["draft_source"] = str(draft_source)
        _validate_drafts(session["pages"], draft_source, by="stem")
    save_session(root, session)
    return session


def create_iiif_session(
    root: Path, manifest_url: str, records: list[CanvasRecord],
    mode: str, collection: str, draft_source: Path | None = None,
) -> dict:
    session = _base_session(
        mode, collection, {"type": "iiif", "manifest_url": manifest_url})
    for i, record in enumerate(records):
        page = _page_record(make_stem(i, record.label), i)
        page.update(canvas_id=record.canvas_id, image_url=record.image_url,
                    image_service=record.image_service, label=record.label)
        session["pages"].append(page)
    stems = [p["stem"] for p in session["pages"]]
    if len(stems) != len(set(stems)):
        raise SessionError("Manifest produced colliding page stems.")
    if mode == "corrected":
        if draft_source is None or not draft_source.is_dir():
            raise SessionError("Correction mode needs a draft folder.")
        session["draft_source"] = str(draft_source)
        _validate_drafts(session["pages"], draft_source, by="index")
    save_session(root, session)
    return session


def confirm_session(root: Path, session_id: str, selected_indices: list[int]) -> dict:
    session = load_session(root, session_id)
    if session["state"] != "draft":
        raise SessionError("Session is already confirmed.")
    if not selected_indices:
        raise SessionError("Select at least one page.")
    keep = set(selected_indices)
    session["pages"] = [p for p in session["pages"] if p["source_index"] in keep]
    session["state"] = "active"
    save_session(root, session)
    return session
