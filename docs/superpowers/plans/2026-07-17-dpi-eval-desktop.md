# dpi-eval-desktop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Every implementer must state its position in every report: "Task N of 11."**

**Goal:** A double-clickable Tauri v2 desktop app that bootstraps a bundled Python runtime on first launch and serves the existing `dpi-eval-web` experience in a native window — no terminal, no admin rights.

**Architecture:** Per spec `docs/superpowers/specs/2026-07-17-dpi-eval-desktop-tauri-design.md` (bundled-runtime primary): the app ships a pinned standalone CPython + offline wheelhouse as Tauri resources; a Rust shell bootstraps a venv on first run (pip manufactures the real console scripts), spawns `venv/bin/dpi-eval-web --no-browser`, parses the unbuffered URL sentinel, polls until ready, and kills the whole process tree on exit.

**Tech Stack:** Rust + Tauri v2 (shell), python-build-standalone + uv-built wheelhouse (runtime), existing Python package (engine/web, additive changes only).

**Two tracer bullets, by design:**
1. **The probe artifact (Tasks 2–6, human gate Task 7):** hello-world shell + trivial wheelhouse, run on real HDC hardware. Traces the *institutional* risk (Gatekeeper/AV/MDM) before real build investment — the spec's go/no-go gate.
2. **The product tracer (Task 9):** one fixture page graded end-to-end inside the Tauri window before any polish.

**Model tiers (user directive: reserve fable for the most complex problems):**

| Task | Model | Why |
|---|---|---|
| 1 Python web-layer changes | sonnet | standard TDD, complete code below |
| 2 Tauri scaffold | opus | version-sensitive scaffold; must reconcile plan code with current Tauri v2 APIs |
| 3 Lifecycle core (bootstrap/handshake/kill) | **fable** | cross-platform process semantics (setsid/killpg vs Job Objects), async handshake, self-repairing bootstrap — the hardest problem in the plan |
| 4 Probe runtime payload scripts | haiku | mechanical, complete scripts below |
| 5 Probe artifact assembly (macOS local) | sonnet | integration + manual verification |
| 6 CI probe artifacts (both OSes) | sonnet | GH Actions; Windows artifact comes from CI |
| 7 HDC probe run | **HUMAN (Trevor)** | real lab hardware; go/no-go |
| 8 Real wheelhouse | sonnet, **escalate to fable** if wheel-coverage gaps appear (ocrd stack may have sdist-only deps on Windows) |
| 9 Product tracer | sonnet | wiring + manual verification |
| 10 CI to release pipeline | sonnet | extends Task 6 |
| 11 Docs + findings | haiku | mechanical, text provided |

## Global Constraints

- NEVER import `dinglehopper.*` in any repo file. The bundled-runtime design satisfies this by construction (pip generates all entry shims). If the PyInstaller fallback ever activates, STOP — it requires a spec amendment and human ratification first.
- Engine files (`runner.py`, `cli.py`, `pairing.py`, `adapter.py`) are untouched by every task.
- Python package changes are EXACTLY the enumerated set in the spec: `--no-browser` flag, `flush=True` on the two startup prints, `_next_run_dir` retry. Nothing else without a spec amendment.
- Existing 37 tests stay green; run `uv run pytest` (never bare pytest) at every verify step.
- Server binds `127.0.0.1` only. Nothing leaves the machine; the wheelhouse install is offline (`--no-index`).
- No step of the shipped student experience may require admin rights or a terminal.
- Desktop code lives under `desktop/`; do not restructure the Python package.
- Tauri/Rust API surfaces drift: where this plan's Rust/config code conflicts with current Tauri v2 documentation, the current docs win — consult them (Context7: `/tauri-apps/tauri`), implement the plan's *behavior*, and record every deviation in your report.
- Work on branch `feat/dpi-eval-desktop` (create from `main` at start of Task 1).
- Tasks 6 and 10 require the repo to exist on a GitHub remote with Actions enabled — **blocked until the user approves pushing** (unpushed as of plan-writing). Flag at dispatch time, don't improvise a remote.

---

### Task 1: Python web-layer changes (the enumerated three)

**Files:**
- Modify: `src/dpi_eval/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: existing `main()`, `_next_run_dir`, `_pick_port` in `src/dpi_eval/web.py`.
- Produces: `main(argv=None)` accepting `--no-browser`; startup prints flushed; `_next_run_dir` collision-safe. Sentinel line format UNCHANGED: `dpi-eval-web running at http://127.0.0.1:PORT` — Task 3's Rust parser depends on this exact prefix.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_main_no_browser_skips_browser_timer(tmp_path, monkeypatch):
    import dpi_eval.web as web

    monkeypatch.setattr(web.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: None)

    def forbidden_timer(*a, **k):
        raise AssertionError("browser timer created despite --no-browser")

    monkeypatch.setattr(web.threading, "Timer", forbidden_timer)
    assert web.main(["--no-browser"]) == 0


def test_main_default_still_opens_browser(tmp_path, monkeypatch):
    import dpi_eval.web as web

    created = {}

    class FakeTimer:
        def __init__(self, delay, fn, args=None):
            created["timer"] = True

        def start(self):
            created["started"] = True

    monkeypatch.setattr(web.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(web.threading, "Timer", FakeTimer)
    assert web.main([]) == 0
    assert created == {"timer": True, "started": True}


def test_next_run_dir_retries_on_collision(tmp_path, monkeypatch):
    from dpi_eval.web import _next_run_dir

    base = tmp_path / "runs"
    base.mkdir()
    real_mkdir = Path.mkdir
    state = {"stolen": False}

    def racing_mkdir(self, *args, **kwargs):
        if not state["stolen"] and self.name == "run-001":
            state["stolen"] = True
            real_mkdir(self, *args, **kwargs)  # a rival grader claims run-001
            raise FileExistsError(str(self))
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", racing_mkdir)
    run_dir = _next_run_dir(base)
    assert run_dir.name == "run-002"
    assert run_dir.is_dir()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: `test_main_no_browser_skips_browser_timer` FAILS (`main() takes 0 positional arguments` or the AssertionError from the forbidden timer); `test_next_run_dir_retries_on_collision` FAILS with `FileExistsError`.

- [ ] **Step 3: Implement**

In `src/dpi_eval/web.py`: add `import argparse` to the stdlib imports. Replace `_next_run_dir` with:

```python
def _next_run_dir(base_dir: Path) -> Path:
    while True:
        highest = 0
        for existing in base_dir.glob("run-*"):
            suffix = existing.name[len("run-") :]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        run_dir = base_dir / f"run-{highest + 1:03d}"
        try:
            run_dir.mkdir(parents=True)
        except FileExistsError:
            continue  # concurrent grader (desktop + CLI share the dir) won this name
        return run_dir
```

Replace `main` with:

```python
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dpi-eval-web")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab (a desktop shell provides the window)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    port = _pick_port()
    url = f"http://{HOST}:{port}"
    app = create_app(Path.home() / "dpi-eval-runs")
    print(f"dpi-eval-web running at {url}", flush=True)
    print(
        "Done? Close the browser tab, then close this window (or press Ctrl+C).",
        flush=True,
    )
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0
```

(`flush=True` is the pipe-buffering fix from the spec's PAR findings — without it the sentinel never reaches the shell before uvicorn blocks.)

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: 40 passed (37 + 3).

- [ ] **Step 5: Commit**

```bash
git add src/dpi_eval/web.py tests/test_web.py
git commit -m "feat: --no-browser flag, flushed sentinel, collision-safe run dirs"
```

---

### Task 2: Tauri scaffold (hello-world window)

**Files:**
- Create: `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/src/main.rs`, `desktop/src-tauri/build.rs`, `desktop/src-tauri/capabilities/default.json`, `desktop/ui/index.html`, `desktop/.gitignore`

**Interfaces:**
- Produces: a building Tauri v2 app whose window shows `desktop/ui/index.html` ("Setting up…" placeholder). Task 3 replaces the stub `main.rs` body with the lifecycle core; keep the crate name `dpi-eval-desktop` and the entry shape.

- [ ] **Step 1: Create the scaffold**

`desktop/ui/index.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>dpi-eval</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0}</style>
</head>
<body><main><h1>dpi-eval</h1><p id="status" role="status">Setting up…</p></main></body>
</html>
```

`desktop/src-tauri/Cargo.toml`:

```toml
[package]
name = "dpi-eval-desktop"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
tauri-plugin-single-instance = "2"
tauri-plugin-dialog = "2"
```

`desktop/src-tauri/build.rs`:

```rust
fn main() {
    tauri_build::build()
}
```

`desktop/src-tauri/tauri.conf.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "dpi-eval",
  "version": "0.1.0",
  "identifier": "edu.umd.dpi-eval",
  "app": {
    "windows": [
      { "title": "dpi-eval", "width": 900, "height": 700 }
    ],
    "security": { "csp": null }
  },
  "build": { "frontendDist": "../ui" },
  "bundle": {
    "active": true,
    "targets": ["dmg", "nsis"],
    "windows": { "nsis": { "installMode": "currentUser" } },
    "resources": { "../runtime/payload/": "runtime/" }
  }
}
```

`desktop/src-tauri/capabilities/default.json`:

```json
{
  "identifier": "default",
  "windows": ["main"],
  "permissions": ["core:default", "dialog:default"]
}
```

`desktop/src-tauri/src/main.rs` (stub — Task 3 replaces the body):

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            use tauri::Manager;
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

`desktop/.gitignore`:

```
src-tauri/target/
runtime/payload/
```

Create an empty `desktop/runtime/payload/.gitkeep` so the resources path exists for dev builds (`git add -f desktop/runtime/payload/.gitkeep`).

- [ ] **Step 2: Verify it builds and opens**

Run: `cd desktop/src-tauri && cargo tauri dev` (install the CLI first if absent: `cargo install tauri-cli --version '^2'`).
Expected: a window opens showing "Setting up…". Close it; `cargo tauri build --no-bundle` also exits 0. If the current Tauri v2 schema/API rejects any of the config above, reconcile with current docs (Context7 `/tauri-apps/tauri`) and record the deviation in your report.

- [ ] **Step 3: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): Tauri v2 scaffold with placeholder window"
```

---

### Task 3: Lifecycle core — bootstrap, handshake, process-tree kill (fable)

The hardest task in the plan: cross-platform process lifecycle. The code below is a **reference implementation of the required behavior** — the current Tauri v2 / crate APIs win where they disagree; implement the behavior, keep the tested pure functions exactly as specified, and record deviations.

**Files:**
- Modify: `desktop/src-tauri/src/main.rs` (thin entry calling into the lifecycle module)
- Create: `desktop/src-tauri/src/lifecycle.rs` (bootstrap + spawn + handshake + kill; pure functions unit-tested)
- Modify: `desktop/src-tauri/Cargo.toml` (add `libc` for unix process-group calls; `windows` crate features for Job Objects)
- Modify: `desktop/ui/index.html` (status text driven by events)

**Interfaces:**
- Consumes: resources layout `runtime/cpython/` (standalone CPython, `bin/python3` or `python.exe`) and `runtime/wheelhouse/` (wheels + `MANIFEST`: line 1 package name, line 2 content hash, optional line 3 `probe`), produced by Task 4's scripts; the sentinel `dpi-eval-web running at <URL>` from Task 1.
- Produces (Tasks 5/9 rely on these behaviors):
  1. `ensure_venv(app_data_dir, resource_dir) -> Result<PathBuf>`: idempotent; creates `<app_data>/venv` with the bundled CPython, installs from the wheelhouse offline (`pip install --no-index --find-links <wheelhouse> <package>`; in probe mode: `--no-deps` for the project wheel plus the explicitly listed web deps), writes `<venv>/.bootstrap-ok` containing the MANIFEST hash; on hash mismatch or missing marker, deletes and rebuilds; emits `bootstrap-status` events (`"installing"`, `"ready"`, `"failed: <detail>"`) to the window.
  2. `spawn_sidecar(venv) -> Child`: spawns `<venv>/bin/dpi-eval-web --no-browser` (`Scripts\dpi-eval-web.exe` on Windows) with `PYTHONUNBUFFERED=1`, stdout piped, stderr appended to `<app_data>/logs/sidecar.log`; **unix:** detach into its own process group via a before-spawn hook calling `setsid()` (libc), so the child owns the group; **windows:** assign the child to a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
  3. `parse_sentinel(line) -> Option<String>` — pure, unit-tested:

```rust
pub fn parse_sentinel(line: &str) -> Option<String> {
    line.strip_prefix("dpi-eval-web running at ")
        .map(|url| url.trim().to_string())
}
```

  4. Handshake: read stdout lines up to **60 s** for the sentinel; then poll `GET <url>/` until HTTP 200 (500 ms interval, within the same 60 s budget); on success navigate the main window to the URL; on timeout or child exit, native dialog naming `<app_data>/logs/sidecar.log` — never a blank window.
  5. Shutdown: on exit/window-destroyed, **unix** signal the whole group (`killpg` SIGTERM, then SIGKILL after 3 s); **windows** close the Job handle (kills the tree). No orphaned `dinglehopper` grandchildren — verify manually in Step 4.

- [ ] **Step 1: Write the failing Rust unit tests**

In `desktop/src-tauri/src/lifecycle.rs` (bottom):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sentinel_parses_the_exact_line() {
        assert_eq!(
            parse_sentinel("dpi-eval-web running at http://127.0.0.1:8765"),
            Some("http://127.0.0.1:8765".to_string())
        );
    }

    #[test]
    fn sentinel_ignores_other_lines() {
        assert_eq!(parse_sentinel("Done? Close the browser tab"), None);
        assert_eq!(parse_sentinel(""), None);
    }

    #[test]
    fn bootstrap_marker_roundtrip() {
        let dir = std::env::temp_dir().join("dpi-eval-marker-test");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        assert!(!marker_matches(&dir, "hash-1"));
        write_marker(&dir, "hash-1").unwrap();
        assert!(marker_matches(&dir, "hash-1"));
        assert!(!marker_matches(&dir, "hash-2")); // wheelhouse changed → rebuild
    }
}
```

Run: `cd desktop/src-tauri && cargo test`
Expected: compilation FAILURE (`parse_sentinel`, `marker_matches`, `write_marker` undefined).

- [ ] **Step 2: Implement `lifecycle.rs` + wire into `main.rs`**

Implement the five behaviors above. Marker helpers (keep exactly — tested):

```rust
pub fn marker_matches(venv: &std::path::Path, hash: &str) -> bool {
    std::fs::read_to_string(venv.join(".bootstrap-ok"))
        .map(|s| s.trim() == hash)
        .unwrap_or(false)
}

pub fn write_marker(venv: &std::path::Path, hash: &str) -> std::io::Result<()> {
    std::fs::write(venv.join(".bootstrap-ok"), hash)
}
```

Wire `main.rs`: on `setup`, resolve resource + app-data dirs, run `ensure_venv` off the main thread, then `spawn_sidecar` + handshake; store the child/Job handle in managed state; kill on `RunEvent::ExitRequested`/`Exit`. The `bootstrap-status` events update `#status` in `desktop/ui/index.html` via a small inline `window.__TAURI__.event.listen` script (add the event permission to capabilities if the current API requires it).

- [ ] **Step 3: Rust tests pass**

Run: `cd desktop/src-tauri && cargo test`
Expected: 3 passed.

- [ ] **Step 4: Manual lifecycle verification (dev machine, real venv)**

Create a throwaway venv to stand in for the bootstrap result: `uv venv /tmp/dpi-probe-venv && uv pip install --python /tmp/dpi-probe-venv/bin/python -e .` — then point the app at it (temporary env var override such as `DPI_EVAL_DESKTOP_VENV`; keep the override in committed code — it is also how Task 9 forces re-tests). Run `cargo tauri dev`:
- Window shows the dpi-eval form (handshake worked through the real sentinel).
- Grade `tests/fixtures/text` via the window (folder pickers → results page renders).
- Quit mid-grade on a re-run: `ps aux | grep -E "dinglehopper|dpi-eval-web"` shows NO survivors (process-group kill works).

- [ ] **Step 5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): sidecar lifecycle — bootstrap, handshake, tree-kill"
```

---

### Task 4: Probe runtime payload scripts

**Files:**
- Create: `desktop/runtime/fetch_python.sh`, `desktop/runtime/build_wheelhouse.sh`, `desktop/runtime/python-version.txt`

**Interfaces:**
- Produces: `desktop/runtime/payload/{cpython/, wheelhouse/}` with `wheelhouse/MANIFEST` (line 1: package name to install; line 2: sha256 of the wheel list; line 3 `probe` in probe mode) — the layout Task 3's `ensure_venv` consumes. Probe mode installs **this repo's own wheel** (small, real console scripts, no ocrd weight): the probe sidecar IS `dpi-eval-web`, minus dinglehopper's heavy tree.

- [ ] **Step 1: Write the scripts**

`desktop/runtime/python-version.txt`:

```
cpython-3.12.8+20250115
```

`desktop/runtime/fetch_python.sh`:

```bash
#!/usr/bin/env bash
# Fetch pinned python-build-standalone for the current platform into payload/cpython.
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(cat python-version.txt)
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) TRIPLE="aarch64-apple-darwin" ;;
  Linux-x86_64) TRIPLE="x86_64-unknown-linux-gnu" ;;
  MINGW*|MSYS*|CYGWIN*) TRIPLE="x86_64-pc-windows-msvc" ;;
  *) echo "unsupported platform" >&2; exit 1 ;;
esac
TAG="${VERSION#cpython-}"; TAG="${TAG#*+}"
PYVER="${VERSION#cpython-}"; PYVER="${PYVER%%+*}"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${TAG}/cpython-${PYVER}+${TAG}-${TRIPLE}-install_only.tar.gz"
mkdir -p payload
rm -rf payload/cpython
curl -fL "$URL" -o payload/python.tar.gz
tar -xzf payload/python.tar.gz -C payload
mv payload/python payload/cpython
rm payload/python.tar.gz
echo "fetched $VERSION for $TRIPLE"
```

`desktop/runtime/build_wheelhouse.sh` (amended after Task 3's finding:
`dpi_eval.adapter` imports lxml at module scope, so the probe venv needs
the lxml wheel; downloads are wheels-only — sdists would force compiles
on student machines; pip is the bundled interpreter's own, so
fetch_python.sh must run first):

```bash
#!/usr/bin/env bash
# Build the offline wheelhouse (wheels only). --probe = this repo's wheel +
# the minimal web deps (fastapi/uvicorn/python-multipart/lxml — lxml because
# dpi_eval.adapter imports it at module scope), minus dinglehopper.
set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
MODE="${1:-full}"
OUT="payload/wheelhouse"
if [ -x payload/cpython/bin/python3 ]; then PY=payload/cpython/bin/python3
elif [ -x payload/cpython/python.exe ]; then PY=payload/cpython/python.exe
else echo "run fetch_python.sh first" >&2; exit 1; fi
rm -rf "$OUT"; mkdir -p "$OUT"
(cd "$REPO_ROOT" && uv build --wheel --out-dir "$PWD/desktop/runtime/$OUT")
if [ "$MODE" = "--probe" ]; then
  "$PY" -m pip download --only-binary :all: fastapi uvicorn python-multipart lxml -d "$OUT" >/dev/null
else
  (cd "$REPO_ROOT" && uv export --no-dev --no-emit-project --format requirements-txt) > "$OUT/requirements.txt"
  "$PY" -m pip download --only-binary :all: -r "$OUT/requirements.txt" -d "$OUT" >/dev/null
fi
PKG="dpi-dinglehopper-eval"
HASH=$(ls "$OUT" | sort | shasum -a 256 | cut -d' ' -f1)
printf '%s\n%s\n' "$PKG" "$HASH" > "$OUT/MANIFEST"
if [ "$MODE" = "--probe" ]; then echo probe >> "$OUT/MANIFEST"; fi
echo "wheelhouse ($MODE): $(ls "$OUT" | wc -l | tr -d ' ') files"
```

`chmod +x desktop/runtime/*.sh`.

- [ ] **Step 2: Verify locally**

```bash
desktop/runtime/fetch_python.sh
desktop/runtime/build_wheelhouse.sh --probe
desktop/runtime/payload/cpython/bin/python3 --version
ls desktop/runtime/payload/wheelhouse/ | head
```

Expected: Python 3.12.8 prints; wheelhouse contains `dpi_dinglehopper_eval-*.whl`, fastapi/uvicorn/multipart wheels, `MANIFEST` with three lines.

- [ ] **Step 3: Manual offline-install rehearsal (proves the payload before Rust touches it)**

```bash
desktop/runtime/payload/cpython/bin/python3 -m venv /tmp/probe-venv
/tmp/probe-venv/bin/pip install --no-index --find-links desktop/runtime/payload/wheelhouse --no-deps dpi-dinglehopper-eval
/tmp/probe-venv/bin/pip install --no-index --find-links desktop/runtime/payload/wheelhouse fastapi uvicorn python-multipart lxml
/tmp/probe-venv/bin/dpi-eval-web --help
```

Expected: help text prints (console script manufactured by pip; the probe sidecar will start but cannot grade — dinglehopper absent — which is fine: the probe tests install/launch/AV, not grading).

- [ ] **Step 4: Commit**

```bash
git add desktop/runtime/
git commit -m "feat(desktop): pinned CPython fetch + wheelhouse build scripts"
```

---

### Task 5: Probe artifact assembly (macOS, local)

**Files:**
- Modify: `desktop/src-tauri/src/lifecycle.rs` only if Step 2 exposes wiring gaps (record any change)

**Interfaces:**
- Consumes: Tasks 2–4 outputs. Produces: an unsigned `.dmg` whose app cold-bootstraps from its own resources on a machine-state it has never seen.

- [ ] **Step 1: Build the bundle**

```bash
desktop/runtime/fetch_python.sh
desktop/runtime/build_wheelhouse.sh --probe
cd desktop/src-tauri && cargo tauri build
```

Expected: `.dmg` under `desktop/src-tauri/target/release/bundle/dmg/`.

- [ ] **Step 2: Cold-start rehearsal**

`rm -rf "$HOME/Library/Application Support/edu.umd.dpi-eval"` (fresh app-data), mount the dmg, drag to `~/Applications`, launch: "Setting up…" progress → dpi-eval form appears (probe sidecar has no dinglehopper, so grading a folder shows the engine-failure banner — expected and fine). Quit; relaunch is fast (marker honored). Check `~/Library/Application Support/edu.umd.dpi-eval/logs/sidecar.log` exists.

- [ ] **Step 3: Commit (if changes) and tag the probe artifact**

```bash
git add -A desktop/ && git diff --cached --quiet || git commit -m "fix(desktop): probe assembly wiring"
git tag probe-macos-v1
```

---

### Task 6: CI probe artifacts (both OSes) — BLOCKED on push approval

**Files:**
- Create: `.github/workflows/desktop.yml`

**Interfaces:**
- Consumes: Tasks 1–5. Produces: unsigned probe `.dmg` (arm64 mac) + NSIS per-user `.exe` (Windows) as workflow artifacts — the Windows probe artifact only exists via CI.

- [ ] **Step 1: Write the workflow**

```yaml
name: desktop
on:
  push:
    branches: [feat/dpi-eval-desktop, main]
    paths: [desktop/**, src/**, pyproject.toml, uv.lock, .github/workflows/desktop.yml]
  workflow_dispatch:

jobs:
  bundle:
    strategy:
      matrix:
        include:
          - os: macos-latest
          - os: windows-latest
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: dtolnay/rust-toolchain@stable
      - name: Build runtime payload (probe)
        shell: bash
        run: |
          desktop/runtime/fetch_python.sh
          desktop/runtime/build_wheelhouse.sh --probe
      - name: Offline bootstrap smoke test
        shell: bash
        run: |
          if [ -x desktop/runtime/payload/cpython/bin/python3 ]; then
            PY=desktop/runtime/payload/cpython/bin/python3; BIN=probe-venv/bin
          else
            PY=desktop/runtime/payload/cpython/python.exe; BIN=probe-venv/Scripts
          fi
          "$PY" -m venv probe-venv
          "$BIN/pip" install --no-index --find-links desktop/runtime/payload/wheelhouse --no-deps dpi-dinglehopper-eval
          "$BIN/pip" install --no-index --find-links desktop/runtime/payload/wheelhouse fastapi uvicorn python-multipart lxml
          "$BIN/dpi-eval-web" --help
      - name: Install tauri-cli
        run: cargo install tauri-cli --version '^2' --locked
      - name: Bundle
        working-directory: desktop/src-tauri
        run: cargo tauri build
      - uses: actions/upload-artifact@v4
        with:
          name: probe-${{ matrix.os }}
          path: |
            desktop/src-tauri/target/release/bundle/dmg/*.dmg
            desktop/src-tauri/target/release/bundle/nsis/*.exe
```

(Windows runs the shell scripts under Git Bash via `shell: bash`; if the python-build-standalone tar layout differs on Windows, fix `fetch_python.sh` — that IS this task's discovery work.)

- [ ] **Step 2: Commit, push, verify green** (push requires user approval — coordinate with orchestrator)

```bash
git add .github/workflows/desktop.yml
git commit -m "ci: desktop probe bundles for macOS and Windows"
git push -u origin feat/dpi-eval-desktop
```

Expected: both matrix legs green; two artifacts downloadable from the run.

---

### Task 7: HUMAN GATE — HDC managed-machine probe (Trevor)

No subagent. The orchestrator prepares `desktop/PROBE-CHECKLIST.md` (haiku, from the spec's probe section) covering: install per-user from the artifact, first-run approval path (macOS "damaged" dialog wording → System Settings "Open Anyway"; Windows SmartScreen → "More info → Run anyway"), bootstrap completes, window reaches the form, quit cleanly — all WITHOUT admin credentials or a terminal. Record per machine: OS/version, MDM/AV product if known, outcome, screenshots of any blocking dialog.

Outcome routing (per spec):
- **Pass** → proceed to Task 8.
- **Gatekeeper/SmartScreen-only friction** → pause; signing decision conversation (personal vs UMD identity), then signed re-probe.
- **AV quarantine or MDM install block** → stop; findings entry; uvx path remains the answer.

Either way: findings entry in `docs/findings.md` drafted at gate time from the actual observations.

---

### Task 8: Real wheelhouse (full dependency set)

**Files:**
- Modify: `desktop/runtime/build_wheelhouse.sh` only if full mode needs fixes; otherwise no code — this task is execution + discovery.

- [ ] **Step 1: Build full and rehearse offline**

```bash
desktop/runtime/build_wheelhouse.sh        # full mode
desktop/runtime/payload/cpython/bin/python3 -m venv /tmp/full-venv
/tmp/full-venv/bin/pip install --no-index --find-links desktop/runtime/payload/wheelhouse dpi-dinglehopper-eval
/tmp/full-venv/bin/dpi-eval-web --help && /tmp/full-venv/bin/dinglehopper --help
```

Expected: both console scripts work offline. **If any dependency has no wheel** (ocrd-stack sdist-only risk, especially for the Windows leg in CI): STOP, report DONE_WITH_CONCERNS naming the packages — the orchestrator escalates diagnosis to fable (options there: build the sdists into local wheels inside `build_wheelhouse.sh`, platform-conditional pins, or an upstream findings entry).

- [ ] **Step 2: Grade through the venv (the engine works from a bundled runtime)**

```bash
/tmp/full-venv/bin/dpi-eval-web --no-browser & sleep 3
curl -s -F "gt_files=@tests/fixtures/text/page_0.gt.txt;type=text/plain" -F "ocr_files=@tests/fixtures/text/page_0.txt;type=text/plain" http://127.0.0.1:8765/grade -o /dev/null -w "%{http_code}\n"
kill %1
```

Expected: `303`.

- [ ] **Step 3: Commit any script fixes**

```bash
git add desktop/runtime/ && git diff --cached --quiet || git commit -m "feat(desktop): full wheelhouse build"
```

---

### Task 9: Product tracer — one page graded inside the Tauri window

- [ ] **Step 1:** Rebuild payload full (`fetch_python.sh && build_wheelhouse.sh`), remove the app-data dir (forces re-bootstrap — the MANIFEST hash changed, marker logic must trigger the rebuild path), `cargo tauri dev`.
- [ ] **Step 2:** In the window: pick `tests/fixtures/text` as both GT and OCR folders, Run, confirm the results page (WER 12.5% on the fixture), open a per-page diff, download the zip. Confirm `webkitdirectory` folder pickers behave in WKWebView — **if the picker fails here, this is the spec's contingency trigger: STOP and report; the native-dialog endpoint needs a spec amendment first.**
- [ ] **Step 3:** Quit mid-grade on a re-run; verify no surviving `dinglehopper`/`dpi-eval-web` processes.
- [ ] **Step 4:** Commit any wiring fixes: `git add -A desktop/ && git diff --cached --quiet || git commit -m "fix(desktop): product tracer wiring"`

---

### Task 10: CI to release pipeline

- [ ] **Step 1:** In `.github/workflows/desktop.yml`: switch the payload step to full mode (drop `--probe`); extend the smoke step with the Task 8 Step 2 grade-over-HTTP check (start the venv's `dpi-eval-web --no-browser` in the background, curl `/grade` with the fixtures expecting 303, then kill it); add a `release` job on tag `desktop-v*` attaching both bundles via `softprops/action-gh-release@v2`.
- [ ] **Step 2:** Push; both legs green including the grade smoke; tag `desktop-v0.1.0-rc1` and confirm a draft Release carries `.dmg` + `.exe`.
- [ ] **Step 3:** Commit: `git add .github/workflows/desktop.yml && git commit -m "ci: full-bundle smoke gate and desktop release job"`

---

### Task 11: Docs + findings

**Files:** `README.md`, `docs/findings.md`, `desktop/PROBE-CHECKLIST.md` (if not already created at Task 7 time)

- [ ] **Step 1:** README: add a "Desktop app (pilot)" subsection under the web-interface section: install from the Release artifact, per-user, first-run approval steps (pre-empting the macOS "damaged" wording), and that uvx remains the fallback.
- [ ] **Step 2:** findings.md: append entry #10 "dpi-eval-desktop build learnings" — wheelhouse coverage results (from Task 8), probe outcome reference, WKWebView tracer result. Exact text drafted by the orchestrator at dispatch time from the actual outcomes (this plan cannot pre-write observations).
- [ ] **Step 3:** Commit: `git add README.md docs/findings.md desktop/PROBE-CHECKLIST.md && git commit -m "docs: desktop app pilot instructions and findings"`

---

## Final verification (orchestrator)

- [ ] `uv run pytest` → 40 passed (Python surface unchanged since Task 1)
- [ ] `cd desktop/src-tauri && cargo test` → 3 passed
- [ ] CI both legs green on the full bundle; Release artifacts present
- [ ] Product tracer (Task 9) and probe gate (Task 7) outcomes recorded in findings
- [ ] Whole-branch review (PAR), then Ship/Show/Ask with the user
