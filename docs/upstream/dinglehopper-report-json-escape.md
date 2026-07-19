# Draft upstream issue — qurator-spk/dinglehopper

Status: DRAFT for Trevor to file under his own GitHub account
(decision 2026-07-19). Not yet filed.

Suggested title:

**report.json is invalid JSON when GT/OCR paths contain backslashes
(all Windows absolute paths)**

---

## Body

`templates/report.json.j2` interpolates the GT and OCR paths into the
JSON report without escaping:

```jinja
{
    "gt": "{{ gt }}",
    "ocr": "{{ ocr }}",
```

On Windows, absolute paths contain backslashes, so a report begins:

```json
{
    "gt": "C:\Users\someone\eval\gt\page_0.gt.txt",
```

`\U` is not a legal JSON escape sequence, so the file is invalid JSON.
Any consumer that parses the report fails — including dinglehopper's
own `dinglehopper-summarize`, which crashes on the first report it
reads:

```
File ".../dinglehopper/cli_summarize.py", line 23, in process
  report_data = json.load(f)
...
json.decoder.JSONDecodeError: Invalid \escape: line 2 column 14 (char 15)
```

### Reproduce (Windows)

```
dinglehopper C:\full\path\to\page_0.gt.txt C:\full\path\to\page_0.txt page_0 reports
dinglehopper-summarize reports   # exits 1 with the JSONDecodeError above
```

Relative forward-slash paths (as in most CI examples) mask the bug,
which is why it survives on POSIX systems and in typical test setups.
Observed on dinglehopper 0.11.0 (latest release at time of writing);
the template is unchanged on current master.

### Suggested fix

Use Jinja's `tojson` filter, which both escapes and quotes:

```jinja
{
    "gt": {{ gt|tojson }},
    "ocr": {{ ocr|tojson }},
```

(The `differences` dict already uses `|tojson`, so this matches the
template's existing convention.)

### Context

Found while packaging dinglehopper inside a desktop OCR-grading tool
for library digitization workflows at UMD; our Windows CI lane failed
on every real grade because `summarize` could not read the per-page
reports it was pointed at. Happy to open a PR with the two-line
template change and a Windows-path regression test if useful.
