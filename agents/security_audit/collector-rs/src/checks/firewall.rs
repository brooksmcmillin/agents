use serde_json::{json, Value};

use crate::util::run_cmd;

pub fn run() -> Value {
    // Try ufw
    let ufw_out = run_cmd("ufw", &["status", "verbose"]);
    if !ufw_out.is_empty() {
        if ufw_out.contains("Status: active") {
            return json!({
                "backend": "ufw",
                "status": "active",
                "rules_raw": ufw_out,
            });
        } else if ufw_out.contains("Status: inactive") {
            return json!({
                "backend": "ufw",
                "status": "inactive",
                "alerts": ["Firewall (ufw) is INACTIVE"],
            });
        }
    }

    // Try iptables
    let ipt_out = run_cmd("iptables", &["-L", "-n", "--line-numbers"]);
    if !ipt_out.is_empty() {
        let status = if ipt_out.contains("ACCEPT     all") && ipt_out.contains("0.0.0.0/0") {
            "permissive"
        } else {
            "active"
        };

        let mut result = json!({
            "backend": "iptables",
            "status": status,
            "rules_raw": ipt_out,
        });

        if status == "permissive" {
            result["alerts"] =
                json!(["iptables has ACCEPT ALL rules from any source"]);
        }

        return result;
    }

    // Try nftables
    let nft_out = run_cmd("nft", &["list", "ruleset"]);
    if !nft_out.is_empty() {
        let status = if nft_out.trim().is_empty() {
            "empty"
        } else {
            "active"
        };
        return json!({
            "backend": "nftables",
            "status": status,
            "rules_raw": nft_out,
        });
    }

    json!({
        "status": "not_found",
        "alerts": ["No firewall (ufw/iptables/nftables) detected"],
    })
}
