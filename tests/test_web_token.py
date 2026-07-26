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


def test_check_token_denies_non_ascii_supplied_token(monkeypatch):
    """S12: secrets.compare_digest raises TypeError on a non-ASCII str, so
    the auth gate faulted with an unhandled 500 instead of denying. A gate
    that faults is not a gate."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    with pytest.raises(HTTPException) as header_exc:
        _check_token(_request({"X-DPI-Eval-Token": "sekrét"}))
    assert header_exc.value.status_code == 403
    with pytest.raises(HTTPException) as form_exc:
        _check_token(_request({}), form_token="sekrét")
    assert form_exc.value.status_code == 403


def test_non_ascii_form_token_is_a_403_not_a_traceback(tmp_path, monkeypatch):
    """S12 end to end: Reviewer B got an unhandled traceback out of
    transcribe_create by posting a UTF-8 token field."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/transcribe/sessions",
        data={"token": "sekrét", "source_type": "local", "folder": "/nope"})
    assert response.status_code == 403


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


def _grade_files():
    return [("gt_files", ("page_0.gt.txt", b"hello\n")),
            ("ocr_files", ("page_0.txt", b"hello\n"))]


def test_grade_rejects_request_without_token(tmp_path, monkeypatch):
    """PAR C2. /grade was the only mutating route with no _check_token.
    multipart/form-data is CORS-safelisted, so any page could POST to it
    with no preflight and drive the engine."""
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    client = TestClient(create_app(tmp_path))
    response = client.post("/grade", files=_grade_files())
    assert response.status_code == 403


def test_grade_accepts_request_with_form_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/grade", files=_grade_files(), data={"token": "sekrit"})
    assert response.status_code in (200, 303)


def test_grade_accepts_request_with_header_token(tmp_path, monkeypatch):
    monkeypatch.setenv("DPI_EVAL_TOKEN", "sekrit")
    client = TestClient(create_app(tmp_path))
    response = client.post(
        "/grade", files=_grade_files(),
        headers={"X-DPI-Eval-Token": "sekrit"})
    assert response.status_code in (200, 303)


def test_grading_form_embeds_the_token_so_browser_mode_still_posts(monkeypatch):
    """web.py's own comment promised 'forms embed it as a hidden field
    (CSRF)'; the grading form carried the token only in a <meta> tag for the
    /grade-paths fetch, so the plain form POST had nothing to send."""
    from dpi_eval import pages
    page = pages.form_page(token="sekrit")
    form = page[page.index('action="/grade"'):]
    assert '<input type="hidden" name="token" value="sekrit">' in form
