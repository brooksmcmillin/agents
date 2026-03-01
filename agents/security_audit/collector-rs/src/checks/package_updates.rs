use serde_json::{json, Value};

use crate::util::run_cmd;

pub fn run() -> Value {
    // Try apt (Debian/Ubuntu)
    let apt_out = run_cmd("apt", &["list", "--upgradable"]);
    if !apt_out.is_empty() {
        let lines: Vec<&str> = apt_out.lines().filter(|l| l.contains('/')).collect();
        let security_count = lines
            .iter()
            .filter(|l| l.to_lowercase().contains("security"))
            .count();
        let sample: Vec<&str> = lines.iter().take(20).copied().collect();

        return json!({
            "package_manager": "apt",
            "total_upgradable": lines.len(),
            "security_updates": security_count,
            "sample_updates": sample,
        });
    }

    // Try dnf/yum (RHEL/Fedora)
    for pm in &["dnf", "yum"] {
        let out = run_cmd(pm, &["check-update", "--security"]);
        if !out.is_empty() {
            let lines: Vec<&str> = out
                .lines()
                .filter(|l| !l.is_empty() && !l.starts_with("Last"))
                .collect();
            let sample: Vec<&str> = lines.iter().take(20).copied().collect();

            return json!({
                "package_manager": pm,
                "security_updates": lines.len(),
                "sample_updates": sample,
            });
        }
    }

    json!({
        "package_manager": "unknown",
        "reason": "No supported package manager found",
    })
}
