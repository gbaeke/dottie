fn main() {
    // the page is remote, so its commands must be allowed by name (capabilities/default.json)
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["set_status", "notify"])),
    )
    .expect("failed to run tauri-build");
}
