use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenSet {
    pub access_token: String,
    pub refresh_token: Option<String>,
    pub expires_in: Option<u64>,
    pub client_id: Option<String>,
    pub client_secret: Option<String>,
    pub issued_at: u64,
    pub token_endpoint: String,
}

impl TokenSet {
    /// Check if the token is expired (with a 60-second buffer).
    pub fn is_expired(&self) -> bool {
        let Some(expires_in) = self.expires_in else {
            return false;
        };
        let now = chrono::Utc::now().timestamp() as u64;
        self.issued_at + expires_in < now + 60
    }
}

/// Load a token set from disk.
pub fn load(path: &Path) -> Option<TokenSet> {
    let data = fs::read_to_string(path).ok()?;
    serde_json::from_str(&data).ok()
}

/// Save a token set to disk atomically with 0o600 permissions.
pub fn save(path: &Path, token_set: &TokenSet) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create token directory: {e}"))?;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))
            .map_err(|e| format!("Failed to set directory permissions: {e}"))?;
    }

    let json = serde_json::to_string_pretty(token_set)
        .map_err(|e| format!("Failed to serialize token: {e}"))?;

    // Write to temp file with 0o600 from creation, then atomically rename
    let tmp = path.with_extension("json.tmp");
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .mode(0o600)
        .open(&tmp)
        .map_err(|e| format!("Failed to create temp token file: {e}"))?;

    file.write_all(json.as_bytes())
        .map_err(|e| format!("Failed to write temp token file: {e}"))?;

    fs::rename(&tmp, path).map_err(|e| format!("Failed to rename token file: {e}"))?;

    Ok(())
}
