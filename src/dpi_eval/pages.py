"""Self-contained HTML pages for dpi-eval-web.

Pure string builders: no framework imports, no external assets (lab
machines may be offline; nothing leaves localhost).
"""

from html import escape


def _document(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{escape(title)}</title>\n</head>\n<body>\n{body}\n</body>\n</html>"
    )


def form_page() -> str:
    body = """
<h1>Grade OCR against ground truth</h1>
<form action="/grade" method="post" enctype="multipart/form-data">
  <label>Ground-truth folder
    <input type="file" name="gt_files" webkitdirectory multiple required></label>
  <label>OCR folder
    <input type="file" name="ocr_files" webkitdirectory multiple required></label>
  <button type="submit">Run</button>
</form>
"""
    return _document("dpi-eval", body)


def results_page(
    run_id: str,
    succeeded: list[str],
    failed: list[str],
    missing: list[str],
    exit_code: int,
) -> str:
    stems = "".join(f"<li>{escape(stem)}</li>" for stem in succeeded)
    body = (
        f"<h1>Run {escape(run_id)}</h1>"
        f"<p>graded {len(succeeded)}, failed {len(failed)}, "
        f"missing {len(missing)}, exit {exit_code}</p>"
        f"<ul>{stems}</ul>"
    )
    return _document(f"dpi-eval — {run_id}", body)


def error_page(message: str, details: tuple[str, ...] = ()) -> str:
    items = "".join(f"<li><code>{escape(d)}</code></li>" for d in details)
    detail_html = f"<ul>{items}</ul>" if items else ""
    body = f"<h1>Can't grade this batch</h1><p>{escape(message)}</p>{detail_html}" \
           '<p><a href="/">Back to the form</a></p>'
    return _document("dpi-eval — problem", body)
