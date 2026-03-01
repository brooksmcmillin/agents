use serde_json::{json, Value};

use crate::util::read_file_string;

struct SysctlCheck {
    key: &'static str,
    expected: &'static str,
    severity: &'static str,
    description: &'static str,
}

const CHECKS: &[SysctlCheck] = &[
    SysctlCheck {
        key: "net.ipv4.ip_forward",
        expected: "0",
        severity: "medium",
        description: "IP forwarding enabled (router mode)",
    },
    SysctlCheck {
        key: "net.ipv4.conf.all.accept_redirects",
        expected: "0",
        severity: "medium",
        description: "ICMP redirects accepted",
    },
    SysctlCheck {
        key: "net.ipv4.conf.all.send_redirects",
        expected: "0",
        severity: "low",
        description: "ICMP redirects sent",
    },
    SysctlCheck {
        key: "net.ipv4.conf.all.accept_source_route",
        expected: "0",
        severity: "medium",
        description: "Source routing accepted",
    },
    SysctlCheck {
        key: "net.ipv4.conf.all.log_martians",
        expected: "1",
        severity: "low",
        description: "Martian packets not logged",
    },
    SysctlCheck {
        key: "net.ipv4.tcp_syncookies",
        expected: "1",
        severity: "medium",
        description: "SYN cookies disabled (vulnerable to SYN flood)",
    },
    SysctlCheck {
        key: "kernel.randomize_va_space",
        expected: "2",
        severity: "high",
        description: "ASLR not fully enabled",
    },
    SysctlCheck {
        key: "kernel.dmesg_restrict",
        expected: "1",
        severity: "low",
        description: "Kernel logs readable by unprivileged users",
    },
    SysctlCheck {
        key: "fs.suid_dumpable",
        expected: "0",
        severity: "medium",
        description: "SUID programs may dump core (info leak)",
    },
];

pub fn run() -> Value {
    let mut findings = Vec::new();

    for check in CHECKS {
        let proc_path = format!("/proc/sys/{}", check.key.replace('.', "/"));
        if let Some(value) = read_file_string(&proc_path) {
            let value = value.trim();
            if value != check.expected {
                findings.push(json!({
                    "parameter": check.key,
                    "current_value": value,
                    "expected_value": check.expected,
                    "severity": check.severity,
                    "description": check.description,
                }));
            }
        }
    }

    let count = findings.len();
    json!({
        "checked_parameters": CHECKS.len(),
        "findings": findings,
        "findings_count": count,
    })
}
