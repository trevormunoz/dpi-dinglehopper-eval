"""Tests for run_page's subprocess argv construction."""

from pathlib import PureWindowsPath

from dpi_eval.runner import run_page


class _StubCompletedProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def test_run_page_passes_posix_style_paths_for_windows_inputs(tmp_path, monkeypatch):
    """dinglehopper's report.json.j2 interpolates the gt/ocr argv paths into its
    JSON report unescaped. A backslash-bearing Windows path therefore produces
    invalid JSON and crashes dinglehopper-summarize. .as_posix() keeps the argv
    both valid on Windows and safe to embed in the JSON report.
    """
    gt = PureWindowsPath("C:/Users/student/eval/gt/page_0.gt.txt")
    ocr = PureWindowsPath("C:/Users/student/eval/ocr/page_0.txt")
    reports_dir = tmp_path / "reports"

    captured_argv = {}

    def fake_run(argv, **kwargs):
        captured_argv["argv"] = argv
        return _StubCompletedProcess(returncode=0)

    monkeypatch.setattr("dpi_eval.runner.subprocess.run", fake_run)

    run_page(gt, ocr, reports_dir, prefix="page_0")

    argv = captured_argv["argv"]
    gt_arg, ocr_arg = argv[1], argv[2]
    assert "\\" not in gt_arg
    assert "\\" not in ocr_arg
    assert gt_arg == gt.as_posix()
    assert ocr_arg == ocr.as_posix()
