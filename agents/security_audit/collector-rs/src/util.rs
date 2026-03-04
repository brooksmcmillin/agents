use std::fs;
use std::process::Command;

/// Run a command and return its stdout, or an empty string on failure.
pub fn run_cmd(program: &str, args: &[&str]) -> String {
    Command::new(program)
        .args(args)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).into_owned())
        .unwrap_or_default()
}

/// Read a file to string, returning None on any error.
pub fn read_file_string(path: &str) -> Option<String> {
    fs::read_to_string(path).ok()
}

/// Sanitize a hostname for use in a filename.
///
/// Replaces any character that is not alphanumeric, `-`, or `.` with `_` to
/// prevent path traversal when the hostname is embedded in an output filename.
fn sanitize_hostname(raw: &str) -> String {
    raw.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '.' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

/// Get the system hostname, sanitized for safe use in filenames.
pub fn hostname() -> String {
    let raw = read_file_string("/etc/hostname")
        .map(|s| s.trim().to_string())
        .or_else(|| {
            let out = run_cmd("hostname", &[]);
            if out.is_empty() {
                None
            } else {
                Some(out.trim().to_string())
            }
        })
        .unwrap_or_else(|| "unknown".to_string());
    sanitize_hostname(&raw)
}
