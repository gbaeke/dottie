//! The desktop shell: one window onto a Dottie server, and a tray icon. The server's own web app does the rest
//! (sign-in, chat, the sleeping and awake dotties), so there is little to keep in step here. DOTTIE_URL picks the server.
//!
//! bridge.js runs inside the page: it remembers the last dottie, reports their states to `set_status` and asks `notify`
//! to announce what a dottie writes to you.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    AppHandle, Manager, State, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};

const DEFAULT_URL: &str = "http://localhost:8370";
const ASLEEP: &[u8] = include_bytes!("../icons/tray-asleep.png");
const AWAKE: &[u8] = include_bytes!("../icons/tray-awake.png");

/// The tray menu's first line, which says what the dotties are doing (tooltips do not exist on every desktop).
struct StatusLine(MenuItem<tauri::Wry>);
static SHOWING_AWAKE: AtomicBool = AtomicBool::new(false);

#[tauri::command]
fn set_status(app: AppHandle, status: State<StatusLine>, working: Vec<String>, unread: u32) {
    let awake = !working.is_empty();
    let mut text = if awake {
        format!("{} working", working.join(", "))
    } else {
        "All asleep".to_string()
    };
    if unread > 0 {
        text += &format!(" · {unread} unread");
    }
    let _ = status.0.set_text(&text);
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_tooltip(Some(&text));
        if SHOWING_AWAKE.swap(awake, Ordering::Relaxed) != awake {
            let icon = if awake { AWAKE } else { ASLEEP };
            let _ = tray.set_icon(Image::from_bytes(icon).ok());
        }
    }
}

/// A desktop notification, unless you are already looking at the window. Clicking it shows the window on `path`.
#[tauri::command]
fn notify(app: AppHandle, title: String, body: String, path: String) {
    let watching = app
        .get_webview_window("main")
        .is_some_and(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false));
    if !watching {
        announce(app, title, body, path);
    }
}

#[cfg(target_os = "linux")]
fn announce(app: AppHandle, title: String, body: String, path: String) {
    std::thread::spawn(move || {
        let shown = notify_rust::Notification::new()
            .appname("dottie-desktop")
            .summary(&title)
            .body(&body)
            .action("default", "Open")
            .show();
        if let Ok(handle) = shown {
            handle.wait_for_action(|action| {
                if action == "default" {
                    open_chat(&app, &path);
                }
            });
        }
    });
}

/// Elsewhere the plugin shows it; a click on it does nothing yet.
#[cfg(not(target_os = "linux"))]
fn announce(app: AppHandle, title: String, body: String, _path: String) {
    use tauri_plugin_notification::NotificationExt;
    let _ = app.notification().builder().title(title).body(body).show();
}

#[cfg(target_os = "linux")]
fn open_chat(app: &AppHandle, path: &str) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
    // the path is built from ids by bridge.js; refuse anything else before it reaches the page
    if path.starts_with("/dotties/")
        && path
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "/-_".contains(c))
    {
        let _ = window.eval(format!("window.location.assign('{path}')"));
    }
}

fn show_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
}

fn toggle_window(app: &AppHandle) {
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    // by visibility alone: using the tray menu takes the focus from the window, and Wayland will not give it back
    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
    } else {
        show_window(app);
    }
}

pub fn run() {
    tauri::Builder::default()
        // first, so a second launch only asks the running copy to show itself (and exits): no second tray icon
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_window(app)
        }))
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![set_status, notify])
        .setup(|app| {
            let url = std::env::var("DOTTIE_URL").unwrap_or_else(|_| DEFAULT_URL.into());
            let url: tauri::Url = url.parse()?;
            let bridge = include_str!("bridge.js")
                .replace("__ORIGIN__", &url.origin().ascii_serialization());
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("Dottie")
                .inner_size(1100.0, 760.0)
                .initialization_script(bridge)
                .build()?;
            // closing the window hides it: the dotties keep running and the tray stays
            let hidden = window.clone();
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = hidden.hide();
                }
            });

            let status = MenuItem::with_id(app, "status", "Connecting…", false, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show / hide Dottie", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&status, &show, &quit])?;
            app.manage(StatusLine(status));
            TrayIconBuilder::with_id("main")
                .icon(Image::from_bytes(ASLEEP)?)
                .tooltip("Dottie")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => toggle_window(app),
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
                        toggle_window(tray.app_handle());
                    }
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Dottie");
}
