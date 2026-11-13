//! HMS desktop shell (Tauri 2).
//!
//! A native window around the web interface served by the hotel server, as
//! designed in docs/architecture/01-architecture.md §1.4:
//!
//! * a bundled connection screen chooses, tests and remembers the server
//!   address (and explains a certificate the computer does not trust);
//! * the window then loads the interface **from the server**, so every
//!   computer always runs the version that matches the server, and there is no
//!   local database;
//! * links to other sites open in the system browser, the window cannot be
//!   sent to `file:` or other schemes;
//! * documents (invoices, receipts, contracts) open in their own window;
//!   downloaded PDFs are saved in the Downloads folder (never overwriting a
//!   file) and opened with the system viewer, which prints;
//! * one instance only; a second launch focuses the existing window.
//!
//! Security: pages from the hotel server get no access to the shell's
//! commands (Tauri only exposes IPC to remote URLs listed in a capability,
//! and none is). The commands below serve the bundled connection screen.

use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use hms_desktop_core as core;
use tauri::menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::webview::{DownloadEvent, NewWindowResponse};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

const MAIN: &str = "main";

struct Shared {
    /// The hotel server, once connected.
    server: Mutex<Option<Url>>,
    /// URL of the bundled connection screen on this platform.
    app_page: Mutex<Option<Url>>,
    settings_path: PathBuf,
    windows: AtomicU32,
}

type State = Arc<Shared>;

async fn check(server: &Url) -> core::CheckResult {
    let client = match reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .redirect(reqwest::redirect::Policy::none())
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return core::CheckResult {
                kind: core::CheckKind::Unreachable,
                url: Some(server.to_string()),
                status: None,
                detail: Some(e.to_string()),
            }
        }
    };
    let result = client.get(core::health_url(server)).send().await;
    let (kind, status, detail) = match result {
        Err(e) => {
            // The cause (DNS, refused, TLS...) is in the source chain.
            let mut chain = e.to_string();
            let mut source = std::error::Error::source(&e);
            while let Some(s) = source {
                chain.push_str(": ");
                chain.push_str(&s.to_string());
                source = s.source();
            }
            (core::classify_error(&chain), None, Some(chain))
        }
        Ok(resp) => {
            let status = resp.status().as_u16();
            let body = resp.text().await.unwrap_or_default();
            if status != 200 {
                (core::CheckKind::HttpStatus, Some(status), None)
            } else if core::is_hms_health(&body) {
                (core::CheckKind::Ok, Some(status), None)
            } else {
                (core::CheckKind::NotHms, Some(status), None)
            }
        }
    };
    core::CheckResult {
        kind,
        url: Some(server.to_string()),
        status,
        detail,
    }
}

/// Test an address without connecting.
#[tauri::command]
async fn check_server(url: String) -> core::CheckResult {
    match core::normalize_server_url(&url) {
        Ok(server) => check(&server).await,
        Err(problem) => core::CheckResult {
            kind: problem.into(),
            url: None,
            status: None,
            detail: None,
        },
    }
}

/// The remembered server address, if any.
#[tauri::command]
fn saved_server(state: tauri::State<'_, State>) -> Option<String> {
    core::load_settings(&state.settings_path).server_url
}

/// Test the address, remember it and show the hotel's interface.
#[tauri::command]
async fn connect(
    app: AppHandle,
    state: tauri::State<'_, State>,
    url: String,
) -> Result<core::CheckResult, String> {
    let server = match core::normalize_server_url(&url) {
        Ok(s) => s,
        Err(problem) => {
            return Ok(core::CheckResult {
                kind: problem.into(),
                url: None,
                status: None,
                detail: None,
            })
        }
    };
    let result = check(&server).await;
    if !result.ok() {
        return Ok(result);
    }
    core::save_settings(
        &state.settings_path,
        &core::Settings {
            server_url: Some(server.to_string()),
        },
    )
    .map_err(|e| e.to_string())?;
    *state.server.lock().unwrap() = Some(server.clone());
    if let Some(window) = app.get_webview_window(MAIN) {
        window.navigate(server).map_err(|e| e.to_string())?;
    }
    Ok(result)
}

/// Forget the remembered address (the connection screen asks again).
#[tauri::command]
fn forget_server(state: tauri::State<'_, State>) -> Result<(), String> {
    *state.server.lock().unwrap() = None;
    core::save_settings(&state.settings_path, &core::Settings::default()).map_err(|e| e.to_string())
}

fn show_connection_screen(app: &AppHandle, change: bool) {
    let state = app.state::<State>();
    let page = state.app_page.lock().unwrap().clone();
    if let (Some(window), Some(mut page)) = (app.get_webview_window(MAIN), page) {
        page.set_query(if change { Some("change=1") } else { None });
        let _ = window.navigate(page);
    }
}

fn download_handler<R: tauri::Runtime>(
    app: AppHandle<R>,
) -> impl Fn(tauri::Webview<R>, DownloadEvent<'_>) -> bool + Send + Sync + 'static {
    move |_webview, event| match event {
        DownloadEvent::Requested { url, destination } => {
            let dir = app.path().download_dir().unwrap_or_else(|_| std::env::temp_dir());
            let suggested = destination
                .file_name()
                .and_then(|n| n.to_str())
                .map(str::to_string)
                .or_else(|| {
                    url.path_segments()
                        .and_then(|mut s| s.next_back())
                        .map(str::to_string)
                })
                .unwrap_or_default();
            *destination = core::download_target(&dir, &suggested);
            true
        }
        DownloadEvent::Finished { path, success, .. } => {
            if let (true, Some(path)) = (success, path) {
                if core::open_after_download(&path) {
                    let _ = app.opener().open_path(path.to_string_lossy(), None::<&str>);
                }
            }
            true
        }
        _ => true,
    }
}

fn navigation_guard(app: AppHandle, state: State) -> impl Fn(&Url) -> bool + Send + 'static {
    move |url| {
        let server = state.server.lock().unwrap().clone();
        match core::navigation(url, server.as_ref()) {
            core::Navigation::Allow => true,
            core::Navigation::OpenExternally => {
                let _ = app.opener().open_url(url.as_str(), None::<&str>);
                false
            }
            core::Navigation::Deny => false,
        }
    }
}

fn build_main_window(app: &AppHandle, state: State) -> tauri::Result<WebviewWindow> {
    let opener = app.clone();
    let new_windows = app.clone();
    let shared = state.clone();
    WebviewWindowBuilder::new(app, MAIN, WebviewUrl::App("index.html".into()))
        .title("HMS")
        .inner_size(1360.0, 860.0)
        .min_inner_size(1024.0, 640.0)
        .on_navigation(navigation_guard(opener, state.clone()))
        .on_download(download_handler(app.clone()))
        .on_new_window(move |url, features| {
            let server = shared.server.lock().unwrap().clone();
            match core::navigation(&url, server.as_ref()) {
                // A document from the hotel server (invoice, receipt...): its
                // own window, sharing the session of the main window.
                core::Navigation::Allow => {
                    let n = shared.windows.fetch_add(1, Ordering::Relaxed);
                    let label = format!("document-{n}");
                    let builder = WebviewWindowBuilder::new(
                        &new_windows,
                        label,
                        WebviewUrl::External("about:blank".parse().unwrap()),
                    )
                    .window_features(features)
                    .title("HMS")
                    .inner_size(960.0, 900.0)
                    .on_navigation(navigation_guard(new_windows.clone(), shared.clone()))
                    .on_download(download_handler(new_windows.clone()))
                    .on_document_title_changed(|window, title| {
                        let _ = window.set_title(&title);
                    });
                    match builder.build() {
                        Ok(window) => NewWindowResponse::Create { window },
                        Err(_) => NewWindowResponse::Deny,
                    }
                }
                core::Navigation::OpenExternally => {
                    let _ = new_windows.opener().open_url(url.as_str(), None::<&str>);
                    NewWindowResponse::Deny
                }
                core::Navigation::Deny => NewWindowResponse::Deny,
            }
        })
        .build()
}

fn build_menu(app: &AppHandle) -> tauri::Result<()> {
    let labels = core::menu_labels(&sys_locale::get_locale().unwrap_or_default());
    let change = MenuItemBuilder::with_id("change_server", labels.change_server).build(app)?;
    let reload = MenuItemBuilder::with_id("reload", labels.reload)
        .accelerator("CmdOrCtrl+R")
        .build(app)?;
    let quit = PredefinedMenuItem::quit(app, Some(labels.quit))?;
    let server = SubmenuBuilder::new(app, labels.server)
        .item(&change)
        .item(&reload)
        .separator()
        .item(&quit)
        .build()?;
    let menu = MenuBuilder::new(app).item(&server).build()?;
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| match event.id().as_ref() {
        "change_server" => show_connection_screen(app, true),
        "reload" => {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.reload();
            }
        }
        _ => {}
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window(MAIN) {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            check_server,
            saved_server,
            connect,
            forget_server
        ])
        .setup(|app| {
            let settings_path = app.path().app_config_dir()?.join("settings.json");
            let state: State = Arc::new(Shared {
                server: Mutex::new(None),
                app_page: Mutex::new(None),
                settings_path,
                windows: AtomicU32::new(1),
            });
            app.manage(state.clone());
            build_menu(app.handle())?;
            let window = build_main_window(app.handle(), state.clone())?;
            *state.app_page.lock().unwrap() = window.url().ok();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the HMS desktop application");
}
