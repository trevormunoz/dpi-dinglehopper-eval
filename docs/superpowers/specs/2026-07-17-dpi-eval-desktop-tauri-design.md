# dpi-eval-desktop — Tauri Shell Design

**Date:** 2026-07-17
**Status:** Draft, adversarial review incorporated (PAR, two blind
reviewers, 2026-07-17) — pending human approval
**Scope posture:** HOLD — the existing `dpi-eval-web` experience in a
desktop shell, made bulletproof. No new user-facing features.
**Deliverable of this cycle:** this spec only. Implementation is a later
plan/build cycle.
**Decision:** Tauri v2 shell around the existing FastAPI localhost app.
**Primary packaging: bundled runtime** — a standalone CPython plus an
offline wheelhouse, installed into a venv on first launch, so pip
manufactures the real console scripts and nothing is frozen. PyInstaller
shapes are demoted to fallbacks. macOS and Windows from day one.
Unsigned artifacts for the pilot, gated by a managed-machine probe
(below).

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
minimal unsigned Tauri app with a trivial bundled-runtime sidecar
(pinned CPython + one-wheel wheelhouse + first-run venv bootstrap),
per-user install, and run it on an actual HDC lab machine (both a macOS
and a Windows workstation). The probe artifact uses the **primary bundled-runtime shape**
(standalone CPython + trivial wheelhouse + first-run venv bootstrap);
the PyInstaller fallback shapes are probed only if the primary fails
on HDC hardware. This probe is the
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
2. **Bundled Python runtime (primary)**: the app's resources carry a
   standalone CPython (python-build-standalone, per-arch) and an
   offline **wheelhouse** — every wheel the venv needs (our package,
   dinglehopper, the ocrd stack, FastAPI/uvicorn). On first launch the
   shell bootstraps a venv under the app data dir and installs from the
   wheelhouse, offline, once. pip thereby generates the real
   `dpi-eval-web`, `dinglehopper`, and `dinglehopper-summarize` console
   scripts — the same installer-manufactured entry points uvx creates
   today. The sidecar is `<venv>/bin/dpi-eval-web` (Scripts\ on
   Windows). Nothing is frozen; there are no hand-written entry stubs.
3. **The existing web pages** (`pages.py`), byte-for-byte unchanged,
   rendered in the system webview (WKWebView on macOS, WebView2 on
   Windows) pointed at the sidecar's localhost URL.

**Precedent:** this is the Datasette Desktop pattern (bundled Python +
first-run pip install into a venv) — boring, long-precedented parts,
in contrast to the PyInstaller shapes whose Tauri composition is
unprecedented for a multi-command engine (see fallbacks below).

**Fallback packaging shapes (PyInstaller — only if the bundled runtime
fails its probe).** Recorded for completeness with the evidence that
demoted them; not built unless the primary fails:

- **A — onedir as `resources`:** three thin exes share one `_internal`
  runtime; folder ships as Tauri resources; shell spawns by absolute
  path. No community example ships this exact shape.
- **B — onefile + argv0 multiplexer via `externalBin`:** one
  self-extracting binary dispatching on invoked name
  (github.com/orgs/pyinstaller/discussions/6634). Disfavored by an
  **open Tauri bug** — `child.kill()` kills only the PyInstaller
  bootloader on Windows, the real server survives
  (github.com/tauri-apps/tauri/issues/11686) — and onefile's
  extract-to-temp is the documented worst case for AV heuristics
  (pythonguis.com/faq/problems-with-antivirus-software-and-pyinstaller).
- If a fallback is ever activated, the PyInstaller entry stubs
  (`from dinglehopper.cli import main` / `from dinglehopper.cli_summarize
  import main`) come back, and with them the constraint-interpretation
  question the primary design dissolves (see Constraint statement) —
  that question would need ratifying then, not now.

**First-run bootstrap.** Before the first spawn, the shell creates the
venv from the bundled CPython and installs from the wheelhouse
(offline; roughly a minute), showing a "Setting up…" progress state —
never a frozen blank window. The bootstrap is idempotent and
self-repairing: a marker file records success; a missing/corrupt venv
is deleted and rebuilt. Subsequent launches skip straight to spawn.

**Startup sequence.** Shell spawns `<venv>/bin/dpi-eval-web
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

## The console-scripts problem (dissolved by the primary design)

`runner.py` invokes `dinglehopper` / `dinglehopper-summarize` by name
via PATH (`runner.py:19`, `runner.py:30`). In the bundled-runtime
design these are ordinary pip-generated console scripts inside the
venv; the shell prepends the venv's bin/Scripts directory to the
sidecar's PATH. Zero engine changes, zero hand-written entry points.

**Constraint statement.** The hard rule "never import `dinglehopper.*`"
is satisfied in its strictest reading by the primary design: no file in
this repo imports dinglehopper — the only import shims are the ones pip
itself generates at install time, exactly as with uvx today. The
permissive-vs-strict interpretation debate is live only in the
PyInstaller fallback branch and is deferred until/unless that branch
activates.

## Changes to the Python package (enumerated and closed)

All in the web layer; engine files (`runner.py`, `cli.py`,
`pairing.py`, `adapter.py`) remain untouched — one narrow exception,
item 5 below, added by amendment 2026-07-19. This list is the complete
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
   — it is not silently pre-authorized. **ACTIVATED by amendment
   2026-07-18** (macOS tracer failed; see the Known-risk section for
   the verdict and the authorized shape): `POST /grade-paths`
   directory-read endpoint plus a feature-detected desktop picker
   variant of the form page.

5. **Amendment 2026-07-19 — engine fence, narrow exception (approved
   by Trevor).** `run_page` in `runner.py` passes `gt.as_posix()` /
   `ocr.as_posix()` (instead of `str()`) as the two path arguments to
   the `dinglehopper` subprocess. Root cause being fixed: dinglehopper's
   `report.json.j2` interpolates these two paths into its JSON report
   unescaped (`"gt": "{{ gt }}"`), so any backslash-bearing path —
   every real Windows absolute path — produces invalid JSON;
   `dinglehopper-summarize` then crashes on `json.load` (exit 1 →
   unhandled 500 in `/grade`). Forward-slash paths are valid on Windows
   for process spawning and Python file APIs, and render as valid JSON.
   Scope: exactly these two argument expressions in `run_page`; no
   other engine line changes; test pins the argv strings backslash-free.
   Upstream bug (qurator-spk/dinglehopper, present through 0.11.0 and
   master, no existing issue): draft report in
   `docs/upstream/dinglehopper-report-json-escape.md` for Trevor to
   file. PAR waived: the amendment records a decision Trevor made
   directly with the root-cause evidence in front of him (diag-v2
   replay, CI run 29691628333).

6. **Amendment 2026-07-19b — engine fence, second narrow exception
   (approved by Trevor: "Do A through D").** `run_page` additionally
   passes dinglehopper's `--differences` option in the same argv
   (exact invocation form verified empirically against the pinned
   version — the option is a click BOOL value option, not a bare
   flag). Purpose: per-page reports then carry character/word
   difference data, and `dinglehopper-summarize` aggregates
   common-mistakes tables the batch summary currently lacks entirely
   (discovered 2026-07-19: a 4-page batch summary rendered as
   averages plus blank space). Scope: this one argv addition in
   `run_page`; nothing else in engine files.

Existing 37 tests stay green throughout.

## Bundling risks (named, each with its gate)

- **Wheelhouse completeness:** every transitive dependency must be
  present as a wheel for the target platform/arch — a missing wheel
  means a first-run failure on a student's machine, not ours.
- **Gate (blocking, in CI):** on a network-isolated runner step, run
  the bootstrap (venv + offline wheelhouse install) from the built
  resources, then grade the `tests/fixtures/text` pair through the
  venv's `dpi-eval-web` HTTP path end to end — must pass on every CI
  platform lane before any bundle is published.
- **macOS architectures (review finding, decided):** `macos-latest`
  runners are arm64 and PyInstaller does not cross-compile; a
  universal2 build is unrealistic with the ocrd stack's native wheels.
  **Decision: arm64 only** — a deliberate gamble that HDC Macs are
  Apple Silicon by now. An x86_64 lane (`macos-13`) is added only if
  Pamela's workflow tour surfaces Intel machines; until the inventory
  confirms, an Intel Mac receiving the artifact simply cannot launch
  it, and the uvx path is the answer there.
- **Bundle size:** the wheelhouse plus a standalone CPython is large
  (the ocrd stack is heavy), and the installed venv roughly doubles the
  on-disk footprint after first run. Acceptable for lab machines;
  recorded so nobody is surprised.

## Known risk: folder pickers in WKWebView

`webkitdirectory` is solid in WebView2 (Chromium) but historically
flaky in WKWebView. **Tracer bullet decides:** one page graded inside
the Tauri window on both OSes is the first post-probe milestone of any
build cycle. Contingency if macOS fails: Tauri dialog plugin native
folder picker feeding a server-side directory-read endpoint (localhost,
same machine — no privacy change), authorized via an explicit spec
amendment per the enumerated-changes rule above.

**Amendment 2026-07-18 — tracer failed on macOS; contingency
activated.** The failure is narrow: the WKWebView folder picker opens
and selects, but the form-navigation POST carrying `webkitdirectory`
files never reaches the server — the window resets to the empty form
and no run dir is created, while the identical multipart POST via curl
succeeds immediately before and after (server exonerated; the break is
in WebKit's upload path). Decision (Trevor, 2026-07-18): **native
pickers on both desktop OSes** — one code path, testable on available
hardware, no bet on the still-untested WebView2 leg. The browser-served
form is unchanged; `webkitdirectory` stays for uvx users. Authorized
shape:

- `web.py` gains `POST /grade-paths` (JSON `{gt_dir, ocr_dir}`): both
  must exist and be readable directories, else **400 with a JSON error
  naming the offending path** (fail loud; never a partial grade —
  a read error mid-enumeration also 400s). Files are enumerated
  recursively (files only; `rglob` semantics: symlinked files read
  through, symlinked directories not followed) and flattened into the
  run dir's `gt/`/`ocr/`, applying **all** of the upload path's rules
  in the same order: the hidden-file drop (basename starting with `.`
  — `_real_uploads`' `.DS_Store` filter, reimplemented for paths since
  the original takes `UploadFile`s), the no-`.gt.txt` and empty-OCR
  validations, and the collision rule. Then the existing `run_batch`
  flow — results, per-page diffs, and zip come out identical.
  **Response contract (fetch can't follow a 303 into a navigation):
  success returns JSON `{run_url: "/runs/run-NNN"}` and the page sets
  `window.location`; validation failures return 400 JSON `{error}`
  rendered inline by the page.** Windows paths travel as ordinary
  JSON strings (backslashes escaped by `JSON.stringify`, consumed by
  `pathlib` verbatim).
- **Desktop detection is feature detection, not a URL flag:** the form
  page probes `window.__TAURI__` and, when present, swaps the file
  inputs for "Choose folder…" buttons wired to `tauri-plugin-dialog`
  (directory mode), showing the chosen paths and submitting JSON to
  `/grade-paths`. No query param: internal links back to `/` keep
  working in the shell (a `?shell=desktop` flag would be dropped by
  "Grade another batch" links and would render dead buttons if a
  browser user ever reached it), and the shell's navigation code is
  untouched. Browsers never define `__TAURI__`, so the served form is
  byte-identical for uvx users and degrades to exactly today's page.
- Tauri v2 grants the dialog capability to remote content via a
  capability `remote.urls` entry with a **port wildcard**
  (`http://127.0.0.1:*/*` URLPattern form — an exact `:8765` origin
  would fail whenever `_pick_port`'s documented ephemeral fallback
  fires, e.g. uvx already holding 8765, silently killing the pickers;
  exact-port patterns may not even validate). Permission is
  **`dialog:allow-open` only — not `dialog:default`**, which would
  also grant message/save (the dialog plugin's automatic fs-scope
  grant on pick is irrelevant here — the sidecar reads disk itself,
  so no `fs:*` permission is added). `withGlobalTauri` injection into
  the webview's remote-served page is the mechanism; two sourced
  footguns bind the implementation: the page probes
  `window.__TAURI__` on load, never at script top level (init-script
  ordering has raced page scripts on WebView2 — tauri#12990), and no
  part of the picker UI may live in an iframe (init scripts don't
  reach iframes — tauri#13577). **Tauri floor ≥ 2.11.1**
  (CVE-2026-42184 / GHSA-7gmj-67g7-phm9: origin-confusion IPC bypass
  on the remote-origin surface this design uses; Cargo.lock currently
  pins 2.11.5).
- Security posture, stated honestly: this endpoint turns a path string
  into a server-side read whose results become HTTP-retrievable (via
  the `/files` static mount and the results zip). That is acceptable
  under the app's existing trust model — a single-user localhost tool
  whose `/grade` already accepts arbitrary POSTs from any local
  process — but per the community standard for localhost sidecars
  (Jupyter/VS Code token model; 127.0.0.1 binding alone does not stop
  other local processes or DNS-rebinding pages), the endpoint is
  gated: **the shell mints a random per-launch token, passes it to
  the sidecar via environment, and the sidecar both requires it on
  `/grade-paths` (header; 403 otherwise — the endpoint is refused
  entirely when the env token is absent, i.e. under plain uvx) and
  embeds it in the served form page for the picker variant's use.
  The server also rejects any request whose `Host` header is not the
  loopback host:port it bound** (DNS-rebinding guard, applies
  app-wide, invisible to legitimate localhost use). Standing
  invariants: 127.0.0.1 bind only; JSON body required on
  `/grade-paths`; **no CORS middleware is ever added to this app**.
  No directory confinement is claimed or implemented.
- Accessibility parity (this sprint's lens): the picker variant must
  not regress the plain form's built-in affordances — validation and
  grading errors are announced via an `aria-live` region, keyboard
  focus lands on the error (or the first actionable control) after a
  failure, the chosen-path display is programmatically associated
  with its button (labelled group, not adjacent text), and the
  Run/"Grading…" state change is exposed to assistive tech, not only
  visually.
- Engine files stay untouched; existing web tests stay green; the new
  endpoint gets its own tests (directory validation incl. unreadable
  and missing paths, dotfile filtering, collisions, happy path). The
  dialog→IPC→endpoint *wiring* cannot be exercised by automated tests
  (native dialogs need a human click) — the re-run in-window tracer is
  the gate for it, explicitly re-run after this change on macOS and at
  the Windows probe.

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
- **Auto-updater deferred, NOT signing-blocked (corrected 2026-07-17).**
  The earlier claim that updates "re-trigger the approval flow" was
  wrong: Gatekeeper's dialog is driven by the quarantine xattr that
  *browsers* attach to downloads — self-updaters (Sparkle, Tauri's
  `tauri-plugin-updater`) don't set it, so after the one-time
  Open Anyway, updater-delivered updates install and launch silently.
  session-notebook proves the pattern in production (unsigned + Sparkle
  self-updates). Tauri's updater is cross-platform, backed by a
  `latest.json` on GitHub Releases, and signed with its own free
  Ed25519 key — independent of Apple/Microsoft identities. It stays out
  of this HOLD cycle's scope, but the trigger is pilot demand (manual
  re-downloads re-run the Gatekeeper dance; the updater would avoid
  it), not a signing identity. Verify the no-quarantine behavior on our
  stack when built. Pilot updates meanwhile: manual downloads from
  GitHub Releases, versions pinned by tag.
- **Triggers to sign:** probe or pilot friction that blocks students,
  or a UMD Libraries signing identity becoming available. Signing
  unlocks notarization (no dialogs at all); the updater does not wait
  for it.
- Honest tension, still recorded: even corrected, unsigned first-run
  friction may exceed the uvx terminal command it replaces. The probe
  and pilot measure this; the uvx path stays documented as fallback.

## CI

GitHub Actions matrix — `macos-latest` (arm64) and `windows-latest`
(x86_64 macOS lane added only on Intel-inventory evidence): wheelhouse
build (uv, locked) + pinned python-build-standalone fetch →
network-isolated bootstrap + grade smoke test (blocking gate) →
`tauri build` (NSIS per-user on Windows) → artifacts attached to the
Release. Toolchains: Python (uv), Rust, Node (Tauri CLI).

## Repo layout

Same repo, new top-level `desktop/`:

    desktop/
      src-tauri/           # Rust shell, tauri.conf.json, bootstrap logic
      runtime/
        build_wheelhouse.sh  # uv-driven: export locked wheels per platform
        python-version.txt   # pinned python-build-standalone release

## Testing / success criteria

- Existing 37 tests green; new tests for the enumerated web-layer
  changes green.
- Managed-machine probe passes on real HDC hardware (go/no-go).
- CI network-isolated bootstrap + grade smoke test passes on both lanes
  (blocking).
- Tracer: one fixture page graded end-to-end inside the Tauri window on
  macOS and Windows before any polish work.
- A student-shaped walkthrough (double-click → approve once → pick
  folders → run → read results → download zip → quit) succeeds on both
  OSes with no terminal and no admin prompt at any point.

## Out of scope (HOLD fence)

- Auto-updater (deferred; unsigned-compatible via Tauri's updater —
  see corrected distribution note; trigger is pilot update friction)
- Any new user-facing features beyond the shell (see findings #8)
- Replacing the web form with native Tauri UI; the webview renders the
  existing pages (the 2026-07-18 amendment's native folder *pickers*
  replace an input mechanism WKWebView broke, not the UI)
- Linux packaging (no HDC demand)

## Review record

Amendment PAR 2026-07-18: two blind same-model reviewers on the
contingency amendment. Both independently found: the pinned-`:8765`
capability origin breaking on the ephemeral-port fallback, the dotfile
parity omission, the trust-boundary overclaim, and the
query-param-gating break (dead buttons in browsers / pickers working
exactly once past internal links). Singletons kept: the fetch-vs-303
response contract, `dialog:allow-open` vs `dialog:default` scoping,
fail-loud error semantics, `rglob` traversal details. All incorporated
above.

Amendment community research 2026-07-18 (sourced, not from model
memory): the dominant Tauri sidecar pattern is bundled `frontendDist`
+ fetch — remote-origin webviews like this design are the documented
but dis-preferred minority ("if in doubt, use the default custom
protocol"); kept anyway because the product IS a server-rendered app
and the fence forbids a frontend rewrite. Port-wildcard necessity
confirmed from Tauri's ACL parsing source (path auto-wildcards, port
never; discussion #11622, plugins-workspace #2131). The WKWebView
multipart failure is WebKit-level with no owning Tauri issue and no
fix in flight (Apple dev forums) — native dialogs are the permanent
ecosystem answer, not a stopgap. Research added: token+Host gating
(Jupyter/VS Code standard), Tauri ≥ 2.11.1 floor (GHSA-7gmj-67g7-phm9),
`__TAURI__` load-timing and no-iframe constraints, and the
no-`fs:*`-needed simplification. All incorporated above.

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

Packaging pivot 2026-07-17: the "no proven Tauri precedent for a
multi-command frozen bundle" finding was treated as a smell (human
call), and the bundled-runtime design was promoted to primary — it
dissolves the three-executable problem and the entry-stub constraint
question simultaneously (two independent pressures converging on one
architecture), trading exotic-but-few moving parts for
boring-but-more. PyInstaller shapes retained as documented fallbacks.

## Open questions (resolve during the build cycle, not before)

- Managed-machine probe outcome — go/no-go and, on failure, which
  response branch the failure mode argues for; fallback shapes A/B
  probed only if the bundled runtime fails
- HDC hardware inventory: macOS arm64 vs x86_64 mix; Windows version
  (pilot precheck, from Pamela's workflow tour)
- First-run bootstrap duration on real lab hardware (sets the progress
  UI's expectations copy)
- Whether WKWebView passes the `webkitdirectory` tracer (decides the
  native-dialog contingency and its spec amendment) — **resolved
  2026-07-18: it does not** (picker selects, upload POST never sent);
  contingency activated by amendment, native pickers both OSes
- Windows: whether SmartScreen reputation makes NSIS `.exe` per-user
  the least-scary artifact in practice (probe data)
- (Fallback branch only) exact PyInstaller hook set for the ocrd
  stack, and ratification of the entry-stub constraint interpretation
