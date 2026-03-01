use serde_json::{json, Value};
use std::fs;

use crate::util::read_file_string;

pub fn run() -> Value {
    let mut findings = Vec::new();

    // System crontab
    if let Some(content) = read_file_string("/etc/crontab") {
        for line in content.lines() {
            let line = line.trim();
            if !line.is_empty() && !line.starts_with('#') {
                if line.contains("curl ") || line.contains("wget ") {
                    let truncated: String = line.chars().take(200).collect();
                    findings.push(json!({
                        "source": "/etc/crontab",
                        "line": truncated,
                        "severity": "high",
                        "issue": "Cron job fetches remote content",
                    }));
                }
            }
        }
    }

    // Check cron directories
    for cron_dir in &["/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly"] {
        if let Ok(entries) = fs::read_dir(cron_dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if let Some(content) = read_file_string(path.to_str().unwrap_or_default()) {
                    if content.contains("curl ") || content.contains("wget ") {
                        findings.push(json!({
                            "source": path.to_str().unwrap_or_default(),
                            "severity": "medium",
                            "issue": format!("Cron script in {} fetches remote content", cron_dir),
                        }));
                    }
                }
            }
        }
    }

    let count = findings.len();
    json!({
        "findings": findings,
        "findings_count": count,
    })
}
