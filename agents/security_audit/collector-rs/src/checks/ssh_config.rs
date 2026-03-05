use serde_json::{json, Value};

use crate::util::read_file_string;

struct SshCheck {
    name: &'static str,
    key: &'static str,
    bad_values: &'static [&'static str],
    max_int_value: Option<u32>,
    severity: &'static str,
    recommendation: &'static str,
}

const CHECKS: &[SshCheck] = &[
    SshCheck {
        name: "PermitRootLogin",
        key: "permitrootlogin",
        bad_values: &["yes"],
        max_int_value: None,
        severity: "critical",
        recommendation: "Set PermitRootLogin to 'no' or 'prohibit-password'",
    },
    SshCheck {
        name: "PasswordAuthentication",
        key: "passwordauthentication",
        bad_values: &["yes"],
        max_int_value: None,
        severity: "high",
        recommendation: "Set PasswordAuthentication to 'no' and use key-based auth",
    },
    SshCheck {
        name: "PermitEmptyPasswords",
        key: "permitemptypasswords",
        bad_values: &["yes"],
        max_int_value: None,
        severity: "critical",
        recommendation: "Set PermitEmptyPasswords to 'no'",
    },
    SshCheck {
        name: "X11Forwarding",
        key: "x11forwarding",
        bad_values: &["yes"],
        max_int_value: None,
        severity: "low",
        recommendation: "Set X11Forwarding to 'no' unless required",
    },
    SshCheck {
        name: "MaxAuthTries",
        key: "maxauthtries",
        bad_values: &[],
        max_int_value: Some(6),
        severity: "medium",
        recommendation: "Set MaxAuthTries to 3-6",
    },
    SshCheck {
        name: "Protocol",
        key: "protocol",
        bad_values: &["1", "1,2"],
        max_int_value: None,
        severity: "critical",
        recommendation: "Set Protocol to '2'",
    },
];

pub fn run() -> Value {
    let content = match read_file_string("/etc/ssh/sshd_config") {
        Some(c) => c,
        None => {
            return json!({
                "available": false,
                "reason": "sshd_config not found or not readable",
            });
        }
    };

    let mut findings = Vec::new();

    // Parse sshd_config into a map of lowercase key -> original value
    let mut config: Vec<(String, String)> = Vec::new();
    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut parts = line.splitn(2, |c: char| c.is_whitespace());
        if let (Some(key), Some(val)) = (parts.next(), parts.next()) {
            config.push((key.to_lowercase(), val.trim().to_string()));
        }
    }

    for check in CHECKS {
        if let Some((_, value)) = config.iter().find(|(k, _)| k == check.key) {
            let lower_val = value.to_lowercase();
            let is_bad = if !check.bad_values.is_empty() {
                check.bad_values.contains(&lower_val.as_str())
            } else if let Some(max_val) = check.max_int_value {
                lower_val.parse::<u32>().is_ok_and(|v| v > max_val)
            } else {
                false
            };

            if is_bad {
                findings.push(json!({
                    "setting": check.name,
                    "current_value": value,
                    "severity": check.severity,
                    "recommendation": check.recommendation,
                }));
            }
        }
    }

    let count = findings.len();
    json!({
        "available": true,
        "config_path": "/etc/ssh/sshd_config",
        "findings": findings,
        "findings_count": count,
    })
}
