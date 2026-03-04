use serde::{Deserialize, Serialize};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

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
pub fn load(path: &PathBuf) -> Option<TokenSet> {
    let data = fs::read_to_string(path).ok()?;
    serde_json::from_str(&data).ok()
}

/// Save a token set to disk with 0o600 permissions.
pub fn save(path: &PathBuf, token_set: &TokenSet) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create token directory: {e}"))?;
        // Set directory to 0o700
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))
            .map_err(|e| format!("Failed to set directory permissions: {e}"))?;
    }

    let json = serde_json::to_string_pretty(token_set)
        .map_err(|e| format!("Failed to serialize token: {e}"))?;

    fs::write(path, &json).map_err(|e| format!("Failed to write token file: {e}"))?;

    fs::set_permissions(path, fs::Permissions::from_mode(0o600))
        .map_err(|e| format!("Failed to set token file permissions: {e}"))?;

    Ok(())
}
