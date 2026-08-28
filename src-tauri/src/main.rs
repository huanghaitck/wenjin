#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    fs::{self, OpenOptions},
    io::Write,
    net::{TcpListener, TcpStream},
    path::{Path, PathBuf},
    sync::Mutex,
    time::Duration,
};
use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

struct SidecarState(Mutex<Option<CommandChild>>);
struct StartupState(Mutex<Option<String>>);

fn data_root(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("WENJIN_DATA_ROOT") {
        return Ok(PathBuf::from(path));
    }
    app.path().app_data_dir().map_err(|error| error.to_string())
}

#[tauri::command]
fn desktop_status() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn desktop_url(state: tauri::State<'_, StartupState>) -> Option<String> {
    state.0.lock().ok().and_then(|value| value.clone())
}

#[tauri::command]
fn open_data_directory(app: tauri::AppHandle) -> Result<(), String> {
    let path = data_root(&app)?;
    fs::create_dir_all(&path).map_err(|error| error.to_string())?;
    std::process::Command::new("explorer.exe")
        .arg(&path)
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn open_sidecar_log(app: tauri::AppHandle) -> Result<(), String> {
    let path = data_root(&app)?.join("logs").join("sidecar.log");
    if !path.is_file() {
        return Err("启动日志尚未生成".into());
    }
    std::process::Command::new("notepad.exe")
        .arg(&path)
        .spawn()
        .map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn choose_folder() -> Option<String> {
    rfd::FileDialog::new()
        .pick_folder()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn choose_file(kind: String) -> Option<String> {
    let mut dialog = rfd::FileDialog::new();
    dialog = match kind.as_str() {
        "pdf" => dialog.add_filter("PDF 文献", &["pdf"]),
        "docx" => dialog.add_filter("Microsoft Word 稿件", &["docx"]),
        "data" => dialog.add_filter(
            "本地数据库与数据文件",
            &["sqlite", "sqlite3", "db", "duckdb", "csv", "tsv", "json", "jsonl", "parquet", "geojson"],
        ),
        "plugin" => dialog.add_filter("问津领域包", &["zip"]),
        _ => return None,
    };
    dialog
        .pick_file()
        .map(|path| path.to_string_lossy().into_owned())
}

#[tauri::command]
fn open_in_word(path: String) -> Result<(), String> {
    let selected = Path::new(&path);
    if !selected.is_file()
        || selected
            .extension()
            .and_then(|value| value.to_str())
            .map(|value| value.eq_ignore_ascii_case("docx"))
            != Some(true)
    {
        return Err("只能把已经存在的 DOCX 交给 Microsoft Word".into());
    }
    let operation: Vec<u16> = "open\0".encode_utf16().collect();
    let executable: Vec<u16> = "WINWORD.EXE\0".encode_utf16().collect();
    let parameters: Vec<u16> = format!("\"{}\"\0", selected.display())
        .encode_utf16()
        .collect();
    let result = unsafe {
        windows_sys::Win32::UI::Shell::ShellExecuteW(
            std::ptr::null_mut(),
            operation.as_ptr(),
            executable.as_ptr(),
            parameters.as_ptr(),
            std::ptr::null(),
            windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL,
        )
    };
    if result as isize <= 32 {
        return Err("没有找到可用的 Microsoft Word；请确认桌面版 Word 已安装".into());
    }
    Ok(())
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    let selected = Path::new(&path);
    if !selected.exists() {
        return Err("文件或目录已经不存在".into());
    }
    if selected.is_dir() {
        std::process::Command::new("explorer.exe")
            .arg(selected)
            .spawn()
            .map_err(|error| error.to_string())?;
        return Ok(());
    }
    let operation: Vec<u16> = "open\0".encode_utf16().collect();
    let target: Vec<u16> = format!("{}\0", selected.display()).encode_utf16().collect();
    let result = unsafe {
        windows_sys::Win32::UI::Shell::ShellExecuteW(
            std::ptr::null_mut(), operation.as_ptr(), target.as_ptr(),
            std::ptr::null(), std::ptr::null(),
            windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL,
        )
    };
    if result as isize <= 32 {
        return Err("系统没有找到可打开该产物的应用".into());
    }
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![desktop_status, desktop_url, open_data_directory, open_sidecar_log, choose_folder, choose_file, open_in_word, open_path])
        .setup(|app| {
            app.manage(StartupState(Mutex::new(None)));
            let data_root = data_root(app.handle()).map_err(std::io::Error::other)?;
            fs::create_dir_all(data_root.join("logs"))?;
            let listener = TcpListener::bind("127.0.0.1:0")?;
            let port = listener.local_addr()?.port();
            drop(listener);
            let (mut receiver, child) = app.shell().sidecar("hrw-sidecar")?
                .args([
                    "desktop-serve", "--data-root", &data_root.to_string_lossy(),
                    "--host", "127.0.0.1", "--port", &port.to_string(),
                    "--desktop-build", env!("CARGO_PKG_VERSION"),
                ])
                .env("PYTHONUNBUFFERED", "1")
                .spawn()?;
            app.manage(SidecarState(Mutex::new(Some(child))));
            let log_path = data_root.join("logs").join("sidecar.log");
            if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&log_path) {
                let _ = writeln!(file, "\n=== Wenjin {} startup ===", env!("CARGO_PKG_VERSION"));
            }
            tauri::async_runtime::spawn(async move {
                while let Some(event) = receiver.recv().await {
                    let line = match event {
                        CommandEvent::Stdout(bytes) => Some(String::from_utf8_lossy(&bytes).into_owned()),
                        CommandEvent::Stderr(bytes) => Some(String::from_utf8_lossy(&bytes).into_owned()),
                        CommandEvent::Terminated(payload) => Some(format!("sidecar terminated: {:?}", payload)),
                        _ => None,
                    };
                    if let Some(line) = line {
                        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&log_path) {
                            let _ = writeln!(file, "{}", line.trim_end());
                        }
                    }
                }
            });

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ready = (0..600).any(|_| {
                    if TcpStream::connect_timeout(&format!("127.0.0.1:{port}").parse().unwrap(), Duration::from_millis(100)).is_ok() {
                        true
                    } else {
                        std::thread::sleep(Duration::from_millis(100));
                        false
                    }
                });
                if !ready {
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.eval("document.getElementById('status').textContent='本地研究服务没有在一分钟内启动。请查看应用数据目录中的 logs/sidecar.log。';document.querySelector('.bar').style.display='none';");
                    }
                } else if let Some(state) = handle.try_state::<StartupState>() {
                    if let Ok(mut startup_url) = state.0.lock() {
                        *startup_url = Some(format!("http://127.0.0.1:{port}/"));
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build Wenjin Research Workbench");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = handle.try_state::<SidecarState>() {
                if let Ok(mut child) = state.0.lock() {
                    if let Some(process) = child.take() {
                        let _ = std::process::Command::new("taskkill")
                            .args(["/PID", &process.pid().to_string(), "/T", "/F"])
                            .output();
                    }
                }
            }
        }
    });
}
