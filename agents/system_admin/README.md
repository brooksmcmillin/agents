# System Admin Agent

Network and system security assessment agent. Performs host discovery, port scanning, service banner grabbing, TLS inspection, SSH configuration auditing, firewall review, and default credential detection against local infrastructure.

## Features

- **Network discovery** — find live hosts and open ports on local subnets
- **Service auditing** — check TLS/SSL certificates, protocol versions, and service banners
- **System hardening** — audit SSH config, file permissions, and firewall rules
- **Default credential detection** — test for insecure defaults on SSH, HTTP panels, and SNMP
- **Comprehensive reports** — aggregated findings sorted by severity with remediation steps
- **Baseline tracking** — save scan results to memory for drift detection over time

## Quick Start

```bash
# Required: configure allowed subnets before network scanning
# In .env:
SYSADMIN_ALLOWED_SUBNETS=192.168.1.0/24

uv run bin/run-agent sysadmin
```

## MCP Tools

### Network Tools
- `network_discover_hosts` — scan a subnet for live hosts using TCP probes
- `network_scan_ports` — scan TCP ports on a specific host (common, range, or custom list)
- `network_grab_banners` — connect to open ports and read service banners
- `network_check_tls` — inspect TLS/SSL certificate and cipher suite strength
- `network_check_dns` — DNS configuration analysis (A, MX, NS, SPF, DMARC)
- `network_check_default_credentials` — test SSH, HTTP admin panels, and SNMP for insecure defaults
- `network_generate_report` — orchestrate all relevant scans and aggregate findings

### System Tools (Local)
- `system_get_info` — OS version, hostname, interfaces, listening services
- `system_check_ssh_config` — audit SSH server settings (PermitRootLogin, PasswordAuth, etc.)
- `system_check_file_permissions` — check sensitive file permissions (shadow, SSH keys, .env)
- `system_check_firewall` — review ufw, iptables, and nftables rules

### Other Tools
- `get_memories`, `save_memory`, `search_memories` — persist scan baselines and findings
- `send_slack_message` — notify on critical findings

## Usage Examples

```
You: What's visible on my network?
Agent: [discovers live hosts on the subnet, scans ports, grabs banners,
        saves findings as a baseline, presents prioritized summary]

You: Is this server secure?
Agent: [runs system_get_info, scans ports, audits SSH config, checks file
        permissions, reviews firewall, tests default credentials, generates report]

You: Are there any default passwords on my network?
Agent: [discovers hosts, runs default credential checks on each,
        compiles results, provides specific remediation steps]
```

## Configuration

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Required for network scanning — specify subnets to allow
SYSADMIN_ALLOWED_SUBNETS=192.168.1.0/24

# Optional — for sending reports
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

## Security Guardrails

- **Scope control** — only scans targets within `SYSADMIN_ALLOWED_SUBNETS`
- **No exploitation** — discovery and auditing only; vulnerabilities are reported, not exploited
- **Credential redaction** — tested credentials are always redacted in output
- **Rate limiting** — scans in batches to avoid overwhelming the network

## Architecture

Uses `create_simple_agent()` with network admin tools, memory tools, and communication tools. The network tools implement SSRF protection via the allowed-subnets allowlist to prevent scanning arbitrary internet hosts.

## Related Documentation

- [CLAUDE.md](../../CLAUDE.md) — project overview
- [docs/tools.md](../../docs/tools.md) — MCP tools reference
- [agents/security_audit/](../security_audit/) — offline audit report analysis
- [agents/red_team/](../red_team/) — dynamic web application penetration testing
