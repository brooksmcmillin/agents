use serde_json::{json, Value};
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

/// Files and their maximum acceptable permissions.
const SENSITIVE_PATHS: &[(&str, u32, &str)] = &[
    ("/etc/shadow", 0o640, "Password hashes"),
    ("/etc/gshadow", 0o640, "Group password hashes"),
    ("/etc/passwd", 0o644, "User database"),
    ("/etc/ssh/sshd_config", 0o600, "SSH server config"),
    (
        "/root/.ssh/authorized_keys",
        0o600,
        "Root SSH authorized keys",
    ),
];

pub fn run() -> Value {
    let mut findings = Vec::new();
    let mut checked = 0usize;

    // Check known sensitive paths
    for &(path, _expected, description) in SENSITIVE_PATHS {
        check_path(path, description, &mut findings);
        checked += 1;
    }

    // Scan home directories for .env files
    if let Ok(entries) = fs::read_dir("/home") {
        for entry in entries.flatten() {
            let home = entry.path();
            for env_name in &[".env", ".env.local", ".env.production"] {
                let p = home.join(env_name);
                if p.exists() {
                    check_path(
                        p.to_str().unwrap_or_default(),
                        "Environment file with potential secrets",
                        &mut findings,
                    );
                    checked += 1;
                }
            }
        }
    }

    // Also check /root for .env files
    for env_name in &[".env", ".env.local", ".env.production"] {
        let p = Path::new("/root").join(env_name);
        if p.exists() {
            check_path(
                p.to_str().unwrap_or_default(),
                "Environment file with potential secrets",
                &mut findings,
            );
            checked += 1;
        }
    }

    let count = findings.len();
    json!({
        "checked_paths": checked,
        "findings": findings,
        "findings_count": count,
    })
}

fn check_path(path: &str, description: &str, findings: &mut Vec<Value>) {
    let meta = match fs::metadata(path) {
        Ok(m) => m,
        Err(_) => return,
    };

    let mode = meta.mode() & 0o777;
    let world_readable = mode & 0o004 != 0;
    let world_writable = mode & 0o002 != 0;
    let group_writable = mode & 0o020 != 0;

    let mut issues = Vec::new();
    if world_readable {
        issues.push("world-readable");
    }
    if world_writable {
        issues.push("world-writable");
    }
    if group_writable && (path == "/etc/shadow" || path == "/etc/gshadow") {
        issues.push("group-writable");
    }

    if !issues.is_empty() {
        let severity = if world_writable { "critical" } else { "high" };
        findings.push(json!({
            "path": path,
            "description": description,
            "current_mode": format!("0o{:o}", mode),
            "issues": issues,
            "severity": severity,
        }));
    }
}
