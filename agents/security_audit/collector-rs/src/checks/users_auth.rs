use serde_json::{json, Value};
use std::fs;

use crate::util::read_file_string;

pub fn run() -> Value {
    let mut findings = Vec::new();

    // Check /etc/passwd for UID 0 non-root users and shell checks
    if let Some(passwd) = read_file_string("/etc/passwd") {
        for line in passwd.lines() {
            let fields: Vec<&str> = line.split(':').collect();
            if fields.len() < 7 {
                continue;
            }
            let user = fields[0];
            let uid: u32 = match fields[2].parse() {
                Ok(u) => u,
                Err(_) => continue,
            };
            let passwd_field = fields[1];

            if uid == 0 && user != "root" {
                findings.push(json!({
                    "issue": "non_root_uid_zero",
                    "user": user,
                    "severity": "critical",
                    "detail": format!("User '{}' has UID 0 (root equivalent)", user),
                }));
            }

            // Empty password field in /etc/passwd
            if passwd_field.is_empty() || passwd_field == " " {
                findings.push(json!({
                    "issue": "empty_password",
                    "user": user,
                    "severity": "critical",
                    "detail": format!("User '{}' has no password set", user),
                }));
            }
        }
    }

    // Check /etc/shadow for weak password hashes
    if let Some(shadow) = read_file_string("/etc/shadow") {
        for line in shadow.lines() {
            let fields: Vec<&str> = line.split(':').collect();
            if fields.len() < 2 {
                continue;
            }
            let user = fields[0];
            let hash = fields[1];

            // Skip locked/no-login accounts
            if hash.is_empty() || hash == "!!" || hash == "*" || hash.starts_with('!') {
                continue;
            }

            // Valid hashes start with $ (e.g., $6$, $y$, $2b$)
            if !hash.starts_with('$') {
                findings.push(json!({
                    "issue": "weak_password_hash",
                    "user": user,
                    "severity": "high",
                    "detail": format!("User '{}' has a non-standard password hash format", user),
                }));
            }
        }
    }

    // Check sudoers for NOPASSWD rules
    check_sudoers("/etc/sudoers", &mut findings);

    // Check /etc/sudoers.d/
    if let Ok(entries) = fs::read_dir("/etc/sudoers.d") {
        for entry in entries.flatten() {
            let path = entry.path();
            if let Some(path_str) = path.to_str() {
                check_sudoers(path_str, &mut findings);
            }
        }
    }

    let count = findings.len();
    json!({
        "findings": findings,
        "findings_count": count,
    })
}

fn check_sudoers(path: &str, findings: &mut Vec<Value>) {
    let content = match read_file_string(path) {
        Some(c) => c,
        None => return,
    };

    for line in content.lines() {
        let line = line.trim();
        if !line.is_empty() && !line.starts_with('#') && line.contains("NOPASSWD") {
            let truncated: String = line.chars().take(120).collect();
            findings.push(json!({
                "issue": "sudo_nopasswd",
                "severity": "medium",
                "detail": format!("NOPASSWD sudo rule in {}: {}", path, truncated),
            }));
        }
    }
}
