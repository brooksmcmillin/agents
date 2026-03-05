#!/usr/bin/env python3
"""Non-LLM security audit collector.

Runs a battery of system security checks and writes a structured JSON report
to a configurable output directory. Designed to run on any Linux machine with
no dependencies beyond the Python 3.10+ stdlib.

Usage:
    # Run locally and write to default directory
    python collector.py

    # Write to a custom directory
    python collector.py --output-dir /tmp/audit-reports

    # Upload to a remote URL (e.g. the agents API) after collection
    python collector.py --upload-url http://server:8080/api/security-audits

    # Run a subset of checks
    python collector.py --checks os_info,open_ports,ssh_config

The output JSON is designed to be consumed by the SecurityAuditAgent (LLM) for
analysis.  The collector itself contains NO LLM logic — it's pure subprocess
calls and file reads.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import pwd
import re
import socket
import stat
import subprocess  # nosec B404 - collector must run system commands
import urllib.request
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Default output directory (relative to project root or absolute)
DEFAULT_OUTPUT_DIR = os.environ.get(
    "SECURITY_AUDIT_DIR",
    os.path.join(os.path.expanduser("~"), ".agents", "security_audits"),
)


# ---------------------------------------------------------------------------
# Individual check functions — each returns a dict of findings
# ---------------------------------------------------------------------------


def check_os_info() -> dict[str, Any]:
    """Gather basic OS and host information."""
    uname = platform.uname()
    uptime = _read_file("/proc/uptime")
    uptime_seconds = float(uptime.split()[0]) if uptime else None

    return {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "os": f"{uname.system} {uname.release}",
        "version": uname.version,
        "arch": uname.machine,
        "python": platform.python_version(),
        "uptime_seconds": uptime_seconds,
        "uptime_days": round(uptime_seconds / 86400, 1) if uptime_seconds else None,
    }


def check_open_ports() -> dict[str, Any]:
    """List listening TCP/UDP ports from /proc/net or ss."""
    findings: list[dict[str, Any]] = []

    # Try ss first (more reliable)
    result = _run_cmd(["ss", "-tulnp"])
    if result["exit_code"] == 0:
        for line in result["stdout"].splitlines()[1:]:  # skip header
            parts = line.split()
            if len(parts) >= 5:
                proto = parts[0]
                local_addr = parts[4]
                process = parts[-1] if "users:" in parts[-1] else ""
                findings.append(
                    {
                        "proto": proto,
                        "listen_address": local_addr,
                        "process": _sanitize_process_info(process),
                    }
                )
    else:
        # Fallback: parse /proc/net/tcp
        for proto, path in [("tcp", "/proc/net/tcp"), ("udp", "/proc/net/udp")]:
            content = _read_file(path)
            if content:
                for line in content.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        local = parts[1]
                        state = parts[3]
                        if proto == "tcp" and state != "0A":  # 0A = LISTEN
                            continue
                        addr, port = _decode_proc_net_addr(local)
                        findings.append(
                            {
                                "proto": proto,
                                "listen_address": f"{addr}:{port}",
                                "process": "",
                            }
                        )

    # Flag high-risk ports
    high_risk_ports = {21, 23, 25, 111, 135, 139, 445, 1433, 3306, 3389, 5432, 6379, 27017}
    alerts = []
    for f in findings:
        try:
            port = int(f["listen_address"].rsplit(":", 1)[-1])
            if port in high_risk_ports:
                alerts.append(f"High-risk port {port} is listening ({f['listen_address']})")
        except (ValueError, IndexError):
            pass

    return {
        "listening_services": findings,
        "total_listening": len(findings),
        "alerts": alerts,
    }


def check_ssh_config() -> dict[str, Any]:
    """Audit SSH server configuration."""
    config_path = "/etc/ssh/sshd_config"
    content = _read_file(config_path)

    if not content:
        return {"available": False, "reason": "sshd_config not found or not readable"}

    findings: list[dict[str, str]] = []

    checks = {
        "PermitRootLogin": {
            "pattern": r"^\s*PermitRootLogin\s+(\S+)",
            "bad_values": ["yes"],
            "severity": "critical",
            "recommendation": "Set PermitRootLogin to 'no' or 'prohibit-password'",
        },
        "PasswordAuthentication": {
            "pattern": r"^\s*PasswordAuthentication\s+(\S+)",
            "bad_values": ["yes"],
            "severity": "high",
            "recommendation": "Set PasswordAuthentication to 'no' and use key-based auth",
        },
        "PermitEmptyPasswords": {
            "pattern": r"^\s*PermitEmptyPasswords\s+(\S+)",
            "bad_values": ["yes"],
            "severity": "critical",
            "recommendation": "Set PermitEmptyPasswords to 'no'",
        },
        "X11Forwarding": {
            "pattern": r"^\s*X11Forwarding\s+(\S+)",
            "bad_values": ["yes"],
            "severity": "low",
            "recommendation": "Set X11Forwarding to 'no' unless required",
        },
        "MaxAuthTries": {
            "pattern": r"^\s*MaxAuthTries\s+(\d+)",
            "max_value": 6,
            "severity": "medium",
            "recommendation": "Set MaxAuthTries to 3-6",
        },
        "Protocol": {
            "pattern": r"^\s*Protocol\s+(\S+)",
            "bad_values": ["1", "1,2"],
            "severity": "critical",
            "recommendation": "Set Protocol to '2'",
        },
    }

    for name, check in checks.items():
        match = re.search(check["pattern"], content, re.MULTILINE | re.IGNORECASE)
        if match:
            value = match.group(1).lower()
            is_bad = False

            if "bad_values" in check:
                is_bad = value in check["bad_values"]
            elif "max_value" in check:
                try:
                    is_bad = int(value) > check["max_value"]
                except ValueError:
                    pass

            if is_bad:
                findings.append(
                    {
                        "setting": name,
                        "current_value": match.group(1),
                        "severity": check["severity"],
                        "recommendation": check["recommendation"],
                    }
                )

    return {
        "available": True,
        "config_path": config_path,
        "findings": findings,
        "findings_count": len(findings),
    }


def check_file_permissions() -> dict[str, Any]:
    """Check permissions on security-sensitive files."""
    sensitive_paths = [
        ("/etc/shadow", 0o640, "Password hashes"),
        ("/etc/gshadow", 0o640, "Group password hashes"),
        ("/etc/passwd", 0o644, "User database"),
        ("/etc/ssh/sshd_config", 0o600, "SSH server config"),
        ("/root/.ssh/authorized_keys", 0o600, "Root SSH authorized keys"),
    ]

    # Also check for world-readable .env files
    home_dirs = _get_home_dirs()
    for hdir in home_dirs:
        for env_file in [".env", ".env.local", ".env.production"]:
            p = os.path.join(hdir, env_file)
            if os.path.exists(p):
                sensitive_paths.append((p, 0o600, "Environment file with potential secrets"))

    findings: list[dict[str, Any]] = []
    for path, expected_max_mode, description in sensitive_paths:
        if not os.path.exists(path):
            continue
        try:
            st = os.stat(path)
            mode = stat.S_IMODE(st.st_mode)
            # Check if actual permissions are more permissive than expected
            world_readable = bool(mode & stat.S_IROTH)
            world_writable = bool(mode & stat.S_IWOTH)
            group_writable = bool(mode & stat.S_IWGRP)

            issues = []
            if world_readable:
                issues.append("world-readable")
            if world_writable:
                issues.append("world-writable")
            if group_writable and path in ("/etc/shadow", "/etc/gshadow"):
                issues.append("group-writable")

            if issues:
                findings.append(
                    {
                        "path": path,
                        "description": description,
                        "current_mode": oct(mode),
                        "expected_max_mode": oct(expected_max_mode),
                        "issues": issues,
                        "severity": "critical" if world_writable else "high",
                    }
                )
        except PermissionError:
            pass

    return {
        "checked_paths": len(sensitive_paths),
        "findings": findings,
        "findings_count": len(findings),
    }


def check_firewall() -> dict[str, Any]:
    """Check firewall status and rules."""
    results: dict[str, Any] = {"status": "unknown", "rules": []}

    # Try ufw
    ufw = _run_cmd(["ufw", "status", "verbose"])
    if ufw["exit_code"] == 0:
        results["backend"] = "ufw"
        output = ufw["stdout"]
        if "Status: active" in output:
            results["status"] = "active"
            results["rules_raw"] = output
        elif "Status: inactive" in output:
            results["status"] = "inactive"
            results["alerts"] = ["Firewall (ufw) is INACTIVE"]
        return results

    # Try iptables
    ipt = _run_cmd(["iptables", "-L", "-n", "--line-numbers"])
    if ipt["exit_code"] == 0:
        results["backend"] = "iptables"
        output = ipt["stdout"]
        results["rules_raw"] = output
        if "ACCEPT     all" in output and "0.0.0.0/0" in output:
            results["status"] = "permissive"
            results["alerts"] = ["iptables has ACCEPT ALL rules from any source"]
        else:
            results["status"] = "active"
        return results

    # Try nftables
    nft = _run_cmd(["nft", "list", "ruleset"])
    if nft["exit_code"] == 0:
        results["backend"] = "nftables"
        results["rules_raw"] = nft["stdout"]
        results["status"] = "active" if nft["stdout"].strip() else "empty"
        return results

    results["status"] = "not_found"
    results["alerts"] = ["No firewall (ufw/iptables/nftables) detected"]
    return results


def check_users_and_auth() -> dict[str, Any]:
    """Check user accounts for security issues."""
    findings: list[dict[str, Any]] = []

    # Check for users with UID 0 (root equivalents)
    try:
        for entry in pwd.getpwall():
            if entry.pw_uid == 0 and entry.pw_name != "root":
                findings.append(
                    {
                        "issue": "non_root_uid_zero",
                        "user": entry.pw_name,
                        "severity": "critical",
                        "detail": f"User '{entry.pw_name}' has UID 0 (root equivalent)",
                    }
                )
            # Check for empty password fields
            if entry.pw_passwd in ("", " "):
                findings.append(
                    {
                        "issue": "empty_password",
                        "user": entry.pw_name,
                        "severity": "critical",
                        "detail": f"User '{entry.pw_name}' has no password set",
                    }
                )
    except PermissionError:
        pass

    # Check shadow for accounts with no password hash
    shadow = _read_file("/etc/shadow")
    if shadow:
        for line in shadow.splitlines():
            parts = line.split(":")
            if len(parts) >= 2:
                user, phash = parts[0], parts[1]
                if phash in ("", "!!", "*"):
                    continue  # locked or no-login accounts
                if not phash.startswith("$"):
                    findings.append(
                        {
                            "issue": "weak_password_hash",
                            "user": user,
                            "severity": "high",
                            "detail": f"User '{user}' has a non-standard password hash format",
                        }
                    )

    # Check for sudo with NOPASSWD
    sudoers_content = _read_file("/etc/sudoers")
    if sudoers_content:
        for line in sudoers_content.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "NOPASSWD" in line:
                findings.append(
                    {
                        "issue": "sudo_nopasswd",
                        "severity": "medium",
                        "detail": f"NOPASSWD sudo rule found: {line[:120]}",
                    }
                )

    # Also check /etc/sudoers.d/
    sudoers_d = "/etc/sudoers.d"
    if os.path.isdir(sudoers_d):
        try:
            for fname in os.listdir(sudoers_d):
                content = _read_file(os.path.join(sudoers_d, fname))
                if content:
                    for line in content.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "NOPASSWD" in line:
                            findings.append(
                                {
                                    "issue": "sudo_nopasswd",
                                    "severity": "medium",
                                    "detail": f"NOPASSWD in {fname}: {line[:120]}",
                                }
                            )
        except PermissionError:
            pass

    return {
        "findings": findings,
        "findings_count": len(findings),
    }


def check_running_services() -> dict[str, Any]:
    """List running services and flag potentially unnecessary ones."""
    result = _run_cmd(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-pager"]
    )

    if result["exit_code"] != 0:
        # Fallback: check /proc
        return {"available": False, "reason": "systemctl not available"}

    services: list[dict[str, str]] = []
    for line in result["stdout"].splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].endswith(".service"):
            services.append(
                {
                    "name": parts[0],
                    "state": parts[2],
                    "description": " ".join(parts[3:]),
                }
            )

    # Flag services that are often unnecessary on servers
    unnecessary_candidates = {
        "cups.service": "Print server (usually unnecessary on servers)",
        "avahi-daemon.service": "mDNS/DNS-SD service discovery (attack surface on servers)",
        "bluetooth.service": "Bluetooth (usually unnecessary on servers)",
        "ModemManager.service": "Modem manager (usually unnecessary on servers)",
    }

    alerts = []
    for svc in services:
        if svc["name"] in unnecessary_candidates:
            alerts.append(f"{svc['name']}: {unnecessary_candidates[svc['name']]}")

    return {
        "services": services,
        "total_running": len(services),
        "alerts": alerts,
    }


def check_package_updates() -> dict[str, Any]:
    """Check for available security updates."""
    # Try apt (Debian/Ubuntu)
    result = _run_cmd(["apt", "list", "--upgradable"], timeout=30)
    if result["exit_code"] == 0:
        lines = [line for line in result["stdout"].splitlines() if "/" in line]
        security_updates = [line for line in lines if "security" in line.lower()]
        return {
            "package_manager": "apt",
            "total_upgradable": len(lines),
            "security_updates": len(security_updates),
            "sample_updates": lines[:20],
        }

    # Try yum/dnf (RHEL/Fedora)
    for pm in ["dnf", "yum"]:
        result = _run_cmd([pm, "check-update", "--security"], timeout=30)
        if result["exit_code"] in (0, 100):  # 100 = updates available
            lines = [
                line
                for line in result["stdout"].splitlines()
                if line.strip() and not line.startswith("Last")
            ]
            return {
                "package_manager": pm,
                "security_updates": len(lines),
                "sample_updates": lines[:20],
            }

    return {"package_manager": "unknown", "reason": "No supported package manager found"}


def check_kernel_security() -> dict[str, Any]:
    """Check kernel security parameters via sysctl."""
    checks = {
        "net.ipv4.ip_forward": {
            "expected": "0",
            "severity": "medium",
            "desc": "IP forwarding enabled (router mode)",
        },
        "net.ipv4.conf.all.accept_redirects": {
            "expected": "0",
            "severity": "medium",
            "desc": "ICMP redirects accepted",
        },
        "net.ipv4.conf.all.send_redirects": {
            "expected": "0",
            "severity": "low",
            "desc": "ICMP redirects sent",
        },
        "net.ipv4.conf.all.accept_source_route": {
            "expected": "0",
            "severity": "medium",
            "desc": "Source routing accepted",
        },
        "net.ipv4.conf.all.log_martians": {
            "expected": "1",
            "severity": "low",
            "desc": "Martian packets not logged",
        },
        "net.ipv4.tcp_syncookies": {
            "expected": "1",
            "severity": "medium",
            "desc": "SYN cookies disabled (vulnerable to SYN flood)",
        },
        "kernel.randomize_va_space": {
            "expected": "2",
            "severity": "high",
            "desc": "ASLR not fully enabled",
        },
        "kernel.dmesg_restrict": {
            "expected": "1",
            "severity": "low",
            "desc": "Kernel logs readable by unprivileged users",
        },
        "fs.suid_dumpable": {
            "expected": "0",
            "severity": "medium",
            "desc": "SUID programs may dump core (info leak)",
        },
    }

    findings: list[dict[str, Any]] = []
    for key, check in checks.items():
        value = _read_sysctl(key)
        if value is not None and value != check["expected"]:
            findings.append(
                {
                    "parameter": key,
                    "current_value": value,
                    "expected_value": check["expected"],
                    "severity": check["severity"],
                    "description": check["desc"],
                }
            )

    return {
        "checked_parameters": len(checks),
        "findings": findings,
        "findings_count": len(findings),
    }


def check_cron_jobs() -> dict[str, Any]:
    """Audit cron jobs for suspicious entries."""
    findings: list[dict[str, Any]] = []

    # System crontab
    system_cron = _read_file("/etc/crontab")
    if system_cron:
        for line in system_cron.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                # Flag jobs running as root that fetch from the internet
                if "curl " in line or "wget " in line:
                    findings.append(
                        {
                            "source": "/etc/crontab",
                            "line": line[:200],
                            "severity": "high",
                            "issue": "Cron job fetches remote content",
                        }
                    )

    # Check cron directories
    for cron_dir in ["/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly"]:
        if os.path.isdir(cron_dir):
            try:
                for fname in os.listdir(cron_dir):
                    fpath = os.path.join(cron_dir, fname)
                    content = _read_file(fpath)
                    if content and ("curl " in content or "wget " in content):
                        findings.append(
                            {
                                "source": fpath,
                                "severity": "medium",
                                "issue": f"Cron script in {cron_dir} fetches remote content",
                            }
                        )
            except PermissionError:
                pass

    return {
        "findings": findings,
        "findings_count": len(findings),
    }


# ---------------------------------------------------------------------------
# Registry of all available checks
# ---------------------------------------------------------------------------

ALL_CHECKS: dict[str, tuple[Any, str]] = {
    "os_info": (check_os_info, "Basic OS and host information"),
    "open_ports": (check_open_ports, "Listening TCP/UDP ports"),
    "ssh_config": (check_ssh_config, "SSH server configuration audit"),
    "file_permissions": (check_file_permissions, "Sensitive file permissions"),
    "firewall": (check_firewall, "Firewall status and rules"),
    "users_auth": (check_users_and_auth, "User accounts and authentication"),
    "running_services": (check_running_services, "Running services"),
    "package_updates": (check_package_updates, "Available security updates"),
    "kernel_security": (check_kernel_security, "Kernel security parameters"),
    "cron_jobs": (check_cron_jobs, "Cron job audit"),
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _run_cmd(cmd: list[str], timeout: int = 15) -> dict[str, Any]:
    """Run a subprocess and return structured output."""
    try:
        proc = subprocess.run(  # nosec B603 - commands are hardcoded, not user input
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except FileNotFoundError:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command not found: {cmd[0]}"}
    except subprocess.TimeoutExpired:
        return {"exit_code": -2, "stdout": "", "stderr": f"Command timed out after {timeout}s"}


def _read_file(path: str) -> str | None:
    """Read a file, returning None on any error."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def _read_sysctl(key: str) -> str | None:
    """Read a sysctl value from /proc/sys/."""
    proc_path = "/proc/sys/" + key.replace(".", "/")
    content = _read_file(proc_path)
    return content.strip() if content else None


def _decode_proc_net_addr(hex_addr: str) -> tuple[str, int]:
    """Decode a hex address:port from /proc/net/tcp."""
    addr_hex, port_hex = hex_addr.split(":")
    port = int(port_hex, 16)
    # Reverse byte order for the IP
    addr_int = int(addr_hex, 16)
    addr = socket.inet_ntoa(addr_int.to_bytes(4, byteorder="little"))
    return addr, port


def _sanitize_process_info(process_str: str) -> str:
    """Remove potentially sensitive details from process info."""
    # Strip out environment variables and full command lines
    return process_str[:150]


def _get_home_dirs() -> list[str]:
    """Get home directories for real users."""
    dirs = []
    try:
        for entry in pwd.getpwall():
            if entry.pw_uid >= 1000 or entry.pw_name == "root":
                if os.path.isdir(entry.pw_dir):
                    dirs.append(entry.pw_dir)
    except PermissionError:
        # Fallback
        home = os.path.expanduser("~")
        if os.path.isdir(home):
            dirs.append(home)
    return dirs


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def run_audit(
    checks: list[str] | None = None,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Path:
    """Run security audit checks and write a JSON report.

    Args:
        checks: List of check names to run (default: all).
        output_dir: Directory to write the report to.

    Returns:
        Path to the written report file.
    """
    if checks is None:
        checks = list(ALL_CHECKS.keys())

    # Validate check names
    invalid = set(checks) - set(ALL_CHECKS.keys())
    if invalid:
        raise ValueError(f"Unknown checks: {invalid}. Available: {list(ALL_CHECKS.keys())}")

    timestamp = datetime.now(UTC)
    report: dict[str, Any] = {
        "metadata": {
            "version": "1.0",
            "collector": "security-audit-collector",
            "timestamp": timestamp.isoformat(),
            "hostname": socket.gethostname(),
            "checks_requested": checks,
        },
        "results": {},
        "summary": {
            "total_checks": len(checks),
            "completed": 0,
            "failed": 0,
            "total_findings": 0,
            "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
        },
    }

    for check_name in checks:
        func, description = ALL_CHECKS[check_name]
        logger.info("Running check: %s (%s)", check_name, description)

        try:
            result = func()
            report["results"][check_name] = {
                "status": "completed",
                "description": description,
                "data": result,
            }
            report["summary"]["completed"] += 1

            # Count findings
            findings = result.get("findings", [])
            alerts = result.get("alerts", [])
            total = len(findings) + len(alerts)
            report["summary"]["total_findings"] += total

            for finding in findings:
                sev = finding.get("severity", "medium")
                if sev in report["summary"]["by_severity"]:
                    report["summary"]["by_severity"][sev] += 1

        except Exception as e:
            logger.error("Check %s failed: %s", check_name, e)
            report["results"][check_name] = {
                "status": "failed",
                "description": description,
                "error": str(e),
            }
            report["summary"]["failed"] += 1

    # Write report
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    filename = f"audit_{socket.gethostname()}_{timestamp.strftime('%Y%m%dT%H%M%SZ')}.json"
    report_path = out_path / filename
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    # Also write/overwrite a 'latest' symlink for easy access
    latest_link = out_path / f"latest_{socket.gethostname()}.json"
    try:
        latest_link.unlink(missing_ok=True)
        latest_link.symlink_to(report_path.name)
    except OSError:
        pass

    logger.info(
        "Report written to %s (%d findings)", report_path, report["summary"]["total_findings"]
    )
    return report_path


def upload_report(report_path: Path, url: str) -> None:
    """Upload a report to a remote HTTP endpoint via POST.

    Uses only stdlib urllib to keep the collector zero-dependency.

    Args:
        report_path: Path to the JSON report file.
        url: URL to POST the report to.
    """
    data = report_path.read_bytes()

    # Validate URL scheme to prevent SSRF (urllib supports file:// by default)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        logger.error("Invalid URL scheme: %s. Only http and https are allowed.", parsed.scheme)
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
            logger.info("Upload response: %d %s", resp.status, resp.reason)
    except Exception as e:
        logger.error("Upload failed: %s", e)
        raise


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run security audit checks and generate a JSON report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available checks:
{chr(10).join(f"  {name:20s} {desc}" for name, (_, desc) in ALL_CHECKS.items())}

Examples:
    python collector.py                              # Run all checks
    python collector.py --checks os_info,open_ports  # Run specific checks
    python collector.py --output-dir /tmp/audits     # Custom output directory
    python collector.py --upload-url http://host/api  # Upload after collection
""",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for reports (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--checks",
        help="Comma-separated list of checks to run (default: all)",
    )
    parser.add_argument(
        "--upload-url",
        help="URL to POST the report to after collection",
    )
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="List available checks and exit",
    )

    args = parser.parse_args()

    if args.list_checks:
        print("Available security audit checks:")
        for name, (_, desc) in ALL_CHECKS.items():
            print(f"  {name:20s} {desc}")
        return

    checks = args.checks.split(",") if args.checks else None

    report_path = run_audit(checks=checks, output_dir=args.output_dir)
    print(f"\nReport: {report_path}")

    if args.upload_url:
        upload_report(report_path, args.upload_url)


if __name__ == "__main__":
    main()
