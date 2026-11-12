//! JACK AI desktop core: window, tray, single instance, and the service supervisor.

pub mod supervisor;

use std::path::PathBuf;
use std::sync::Arc;
use supervisor::{Connection, LaunchSpec, Status, Supervisor};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent};

struct AppState {
    supervisor: Arc<Supervisor>,
}

#[tauri::command]
async fn backend_connection(state: tauri::State<'_, AppState>) -> Result<Connection, String> {
    state
        .supervisor
        .connection()
        .await
        .ok_or_else(|| "JACK service is not running yet".to_string())
}

#[tauri::command]
async fn backend_status(state: tauri::State<'_, AppState>) -> Result<Status, String> {
    Ok(state.supervisor.status().await)
}

#[tauri::command]
fn restart_backend(state: tauri::State<'_, AppState>) {
    state.supervisor.request_restart();
}

/// Resolve how to start jack-service.
///
/// Release builds run the bundled sidecar next to the main executable. Debug builds run the
/// Python source with `uv` from the repo unless `JACK_SERVICE_BIN` points to a frozen binary.
fn launch_spec(app: &AppHandle) -> Result<LaunchSpec, String> {
    let data_dir = app
        .path()
        .app_local_data_dir()
        .map_err(|e| e.to_string())?
        .join("data");
    let dev_mode = cfg!(debug_assertions);

    if let Ok(bin) = std::env::var("JACK_SERVICE_BIN") {
        return Ok(LaunchSpec {
            program: bin.into(),
            args: vec![],
            cwd: None,
            data_dir,
            dev_mode,
        });
    }
    if dev_mode {
        let api_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/api");
        return Ok(LaunchSpec {
            program: "uv".into(),
            args: vec!["run".into(), "--quiet".into(), "jack-service".into()],
            cwd: Some(api_dir),
            data_dir,
            dev_mode,
        });
    }
    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let dir = exe.parent().ok_or("executable has no parent directory")?;
    let name = if cfg!(windows) {
        "jack-service.exe"
    } else {
        "jack-service"
    };
    Ok(LaunchSpec {
        program: dir.join(name),
        args: vec![],
        cwd: Some(dir.into()),
        data_dir,
        dev_mode,
    })
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main(app)
        }))
        .plugin(
            tauri_plugin_log::Builder::new()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            backend_status,
            restart_backend
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            let spec = launch_spec(&handle)?;
            let emitter = handle.clone();
            let supervisor = Supervisor::new(
                spec,
                Arc::new(move |s: &Status| {
                    let _ = emitter.emit("backend://status", s);
                }),
            );
            app.manage(AppState {
                supervisor: supervisor.clone(),
            });
            tauri::async_runtime::spawn(supervisor.run());

            // System tray: JACK stays available when the window is closed (Section 4).
            let show = MenuItem::with_id(app, "show", "Open JACK AI", true, None::<&str>)?;
            let restart =
                MenuItem::with_id(app, "restart", "Restart JACK service", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit JACK AI", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &restart, &quit])?;
            let mut tray = TrayIconBuilder::with_id("jack-tray")
                .tooltip("JACK AI")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "restart" => app.state::<AppState>().supervisor.request_restart(),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Close-to-tray: hide instead of exiting.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building JACK AI");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let sup = handle.state::<AppState>().supervisor.clone();
            tauri::async_runtime::block_on(sup.stop());
        }
    });
}
