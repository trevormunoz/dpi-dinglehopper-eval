"""Pure unit tests for dpi_eval.pages — no server, no browser.

Covers the Task 9b Step 3 picker variant: form_page() gains a
keyword-only `token` that, when truthy, embeds a `<meta>` tag consumed
by the desktop shell's feature-detected picker script.
"""

import re

from dpi_eval import pages


def test_form_page_without_token_has_no_meta_tag():
    page = pages.form_page()
    assert '<meta name="dpi-eval-token"' not in page


def test_form_page_without_token_matches_default_call():
    # Explicitly passing None must be identical to omitting the arg.
    assert pages.form_page() == pages.form_page(token=None)


def test_form_page_with_token_embeds_meta_tag():
    page = pages.form_page(token="abc123")
    assert '<meta name="dpi-eval-token" content="abc123">' in page


def test_form_page_with_empty_token_has_no_meta_tag():
    page = pages.form_page(token="")
    assert '<meta name="dpi-eval-token"' not in page


def test_form_page_token_is_html_escaped():
    page = pages.form_page(token='"><script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in page
    assert "&quot;" in page or "&#34;" in page
    assert "&gt;" in page
    assert "&lt;" in page


def test_form_page_still_has_webkitdirectory_inputs_with_token():
    # Browser fallback must remain intact even when the token is present
    # (feature detection happens client-side, not server-side).
    page = pages.form_page(token="abc123")
    assert "webkitdirectory" in page


def test_form_page_still_has_webkitdirectory_inputs_without_token():
    page = pages.form_page()
    assert "webkitdirectory" in page


def test_picker_script_present_regardless_of_token():
    assert "__TAURI__" in pages.form_page()
    assert "__TAURI__" in pages.form_page(token="abc123")


def test_picker_script_probes_tauri_inside_load_handler_not_top_level():
    # tauri#12990 footgun: init-script ordering has raced page scripts,
    # so window.__TAURI__ must only be touched inside a load listener.
    page = pages.form_page(token="abc123")
    script_start = page.index("<script>")
    load_idx = page.index("addEventListener('load'", script_start)
    tauri_idx = page.index("__TAURI__", script_start)
    assert load_idx < tauri_idx


def test_picker_script_has_no_iframe():
    assert "<iframe" not in pages.form_page(token="abc123")
    assert "<iframe" not in pages.form_page()


def test_aria_live_error_region_present_from_load():
    for page in (pages.form_page(), pages.form_page(token="abc123")):
        assert 'aria-live="polite"' in page
        assert 'tabindex="-1"' in page


def test_choose_folder_buttons_are_real_buttons_with_aria_describedby():
    page = pages.form_page(token="abc123")
    assert '<button type="button"' in page
    assert "aria-describedby" in page


def test_run_button_aria_busy_wiring_present():
    page = pages.form_page(token="abc123")
    assert "aria-busy" in page


def test_form_page_default_call_signature_unchanged_for_existing_callers():
    # Existing callers (e.g. web.py before this change) call
    # form_page() with no args — must keep working.
    assert isinstance(pages.form_page(), str)


def test_results_page_leads_with_verdict_score():
    page = pages.results_page(
        "run-001", ["page_0"], [], [], 0,
        summary={"wer_avg": 0.125, "cer_avg": 0.034,
                 "n_words_gt": 16, "n_characters_gt": 87},
        page_metrics={"page_0": {"wer": 0.125, "cer": 0.034, "n_words": 16}},
    )
    # Verdict-first: the score element appears before the explanatory prose.
    assert page.index('class="verdict"') < page.index("share of words")
    assert "12.5%" in page


def test_style_defines_design_tokens():
    page = pages.form_page()
    for token in ("--space-1", "--fs-base", "--color-ink"):
        assert token in page


# --- Task 7.1: progressive form-page bundle (F3, F6, F7, F9, F10, F17) ---


def test_form_leads_with_choose_two_folders_sentence():
    # F6: dense filename paragraph replaced by a short lead + bullets.
    page = pages.form_page()
    assert "Choose two folders, then grade." in page


def test_naming_rules_are_a_bulleted_list_not_a_paragraph():
    # F6: naming rules become a short bulleted list; .gt.txt survives.
    page = pages.form_page()
    assert "<ul>" in page
    assert page.count("<li>") >= 3
    assert ".gt.txt" in page


def test_fieldset_legends_are_numbered():
    # F17: sequence communicated by numbering the steps.
    page = pages.form_page()
    assert "1. Ground-truth folder" in page
    assert "2. OCR folder" in page


def test_submit_button_reads_grade_this_batch_not_run():
    # F9: "Run" is CLI jargon.
    page = pages.form_page()
    assert ">Grade this batch</button>" in page
    assert ">Run</button>" not in page


def test_ready_state_notice_uses_ok_tier_hidden_by_default():
    # F10: explicit ready state, reusing Task 4's notice-ok component.
    page = pages.form_page(token="abc123")
    ready_idx = page.index('id="ready-notice"')
    tag = page[ready_idx - 40 : ready_idx + 60]
    assert "notice-ok" in tag
    assert "hidden" in tag
    assert "Both folders chosen" in page


def test_picker_confirmation_row_markup_present():
    # F10: ✓ + emphasized folder name + de-emphasized wrapping path,
    # replacing the raw-path-only gray text. aria-describedby target kept.
    page = pages.form_page(token="abc123")
    assert 'class="picked"' in page
    assert "picked-name" in page
    assert "picked-path" in page
    # The aria-describedby path-display mechanism survives.
    assert 'aria-describedby="gt-picker-path"' in page
    assert 'id="gt-picker-path"' in page


def test_confirmation_path_wraps_without_overflow():
    # F10: long paths must wrap, never overflow.
    page = pages.form_page()
    assert "overflow-wrap: anywhere" in page


def test_grading_status_region_present_and_hidden_until_submit():
    # F7: page-level status region for the wait, hidden until submit.
    page = pages.form_page(token="abc123")
    idx = page.index('id="grading-status"')
    assert "hidden" in page[idx : idx + 80]


def test_grading_message_is_aria_live_but_counter_is_not():
    # F7: the initial message announces once via aria-live; the ticking
    # seconds counter lives OUTSIDE the live region and is aria-hidden,
    # so ticks are never announced.
    page = pages.form_page(token="abc123")
    msg_idx = page.index('id="grading-status-msg"')
    assert 'aria-live="polite"' in page[msg_idx - 60 : msg_idx + 60]
    elapsed_idx = page.index('id="grading-elapsed"')
    elapsed_tag = page[elapsed_idx - 20 : elapsed_idx + 80]
    assert 'aria-hidden="true"' in elapsed_tag
    assert "aria-live" not in elapsed_tag


def test_grading_supporting_line_present_and_honest():
    # F7: honest supporting line — no spinner/progress bar/percent in the
    # waiting UI (scoped to the status region so CSS `100%`/"progressive"
    # comments don't false-positive).
    page = pages.form_page()
    assert "the page updates when grading finishes" in page
    region = page[page.index('id="grading-status"') :]
    region = region[: region.index("</div>")].lower()
    for forbidden in ("spinner", "progress", "%"):
        assert forbidden not in region
    # The JS-set message must also be honest.
    assert "Grading your batch" in page


def test_footer_terminal_sentence_is_wrapped_for_desktop_hiding():
    # F3: the "terminal window it came from" sentence is gated behind
    # the desktop feature detection via a dedicated element.
    page = pages.form_page()
    assert 'id="footer-terminal-note"' in page
    assert "terminal window it came from" in page
    # Browser variant keeps a shutdown instruction outside the gate.
    assert "Close this window" in page


def test_desktop_script_hides_footer_terminal_note_inside_load_handler():
    # F3: the hide happens only in the desktop path (load handler), never
    # top-level — same footgun discipline as the __TAURI__ probe.
    page = pages.form_page(token="abc123")
    script_start = page.index("<script>")
    load_idx = page.index("addEventListener('load'", script_start)
    hide_idx = page.index("footer-terminal-note", script_start)
    assert load_idx < hide_idx


def test_muted_fieldset_is_visual_only_never_disabling():
    # Keyboard invariant: muting fieldset 2 is a visual hint (opacity),
    # it must not disable the control or drop it from the tab order.
    page = pages.form_page()
    assert "fieldset.is-muted" in page
    rule_idx = page.index("fieldset.is-muted")
    rule = page[rule_idx : rule_idx + 120]
    assert "opacity" in rule
    assert "pointer-events" not in rule
    assert "display: none" not in rule


def test_every_script_referenced_id_exists_in_markup():
    # Spec-mandated: close the silent-desktop-breakage gap. Every element
    # the inline script wires must exist in the markup it runs against.
    page = pages.form_page(token="abc123")
    script_start = page.index("<script>")
    script = page[script_start:]
    markup = page[:script_start]

    ids = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", script))
    # wirePicker(kind, inputId, btnId, pathId): args after the kind label
    # are all element ids passed indirectly to getElementById.
    # Only calls (first arg is a quoted 'kind' label), never the function
    # definition (`wirePicker(kind, inputId, ...)`).
    for call in re.findall(r"wirePicker\((['\"][^)]*)\)", script):
        args = [a.strip().strip("'\"") for a in call.split(",")]
        ids.update(args[1:])

    assert ids, "script wires no elements by id — regex or markup drifted"
    for element_id in ids:
        assert f'id="{element_id}"' in markup, (
            f"script references #{element_id} but markup has no such id"
        )

    # meta the script reads by attribute selector must also exist.
    for name in re.findall(r'meta\[name="([^"]+)"\]', script):
        assert f'name="{name}"' in page
