#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod lifecycle;

use tauri::Manager;

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
