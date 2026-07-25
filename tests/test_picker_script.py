"""Behavioural tests for the transcription pages' folder-picker script.

Why this file exists: the original guard for the tauri#12990 regression
asserted only that the first textual offset of `addEventListener('load'`
preceded the first offset of `__TAURI__`. That checks *ordering*, not
*nesting* — a script that registers an empty load handler and then probes
`window.__TAURI__` at top level (exactly the regression) passed it. PAR
review demonstrated the counterexample.

Two layers here:

* `test_tauri_is_referenced_only_inside_the_load_handler` walks braces to
  prove containment. No external dependency, always runs.
* The node-backed tests run the real script through `vm.runInThisContext`
  against a DOM stub whose `window.__TAURI__` is a getter recording *when*
  it was read, so the init-script race is tested as behaviour rather than
  as source shape. They also cover the two contract items that had no test
  at all: hiding the typed input when the dialog is available, and
  restoring it when the dialog errors.
"""

import json
import shutil
import subprocess
import textwrap

import pytest

from dpi_eval import pages

NODE = shutil.which("node")
requires_node = pytest.mark.skipif(NODE is None, reason="needs node")


def _script_body(page: str) -> str:
    """The picker script's JS, without the surrounding <script> tags."""
    start = page.index("<script>", page.index('id="folder-picker-btn"'))
    end = page.index("</script>", start)
    return page[start + len("<script>"):end]


def test_tauri_is_referenced_only_inside_the_load_handler():
    """Containment, not ordering. Brace-walk the load callback and require
    every __TAURI__ reference to fall inside it."""
    js = _script_body(pages.transcribe_home_page([], "tok"))
    marker = "addEventListener('load'"
    assert marker in js
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
    assert close_brace is not None, "load handler never closes"

    occurrences = [i for i in range(len(js)) if js.startswith("__TAURI__", i)]
    assert occurrences, "script never references __TAURI__"
    outside = [i for i in occurrences if not (open_brace < i < close_brace)]
    assert not outside, (
        f"__TAURI__ referenced outside the load handler at offsets {outside} "
        "— this is the tauri#12990 init-script race")


HARNESS = """
const vm = require('node:vm');
const script = process.argv[2];
const scenario = process.argv[3];
const log = {tauriReadBeforeLoad: false, loadFired: false};

function makeEl(id) {
  return {id, hidden: false, value: '', textContent: '',
          _listeners: {}, _q: {},
          addEventListener(ev, fn) { (this._listeners[ev] ||= []).push(fn); },
          querySelector(sel) { return (this._q[sel] ||= {textContent: ''}); }};
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
    log.btnHidden = btn.hidden;
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
    assert _run("resolve", tmp_path)["tauriReadBeforeLoad"] is False


@requires_node
def test_picking_a_folder_writes_the_path_into_the_posted_input(tmp_path):
    assert _run("resolve", tmp_path)["inputValue"] == "/picked/folder"


@requires_node
def test_typed_input_is_hidden_when_the_native_dialog_is_available(tmp_path):
    """Contract item 2, first half — previously untested."""
    assert _run("resolve", tmp_path)["typedHidden"] is True


@requires_node
def test_typed_input_survives_when_there_is_no_native_dialog(tmp_path):
    """Browser mode: the typed field stays the control of record."""
    result = _run("no-tauri", tmp_path)
    assert result["typedHidden"] is False
    assert result["btnHidden"] is False


@requires_node
def test_dialog_error_restores_the_typed_input(tmp_path):
    """Contract item 5 — previously untested. A rejected dialog must leave
    the user a working control, not a vanished button."""
    assert _run("reject", tmp_path)["typedHidden"] is False


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
