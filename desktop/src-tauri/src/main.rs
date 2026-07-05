// Layla desktop shell (BL-154) — a native window around the local Layla UI.
//
// The window loads http://127.0.0.1:8000/ui (see tauri.conf.json). Layla's Python
// server must be running; `start_layla_server` can spawn it if LAYLA_AUTOSTART=1 and
// LAYLA_DIR points at the agent checkout — otherwise the user starts it themselves.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::Command;

fn start_layla_server() {
    if std::env::var("LAYLA_AUTOSTART").ok().as_deref() != Some("1") {
        return;
    }
    let dir = match std::env::var("LAYLA_DIR") {
        Ok(d) => d,
        Err(_) => return,
    };
    // Best-effort: launch uvicorn; ignore failures (the window still loads once up).
    let _ = Command::new("python")
        .args([
            "-m", "uvicorn", "main:app",
            "--app-dir", "agent",
            "--host", "127.0.0.1", "--port", "8000",
        ])
        .current_dir(dir)
        .spawn();
}

fn main() {
    start_layla_server();
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the Layla desktop shell");
}
