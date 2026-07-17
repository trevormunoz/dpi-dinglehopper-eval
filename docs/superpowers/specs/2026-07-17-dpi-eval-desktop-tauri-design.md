# dpi-eval-desktop — Tauri Shell Design

**Date:** 2026-07-17
**Status:** Draft, adversarial review incorporated (PAR, two blind
reviewers, 2026-07-17) — pending human approval
**Scope posture:** HOLD — the existing `dpi-eval-web` experience in a
desktop shell, made bulletproof. No new user-facing features.
**Deliverable of this cycle:** this spec only. Implementation is a later
plan/build cycle.
**Decision:** Tauri v2 shell around the existing FastAPI localhost app,
with the Python engine frozen into a PyInstaller sidecar. macOS and
Windows from day one. Unsigned artifacts for the pilot, gated by a
managed-machine probe (below).

## Goal

An HDC student double-clicks an app icon. A window opens on the same
form, grade, and results experience `dpi-eval-web` ships today — no
terminal anywhere, not even the one pinned uvx command. Everything else
(runs in `~/dpi-eval-runs`, reports served as-is, zip handoff, files
never leave the machine) is unchanged.

## Why Tauri (decision record)

Considered: Tauri (chosen, per project direction), pywebview/Briefcase
(single-language, smaller lift, weaker updater/binary story), Electron
(no benefit over Tauri here, much heavier). Also surveyed (community
research, 2026-07-17): **pytauri** (PyO3, embeds Python in-process — no
sidecar, no handshake) — rejected for now: pre-1.0, greenfield-oriented
with no documented path for an existing FastAPI app, and it would not
remove subprocess management anyway since the engine shells out to the
dinglehopper console scripts regardless
(github.com/pytauri/pytauri). Tauri's own docs name "Python API servers
bundled using pyinstaller" as the intended sidecar use case
(v2.tauri.app/develop/sidecar/). Tauri chosen deliberately with eyes
open to its main cost: a second toolchain (Rust) and a frozen Python
sidecar. The uvx path remains the canonical fallback distribution; the
desktop app is additive.

## Go/no-go gate: the managed-machine probe (do this first)

Unsigned frozen-Python apps face two independent institutional walls on
managed lab machines: OS trust UX (Gatekeeper — and macOS 15 removed
the right-click-→-Open bypass for unnotarized apps, leaving the System
Settings "Open Anyway" flow, which MDM policy can disable outright) and
endpoint security (Defender/CrowdStrike/AppLocker-class tools routinely
quarantine unsigned PyInstaller bootloaders, often silently). Either
can kill the pilot regardless of how good the app is.

**Before any build work beyond a hello-world artifact:** produce a
minimal unsigned Tauri app with a trivial PyInstaller sidecar, per-user
install, and run it on an actual HDC lab machine (both a macOS and a
Windows workstation). The probe artifact is built in **both packaging
shapes** (onedir-as-resources and onefile-multiplexer, below) so real
machines arbitrate the packaging choice with data. This probe is the
build cycle's Task 0 and its result is a findings entry either way.

**On probe failure, the response is chosen at probe time by failure
mode** (decision deliberately deferred): a pure Gatekeeper/SmartScreen
friction failure is evidence for pursuing signing (personal or UMD
identity) and a signed re-probe; a silent AV/EDR quarantine or MDM
install block is evidence for stopping the track with findings — the
uvx path already works. Neither branch is pre-committed.

## Architecture

Three layers; two already exist.

1. **Tauri v2 Rust shell** (`desktop/src-tauri/`): window, native menus,
   sidecar lifecycle, single-instance guard. No business logic.
2. **Frozen Python sidecar**: one PyInstaller **onedir** bundle exposing
   three executables over a shared `_internal` runtime:
   - `dpi-eval-web` — our server (app code unchanged except the
     enumerated web-layer changes below)
   - `dinglehopper` (stub: `from dinglehopper.cli import main`) and
     `dinglehopper-summarize` (stub: `from dinglehopper.cli_summarize
     import main` — note the distinct module) — dinglehopper's own
     console entry points
3. **The existing web pages** (`pages.py`), byte-for-byte unchanged,
   rendered in the system webview (WKWebView on macOS, WebView2 on
   Windows) pointed at the sidecar's localhost URL.

**Packaging: two candidate shapes, probe decides.** Tauri's
`externalBin` sidecar API expects a *single* target-triple-suffixed
binary; a PyInstaller onedir is a *directory* (executables beside an
`_internal` tree). The candidates:

- **A — onedir as `resources`:** three thin exes share one `_internal`
  runtime; the whole folder ships as Tauri resources and the shell
  spawns `dpi-eval-web` by absolute path via the shell plugin /
  `std::process`. Process-lifetime handling is ours, not the sidecar
  API's. No community example ships this exact shape, but it is the
  inferred fix in the sources below.
- **B — onefile + argv0 multiplexer via `externalBin`:** one
  self-extracting binary dispatching on invoked name/first argument
  (the community-recommended PyInstaller multi-entry pattern,
  github.com/orgs/pyinstaller/discussions/6634), registered as the
  single sidecar binary.

Community evidence weighing on the probe (2026-07-17 research): onefile
has an **open Tauri bug** — `child.kill()` kills only the PyInstaller
bootloader on Windows and the real server survives
(github.com/tauri-apps/tauri/issues/11686; also hit by the
dieharders/example-tauri-v2-python-server-sidecar template, which is
onefile and documents the same kill failure) — so candidate B is viable
only with explicit real-child-PID/process-tree kill. Onefile's
extract-to-temp behavior is also the documented worst case for AV
heuristics (pythonguis.com/faq/problems-with-antivirus-software-and-
pyinstaller), which bears directly on the probe's AV leg. If the probe
is a tie on HDC machines, this evidence breaks it toward A.

**Startup sequence.** Shell spawns `<resources>/sidecar/dpi-eval-web
--no-browser` with `PYTHONUNBUFFERED=1` in the child environment →
sidecar resolves a concrete port up front via the existing `_pick_port`
(8765 preferred, ephemeral fallback — the printed URL is always real;
there is no `--port 0` mode) and prints its existing
`dpi-eval-web running at http://127.0.0.1:PORT` line, now with
`flush=True` (stdout is a pipe here, not a tty; without an explicit
flush the line sits block-buffered while `uvicorn.run` blocks — the
handshake never completes) → shell parses the URL, then polls it until
the server accepts connections (the line prints just before uvicorn
binds; navigation must tolerate a brief connection-refused) → window
navigates. **Startup timeout: 60 s** (first launch of a large frozen
bundle under AV scanning is slow); on timeout, a native error dialog
with the sidecar log path — never a blank window.

**Process lifetime.** The shell puts the sidecar in its own process
group (POSIX: `setsid`, kill via `killpg`) / Windows Job Object with
kill-on-job-close, so quitting mid-grade also takes down any in-flight
`dinglehopper` grandchild spawned by `run_batch` — kill-on-drop of the
direct child alone would orphan them, and Windows has no SIGTERM.
Community consensus agrees single-PID `kill()` is insufficient for
multi-process sidecars (tauri discussions #3273; `taskkill /T /F` and
sysinfo tree-walks are the reported workarounds). Belt-and-suspenders
fallback from the same sources: the sidecar polls parent liveness and
self-terminates if orphaned.

## The console-scripts problem (and why the engine stays unmodified)

`runner.py` invokes `dinglehopper` / `dinglehopper-summarize` by name
via PATH (`runner.py:19`, `runner.py:30`). The sidecar launcher prepends
its own bundle directory to PATH before starting the server, so those
subprocess calls resolve to the frozen executables. Zero engine changes.

**Constraint statement.** The hard rule "never import `dinglehopper.*`"
governs wrapper *code paths*. The PyInstaller entry stubs are packaging
metadata — the same shims setuptools/uvx generate for console scripts
today. No runtime wrapper code path gains a dinglehopper import;
dinglehopper remains an unmodified dependency invoked as a subprocess.

## Changes to the Python package (enumerated and closed)

All in the web layer; engine files (`runner.py`, `cli.py`,
`pairing.py`, `adapter.py`) remain untouched. This list is the complete
set — "additive only" means exactly these, each with tests:

1. `main()` gains a `--no-browser` flag (the shell IS the browser);
   default behavior unchanged.
2. The two startup `print()` calls gain `flush=True` (pipe-buffering
   fix above; behaviorally invisible in a terminal).
3. `_next_run_dir` retries on `FileExistsError` (the shared
   `~/dpi-eval-runs` dir plus "desktop and uvx can run at once" makes
   the current unguarded `mkdir` a real, if rare, race → 500).
4. **Contingent, only if the WKWebView tracer fails** (below): a native
   folder-picker endpoint. If built, this list and the spec get amended
   — it is not silently pre-authorized.

Existing 37 tests stay green throughout.

## Freezing risks (named, each with its gate)

- **Data files:** dinglehopper's Jinja report templates, uniseg data
  tables, ocrd resource files, rapidfuzz native modules — collected via
  PyInstaller hooks/data specs.
- **Gate (blocking, in CI):** a smoke test that grades the
  `tests/fixtures/text` pair *inside the frozen bundle* — through the
  frozen `dpi-eval-web` HTTP path end to end — must pass on every CI
  platform lane before any bundle is published.
- **macOS architectures (review finding, decided):** `macos-latest`
  runners are arm64 and PyInstaller does not cross-compile; a
  universal2 build is unrealistic with the ocrd stack's native wheels.
  **Decision: arm64 only** — a deliberate gamble that HDC Macs are
  Apple Silicon by now. An x86_64 lane (`macos-13`) is added only if
  Pamela's workflow tour surfaces Intel machines; until the inventory
  confirms, an Intel Mac receiving the artifact simply cannot launch
  it, and the uvx path is the answer there.
- **Bundle size:** the ocrd stack is heavy; onedir avoids onefile's
  unpack-per-launch cost. Expect a large app; recorded so nobody is
  surprised.

## Known risk: folder pickers in WKWebView

`webkitdirectory` is solid in WebView2 (Chromium) but historically
flaky in WKWebView. **Tracer bullet decides:** one page graded inside
the Tauri window on both OSes is the first post-probe milestone of any
build cycle. Contingency if macOS fails: Tauri dialog plugin native
folder picker feeding a server-side directory-read endpoint (localhost,
same machine — no privacy change), authorized via an explicit spec
amendment per the enumerated-changes rule above.

## Bulletproofing (the HOLD substance)

- **Single instance:** `tauri-plugin-single-instance`; a second launch
  focuses the existing window — the point is one window/one server per
  student, not port contention (ephemeral ports don't collide).
- **Sidecar death:** shell detects child exit → native error dialog with
  the sidecar log path; logs under the app's data dir.
- **Startup failure:** 60 s timeout + connection polling as above;
  never a blank window.
- **Quit-mid-batch:** process-group/Job-Object kill covers engine
  grandchildren (above).
- **Runs directory:** unchanged `~/dpi-eval-runs/run-NNN/`, shared with
  the uvx/CLI path (with the `_next_run_dir` retry making concurrent
  use safe).
- **Server binding:** `127.0.0.1` only, exactly as today.

## Unsigned pilot distribution (rewritten after review)

The original draft's story (drag to `/Applications`, per-machine
`.msi`, supervisor `xattr` in a terminal) violated the charter it was
built to serve — admin rights and a terminal command. Corrected:

- **Per-user installs only.** macOS: `.dmg` with drag-to-
  `~/Applications` (user-writable — never `/Applications`). Windows:
  Tauri's NSIS installer in **per-user (`currentUser`) mode** — no UAC
  elevation; not the per-machine WiX `.msi`.
- **First-run approval, documented per OS:** macOS 15+ System Settings
  → Privacy & Security → "Open Anyway" (the right-click bypass no
  longer exists for unnotarized apps) — and note the dialog students
  actually see claims the app "is damaged and can't be opened," not
  that it is unsigned (community-documented Gatekeeper wording); the
  instructions must pre-empt that scary phrasing. Windows SmartScreen
  "More info → Run anyway". No step may require admin rights or a
  terminal; anything that turns out to need either is a probe failure,
  not a workaround.
- **Endpoint security is the honest headline risk:** managed AV/EDR may
  quarantine the unsigned frozen sidecar silently. The managed-machine
  probe exists to surface this before the build, not after.
- **No auto-updater while unsigned** — updates re-trigger the approval
  flow; pilot updates are manual downloads from GitHub Releases,
  versions pinned by tag.
- **Triggers to sign:** probe or pilot friction that blocks students,
  or a UMD Libraries signing identity becoming available. Signing
  unlocks notarization and the Tauri updater as follow-ons.
- Honest tension, still recorded: even corrected, unsigned first-run
  friction may exceed the uvx terminal command it replaces. The probe
  and pilot measure this; the uvx path stays documented as fallback.

## CI

GitHub Actions matrix — `macos-latest` (arm64) and `windows-latest`
(x86_64 macOS lane added only on Intel-inventory evidence): PyInstaller
sidecar build in whichever shape the probe selected → frozen smoke test
(blocking gate) → `tauri build` (NSIS per-user on Windows) → artifacts
attached to the Release. Toolchains: Python (uv), Rust, Node (Tauri
CLI).

## Repo layout

Same repo, new top-level `desktop/`:

    desktop/
      src-tauri/           # Rust shell, tauri.conf.json
      sidecar/
        dpi_eval_web.spec  # PyInstaller spec, three entry points
        stub_dinglehopper.py   # from dinglehopper.cli import main
        stub_summarize.py      # from dinglehopper.cli_summarize import main

## Testing / success criteria

- Existing 37 tests green; new tests for the enumerated web-layer
  changes green.
- Managed-machine probe passes on real HDC hardware (go/no-go).
- CI frozen smoke test passes on all three lanes (blocking).
- Tracer: one fixture page graded end-to-end inside the Tauri window on
  macOS and Windows before any polish work.
- A student-shaped walkthrough (double-click → approve once → pick
  folders → run → read results → download zip → quit) succeeds on both
  OSes with no terminal and no admin prompt at any point.

## Out of scope (HOLD fence)

- Auto-updater (blocked on signing; trigger above)
- Any new user-facing features beyond the shell (see findings #8)
- Replacing the web form with native Tauri UI; the webview renders the
  existing pages
- Linux packaging (no HDC demand)

## Review record

PAR 2026-07-17: two blind same-model reviewers, aggregated worst-severity.
Both independently found: the stdout-buffering handshake break (critical),
the `--port 0` dead-URL flaw, the admin/terminal charter contradiction in
the distribution story, the AV/EDR omission, and the externalBin/onedir
mismatch. Singletons kept: macOS arm64/x86_64 gap, `_next_run_dir` race,
grandchild-orphan kill semantics. All incorporated above; `--port` was
dropped entirely rather than fixed.

Community research 2026-07-17 (sourced, not from model memory)
corroborated the reviewers independently: the onefile kill bug is an
open Tauri issue (#11686), AV heuristics specifically punish onefile,
argv0 dispatch is the recognized multi-entry pattern, no surveyed
project ships multiple externalBin commands from one Python bundle, and
no source shows a stdout-only readiness handshake working reliably in
production — hence sentinel-line-plus-URL-polling here. pytauri
evaluated and deferred (pre-1.0, doesn't remove subprocess needs).

## Open questions

**Open for the human, before the build cycle:**

- Constraint interpretation for the PyInstaller entry stubs — does
  "never import `dinglehopper.*`" govern runtime wrapper code paths
  (stubs allowed as installer-artifact reproductions) or every file in
  the repo (forcing an embedded-venv freezing architecture instead)?
  The Constraint statement section above records the permissive
  reading; it is not yet ratified.

**Resolve during the build cycle, not before:**

- Managed-machine probe outcome — packaging shape (A vs B) and, on
  failure, which response branch the failure mode argues for
- HDC hardware inventory: macOS arm64 vs x86_64 mix; Windows version
  (pilot precheck, from Pamela's workflow tour)
- Exact PyInstaller hook set for the ocrd stack (discovered by the CI
  smoke test, not guessable from docs)
- Whether WKWebView passes the `webkitdirectory` tracer (decides the
  native-dialog contingency and its spec amendment)
- Windows: whether SmartScreen reputation makes NSIS `.exe` per-user
  the least-scary artifact in practice (probe data)
