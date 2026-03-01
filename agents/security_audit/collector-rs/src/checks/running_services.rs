use serde_json::{json, Value};

use crate::util::run_cmd;

/// Services that are often unnecessary on servers.
const UNNECESSARY_SERVICES: &[(&str, &str)] = &[
    (
        "cups.service",
        "Print server (usually unnecessary on servers)",
    ),
    (
        "avahi-daemon.service",
        "mDNS/DNS-SD service discovery (attack surface on servers)",
    ),
    (
        "bluetooth.service",
        "Bluetooth (usually unnecessary on servers)",
    ),
    (
        "ModemManager.service",
        "Modem manager (usually unnecessary on servers)",
    ),
];

pub fn run() -> Value {
    let output = run_cmd(
        "systemctl",
        &[
            "list-units",
            "--type=service",
            "--state=running",
            "--no-pager",
            "--no-legend",
        ],
    );

    if output.is_empty() {
        return json!({
            "available": false,
            "reason": "systemctl not available",
        });
    }

    let mut services = Vec::new();
    let mut alerts = Vec::new();

    for line in output.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.is_empty() || !parts[0].ends_with(".service") {
            continue;
        }

        let name = parts[0];
        let state = if parts.len() > 2 { parts[2] } else { "" };
        let description = if parts.len() > 3 {
            parts[3..].join(" ")
        } else {
            String::new()
        };

        services.push(json!({
            "name": name,
            "state": state,
            "description": description,
        }));

        for &(svc, reason) in UNNECESSARY_SERVICES {
            if name == svc {
                alerts.push(format!("{}: {}", svc, reason));
            }
        }
    }

    let total = services.len();
    json!({
        "services": services,
        "total_running": total,
        "alerts": alerts,
    })
}
