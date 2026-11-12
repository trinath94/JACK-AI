fn main() {
    // Explicit allow-list of app commands; anything not listed is unreachable from the WebView.
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "backend_connection",
            "backend_status",
            "restart_backend",
            "sync_tray",
            "ptt_shortcut",
        ]),
    ))
    .expect("failed to run tauri-build");
}
