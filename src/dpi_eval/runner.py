"""Run dinglehopper over GT/OCR pairs via its console scripts."""

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from dpi_eval.adapter import normalize_ocr_input
from dpi_eval.pairing import discover_pairs

logger = logging.getLogger("dpi_eval")


def run_page(gt: Path, ocr: Path, reports_dir: Path, prefix: str) -> Path:
    """Grade one OCR file against one GT file. Returns path to the JSON report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["dinglehopper", gt.as_posix(), ocr.as_posix(), prefix, str(reports_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return reports_dir / f"{prefix}.json"


def summarize(reports_dir: Path) -> Path:
    """Roll up all per-page reports in reports_dir into summary.{json,html}."""
    subprocess.run(
        ["dinglehopper-summarize", str(reports_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    return reports_dir / "summary.json"


@dataclass
class BatchResult:
    succeeded: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    summary: Path | None = None


def run_batch(
    gt_dir: Path,
    ocr_dir: Path,
    reports_dir: Path,
    max_failure_rate: float = 0.2,
) -> tuple[BatchResult, int]:
    result = BatchResult()
    pairs, result.missing = discover_pairs(gt_dir, ocr_dir)
    for stem in result.missing:
        logger.warning("no OCR file found for GT stem %r — skipping", stem)
    if not pairs:
        logger.error("nothing to grade: no GT/OCR pairs in %s / %s", gt_dir, ocr_dir)
        return result, 1

    if reports_dir.exists():
        stale = list(reports_dir.glob("*.json")) + list(reports_dir.glob("*.html"))
        for stale_file in stale:
            stale_file.unlink()
        normalized_dir = reports_dir / "_normalized"
        if normalized_dir.exists():
            shutil.rmtree(normalized_dir, ignore_errors=True)
        if stale:
            logger.info("cleared %d stale report(s) from %s", len(stale), reports_dir)

    workdir = reports_dir / "_normalized"
    for gt, ocr in pairs:
        stem = gt.name[: -len(".gt.txt")]
        try:
            normalized = normalize_ocr_input(ocr, workdir)
            run_page(gt, normalized, reports_dir, prefix=stem)
            result.succeeded.append(stem)
        except Exception as exc:  # skip-and-log per spec; batch verdict below
            detail = (getattr(exc, "stderr", None) or "").strip()
            last_line = detail.splitlines()[-1] if detail else ""
            suffix = f" — {last_line}" if last_line else ""
            logger.warning("page %r failed: %s%s", stem, exc, suffix)
            result.failed.append(stem)

    if result.succeeded:
        result.summary = summarize(reports_dir)

    failure_rate = len(result.failed) / len(pairs)
    if failure_rate > max_failure_rate:
        logger.error(
            "failure rate %.0f%% exceeds threshold %.0f%%",
            failure_rate * 100,
            max_failure_rate * 100,
        )
        return result, 1
    return result, 0
