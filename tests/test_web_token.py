import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dpi_eval.web import _check_token, _run_and_register, create_app
from fastapi import HTTPException, Request


def _request(headers: dict) -> Request:
    scope = {"type": "http", "headers": [
        (k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_check_token_accepts_header_or_form(monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    _check_token(_request({"X-DPI-Eval-Token": "sekrit"}))
    _check_token(_request({}), form_token="sekrit")
    with pytest.raises(HTTPException):
        _check_token(_request({}), form_token="wrong")


def test_check_token_denies_when_unset(monkeypatch):
    monkeypatch.delenv("DPI_EVAL_TOKEN", raising=False)
    with pytest.raises(HTTPException):
        _check_token(_request({}), form_token="anything")


def test_run_and_register_writes_result_json(tmp_path):
    gt = tmp_path / "gt"; ocr = tmp_path / "ocr"
    gt.mkdir(); ocr.mkdir()
    (gt / "page_0.gt.txt").write_text("hello world\n")
    (ocr / "page_0.txt").write_text("hello world\n")
    run_dir = _run_and_register(gt, ocr, tmp_path / "runs")
    assert run_dir.name.startswith("run-")
    assert (run_dir / "result.json").exists()


def test_existing_grade_still_works(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.post("/grade", files=[
        ("gt_files", ("page_0.gt.txt", b"hello\n")),
        ("ocr_files", ("page_0.txt", b"hello\n"))])
    assert response.status_code in (200, 303)
