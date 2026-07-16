"""Run dinglehopper over GT/OCR pairs via its console scripts."""

import subprocess
from pathlib import Path


def run_page(gt: Path, ocr: Path, reports_dir: Path, prefix: str) -> Path:
    """Grade one OCR file against one GT file. Returns path to the JSON report."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["dinglehopper", str(gt), str(ocr), prefix, str(reports_dir)],
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
