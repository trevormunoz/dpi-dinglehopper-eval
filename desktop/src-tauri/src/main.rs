#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod lifecycle;

use tauri::webview::DownloadEvent;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

fn main() {
    // Before any other thread exists: route SIGTERM/SIGINT through the
    // sidecar tree-kill (unix; no-op elsewhere).
    lifecycle::install_signal_watcher();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            // Create the main window in code (not tauri.conf.json) so we can
            // attach a download handler. WKWebView has no default handling for
            // Content-Disposition attachment navigations, so the results page's
            // "Download reports (.zip)" link is a silent no-op without this.
            // Label MUST stay "main": lifecycle.rs looks the window up by that
            // label to navigate it, and both capabilities bind windows:["main"].
            // WebviewUrl::App("index.html") reproduces the frontendDist ("../ui")
            // load, so the window still shows ui/index.html until navigation.
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("dpi-eval")
                .inner_size(900.0, 700.0)
                .on_download(|webview, event| {
                    match event {
                        DownloadEvent::Requested { url, destination } => {
                            // WKWebView pre-fills `destination` with the
                            // server-suggested filename; redirect it into the
                            // user's Downloads dir, deduplicating on collision.
                            let filename = destination
                                .file_name()
                                .map(|n| n.to_string_lossy().into_owned())
                                .unwrap_or_else(|| "download".to_string());
                            match webview.path().download_dir() {
                                Ok(dir) => {
                                    let target = lifecycle::dedupe_download_path(
                                        &dir,
                                        &filename,
                                        |p| p.exists(),
                                    );
                                    eprintln!(
                                        "[dpi-eval-desktop] download requested ({url}); saving to {}",
                                        target.display()
                                    );
                                    *destination = target;
                                }
                                Err(e) => {
                                    // Fall back to the webview's default location
                                    // rather than cancelling the download.
                                    eprintln!(
                                        "[dpi-eval-desktop] cannot resolve Downloads dir ({e}); using webview default {}",
                                        destination.display()
                                    );
                                }
                            }
                        }
                        DownloadEvent::Finished { url, path, success } => {
                            if success {
                                // macOS never reports `path` (WKWebView API limit).
                                match path {
                                    Some(p) => eprintln!(
                                        "[dpi-eval-desktop] download finished ({url}) -> {}",
                                        p.display()
                                    ),
                                    None => eprintln!(
                                        "[dpi-eval-desktop] download finished ({url})"
                                    ),
                                }
                            } else {
                                eprintln!("[dpi-eval-desktop] download failed ({url})");
                            }
                        }
                        // DownloadEvent is #[non_exhaustive].
                        _ => {}
                    }
                    // Allow the download to proceed.
                    true
                })
                .build()?;

            // Bootstrap + spawn + handshake run off the main thread; the
            // window shows ui/index.html status text until navigation.
            let handle = app.handle().clone();
            std::thread::spawn(move || lifecycle::run(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| match event {
            tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit => {
                lifecycle::shutdown();
            }
            _ => {}
        });
}
