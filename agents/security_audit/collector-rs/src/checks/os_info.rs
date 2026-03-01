use serde_json::{json, Value};

use crate::util::{hostname, read_file_string, run_cmd};

pub fn run() -> Value {
    let uname = run_cmd("uname", &["-a"]);
    let release = run_cmd("uname", &["-r"]);
    let machine = run_cmd("uname", &["-m"]);
    let os_release = read_file_string("/etc/os-release").unwrap_or_default();

    let pretty_name = os_release
        .lines()
        .find(|l| l.starts_with("PRETTY_NAME="))
        .map(|l| l.trim_start_matches("PRETTY_NAME=").trim_matches('"'))
        .unwrap_or("Unknown")
        .to_string();

    let uptime_str = read_file_string("/proc/uptime").unwrap_or_default();
    let uptime_seconds: Option<f64> = uptime_str
        .split_whitespace()
        .next()
        .and_then(|s| s.parse().ok());

    json!({
        "hostname": hostname(),
        "os": pretty_name,
        "kernel": release.trim(),
        "arch": machine.trim(),
        "uname": uname.trim(),
        "uptime_seconds": uptime_seconds,
        "uptime_days": uptime_seconds.map(|s| (s / 86400.0 * 10.0).round() / 10.0),
    })
}
