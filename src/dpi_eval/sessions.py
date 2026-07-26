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
import shutil
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dpi_eval.adapter import hocr_to_text, sniff_format
from dpi_eval.alignment import OCR_STAGE_EXTENSIONS, align
from dpi_eval.conventions import CONVENTIONS_VERSION, normalize
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


LOCK_TIMEOUT = 10.0
LOCK_STALE_AFTER = 60.0
_LOCK_POLL = 0.01
_held_locks = threading.local()


@contextmanager
def session_lock(root: Path, session_id: str):
    """Serialize one session's read-modify-write of session.json.

    `save_session` is atomic (os.replace), which prevents a torn file but
    not a lost update: every mutator loads the whole record, edits it and
    writes it back, and the routes are plain `def`, so FastAPI runs them
    in a threadpool and two requests (two editor tabs, or a flag submit
    racing a save) genuinely interleave. The loser's entire record used
    to be discarded, including seconds_elapsed/seconds_active — the
    pilot's measurement, recorded and shown to the student and then
    silently dropped.

    The lock is an O_CREAT|O_EXCL lock file, not fcntl/msvcrt: those are
    per-platform, this ships on macOS and Windows, and no dependency may
    be added (every wheel has to be bundled for offline lab installs).
    It therefore covers threads and separate processes alike, and is held
    across the whole load-mutate-save window, not just the write.

    Re-entrant per thread, so a mutator that calls another locked helper
    cannot self-deadlock. Only ever one lock path per session, so no
    lock-ordering cycle between sessions is possible.
    """
    directory = session_dir(root, session_id)
    key = str(directory)
    depths = getattr(_held_locks, "depths", None)
    if depths is None:
        depths = _held_locks.depths = {}
    if depths.get(key):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return

    path = directory / "session.lock"
    directory.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            # A crash can leave the file behind; a session that stays
            # locked forever would be worse than the race.
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > LOCK_STALE_AFTER:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise SessionError(
                    "Another change to this session is still in progress. "
                    "Wait a moment and try again — your text is still in "
                    "the editor.")
            time.sleep(_LOCK_POLL)
    try:
        os.write(fd, str(os.getpid()).encode("ascii"))
    finally:
        os.close(fd)
    depths[key] = 1
    try:
        yield
    finally:
        depths[key] = 0
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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
    with session_lock(root, session_id):
        session = load_session(root, session_id)
        if session["state"] != "draft":
            raise SessionError("Session is already confirmed.")
        if not selected_indices:
            raise SessionError("Select at least one page.")
        known = {p["source_index"] for p in session["pages"]}
        unknown = sorted(set(selected_indices) - known)
        if unknown:
            # The selection arrives from a checkbox form, so an index with
            # no page means the client and the server disagree about the
            # page set. Confirming the intersection would silently drop
            # pages the student ticked and, if nothing matched, activate a
            # session with pages: [] that exports as an empty bundle.
            # Fail the whole request and name the offenders instead.
            listed = ", ".join(str(i) for i in unknown)
            raise SessionError(
                f"This session has no page {listed}. The page list on your "
                "screen no longer matches the session — reload the page and "
                "choose again.")
        keep = set(selected_indices)
        session["pages"] = [p for p in session["pages"] if p["source_index"] in keep]
        session["state"] = "active"
        # gt/ is part of an active session's directory shape from the start,
        # so crash-recovery scenarios (orphan GT files) can be detected even
        # before the first save_page.
        (session_dir(root, session_id) / "gt").mkdir(parents=True, exist_ok=True)
        save_session(root, session)
        return session


NO_TEXT_REASONS = ("blank", "image_only", "illegible")


def page_by_index(session: dict, source_index: int) -> dict:
    for page in session["pages"]:
        if page["source_index"] == source_index:
            return page
    raise SessionError("No such page in this session.")


def gt_path(root: Path, session: dict, page: dict) -> Path:
    return session_dir(root, session["id"]) / "gt" / f"{page['stem']}.gt.txt"


def check_version(session: dict) -> None:
    if session["conventions_version"] != CONVENTIONS_VERSION:
        raise SessionError(
            f"This session was created under conventions "
            f"v{session['conventions_version']}; the app now runs "
            f"v{CONVENTIONS_VERSION}. The session is read-only — export "
            "what exists and start a new session."
        )


def _mutable(root: Path, session_id: str) -> dict:
    session = load_session(root, session_id)
    if session["state"] != "active":
        raise SessionError("Session is not confirmed yet.")
    check_version(session)
    return session


def save_page(
    root: Path, session_id: str, source_index: int, text: str,
    *, elapsed: int, active: int, nonce: str,
) -> tuple[dict, int]:
    with session_lock(root, session_id):
        session = _mutable(root, session_id)
        page = page_by_index(session, source_index)
        normalized, changes = normalize(text)
        if not normalized.strip():
            raise SessionError(
                'The transcription is empty — use "No text on this page" instead.')
        # Write order is fixed (spec): GT file first, session.json second.
        target = gt_path(root, session, page)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(normalized, encoding="utf-8")
        os.replace(tmp, target)
        page["status"] = "saved"
        page["no_text_reason"] = None
        page["saved_at"] = _now()
        if nonce != page.get("last_nonce"):
            page["seconds_elapsed"] += max(0, int(elapsed))
            page["seconds_active"] += max(0, int(active))
            page["last_nonce"] = nonce
        save_session(root, session)
        return session, changes


def mark_no_text(root: Path, session_id: str, source_index: int, reason: str) -> dict:
    if reason not in NO_TEXT_REASONS:
        raise SessionError(
            "Pick why there is no text: blank, image-only, or illegible.")
    with session_lock(root, session_id):
        session = _mutable(root, session_id)
        page = page_by_index(session, source_index)
        target = gt_path(root, session, page)
        if target.exists():
            target.unlink()  # a retracted page must never be graded
        page["status"] = "no_text"
        page["no_text_reason"] = reason
        page["saved_at"] = _now()
        save_session(root, session)
        return session


def set_flag(root: Path, session_id: str, source_index: int,
             flagged: bool, note: str) -> dict:
    with session_lock(root, session_id):
        session = _mutable(root, session_id)
        page = page_by_index(session, source_index)
        page["flagged"] = bool(flagged)
        page["note"] = note.strip()
        save_session(root, session)
        return session


def reconcile(root: Path, session: dict) -> list[dict]:
    """Compare gt/ against session.json. Grading is blocked while any
    item is returned (stage_for_grade enforces)."""
    problems = []
    gt_dir = session_dir(root, session["id"]) / "gt"
    on_disk = {p.name[: -len(".gt.txt")] for p in gt_dir.glob("*.gt.txt")} if gt_dir.exists() else set()
    for page in session["pages"]:
        if page["status"] == "saved" and page["stem"] not in on_disk:
            problems.append({"stem": page["stem"], "problem": "missing_gt"})
        if page["status"] != "saved" and page["stem"] in on_disk:
            problems.append({"stem": page["stem"], "problem": "orphan_gt"})
    return problems


def resolve_attention(root: Path, session_id: str, source_index: int,
                      action: str) -> dict:
    with session_lock(root, session_id):
        session = _mutable(root, session_id)
        page = page_by_index(session, source_index)
        target = gt_path(root, session, page)
        if action == "adopt":
            if not target.exists():
                raise SessionError("Nothing on disk to adopt for that page.")
            page["status"] = "saved"
            page["no_text_reason"] = None
            page["saved_at"] = _now()
        elif action == "discard":
            if target.exists():
                target.unlink()
            page["status"] = "pending"
            page["saved_at"] = None
        else:
            raise SessionError("Resolve with adopt or discard.")
        save_session(root, session)
        return session


def draft_text(session: dict, page: dict) -> str:
    if not session.get("draft_source") or not page.get("draft_file"):
        return ""
    path = Path(session["draft_source"]) / page["draft_file"]
    if not path.exists():
        return ""
    if detect_draft_format(path) == "hocr":
        return hocr_to_text(path)
    return path.read_text(encoding="utf-8", errors="replace")


def _staging(root: Path, session_id: str) -> Path:
    return session_dir(root, session_id) / "staging"


def clear_staging(root: Path, session_id: str) -> None:
    shutil.rmtree(_staging(root, session_id), ignore_errors=True)


def stage_ocr(root: Path, session_id: str, files: list[tuple[str, bytes]]) -> dict:
    session = _mutable(root, session_id)
    # Names arrive relative to the picked folder, so `batch-a/page_0.txt`
    # and `batch-b/page_0.txt` both flatten to `page_0.txt`: one silently
    # won and was then graded against the other page's ground truth.
    # _grade_pipeline refuses the same shape ("grading could silently use
    # the wrong page"), and it rejects before writing anything — so do the
    # check ahead of clear_staging, or a rejected upload would also
    # destroy the staging that was already there.
    kept: list[tuple[str, bytes]] = []
    seen: dict[str, str] = {}
    for name, data in files:
        flat = Path(name).name
        if flat.startswith("."):
            continue
        if flat in seen:
            raise SessionError(
                f"Two OCR files would end up with the same name "
                f"({flat}), so grading could silently use the wrong page: "
                f"{seen[flat]} and {name}. Flatten the folder or rename "
                "these files, then try again.")
        seen[flat] = name
        kept.append((flat, data))
    clear_staging(root, session_id)
    ocr_dir = _staging(root, session_id) / "ocr"
    ocr_dir.mkdir(parents=True)
    for flat, data in kept:
        (ocr_dir / flat).write_bytes(data)
    by = "index" if session["source"]["type"] == "iiif" else "stem"
    result = align(session["pages"], [p.name for p in ocr_dir.iterdir()], by=by)
    (_staging(root, session_id) / "alignment.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    return result


def stage_for_grade(
    root: Path, session_id: str, overrides: dict[str, str]
) -> tuple[Path, Path]:
    session = _mutable(root, session_id)
    problems = reconcile(root, session)
    if problems:
        raise SessionError(
            "Some pages need attention before grading (transcriptions on "
            "disk that don't match the session record). Resolve them from "
            "the session page first.")
    alignment_file = _staging(root, session_id) / "alignment.json"
    if not alignment_file.exists():
        raise SessionError("Upload or pick the OCR folder first (preview step).")
    mapping = json.loads(alignment_file.read_text(encoding="utf-8"))["matched"]
    mapping.update({k: v for k, v in overrides.items() if v})

    ocr_src = _staging(root, session_id) / "ocr"
    for stem, ocr_name in overrides.items():
        if not ocr_name:
            continue
        # Containment first: `.exists()` and the suffix check below constrain
        # what the file is named, never where it lives, so `../../secret.txt`
        # and absolute paths satisfied both and were copied into the graded
        # set (and thence into the report). stage_ocr already flattens every
        # staged name to its basename, so a legitimate override is always a
        # plain filename.
        if Path(ocr_name).name != ocr_name:
            raise SessionError(
                f"Override for {stem} names {ocr_name}, which is not a plain "
                "filename from the staged OCR upload.")
        if not (ocr_src / ocr_name).exists():
            raise SessionError(
                f"Override for {stem} names {ocr_name}, which is not in the "
                "staged OCR upload.")
        if Path(ocr_name).suffix.lower() not in OCR_STAGE_EXTENSIONS:
            raise SessionError(
                f"Override for {stem} names {ocr_name}, which is not a "
                "recognized OCR format (.hocr/.xml/.txt).")

    saved_pages = [p for p in session["pages"] if p["status"] == "saved"]
    if not saved_pages:
        raise SessionError("No saved transcriptions to grade yet.")

    staged_gt = _staging(root, session_id) / "grade" / "gt"
    staged_ocr = _staging(root, session_id) / "grade" / "ocr"
    for directory in (staged_gt, staged_ocr):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    for page in saved_pages:
        shutil.copy2(gt_path(root, session, page), staged_gt / f"{page['stem']}.gt.txt")
        ocr_name = mapping.get(page["stem"])
        if ocr_name and (ocr_src / ocr_name).exists():
            ext = OCR_STAGE_EXTENSIONS.get(Path(ocr_name).suffix.lower())
            if ext:
                shutil.copy2(ocr_src / ocr_name, staged_ocr / f"{page['stem']}{ext}")
    return staged_gt, staged_ocr


def _safe_collection(label: str) -> str:
    """Flatten a collection label to one safe path segment for export."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return slug or "_unsorted"


def export_session(root: Path, session_id: str) -> Path:
    session = load_session(root, session_id)
    problems = reconcile(root, session)
    if problems:
        raise SessionError("Resolve needs-attention pages before exporting.")
    collection = _safe_collection(session["collection"] or "_unsorted")
    bundle_root = session_dir(root, session_id) / "export"
    shutil.rmtree(bundle_root, ignore_errors=True)
    bundle = bundle_root / collection / session_id
    (bundle / "gt").mkdir(parents=True)
    for page in session["pages"]:
        if page["status"] == "saved":
            shutil.copy2(gt_path(root, session, page), bundle / "gt" / f"{page['stem']}.gt.txt")
    sidecar = {
        "session_id": session_id,
        "collection": session["collection"],
        "arm": session["mode"],
        "conventions_version": session["conventions_version"],
        "source": session["source"],
        "pages": [
            {"stem": p["stem"], "status": p["status"], "arm": session["mode"],
             "no_text_reason": p["no_text_reason"], "canvas_id": p["canvas_id"],
             "seconds_elapsed": p["seconds_elapsed"],
             "seconds_active": p["seconds_active"], "flagged": p["flagged"],
             "note": p["note"], "saved_at": p["saved_at"]}
            for p in session["pages"]
        ],
    }
    (bundle / "transcriptions.json").write_text(
        json.dumps(sidecar, indent=2), encoding="utf-8")
    zip_path = session_dir(root, session_id) / f"dpi-eval-gt-{session_id}"
    archive = shutil.make_archive(str(zip_path), "zip", root_dir=bundle_root)
    with zipfile.ZipFile(archive):  # smoke-validate the archive
        pass
    return Path(archive)
