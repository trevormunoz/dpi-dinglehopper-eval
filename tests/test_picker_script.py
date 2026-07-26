"""Behavioural tests for the two inline scripts that touch the Tauri global:
the transcription pages' folder picker, and the shell's bootstrap window
(desktop/ui/index.html).

Why this file exists: the original guard for the tauri#12990 regression
asserted only that the first textual offset of `addEventListener('load'`
preceded the first offset of `__TAURI__`. That checks *ordering*, not
*nesting* — a script that registers an empty load handler and then probes
`window.__TAURI__` at top level (exactly the regression) passed it. PAR
review demonstrated the counterexample.

Two layers here, and (since R2-S12) both applied to both scripts:

* `_assert_tauri_only_inside_the_load_handler` walks braces to prove
  containment. No external dependency, always runs.
* The node-backed tests run the real script through `vm.runInThisContext`
  against a DOM stub whose `window.__TAURI__` is a getter recording *when*
  it was read, so the init-script race is tested as behaviour rather than
  as source shape. They also cover the two contract items that had no test
  at all: hiding the typed input when the dialog is available, and
  restoring it when the dialog errors.

Both stubs start each element's `hidden` at the value the real markup
renders, and record every write to it. R2-S11 was a false pass that came
straight out of stub defaults that did not match the DOM.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from dpi_eval import pages

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="needs node")

# R2-S12: the shell's own bootstrap window is the other surface the rule has
# to hold on, and it had the top-level probe the whole time.
INDEX_HTML = (Path(__file__).resolve().parents[1]
              / "desktop" / "ui" / "index.html")


def _script_body(page: str) -> str:
    """The picker script's JS, without the surrounding <script> tags."""
    start = page.index("<script>", page.index('id="folder-picker-btn"'))
    end = page.index("</script>", start)
    return page[start + len("<script>"):end]


def _bootstrap_script() -> str:
    """The bootstrap window's inline JS, without the <script> tags."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.count("<script") == 1, "expected one inline script"
    start = html.index("<script>")
    end = html.index("</script>", start)
    return html[start + len("<script>"):end]


def _assert_tauri_only_inside_the_load_handler(js: str, what: str) -> None:
    """Containment, not ordering. Brace-walk the load callback and require
    every __TAURI__ reference to fall inside it."""
    marker = "addEventListener('load'"
    assert marker in js, f"{what} registers no load handler"
    open_brace = js.index("{", js.index(marker))
    depth, close_brace = 0, None
    for i in range(open_brace, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                close_brace = i
                break
    assert close_brace is not None, f"{what}: load handler never closes"

    occurrences = [i for i in range(len(js)) if js.startswith("__TAURI__", i)]
    assert occurrences, f"{what} never references __TAURI__"
    outside = [i for i in occurrences if not (open_brace < i < close_brace)]
    assert not outside, (
        f"{what}: __TAURI__ referenced outside the load handler at offsets "
        f"{outside} — this is the tauri#12990 init-script race")


def test_tauri_is_referenced_only_inside_the_load_handler():
    _assert_tauri_only_inside_the_load_handler(
        _script_body(pages.transcribe_home_page([], "tok")),
        "the picker script")


def test_bootstrap_window_references_tauri_only_inside_the_load_handler():
    """R2-S12: the rule was written down for the sidecar-served pages and
    enforced only there, while desktop/ui/index.html — the window that shows
    the whole multi-minute cold-start install — probed __TAURI__ at IIFE top
    level. Losing that race means bootstrap-status is never subscribed and the
    window shows no progress at all."""
    _assert_tauri_only_inside_the_load_handler(
        _bootstrap_script(), "the bootstrap window script")


HARNESS = """
const vm = require('node:vm');
const script = process.argv[2];
const scenario = process.argv[3];
const log = {tauriReadBeforeLoad: false, loadFired: false, tauriReads: 0};

function makeEl(id) {
  // Initial `hidden` mirrors the rendered markup (_picker_field): the picker
  // button and the confirmation row carry the `hidden` attribute, the typed
  // paragraph and the text input do not. A stub that starts everything
  // visible cannot tell "the script revealed this" from "the script never
  // ran" — R2-S11 was exactly that false pass.
  const hidden = id.endsWith('-picker-btn') || id.endsWith('-picker-path');
  const el = {id, _hidden: hidden, hiddenWrites: [], value: '',
          textContent: '', _listeners: {}, _q: {},
          addEventListener(ev, fn) { (this._listeners[ev] ||= []).push(fn); },
          querySelector(sel) { return (this._q[sel] ||= {textContent: ''}); }};
  // Record every write to `hidden`, not just the final value. Two contract
  // items are about the script *restoring* a state, and a final-state
  // assertion cannot tell a restore from "never touched" when the value it
  // restores to is also the initial one.
  Object.defineProperty(el, 'hidden', {
    get() { return this._hidden; },
    set(v) { this._hidden = v; this.hiddenWrites.push(v); },
  });
  return el;
}
const els = {};
for (const id of ['folder', 'folder-typed', 'folder-picker-btn',
                  'folder-picker-path', 'draft_folder', 'draft_folder-typed',
                  'draft_folder-picker-btn', 'draft_folder-picker-path']) {
  els[id] = makeEl(id);
}

const dialog = {
  open: () => scenario === 'reject'
    ? Promise.reject(new Error('dialog exploded'))
    : Promise.resolve('/picked/folder'),
};

const loadHandlers = [];
globalThis.window = {
  addEventListener(ev, fn) { if (ev === 'load') loadHandlers.push(fn); },
  get __TAURI__() {
    if (!log.loadFired) log.tauriReadBeforeLoad = true;
    log.tauriReads += 1;
    return scenario === 'no-tauri' ? undefined : {dialog};
  },
};
globalThis.document = {getElementById: (id) => els[id] || null};

vm.runInThisContext(script);

log.loadFired = true;
for (const fn of loadHandlers) fn();

const btn = els['folder-picker-btn'];
const clicks = btn._listeners.click || [];
Promise.all(clicks.map((fn) => fn())).catch(() => {}).then(() => {
  setTimeout(() => {
    log.typedHidden = els['folder-typed'].hidden;
    log.typedHiddenWrites = els['folder-typed'].hiddenWrites;
    log.btnHidden = btn.hidden;
    log.loadHandlers = loadHandlers.length;
    log.inputValue = els['folder'].value;
    const pathEl = els['folder-picker-path'];
    log.surfaced = Object.values(pathEl._q)
      .map((n) => n.textContent).join(' ').trim();
    log.pathHidden = pathEl.hidden;
    console.log(JSON.stringify(log));
  }, 0);
});
"""


def _run(scenario: str, tmp_path) -> dict:
    page = pages.transcribe_home_page([], "tok")
    harness = tmp_path / "harness.js"
    harness.write_text(textwrap.dedent(HARNESS), encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness), _script_body(page), scenario],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@requires_node
def test_tauri_is_not_touched_before_the_load_event(tmp_path):
    """The tauri#12990 property as behaviour: reading window.__TAURI__ at
    script-evaluation time races the init script."""
    result = _run("resolve", tmp_path)
    # Read it at all, or "never before load" is satisfied by doing nothing.
    assert result["tauriReads"] >= 1, "script never consulted __TAURI__"
    assert result["tauriReadBeforeLoad"] is False


@requires_node
def test_picking_a_folder_writes_the_path_into_the_posted_input(tmp_path):
    assert _run("resolve", tmp_path)["inputValue"] == "/picked/folder"


@requires_node
def test_typed_input_is_hidden_when_the_native_dialog_is_available(tmp_path):
    """Contract item 2, first half — previously untested."""
    assert _run("resolve", tmp_path)["typedHidden"] is True


@requires_node
def test_browser_mode_keeps_the_typed_input_and_the_button_hidden(tmp_path):
    """R2-S11: the typed field stays the control of record *and* the picker
    button stays hidden. `_picker_field` renders it with `hidden`, so with no
    dialog to open, revealing it would hand the student a dead button — this
    assertion used to demand the opposite.

    The first two assertions are what keep this honest: with no dialog the
    script's correct behaviour is to change nothing, so without proof that it
    ran and consulted __TAURI__ the test would pass on an empty page.
    """
    result = _run("no-tauri", tmp_path)
    assert result["loadHandlers"] == 1, "script registered no load handler"
    assert result["tauriReads"] >= 1, "script never consulted __TAURI__"
    assert result["typedHidden"] is False
    assert result["btnHidden"] is True


@requires_node
def test_dialog_error_restores_the_typed_input(tmp_path):
    """Contract item 5 — previously untested. A rejected dialog must leave
    the user a working control, not a vanished button.

    Asserted as the sequence of writes, not the final value: the field starts
    visible, so "hidden is False at the end" is also true of a script that
    never ran (R2-S11's lesson)."""
    result = _run("reject", tmp_path)
    assert result["typedHiddenWrites"] == [True, False], (
        "expected the load handler to hide the typed field and the reject "
        f"handler to restore it, got {result['typedHiddenWrites']}")
    assert result["typedHidden"] is False


@requires_node
def test_dialog_error_is_explained_rather_than_swallowed(tmp_path):
    """PAR S2. The reject handler bound `err` and never used it: the button
    vanished, a text box appeared, and nothing said why. The pattern this
    mirrors (wirePicker) surfaces 'Could not open the folder picker: …'."""
    result = _run("reject", tmp_path)
    assert "dialog exploded" in result["surfaced"], result["surfaced"]
    assert result["pathHidden"] is False


@requires_node
def test_dialog_error_leaves_the_picker_button_usable(tmp_path):
    """PAR S2. Hiding the button was irreversible in-page, so one transient
    failure cost the picker until a reload."""
    assert _run("reject", tmp_path)["btnHidden"] is False


# --- The shell's bootstrap window (desktop/ui/index.html) ------------------
#
# Same rule, other surface (R2-S12). This one has no picker: what it must do
# is subscribe to bootstrap-status *after* load and render what arrives, so
# the cold-start install is not a blank window for minutes.

BOOTSTRAP_HARNESS = """
const vm = require('node:vm');
const script = process.argv[2];
const payload = process.argv[3];
const log = {tauriReadBeforeLoad: false, loadFired: false, tauriReads: 0,
             subscribed: []};

// Initial `hidden` mirrors desktop/ui/index.html: only the error panel
// carries the attribute.
function makeEl(id) {
  return {id, hidden: id === 'error-panel', textContent: ''};
}
const els = {};
for (const id of ['status', 'status-detail', 'shimmer', 'error-panel',
                  'error-detail']) {
  els[id] = makeEl(id);
}

const handlers = {};
const loadHandlers = [];
globalThis.window = {
  addEventListener(ev, fn) { if (ev === 'load') loadHandlers.push(fn); },
  get __TAURI__() {
    if (!log.loadFired) log.tauriReadBeforeLoad = true;
    log.tauriReads += 1;
    return {event: {listen(name, fn) {
      log.subscribed.push(name);
      handlers[name] = fn;
    }}};
  },
};
globalThis.document = {getElementById: (id) => els[id] || null};

vm.runInThisContext(script);

log.loadFired = true;
for (const fn of loadHandlers) fn();

// Deliver one status event the way lifecycle.rs emit_status does.
if (handlers['bootstrap-status']) handlers['bootstrap-status']({payload});

log.statusText = els['status'].textContent;
log.statusHidden = els['status'].hidden;
log.detailHidden = els['status-detail'].hidden;
log.shimmerHidden = els['shimmer'].hidden;
log.errorPanelHidden = els['error-panel'].hidden;
log.errorDetail = els['error-detail'].textContent;
console.log(JSON.stringify(log));
"""


def _run_bootstrap(payload: str, tmp_path) -> dict:
    harness = tmp_path / "bootstrap-harness.js"
    harness.write_text(textwrap.dedent(BOOTSTRAP_HARNESS), encoding="utf-8")
    proc = subprocess.run(
        [NODE, str(harness), _bootstrap_script(), payload],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@requires_node
def test_bootstrap_window_does_not_touch_tauri_before_the_load_event(tmp_path):
    """R2-S12 as behaviour, not source shape."""
    result = _run_bootstrap("installing", tmp_path)
    assert result["tauriReads"] >= 1, "script never consulted __TAURI__"
    assert result["tauriReadBeforeLoad"] is False


@requires_node
def test_bootstrap_window_subscribes_to_status_events(tmp_path):
    """The whole point of the script: no subscription, no progress for the
    entire cold-start install."""
    assert _run_bootstrap("installing", tmp_path)["subscribed"] == [
        "bootstrap-status"]


@requires_node
def test_bootstrap_window_renders_a_failure_payload_into_the_error_panel(
        tmp_path):
    result = _run_bootstrap("failed: wheelhouse missing", tmp_path)
    assert result["errorPanelHidden"] is False
    assert result["errorDetail"] == "failed: wheelhouse missing"
    assert result["statusHidden"] is True


@requires_node
def test_bootstrap_window_renders_the_ready_payload_in_plain_words(tmp_path):
    result = _run_bootstrap("ready", tmp_path)
    assert result["statusText"] == "Starting…"
    assert result["errorPanelHidden"] is True
    # "ready" is not "installing", so the activity affordances go away.
    assert result["shimmerHidden"] is True
