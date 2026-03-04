//! Security audit collector — zero-dependency static binary for Linux.
//!
//! Runs a battery of system security checks and writes a structured JSON
//! report.  Designed to be `scp`'d to any Linux host and run without a
//! runtime.
//!
//! Usage:
//!     ./security-audit-collector                          # all checks
//!     ./security-audit-collector --checks os_info,ssh_config
//!     ./security-audit-collector --output-dir /tmp/audits
//!     ./security-audit-collector --upload-url http://host:8080/api/security-audits

mod checks;
mod util;

use serde_json::{json, Map, Value};
use std::env;
use std::fs;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::os::unix::fs as unix_fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

// ---------------------------------------------------------------------------
// Check registry
// ---------------------------------------------------------------------------

type CheckFn = fn() -> Value;

struct CheckEntry {
    func: CheckFn,
    description: &'static str,
}

fn all_checks() -> Vec<(&'static str, CheckEntry)> {
    vec![
        (
            "os_info",
            CheckEntry {
                func: checks::os_info::run,
                description: "Basic OS and host information",
            },
        ),
        (
            "open_ports",
            CheckEntry {
                func: checks::open_ports::run,
                description: "Listening TCP/UDP ports",
            },
        ),
        (
            "ssh_config",
            CheckEntry {
                func: checks::ssh_config::run,
                description: "SSH server configuration audit",
            },
        ),
        (
            "file_permissions",
            CheckEntry {
                func: checks::file_permissions::run,
                description: "Sensitive file permissions",
            },
        ),
        (
            "firewall",
            CheckEntry {
                func: checks::firewall::run,
                description: "Firewall status and rules",
            },
        ),
        (
            "users_auth",
            CheckEntry {
                func: checks::users_auth::run,
                description: "User accounts and authentication",
            },
        ),
        (
            "running_services",
            CheckEntry {
                func: checks::running_services::run,
                description: "Running services",
            },
        ),
        (
            "package_updates",
            CheckEntry {
                func: checks::package_updates::run,
                description: "Available security updates",
            },
        ),
        (
            "kernel_security",
            CheckEntry {
                func: checks::kernel_security::run,
                description: "Kernel security parameters",
            },
        ),
        (
            "cron_jobs",
            CheckEntry {
                func: checks::cron_jobs::run,
                description: "Cron job audit",
            },
        ),
    ]
}

// ---------------------------------------------------------------------------
// CLI argument parsing (no external deps)
// ---------------------------------------------------------------------------

struct Args {
    output_dir: PathBuf,
    checks: Option<Vec<String>>,
    upload_url: Option<String>,
    list_checks: bool,
}

fn parse_args() -> Args {
    let args: Vec<String> = env::args().collect();
    let mut output_dir = default_output_dir();
    let mut checks = None;
    let mut upload_url = None;
    let mut list_checks = false;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--output-dir" => {
                i += 1;
                if i < args.len() {
                    output_dir = PathBuf::from(&args[i]);
                }
            }
            "--checks" => {
                i += 1;
                if i < args.len() {
                    checks = Some(args[i].split(',').map(|s| s.trim().to_string()).collect());
                }
            }
            "--upload-url" => {
                i += 1;
                if i < args.len() {
                    upload_url = Some(args[i].clone());
                }
            }
            "--list-checks" | "--list" => {
                list_checks = true;
            }
            "--help" | "-h" => {
                print_usage();
                std::process::exit(0);
            }
            other => {
                eprintln!("Unknown argument: {}", other);
                print_usage();
                std::process::exit(1);
            }
        }
        i += 1;
    }

    Args {
        output_dir,
        checks,
        upload_url,
        list_checks,
    }
}

fn default_output_dir() -> PathBuf {
    if let Ok(dir) = env::var("SECURITY_AUDIT_DIR") {
        return PathBuf::from(dir);
    }
    let home = env::var("HOME").unwrap_or_else(|_| "/root".to_string());
    PathBuf::from(home)
        .join(".agents")
        .join("security_audits")
}

fn print_usage() {
    eprintln!(
        "Usage: security-audit-collector [OPTIONS]

Options:
    --output-dir DIR    Output directory for reports (default: ~/.agents/security_audits)
    --checks LIST       Comma-separated checks to run (default: all)
    --upload-url URL    HTTP URL to POST the report to after collection
    --list-checks       List available checks and exit
    -h, --help          Show this help

Available checks:"
    );
    for (name, entry) in all_checks() {
        eprintln!("    {:20} {}", name, entry.description);
    }
}

// ---------------------------------------------------------------------------
// Timestamp helpers
// ---------------------------------------------------------------------------

fn iso_timestamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    let (year, month, day, hours, minutes, seconds) = secs_to_datetime(secs);

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, month, day, hours, minutes, seconds
    )
}

fn compact_timestamp() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    let (year, month, day, hours, minutes, seconds) = secs_to_datetime(secs);

    format!(
        "{:04}{:02}{:02}T{:02}{:02}{:02}Z",
        year, month, day, hours, minutes, seconds
    )
}

fn secs_to_datetime(secs: u64) -> (i64, u32, u32, u64, u64, u64) {
    let days = (secs / 86400) as i64;
    let time_of_day = secs % 86400;
    let hours = time_of_day / 3600;
    let minutes = (time_of_day % 3600) / 60;
    let seconds = time_of_day % 60;
    let (year, month, day) = days_to_date(days);
    (year, month, day, hours, minutes, seconds)
}

/// Convert days since Unix epoch to (year, month, day).
/// Algorithm from http://howardhinnant.github.io/date_algorithms.html
fn days_to_date(days: i64) -> (i64, u32, u32) {
    let z = days + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u32;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    (y, m, d)
}

// ---------------------------------------------------------------------------
// Report generation
// ---------------------------------------------------------------------------

fn run_audit(selected_checks: &[String], registry: &[(&str, CheckEntry)]) -> Value {
    let hostname = util::hostname();
    let timestamp = iso_timestamp();

    let mut results = Map::new();
    let mut completed: u64 = 0;
    let mut failed: u64 = 0;
    let mut total_findings: u64 = 0;
    let mut severity_counts: [u64; 4] = [0; 4]; // critical, high, medium, low

    for check_name in selected_checks {
        let entry = match registry.iter().find(|(n, _)| *n == check_name.as_str()) {
            Some((_, e)) => e,
            None => {
                eprintln!("[ERROR] Unknown check: {}", check_name);
                results.insert(
                    check_name.clone(),
                    json!({
                        "status": "failed",
                        "error": format!("Unknown check: {}", check_name),
                    }),
                );
                failed += 1;
                continue;
            }
        };

        eprintln!(
            "[INFO] Running check: {} ({})",
            check_name, entry.description
        );

        let data = (entry.func)();

        results.insert(
            check_name.clone(),
            json!({
                "status": "completed",
                "description": entry.description,
                "data": data,
            }),
        );
        completed += 1;

        // Count findings
        let findings_count = data
            .get("findings")
            .and_then(|f| f.as_array())
            .map(|a| a.len() as u64)
            .unwrap_or(0);
        let alerts_count = data
            .get("alerts")
            .and_then(|a| a.as_array())
            .map(|a| a.len() as u64)
            .unwrap_or(0);
        total_findings += findings_count + alerts_count;

        // Count by severity
        if let Some(findings) = data.get("findings").and_then(|f| f.as_array()) {
            for finding in findings {
                if let Some(sev) = finding.get("severity").and_then(|s| s.as_str()) {
                    match sev {
                        "critical" => severity_counts[0] += 1,
                        "high" => severity_counts[1] += 1,
                        "medium" => severity_counts[2] += 1,
                        "low" => severity_counts[3] += 1,
                        _ => {}
                    }
                }
            }
        }
    }

    json!({
        "metadata": {
            "version": "1.0",
            "collector": "security-audit-collector-rs",
            "timestamp": timestamp,
            "hostname": hostname,
            "checks_requested": selected_checks,
        },
        "results": results,
        "summary": {
            "total_checks": selected_checks.len(),
            "completed": completed,
            "failed": failed,
            "total_findings": total_findings,
            "by_severity": {
                "critical": severity_counts[0],
                "high": severity_counts[1],
                "medium": severity_counts[2],
                "low": severity_counts[3],
            },
        },
    })
}

// ---------------------------------------------------------------------------
// HTTP upload (minimal, stdlib-only)
// ---------------------------------------------------------------------------

fn upload_report(report_path: &Path, url: &str) -> Result<(), String> {
    let url_trimmed = url
        .strip_prefix("http://")
        .ok_or_else(|| {
            "Only http:// URLs are supported for upload. \
             For HTTPS, pipe through curl: \
             curl -X POST -H 'Content-Type: application/json' -d @report.json <url>"
                .to_string()
        })?;

    eprintln!(
        "[WARN] Uploading over plaintext HTTP. Security audit reports contain \
         sensitive system data (open ports, SSH config, user accounts, kernel \
         parameters). Use HTTPS wherever possible to prevent interception."
    );

    let (host_port, path) = match url_trimmed.find('/') {
        Some(i) => (&url_trimmed[..i], &url_trimmed[i..]),
        None => (url_trimmed, "/"),
    };

    let (host, port) = match host_port.rfind(':') {
        Some(i) => (
            &host_port[..i],
            host_port[i + 1..].parse::<u16>().unwrap_or(80),
        ),
        None => (host_port, 80u16),
    };

    let body = fs::read(report_path).map_err(|e| format!("Failed to read report: {}", e))?;

    let request = format!(
        "POST {} HTTP/1.1\r\nHost: {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        path, host_port, body.len()
    );

    let addr = format!("{}:{}", host, port);
    let mut stream =
        TcpStream::connect(&addr).map_err(|e| format!("Failed to connect to {}: {}", addr, e))?;

    stream
        .write_all(request.as_bytes())
        .map_err(|e| format!("Failed to send headers: {}", e))?;
    stream
        .write_all(&body)
        .map_err(|e| format!("Failed to send body: {}", e))?;

    let mut response = String::new();
    stream
        .read_to_string(&mut response)
        .map_err(|e| format!("Failed to read response: {}", e))?;

    if let Some(status_line) = response.lines().next() {
        eprintln!("[INFO] Upload response: {}", status_line);
        if status_line.contains("200")
            || status_line.contains("201")
            || status_line.contains("202")
        {
            return Ok(());
        }
        return Err(format!("Upload failed: {}", status_line));
    }

    Err("No response received".into())
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    let args = parse_args();
    let registry = all_checks();

    if args.list_checks {
        println!("Available security audit checks:");
        for (name, entry) in &registry {
            println!("  {:20} {}", name, entry.description);
        }
        return;
    }

    // Determine which checks to run
    let check_names: Vec<String> = match args.checks {
        Some(names) => {
            let valid: Vec<&str> = registry.iter().map(|(n, _)| *n).collect();
            for name in &names {
                if !valid.contains(&name.as_str()) {
                    eprintln!(
                        "[ERROR] Unknown check: '{}'. Available: {}",
                        name,
                        valid.join(", ")
                    );
                    std::process::exit(1);
                }
            }
            names
        }
        None => registry.iter().map(|(n, _)| n.to_string()).collect(),
    };

    let report = run_audit(&check_names, &registry);

    // Write report
    fs::create_dir_all(&args.output_dir).unwrap_or_else(|e| {
        eprintln!(
            "[ERROR] Cannot create output directory {:?}: {}",
            args.output_dir, e
        );
        std::process::exit(1);
    });

    let hostname = util::hostname();
    let filename = format!("audit_{}_{}.json", hostname, compact_timestamp());
    let report_path = args.output_dir.join(&filename);

    let json_str = serde_json::to_string_pretty(&report).expect("JSON serialization failed");
    fs::write(&report_path, &json_str).unwrap_or_else(|e| {
        eprintln!("[ERROR] Cannot write report to {:?}: {}", report_path, e);
        std::process::exit(1);
    });

    // Create/update 'latest' symlink
    let latest_link = args.output_dir.join(format!("latest_{}.json", hostname));
    let _ = fs::remove_file(&latest_link);
    let _ = unix_fs::symlink(&filename, &latest_link);

    let total_findings = report
        .get("summary")
        .and_then(|s| s.get("total_findings"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    eprintln!(
        "[INFO] Report written to {:?} ({} findings)",
        report_path, total_findings
    );
    println!("{}", report_path.display());

    // Optional upload
    if let Some(url) = args.upload_url {
        match upload_report(&report_path, &url) {
            Ok(()) => eprintln!("[INFO] Upload succeeded"),
            Err(e) => {
                eprintln!("[ERROR] {}", e);
                std::process::exit(1);
            }
        }
    }
}
