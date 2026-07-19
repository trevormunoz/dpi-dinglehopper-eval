#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod lifecycle;

use std::path::PathBuf;
use std::sync::Mutex;

use tauri::webview::DownloadEvent;
use tauri::{Manager, Runtime, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_notification::{NotificationExt, PermissionState};

/// Fire a native OS notification from the shell. Rust-side notifications go
/// through the `NotificationExt` trait (not the IPC bridge), so they need no
/// capability grant. On macOS the permission prompt appears once, on the first
/// notification; the OS remembers the answer thereafter, so calling
/// `request_permission` again is a no-op. Known caveat: an *unbundled* dev
/// binary has no bundle identity, and macOS Notification Center silently drops
/// notifications from such a process — the bundled `.app` displays them fine.
fn send_notification<R: Runtime>(webview: &tauri::Webview<R>, title: &str, body: &str) {
    let notifier = webview.notification();
    let granted = matches!(notifier.permission_state(), Ok(PermissionState::Granted))
        || matches!(notifier.request_permission(), Ok(PermissionState::Granted));
    if !granted {
        eprintln!("[dpi-eval-desktop] notification permission not granted; skipping");
        return;
    }
    if let Err(e) = notifier.builder().title(title).body(body).show() {
        eprintln!("[dpi-eval-desktop] notification failed: {e}");
    }
}

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
        .plugin(tauri_plugin_notification::init())
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
                // On macOS, DownloadEvent::Finished always reports `path: None`
                // (WKWebView API limit), so we can't learn the saved location at
                // completion time. Remember the destination chosen at Requested
                // time and read it back at Finished. Downloads here are serial
                // single-file, so one slot is enough. `Mutex` gives the `Fn`
                // closure interior mutability without needing `FnMut`.
                .on_download({
                    let last_target: Mutex<Option<PathBuf>> = Mutex::new(None);
                    move |webview, event| {
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
                                    // Remember the destination so Finished can
                                    // name it in the notification (path is None
                                    // there on macOS).
                                    *last_target.lock().unwrap() = Some(target.clone());
                                    *destination = target;
                                }
                                Err(e) => {
                                    // Fall back to the webview's default location
                                    // rather than cancelling the download.
                                    *last_target.lock().unwrap() = None;
                                    eprintln!(
                                        "[dpi-eval-desktop] cannot resolve Downloads dir ({e}); using webview default {}",
                                        destination.display()
                                    );
                                }
                            }
                        }
                        DownloadEvent::Finished { url, path, success } => {
                            // macOS never reports `path` (WKWebView API limit);
                            // fall back to the destination we recorded at
                            // Requested time.
                            let saved = last_target.lock().unwrap().take().or(path);
                            if success {
                                match &saved {
                                    Some(p) => eprintln!(
                                        "[dpi-eval-desktop] download finished ({url}) -> {}",
                                        p.display()
                                    ),
                                    None => eprintln!(
                                        "[dpi-eval-desktop] download finished ({url})"
                                    ),
                                }
                                let body = match saved
                                    .as_ref()
                                    .and_then(|p| p.file_name())
                                    .map(|n| n.to_string_lossy().into_owned())
                                {
                                    Some(name) => {
                                        format!("Report saved to Downloads: {name}")
                                    }
                                    None => "Report saved to Downloads".to_string(),
                                };
                                send_notification(&webview, "dpi-eval", &body);
                            } else {
                                eprintln!("[dpi-eval-desktop] download failed ({url})");
                                send_notification(
                                    &webview,
                                    "dpi-eval",
                                    "Report download failed",
                                );
                            }
                        }
                        // DownloadEvent is #[non_exhaustive].
                        _ => {}
                    }
                    // Allow the download to proceed.
                    true
                    }
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
