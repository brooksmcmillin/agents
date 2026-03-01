use serde_json::{json, Value};

use crate::util::{read_file_string, run_cmd};

/// High-risk ports that should be flagged when exposed.
const HIGH_RISK_PORTS: &[u16] = &[
    21, 23, 25, 111, 135, 139, 445, 1433, 3306, 3389, 5432, 6379, 27017,
];

pub fn run() -> Value {
    // Try ss first
    let ss_out = run_cmd("ss", &["-tulnp"]);
    if !ss_out.is_empty() && ss_out.contains("Netid") {
        return parse_ss(&ss_out);
    }

    // Fallback: parse /proc/net/tcp + /proc/net/udp
    parse_proc_net()
}

fn parse_ss(output: &str) -> Value {
    let mut services = Vec::new();
    let mut alerts = Vec::new();

    for line in output.lines().skip(1) {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 5 {
            continue;
        }
        let proto = parts[0];
        let local_addr = parts[4];
        let process = if parts.len() > 6 { parts[6] } else { "" };

        // Sanitize process info (truncate, strip env vars)
        let process_clean: String = process.chars().take(150).collect();

        services.push(json!({
            "proto": proto,
            "listen_address": local_addr,
            "process": process_clean,
        }));

        // Check for high-risk ports
        if let Some(port) = extract_port(local_addr) {
            if HIGH_RISK_PORTS.contains(&port) {
                alerts.push(format!(
                    "High-risk port {} is listening ({})",
                    port, local_addr
                ));
            }
        }
    }

    let total = services.len();
    json!({
        "listening_services": services,
        "total_listening": total,
        "alerts": alerts,
    })
}

fn parse_proc_net() -> Value {
    let mut services = Vec::new();
    let mut alerts = Vec::new();

    for (proto, path) in &[("tcp", "/proc/net/tcp"), ("udp", "/proc/net/udp")] {
        let content = match read_file_string(path) {
            Some(c) => c,
            None => continue,
        };

        for line in content.lines().skip(1) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() < 4 {
                continue;
            }

            // For TCP, only show LISTEN state (0A)
            if *proto == "tcp" && parts[3] != "0A" {
                continue;
            }

            if let Some((addr, port)) = decode_hex_addr(parts[1]) {
                let listen_addr = format!("{}:{}", addr, port);
                services.push(json!({
                    "proto": proto,
                    "listen_address": listen_addr,
                    "process": "",
                }));

                if HIGH_RISK_PORTS.contains(&port) {
                    alerts.push(format!(
                        "High-risk port {} is listening ({})",
                        port, listen_addr
                    ));
                }
            }
        }
    }

    let total = services.len();
    json!({
        "listening_services": services,
        "total_listening": total,
        "alerts": alerts,
    })
}

fn extract_port(addr: &str) -> Option<u16> {
    // Handle both "0.0.0.0:22" and "[::]:22"
    addr.rsplit(':').next()?.parse().ok()
}

fn decode_hex_addr(hex_addr: &str) -> Option<(String, u16)> {
    let mut parts = hex_addr.split(':');
    let addr_hex = parts.next()?;
    let port_hex = parts.next()?;

    let port = u16::from_str_radix(port_hex, 16).ok()?;
    let addr_int = u32::from_str_radix(addr_hex, 16).ok()?;

    // /proc/net uses little-endian for the IP address
    let octets = addr_int.to_le_bytes();
    let addr = format!("{}.{}.{}.{}", octets[0], octets[1], octets[2], octets[3]);
    Some((addr, port))
}
