// Le HUD est volontairement une coquille : toute la logique vit dans le noyau
// Python, et cette fenêtre ne fait que l'afficher. Un binaire natif d'environ
// 10 Mo, sans runtime embarqué, contre ~200 Mo pour l'équivalent Electron.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    jarvis_hud_lib::run()
}
