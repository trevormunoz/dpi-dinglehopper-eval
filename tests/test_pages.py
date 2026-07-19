"""Pure unit tests for dpi_eval.pages — no server, no browser.

Covers the Task 9b Step 3 picker variant: form_page() gains a
keyword-only `token` that, when truthy, embeds a `<meta>` tag consumed
by the desktop shell's feature-detected picker script.
"""

import re
from pathlib import Path

from dpi_eval import pages

FIXTURES = Path(__file__).parent / "fixtures"


def _extract_body(html: str) -> str:
    return html.split("<body", 1)[-1].split(">", 1)[-1].rsplit("</body>", 1)[0]


def _page_0_body() -> str:
    html = (FIXTURES / "reports" / "page_0.html").read_text(encoding="utf-8")
    return _extract_body(html)


def _summary_body() -> str:
    html = (FIXTURES / "reports" / "summary.html").read_text(encoding="utf-8")
    return _extract_body(html)


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


def _graded_results_page(**overrides):
    kwargs = dict(
        run_id="run-001",
        succeeded=["page_0"],
        failed=[],
        missing=[],
        exit_code=0,
        summary={"wer_avg": 0.05, "cer_avg": 0.02},
        page_metrics={"page_0": {"wer": 0.05, "cer": 0.02, "n_words": 16}},
    )
    kwargs.update(overrides)
    return pages.results_page(**kwargs)


def test_results_zero_success_banner_blames_grading_not_naming():
    # Post-F14: naming mismatches 400 before grading (see _grade_pipeline),
    # so the only way to reach a zero-success results page is when every
    # paired page failed to grade. The banner must name that cause, not
    # the naming/pairing problem F14 already rejects upstream.
    page = pages.results_page("run-001", [], ["page_0"], [], 1)
    assert (
        "None of the pages could be graded. The files matched up by name, "
        "but grading failed on every page — check that the OCR files open "
        "correctly, or show this page to a supervisor." in page
    )
    assert "ground-truth files end in" not in page
    assert "share names with the OCR files" not in page


def test_results_zero_success_exit_reads_back_to_the_form():
    # F16: nothing was graded, so the only exit must not claim grading
    # happened.
    page = pages.results_page("run-001", [], [], ["page_0"], 1)
    assert "Back to the form" in page
    assert "Grade another batch" not in page


def test_results_success_exit_still_reads_grade_another_batch():
    # Grading did happen here — the F16 relabel is scoped to the
    # zero-success state only.
    page = _graded_results_page()
    assert "Grade another batch" in page
    assert "Back to the form" not in page


def test_results_partial_success_exit_reads_grade_another_batch():
    # Partial success: some pages were graded, so "nothing was graded"
    # framing does not apply.
    page = pages.results_page("run-001", ["page_0"], ["page_1"], [], 1)
    assert "Grade another batch" in page
    assert "Back to the form" not in page


def test_full_technical_report_link_relabeled_and_deemphasized():
    # F5: the link drops students into raw decimals — relabel and
    # de-emphasize so the results page reads as the primary artifact.
    page = _graded_results_page()
    assert "Full technical report" in page
    assert "Full batch summary" not in page
    assert "<strong>Full technical report</strong>" not in page
    # De-emphasized: the link lives inside a `.note`-styled element, not
    # bare/bolded prose.
    link_idx = page.index("Full technical report")
    tag_start = page.rindex("<p", 0, link_idx)
    tag = page[tag_start : page.index(">", tag_start)]
    assert "note" in tag


def test_download_link_has_downloads_folder_note():
    # F18: tell students where the zip lands. Covers both the desktop
    # app (saves to the OS Downloads folder) and the browser flow
    # (normal browser download behavior).
    page = _graded_results_page()
    assert "Download reports (.zip)" in page
    assert "Downloads folder" in page


def test_report_page_back_link_appears_before_heading():
    # Review-carry: GOV.UK back-link convention — the back link sits
    # above the H1, not below it.
    page = pages.report_page("run-001", "page_0", "<p>DIFF</p>")
    assert page.index("Back to results") < page.index("<h1")


def test_report_page_back_link_still_a_real_anchor_to_the_run():
    # Test-intent preservation: the Task 5 wrapper guarantee (a real
    # <a href="/runs/run-001"> back link exists) must survive the move.
    page = pages.report_page("run-001", "page_0", "<p>DIFF</p>")
    assert '<a href="/runs/run-001">Back to results</a>' in page


def test_report_page_heading_is_friendlier_with_run_id_demoted():
    # Review-carry: "Report: page_0 — run-001" reads as a raw label;
    # friendlier heading, run id demoted to the .note caption style
    # results_page already uses.
    page = pages.report_page("run-001", "page_0", "<p>DIFF</p>")
    assert "<h1>Technical report: page_0</h1>" in page
    assert "Report: page_0 — run-001" not in page
    note_idx = page.index('class="note"')
    assert "run-001" in page[note_idx : note_idx + 200]


# --- F20: transform_report_body(), against real fixture reports -----------


def test_transform_report_body_strips_cdn_scripts_and_inline_script():
    body = pages.transform_report_body(_page_0_body())
    assert "<script" not in body
    assert "jquery" not in body
    assert "popper" not in body
    assert "bootstrap" not in body
    assert "find_diff_class" not in body  # the inline script's own body


def test_transform_report_body_preserves_non_script_content():
    body = pages.transform_report_body(_page_0_body())
    assert "<h2>Character differences</h2>" in body
    assert "The quick bro" in body
    assert 'data-toggle="tooltip"' in body  # native tooltips still work


def test_transform_report_body_rewrites_page_metrics_to_percentages():
    body = pages.transform_report_body(_page_0_body())
    assert "<p>Character error rate (CER): 3.5%</p>" in body
    assert "<p>Word error rate (WER): 12.5%</p>" in body
    assert "<p>CER: 0.0345</p>" not in body
    assert "<p>WER: 0.125</p>" not in body


def test_transform_report_body_rewrites_summary_average_metrics():
    body = pages.transform_report_body(_summary_body())
    assert "3.5%" in body
    assert "12.5%" in body
    assert "Average CER: 0.0345" not in body
    assert "Average WER: 0.125" not in body


def test_transform_report_body_injects_legend_immediately_after_metrics():
    body = pages.transform_report_body(_page_0_body())
    legend = (
        "CER counts character-level differences; WER counts word-level "
        "differences. Lower is better. The percentages here are this "
        "page's raw scores."
    )
    assert f'<p class="note">{legend}</p>' in body
    wer_idx = body.index("Word error rate (WER)")
    legend_idx = body.index(legend)
    heading_idx = body.index("<h2>Character differences</h2>")
    assert wer_idx < legend_idx < heading_idx


def test_transform_report_body_labels_diff_columns_ground_truth_and_ocr():
    body = pages.transform_report_body(_page_0_body())
    # one header per differences section (Character differences, Word
    # differences) — not one per .row.
    assert body.count("Ground truth") == 2
    assert body.count(">OCR<") == 2
    char_h2 = body.index("Character differences")
    char_header = body.index("Ground truth")
    char_row = body.index('<div class="row">')
    assert char_h2 < char_header < char_row


def test_transform_report_body_does_not_touch_fixture_file_on_disk():
    path = FIXTURES / "reports" / "page_0.html"
    before = path.read_bytes()
    pages.transform_report_body(_extract_body(before.decode("utf-8")))
    assert path.read_bytes() == before
