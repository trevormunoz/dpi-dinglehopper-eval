"""dpi-eval: grade a directory of OCR output against ground-truth samples."""

import argparse
import logging
import sys
from pathlib import Path

from dpi_eval.runner import run_batch


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="dpi-eval",
        description=(
            "Grade OCR output (ALTO/PAGE/text/hOCR) against plain-text ground "
            "truth using dinglehopper. GT files are <stem>.gt.txt; OCR files "
            "share the stem with extension .hocr, .xml, or .txt."
        ),
    )
    parser.add_argument("gt_dir", type=Path, help="directory of <stem>.gt.txt files")
    parser.add_argument("ocr_dir", type=Path, help="directory of OCR output files")
    parser.add_argument("reports_dir", type=Path, help="output directory for reports")
    parser.add_argument(
        "--max-failure-rate",
        type=float,
        default=0.2,
        help="fail the batch when this fraction of pages errors (default 0.2)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result, code = run_batch(
        args.gt_dir, args.ocr_dir, args.reports_dir, args.max_failure_rate
    )
    print(
        f"graded {len(result.succeeded)} page(s), "
        f"{len(result.failed)} failed, {len(result.missing)} missing OCR"
    )
    if result.summary:
        print(f"summary: {result.summary}")
    return code


if __name__ == "__main__":
    sys.exit(main())
