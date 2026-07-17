# dpi-eval-desktop — Tauri Shell Design

**Date:** 2026-07-17
**Status:** Draft (brainstorming session; pending adversarial review)
**Scope posture:** HOLD — the existing `dpi-eval-web` experience in a
desktop shell, made bulletproof. No new user-facing features.
**Deliverable of this cycle:** this spec only. Implementation is a later
plan/build cycle.
**Decision:** Tauri v2 shell around the existing FastAPI localhost app,
with the Python engine frozen into a PyInstaller sidecar. macOS and
Windows from day one. Unsigned artifacts for the pilot.

## Goal

An HDC student double-clicks an app icon. A window opens on the same
form, grade, and results experience `dpi-eval-web` ships today — no
terminal anywhere, not even the one pinned uvx command. Everything else
(runs in `~/dpi-eval-runs`, reports served as-is, zip handoff, files
never leave the machine) is unchanged.

## Why Tauri (decision record)

Considered: Tauri (chosen, per project direction), pywebview/Briefcase
(single-language, smaller lift, weaker updater/binary story), Electron
(no benefit over Tauri here, much heavier). Tauri chosen deliberately
with eyes open to its main cost: a second toolchain (Rust) and a frozen
Python sidecar. The uvx path remains the canonical fallback
distribution; the desktop app is additive.

## Architecture

Three layers; two already exist.

1. **Tauri v2 Rust shell** (`desktop/src-tauri/`): window, native menus,
   sidecar lifecycle, single-instance guard. No business logic.
2. **Frozen Python sidecar**: one PyInstaller **onedir** bundle exposing
   three executables over a shared runtime:
   - `dpi-eval-web` — our server (unchanged app code)
   - `dinglehopper`, `dinglehopper-summarize` — dinglehopper's own
     console entry points, frozen from two-line PyInstaller stubs
3. **The existing web app** (`src/dpi_eval/web.py`, `pages.py`),
   byte-for-byte unchanged, rendered in the system webview (WKWebView on
   macOS, WebView2 on Windows) pointed at the sidecar's localhost URL.

**Startup sequence.** Shell spawns `dpi-eval-web --no-browser --port 0`
→ sidecar prints its existing `dpi-eval-web running at
http://127.0.0.1:PORT` line → shell parses the URL from stdout (15 s
timeout → native error dialog with log-file path) → window navigates
there. Shell exit sends SIGTERM/kill to the sidecar (Tauri sidecar API,
kill-on-drop) so no orphaned Python servers survive.

## The console-scripts problem (and why the engine stays unmodified)

`runner.py` invokes `dinglehopper` / `dinglehopper-summarize` by name
via PATH (`runner.py:19`, `runner.py:30`). The sidecar launcher prepends
its own bundle directory to PATH before starting the server, so those
subprocess calls resolve to the frozen executables. Zero engine changes.

**Constraint statement.** The hard rule "never import `dinglehopper.*`"
governs wrapper *code paths*. The PyInstaller entry stubs
(`from dinglehopper.cli import main; main()`) are packaging metadata —
the same shims setuptools/uvx generate for console scripts today. No
runtime wrapper code path gains a dinglehopper import; dinglehopper
remains an unmodified dependency invoked as a subprocess.

## Changes to the Python package (additive only)

`dpi_eval.web.main()` gains two argparse flags, defaults preserving
current behavior exactly:

- `--no-browser` — skip the `webbrowser.open` timer (the shell IS the
  browser)
- `--port N` — bind port N (`0` = ephemeral); default keeps the
  8765-preferred/`_pick_port` behavior

Engine files (`runner.py`, `cli.py`, `pairing.py`, `adapter.py`) remain
untouched. Existing 37 tests stay green; new tests cover both flags.

## Freezing risks (named, each with its gate)

- **Data files:** dinglehopper's Jinja report templates
  (`report.json.j2`, `summary.json.j2` and HTML twins), uniseg data
  tables, ocrd resource files, rapidfuzz native modules. All must be
  collected via PyInstaller hooks/data specs.
- **Gate (blocking, in CI):** a smoke test that grades the
  `tests/fixtures/text` pair *inside the frozen bundle* — invoking the
  frozen `dpi-eval-web` HTTP path end-to-end, not the dev venv — must
  pass on both OS runners before any bundle is published.
- **Bundle size:** the ocrd stack is heavy; onedir avoids onefile's
  unpack-on-every-launch cost. Expect a large app; acceptable for lab
  machines, recorded so nobody is surprised.

## Known risk: folder pickers in WKWebView

`webkitdirectory` is solid in WebView2 (Chromium) but historically
flaky in WKWebView. **Tracer bullet decides:** one page graded inside
the Tauri window on both OSes is the first milestone of any build cycle.
Contingency if macOS fails: Tauri dialog plugin provides a native folder
picker whose selected path feeds a small new endpoint that reads the
directory server-side (localhost, same machine — no privacy change).
Built only if the tracer fails.

## Bulletproofing (the HOLD substance)

- **Single instance:** `tauri-plugin-single-instance`; a second launch
  focuses the existing window instead of fighting over ports.
- **Sidecar death:** shell detects child exit → native error dialog with
  the sidecar log path; logs written under the app's data dir.
- **Startup failure:** timeout on the URL line → same dialog, never a
  blank window.
- **Runs directory:** unchanged `~/dpi-eval-runs/run-NNN/` — shared with
  the uvx/CLI path so a student can move between them freely.
- **Server binding:** `127.0.0.1` only, exactly as today.

## Unsigned pilot distribution

- Artifacts: `.dmg` (macOS), `.msi` (Windows) on GitHub Releases;
  versions pinned by release tag.
- Documented first-run steps: macOS right-click → Open (Gatekeeper);
  Windows SmartScreen "More info → Run anyway". Optional one-time
  supervisor step for lab machines:
  `xattr -d com.apple.quarantine /Applications/dpi-eval.app`.
- **No auto-updater while unsigned** — updates would re-trigger the
  scare dialogs; pilot updates are manual downloads.
- **Triggers to sign:** pilot feedback that the warnings block students,
  or a UMD Libraries signing identity becoming available. Signing
  unlocks the Tauri updater as a follow-on.
- Honest tension, recorded: unsigned first-run friction may be worse
  than the uvx terminal command it replaces. The pilot measures this;
  the uvx path stays documented as the fallback.

## CI

GitHub Actions matrix (`macos-latest`, `windows-latest`):
PyInstaller sidecar build → frozen smoke test (blocking gate above) →
`tauri build` → artifacts attached to the Release. Toolchains: Python
(uv), Rust, Node (Tauri CLI).

## Repo layout

Same repo, new top-level `desktop/`:

    desktop/
      src-tauri/           # Rust shell, tauri.conf.json
      sidecar/
        dpi_eval_web.spec  # PyInstaller spec, three entry points
        stub_dinglehopper.py
        stub_summarize.py

Python package changes limited to the two `main()` flags and their
tests.

## Testing / success criteria

- Existing 37 tests green; new flag tests green.
- CI frozen smoke test passes on both OSes (blocking).
- Tracer: one fixture page graded end-to-end inside the Tauri window on
  macOS and Windows before any polish work.
- A student-shaped walkthrough (double-click → pick folders → run →
  read results → download zip → quit) succeeds on both OSes with no
  terminal appearing at any point.

## Out of scope (HOLD fence)

- Auto-updater (blocked on signing; trigger above)
- Any new user-facing features beyond the shell (GT transcription,
  progress streaming, etc. — see findings #8)
- Replacing the web form with native Tauri UI; the webview renders the
  existing pages
- Linux packaging (no HDC demand)

## Open questions (resolve during the build cycle, not before)

- Exact PyInstaller hook set for the ocrd stack (discovered by the CI
  smoke test, not guessable from docs)
- Whether WKWebView passes the `webkitdirectory` tracer (decides the
  native-dialog contingency)
- Windows: whether SmartScreen reputation makes `.msi` or `.exe`
  (NSIS) the less-scary artifact
