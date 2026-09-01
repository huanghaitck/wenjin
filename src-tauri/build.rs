fn main() {
    let build_id = std::env::var("WENJIN_BUILD_ID").ok().filter(|value| !value.trim().is_empty()).unwrap_or_else(|| {
        std::process::Command::new("git").args(["rev-parse", "--short=12", "HEAD"]).output().ok()
            .filter(|output| output.status.success())
            .map(|output| String::from_utf8_lossy(&output.stdout).trim().to_owned())
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "source-unknown".to_owned())
    });
    println!("cargo:rustc-env=WENJIN_BUILD_ID={build_id}");
    tauri_build::build()
}
