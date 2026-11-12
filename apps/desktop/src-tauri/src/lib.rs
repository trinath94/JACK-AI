//! JACK AI desktop core: window, tray, single instance, global push-to-talk hotkey,
//! start-with-Windows, and the service supervisor.

pub mod backend_client;
pub mod supervisor;

use reqwest::Method;
use std::path::PathBuf;
use std::sync::Arc;
use supervisor::{Connection, LaunchSpec, Status, Supervisor};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WindowEvent, Wry};
use tauri_plugin_global_shortcut::{Code, Modifiers, Shortcut, ShortcutState};

/// Hold to talk, from anywhere in Windows.
pub const PTT_SHORTCUT: &str = "Ctrl+Shift+Space";
/// Passed by the autostart entry so JACK starts in the tray without opening its window.
pub const AUTOSTART_ARG: &str = "--autostart";

struct AppState {
    supervisor: Arc<Supervisor>,
    mute_item: CheckMenuItem<Wry>,
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

/// The UI reports voice state so the tray reflects it (tooltip + mute checkbox).
#[tauri::command]
fn sync_tray(app: AppHandle, state: tauri::State<'_, AppState>, muted: bool, voice_state: String) {
    let _ = state.mute_item.set_checked(muted);
    if let Some(tray) = app.tray_by_id("jack-tray") {
        let _ = tray.set_tooltip(Some(tray_tooltip(&voice_state, muted)));
    }
}

#[tauri::command]
fn ptt_shortcut() -> &'static str {
    PTT_SHORTCUT
}

pub fn tray_tooltip(voice_state: &str, muted: bool) -> String {
    let what = match (muted, voice_state) {
        (true, _) => "microphone muted",
        (_, "listening") => "listening",
        (_, "processing") => "processing",
        (_, "speaking") => "speaking",
        (_, "disabled") => "microphone off (privacy mode)",
        _ => "ready",
    };
    format!("JACK AI — {what}")
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

fn ptt_shortcut_value() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::Space)
}

/// Forward a voice action to the service; failures surface in the UI as an event.
fn voice_call(app: &AppHandle, path: &'static str, body: Option<serde_json::Value>) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let sup = app.state::<AppState>().supervisor.clone();
        if let Err(e) = backend_client::call(&sup, Method::POST, path, body).await {
            log::warn!("voice action {path} failed: {e}");
            let _ = app.emit("voice://error", e);
        }
    });
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
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec![AUTOSTART_ARG]),
        ))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, shortcut, event| {
                    if shortcut != &ptt_shortcut_value() {
                        return;
                    }
                    match event.state() {
                        // Key auto-repeat re-sends Pressed; the service treats start as idempotent.
                        ShortcutState::Pressed => voice_call(
                            app,
                            "/v1/voice/ptt/start",
                            Some(serde_json::json!({ "source": "hotkey" })),
                        ),
                        ShortcutState::Released => voice_call(app, "/v1/voice/ptt/stop", None),
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            backend_connection,
            backend_status,
            restart_backend,
            sync_tray,
            ptt_shortcut
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

            // System tray: JACK stays available when the window is closed (Section 4).
            let show = MenuItem::with_id(app, "show", "Open JACK AI", true, None::<&str>)?;
            let mute =
                CheckMenuItem::with_id(app, "mute", "Mute microphone", true, false, None::<&str>)?;
            let restart =
                MenuItem::with_id(app, "restart", "Restart JACK service", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit JACK AI", true, None::<&str>)?;
            let sep = PredefinedMenuItem::separator(app)?;
            let menu = Menu::with_items(app, &[&show, &mute, &sep, &restart, &quit])?;

            app.manage(AppState {
                supervisor: supervisor.clone(),
                mute_item: mute.clone(),
            });
            tauri::async_runtime::spawn(supervisor.run());

            let mut tray = TrayIconBuilder::with_id("jack-tray")
                .tooltip(tray_tooltip("idle", false))
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "mute" => {
                        let checked = app
                            .state::<AppState>()
                            .mute_item
                            .is_checked()
                            .unwrap_or(false);
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let sup = app.state::<AppState>().supervisor.clone();
                            let body = serde_json::json!({ "muted": checked });
                            if let Err(e) = backend_client::call(
                                &sup,
                                Method::PATCH,
                                "/v1/voice/settings",
                                Some(body),
                            )
                            .await
                            {
                                log::warn!("tray mute failed: {e}");
                                // Revert the checkbox so the tray never shows a false state.
                                let _ = app.state::<AppState>().mute_item.set_checked(!checked);
                            }
                        });
                    }
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

            // Global push-to-talk. Another application may already own the combination;
            // that must not stop JACK from starting.
            use tauri_plugin_global_shortcut::GlobalShortcutExt;
            if let Err(e) = app.global_shortcut().register(ptt_shortcut_value()) {
                log::warn!("could not register push-to-talk shortcut {PTT_SHORTCUT}: {e}");
                let _ = handle.emit(
                    "voice://error",
                    format!("Push-to-talk shortcut {PTT_SHORTCUT} is unavailable: {e}"),
                );
            }

            if std::env::args().any(|a| a == AUTOSTART_ARG) {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tooltip_reflects_state() {
        assert_eq!(tray_tooltip("idle", false), "JACK AI — ready");
        assert_eq!(tray_tooltip("listening", false), "JACK AI — listening");
        assert_eq!(
            tray_tooltip("listening", true),
            "JACK AI — microphone muted"
        );
        assert_eq!(
            tray_tooltip("disabled", false),
            "JACK AI — microphone off (privacy mode)"
        );
    }

    #[test]
    fn ptt_shortcut_is_ctrl_shift_space() {
        let s = ptt_shortcut_value();
        assert!(s.matches(Modifiers::CONTROL | Modifiers::SHIFT, Code::Space));
    }
}
