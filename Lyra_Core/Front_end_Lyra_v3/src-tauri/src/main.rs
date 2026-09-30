// main.rs — lado nativo da casca Tauri "só assistente" (LYRA_NUCLEO.md
// §5.6). Implementa o contrato de `shell.ts` do frontend: get_secret,
// set_setting, start_backend, open_ide.
//
// NÃO COMPILADO/TESTADO — toolchain Rust (cargo/rustc) não está instalado
// na máquina onde isso foi escrito (ver LYRA_NUCLEO.md §5.8, veto de
// download grande sem confirmação). Código escrito seguindo a API pública
// conhecida do Tauri v2; precisa de `cargo check` real antes de confiar
// nele — trate como rascunho revisável, não como testado.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use tauri::{AppHandle, Manager};

// ponytail: settings/segredos guardados num JSON simples no diretório de
// config do app — sem criptografia, sem keytar/Credential Manager do SO.
// Upgrade path: trocar por crate `keyring` quando uma API key de verdade
// precisar sair do texto puro em disco. Hoje já é menos exposto que ficar
// hardcoded no frontend (que é o problema que isso resolve, ver Jan seção
// 3.4 do plano).

fn store_path(app: &AppHandle) -> PathBuf {
    let dir = app.path().app_config_dir().expect("app config dir indisponível");
    fs::create_dir_all(&dir).ok();
    dir.join("settings.json")
}

fn load_store(app: &AppHandle) -> HashMap<String, Value> {
    fs::read_to_string(store_path(app))
        .ok()
        .and_then(|texto| serde_json::from_str(&texto).ok())
        .unwrap_or_default()
}

fn save_store(app: &AppHandle, dados: &HashMap<String, Value>) {
    if let Ok(texto) = serde_json::to_string_pretty(dados) {
        let _ = fs::write(store_path(app), texto);
    }
}

#[tauri::command]
fn get_secret(app: AppHandle, id: String) -> Option<String> {
    // Segredos de provedor de nuvem (Groq/Gemini/Claude) hoje vivem no .env
    // do backend Python, não aqui — este comando é pro caso do app desktop
    // precisar guardar algo do lado do cliente (ex: token de pareamento,
    // seção 3.5/8 do plano). Prefixo "secret:" separa do resto das settings.
    let dados = load_store(&app);
    dados
        .get(&format!("secret:{id}"))
        .and_then(|v| v.as_str().map(String::from))
}

#[tauri::command]
fn set_setting(app: AppHandle, key: String, value: Value) {
    let mut dados = load_store(&app);
    dados.insert(key, value);
    save_store(&app, &dados);
}

#[tauri::command]
fn start_backend() -> Result<(), String> {
    // ponytail: assume que cerebro_maestro.py já está rodando (mesma
    // premissa da BrowserShell hoje). Upgrade: spawnar o processo Python
    // com std::process::Command se o usuário quiser start automático do
    // backend junto com o app — decisão de produto, não decidida ainda.
    Ok(())
}

#[tauri::command]
fn open_ide() -> Result<(), String> {
    // ponytail: tenta abrir a IDE Theia como processo externo via launcher
    // padrão do Windows. Caminho do executável do Lyra_IDE ainda não está
    // definido (a IDE ainda não tem instalador/launcher próprio) — placeholder
    // até isso existir.
    #[cfg(target_os = "windows")]
    {
        std::process::Command::new("cmd")
            .args(["/C", "start", "", "lyra-ide.exe"])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_secret,
            set_setting,
            start_backend,
            open_ide
        ])
        .run(tauri::generate_context!())
        .expect("erro ao rodar a aplicacao Tauri");
}
