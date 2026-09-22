use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Fenêtre sombre et sans chrome : le HUD dessine son propre cadre.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_title("J.A.R.V.I.S.");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("erreur au démarrage du HUD");
}
