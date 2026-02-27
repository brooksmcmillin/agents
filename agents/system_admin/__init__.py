"""System Admin Agent.

A network and system administration agent for local infrastructure security
assessment. Discovers hosts, scans ports, checks TLS configurations, audits
SSH and firewall settings, identifies insecure defaults, and generates
prioritized remediation reports.

Features:
- Local network host discovery and port scanning
- TLS/SSL certificate and cipher suite inspection
- Service banner grabbing and version detection
- SSH server configuration auditing
- File permission checks on sensitive paths
- Firewall rule analysis (ufw, iptables, nftables)
- Default credential detection (SSH, HTTP, SNMP)
- Comprehensive security assessment reports
"""

__version__ = "0.1.0"
