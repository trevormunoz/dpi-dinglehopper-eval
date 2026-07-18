"""Pure unit tests for dpi_eval.pages — no server, no browser.

Covers the Task 9b Step 3 picker variant: form_page() gains a
keyword-only `token` that, when truthy, embeds a `<meta>` tag consumed
by the desktop shell's feature-detected picker script.
"""

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
