"""Network and system administration tools for local infrastructure assessment.

Provides MCP tools for discovering hosts, scanning ports, checking TLS
certificates, auditing service configurations, and identifying insecure
defaults on a local network.

Target allowlist is enforced via SYSADMIN_ALLOWED_SUBNETS env var (fail-secure:
scans are denied when the env var is not set).

All tools accept ``agent_name`` as the first parameter for session isolation.
"""

import asyncio
import ipaddress
import json
import logging
import os
import platform
import re
import socket
import ssl
import time
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default timeout for network probes (seconds)
_DEFAULT_TIMEOUT = 10

# Max ports to scan in a single call to prevent abuse
_MAX_PORTS = 1024

# Max hosts returned from a discovery scan
_MAX_HOSTS = 512

# Common service ports for quick scans
_COMMON_PORTS = [
    21,
    22,
    23,
    25,
    53,
    80,
    110,
    111,
    135,
    139,
    143,
    443,
    445,
    993,
    995,
    1433,
    1521,
    3306,
    3389,
    5432,
    5900,
    6379,
    8080,
    8443,
    9200,
    27017,
]

# Well-known default credentials to check (service -> list of user/pass combos)
# Only included for defensive auditing purposes
_DEFAULT_CREDENTIALS: dict[str, list[dict[str, str]]] = {
    "ssh": [
        {"username": "root", "password": "root"},  # pragma: allowlist secret
        {"username": "admin", "password": "admin"},  # pragma: allowlist secret
        {"username": "pi", "password": "raspberry"},  # pragma: allowlist secret
    ],
    "http": [
        {"username": "admin", "password": "admin"},  # pragma: allowlist secret
        {"username": "admin", "password": "password"},  # pragma: allowlist secret
        {"username": "admin", "password": "1234"},  # pragma: allowlist secret
    ],
    "snmp": [
        {"community": "public"},
        {"community": "private"},
    ],
}

# Sensitive config file paths to check for insecure permissions
_SENSITIVE_PATHS = [
    "/etc/shadow",
    "/etc/passwd",
    "/etc/ssh/sshd_config",
    "/etc/ssl/private",
    "~/.ssh/id_rsa",
    "~/.ssh/id_ed25519",
    "~/.ssh/authorized_keys",
    "~/.env",
    "/etc/sudoers",
]

# Regex that accepts valid hostnames and IPv4/IPv6 addresses.
# Rejects values starting with '@' (dig alternate nameserver syntax) or '-'
# (dig option flags), as well as any other characters that are not valid in a
# hostname or IP literal.  Labels must be 1-63 chars of [A-Za-z0-9-] and must
# not start/end with a hyphen.  IPv6 addresses are accepted inside brackets
# (e.g. [::1]) as well as bare.
_HOSTNAME_RE = re.compile(
    r"^(?:"
    # IPv6 in brackets, e.g. [::1] or [2001:db8::1]
    r"\[(?:[0-9a-fA-F:]+)\]"
    r"|"
    # Bare IPv4, e.g. 192.168.1.1
    r"(?:\d{1,3}\.){3}\d{1,3}"
    r"|"
    # Bare IPv6, e.g. ::1 or 2001:db8::1
    r"(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}"
    r"|"
    # Hostname with optional trailing dot (FQDN), labels separated by dots
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r")$"
)


def _validate_dig_target(target: str) -> None:
    """Raise ValueError if ``target`` is not a safe hostname or IP for dig.

    Prevents argument-injection attacks where a crafted value such as
    ``@attacker.com`` (alternate nameserver) or ``-option`` (dig flag)
    is passed directly to ``asyncio.create_subprocess_exec``.

    Args:
        target: The raw target string supplied by the caller.

    Raises:
        ValueError: If ``target`` does not look like a valid hostname or IP.
    """
    if not _HOSTNAME_RE.match(target):
        raise ValueError(
            f"Invalid dig target {target!r}: must be a valid hostname or IP address. "
            "Values starting with '@' or '-' and other special characters are not allowed."
        )


# ---------------------------------------------------------------------------
# Subnet allowlist
# ---------------------------------------------------------------------------


def _check_subnet_allowed(target: str) -> None:
    """Raise ValueError if the target is not in the allowed subnets.

    Fail-secure: denies all scans when SYSADMIN_ALLOWED_SUBNETS is not set.
    """
    allowed = os.getenv("SYSADMIN_ALLOWED_SUBNETS", "")
    if not allowed:
        raise ValueError(
            "SYSADMIN_ALLOWED_SUBNETS is not set. "
            "Configure it with comma-separated CIDR subnets to allow scans "
            "(e.g. '192.168.1.0/24,10.0.0.0/8')."
        )

    prefixes = [p.strip() for p in allowed.split(",") if p.strip()]

    try:
        # Handle both single IPs and subnets
        if "/" in target:
            target_net = ipaddress.ip_network(target, strict=False)
            for prefix in prefixes:
                allowed_net = ipaddress.ip_network(prefix, strict=False)
                # Target subnet must fit entirely within an allowed subnet
                # Skip mismatched address families (IPv4 vs IPv6)
                if target_net.version != allowed_net.version:
                    continue
                if target_net.subnet_of(allowed_net):  # type: ignore[arg-type]
                    return
        else:
            target_addr = ipaddress.ip_address(target)
            for prefix in prefixes:
                allowed_net = ipaddress.ip_network(prefix, strict=False)
                if target_addr in allowed_net:
                    return
    except ValueError as e:
        raise ValueError(f"Invalid target or subnet: {e}")

    raise ValueError(
        f"Target {target!r} not in SYSADMIN_ALLOWED_SUBNETS. Allowed subnets: {prefixes}"
    )


async def _check_host_allowed(host: str) -> str:
    """Validate a hostname or IP is within allowed subnets.

    Resolves hostnames to IPs first, then checks against the allowlist.
    Returns the resolved IP so callers can reuse it (prevents DNS rebinding).
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, family=socket.AF_INET)
        if not infos:
            raise ValueError(f"Cannot resolve hostname: {host!r}")
        ip = infos[0][4][0]
    except socket.gaierror:
        raise ValueError(f"Cannot resolve hostname: {host!r}")
    _check_subnet_allowed(ip)
    return ip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _tcp_connect(host: str, port: int, timeout: float) -> dict[str, Any]:
    """Attempt a TCP connection and return result."""
    start = time.monotonic()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        elapsed = round(time.monotonic() - start, 3)
        writer.close()
        await writer.wait_closed()
        return {"port": port, "state": "open", "elapsed_seconds": elapsed}
    except TimeoutError:
        return {"port": port, "state": "filtered", "elapsed_seconds": timeout}
    except (ConnectionRefusedError, OSError):
        elapsed = round(time.monotonic() - start, 3)
        return {"port": port, "state": "closed", "elapsed_seconds": elapsed}


async def _grab_banner(host: str, port: int, timeout: float = 3.0) -> str | None:
    """Attempt to grab a service banner from an open port."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        # Some services send a banner immediately; others need a nudge
        try:
            data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
        except TimeoutError:
            # Try sending a basic probe
            writer.write(b"\r\n")
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=2.0)
            except TimeoutError:
                data = b""
        writer.close()
        await writer.wait_closed()
        if data:
            return data.decode("utf-8", errors="replace").strip()[:500]
        return None
    except Exception:
        return None


def _read_text_file(path: str) -> str:
    """Read a text file (for use with asyncio.to_thread)."""
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def network_discover_hosts(
    agent_name: str,
    subnet: str,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Discover live hosts on a local subnet using TCP probes.

    Scans common ports (80, 443, 22, 445) on each IP in the subnet to
    determine if the host is alive. Does not require raw sockets or root.

    Args:
        agent_name: Injected by framework for session isolation.
        subnet: CIDR notation subnet (e.g. '192.168.1.0/24').
        timeout: Per-host probe timeout in seconds.

    Returns:
        Dict with discovered hosts, their responding ports, and scan metadata.
    """
    _check_subnet_allowed(subnet)

    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        return {"status": "error", "message": f"Invalid subnet: {e}"}

    num_hosts = network.num_addresses - 2  # exclude network and broadcast
    if num_hosts > _MAX_HOSTS:
        return {
            "status": "error",
            "message": f"Subnet too large: {num_hosts} hosts (max {_MAX_HOSTS}). Use a smaller CIDR.",
        }

    start = time.monotonic()
    alive_hosts = []
    probe_ports = [80, 443, 22, 445]

    async def _probe_host(ip: str) -> dict[str, Any] | None:
        open_ports = []
        for port in probe_ports:
            result = await _tcp_connect(ip, port, timeout)
            if result["state"] == "open":
                open_ports.append(port)
        if open_ports:
            try:
                hostname = socket.getfqdn(ip)
            except Exception:
                hostname = ip
            return {
                "ip": ip,
                "hostname": hostname if hostname != ip else None,
                "open_probe_ports": open_ports,
            }
        return None

    # Scan in batches to avoid overwhelming the network
    batch_size = 50
    hosts = [str(ip) for ip in network.hosts()]
    for i in range(0, len(hosts), batch_size):
        batch = hosts[i : i + batch_size]
        tasks = [_probe_host(ip) for ip in batch]
        results = await asyncio.gather(*tasks)
        for result in results:
            if result:
                alive_hosts.append(result)

    elapsed = round(time.monotonic() - start, 3)
    return {
        "status": "success",
        "subnet": subnet,
        "total_ips_scanned": len(hosts),
        "hosts_found": len(alive_hosts),
        "hosts": alive_hosts,
        "scan_seconds": elapsed,
    }


async def network_scan_ports(
    agent_name: str,
    host: str,
    ports: str = "common",
    timeout: float = 2.0,
    grab_banners: bool = False,
) -> dict[str, Any]:
    """Scan TCP ports on a target host.

    Args:
        agent_name: Injected by framework for session isolation.
        host: Target hostname or IP address.
        ports: Port specification - 'common' for well-known ports, or a range
               like '1-1024', or comma-separated like '22,80,443'.
        timeout: Per-port connection timeout in seconds.
        grab_banners: If True, attempt to read service banners from open ports.

    Returns:
        Dict with open/closed/filtered port counts and per-port details.
    """
    resolved_ip = await _check_host_allowed(host)

    # Parse port specification
    port_list: list[int] = []
    if ports == "common":
        port_list = list(_COMMON_PORTS)
    elif "-" in ports:
        parts = ports.split("-")
        try:
            start_port = int(parts[0])
            end_port = int(parts[1])
            requested = end_port - start_port + 1
            if requested > _MAX_PORTS:
                return {
                    "status": "error",
                    "message": (
                        f"Port range too large: {requested} ports requested "
                        f"(max {_MAX_PORTS}). Use a smaller range."
                    ),
                }
            port_list = list(range(start_port, end_port + 1))
        except (ValueError, IndexError):
            return {"status": "error", "message": f"Invalid port range: {ports!r}"}
    else:
        try:
            port_list = [int(p.strip()) for p in ports.split(",") if p.strip()]
        except ValueError:
            return {"status": "error", "message": f"Invalid port list: {ports!r}"}

    if len(port_list) > _MAX_PORTS:
        return {
            "status": "error",
            "message": f"Too many ports: {len(port_list)} (max {_MAX_PORTS})",
        }

    start = time.monotonic()

    # Scan ports concurrently in batches
    results = []
    batch_size = 100
    for i in range(0, len(port_list), batch_size):
        batch = port_list[i : i + batch_size]
        tasks = [_tcp_connect(resolved_ip, port, timeout) for port in batch]
        results.extend(await asyncio.gather(*tasks))

    # Optionally grab banners for open ports
    if grab_banners:
        for result in results:
            if result["state"] == "open":
                banner = await _grab_banner(resolved_ip, result["port"])
                if banner:
                    result["banner"] = banner

    elapsed = round(time.monotonic() - start, 3)

    open_ports = [r for r in results if r["state"] == "open"]
    closed_count = sum(1 for r in results if r["state"] == "closed")
    filtered_count = sum(1 for r in results if r["state"] == "filtered")

    return {
        "status": "success",
        "host": host,
        "resolved_ip": resolved_ip,
        "ports_scanned": len(port_list),
        "open": len(open_ports),
        "closed": closed_count,
        "filtered": filtered_count,
        "open_ports": open_ports,
        "all_results": results,
        "scan_seconds": elapsed,
    }


async def network_check_tls(
    agent_name: str,
    host: str,
    port: int = 443,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Inspect TLS/SSL configuration of a service.

    Checks certificate validity, expiration, protocol version, cipher suite,
    and common misconfigurations.

    Args:
        agent_name: Injected by framework for session isolation.
        host: Target hostname or IP address.
        port: Port to connect on (default 443).
        timeout: Connection timeout in seconds.

    Returns:
        Dict with certificate details, protocol info, and security findings.
    """
    resolved_ip = await _check_host_allowed(host)

    findings: list[dict[str, str]] = []

    try:
        context = ssl.create_default_context()
        # We still want to inspect even if cert is bad
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        conn = await asyncio.wait_for(
            asyncio.open_connection(resolved_ip, port, ssl=context),
            timeout=timeout,
        )
        reader, writer = conn
        ssl_object = writer.get_extra_info("ssl_object")

        cert_info: dict[str, Any] = {}
        protocol_info: dict[str, Any] = {}

        if ssl_object:
            # Protocol and cipher
            protocol_info["version"] = ssl_object.version()
            cipher = ssl_object.cipher()
            if cipher:
                protocol_info["cipher_name"] = cipher[0]
                protocol_info["cipher_protocol"] = cipher[1]
                protocol_info["cipher_bits"] = cipher[2]

            # Check for weak protocols
            version = ssl_object.version() or ""
            if "TLSv1.0" in version or "SSLv" in version:
                findings.append(
                    {
                        "severity": "critical",
                        "finding": f"Weak protocol: {version}",
                        "recommendation": "Upgrade to TLS 1.2 or TLS 1.3",
                    }
                )
            elif "TLSv1.1" in version:
                findings.append(
                    {
                        "severity": "high",
                        "finding": f"Deprecated protocol: {version}",
                        "recommendation": "Upgrade to TLS 1.2 or TLS 1.3",
                    }
                )

            # Get peer certificate
            peer_cert = ssl_object.getpeercert()
            if peer_cert:
                cert_info["subject"] = dict(x[0] for x in peer_cert.get("subject", ()) if x)
                cert_info["issuer"] = dict(x[0] for x in peer_cert.get("issuer", ()) if x)
                cert_info["serial_number"] = peer_cert.get("serialNumber")
                cert_info["not_before"] = peer_cert.get("notBefore")
                cert_info["not_after"] = peer_cert.get("notAfter")

                # Check for SAN
                san = peer_cert.get("subjectAltName", ())
                cert_info["san"] = [entry[1] for entry in san]

                # Check expiration
                not_after_str = peer_cert.get("notAfter", "")
                if not_after_str:
                    try:
                        expiry = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
                            tzinfo=UTC
                        )
                        days_remaining = (expiry - datetime.now(UTC)).days
                        cert_info["days_until_expiry"] = days_remaining
                        if days_remaining < 0:
                            findings.append(
                                {
                                    "severity": "critical",
                                    "finding": f"Certificate expired {abs(days_remaining)} days ago",
                                    "recommendation": "Renew the certificate immediately",
                                }
                            )
                        elif days_remaining < 30:
                            findings.append(
                                {
                                    "severity": "high",
                                    "finding": f"Certificate expires in {days_remaining} days",
                                    "recommendation": "Renew the certificate soon",
                                }
                            )
                    except ValueError:
                        pass  # Unable to parse date

            # Try to verify with proper validation
            try:
                verify_ctx = ssl.create_default_context()
                verify_conn = await asyncio.wait_for(
                    asyncio.open_connection(host, port, ssl=verify_ctx),
                    timeout=timeout,
                )
                _, verify_writer = verify_conn
                cert_info["trusted"] = True
                verify_writer.close()
                await verify_writer.wait_closed()
            except ssl.SSLCertVerificationError as e:
                cert_info["trusted"] = False
                findings.append(
                    {
                        "severity": "high",
                        "finding": f"Certificate verification failed: {e}",
                        "recommendation": "Use a certificate from a trusted CA",
                    }
                )
            except Exception:
                cert_info["trusted"] = "unknown"

        writer.close()
        await writer.wait_closed()

        return {
            "status": "success",
            "host": host,
            "port": port,
            "certificate": cert_info,
            "protocol": protocol_info,
            "findings": findings,
            "findings_count": len(findings),
        }

    except TimeoutError:
        return {
            "status": "error",
            "host": host,
            "port": port,
            "message": f"Connection timed out after {timeout}s",
        }
    except ConnectionRefusedError:
        return {
            "status": "error",
            "host": host,
            "port": port,
            "message": "Connection refused - port may not be open or TLS not enabled",
        }
    except Exception as e:
        return {
            "status": "error",
            "host": host,
            "port": port,
            "message": str(e),
        }


async def network_grab_banners(
    agent_name: str,
    host: str,
    ports: str = "common",
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Connect to open ports and retrieve service banners.

    Service banners often reveal software versions and configuration details
    that may indicate insecure or outdated software.

    Args:
        agent_name: Injected by framework for session isolation.
        host: Target hostname or IP address.
        ports: Port specification - 'common', range like '1-100', or comma list.
        timeout: Per-port timeout in seconds.

    Returns:
        Dict with per-port banner data and version info detected.
    """
    resolved_ip = await _check_host_allowed(host)

    # First do a quick port scan to find open ports
    scan_result = await network_scan_ports(agent_name, host, ports, timeout=timeout)
    if scan_result.get("status") != "success":
        return scan_result

    open_ports = [r["port"] for r in scan_result.get("open_ports", [])]
    if not open_ports:
        return {
            "status": "success",
            "host": host,
            "message": "No open ports found to grab banners from",
            "banners": [],
        }
    banners = []
    for port in open_ports:
        banner = await _grab_banner(resolved_ip, port, timeout)
        entry: dict[str, Any] = {"port": port, "banner": banner}
        if banner:
            # Try to detect common service patterns
            lower = banner.lower()
            if "ssh" in lower:
                entry["service"] = "SSH"
            elif "http" in lower or "html" in lower:
                entry["service"] = "HTTP"
            elif "smtp" in lower or "postfix" in lower or "sendmail" in lower:
                entry["service"] = "SMTP"
            elif "ftp" in lower:
                entry["service"] = "FTP"
            elif "mysql" in lower:
                entry["service"] = "MySQL"
            elif "postgresql" in lower:
                entry["service"] = "PostgreSQL"
            elif "redis" in lower:
                entry["service"] = "Redis"
            elif "mongodb" in lower or "mongod" in lower:
                entry["service"] = "MongoDB"
        banners.append(entry)

    return {
        "status": "success",
        "host": host,
        "banners": banners,
        "ports_with_banners": sum(1 for b in banners if b.get("banner")),
    }


async def network_check_dns(
    agent_name: str,
    target: str,
    record_types: list[str] | None = None,
) -> dict[str, Any]:
    """Perform DNS lookups and check for common misconfigurations.

    Checks forward/reverse resolution, DNSSEC, and queries multiple record types.

    Args:
        agent_name: Injected by framework for session isolation.
        target: Hostname or IP to query.
        record_types: DNS record types to query (default: A, AAAA, MX, NS, TXT, SOA).

    Returns:
        Dict with DNS records, reverse lookup results, and findings.
    """
    _validate_dig_target(target)
    await _check_host_allowed(target)

    _VALID_RECORD_TYPES = {"A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "PTR", "SRV", "CAA"}
    if record_types is None:
        record_types = ["A", "AAAA", "MX", "NS", "TXT", "SOA"]
    else:
        record_types = [rt for rt in record_types if rt in _VALID_RECORD_TYPES]

    findings: list[dict[str, str]] = []
    records: dict[str, list[str]] = {}

    # Forward lookup
    loop = asyncio.get_running_loop()
    try:
        addrs = await loop.getaddrinfo(target, None)
        ips = list({addr[4][0] for addr in addrs})
        records["resolved_ips"] = ips
    except socket.gaierror as e:
        records["resolved_ips"] = []
        findings.append(
            {
                "severity": "info",
                "finding": f"DNS resolution failed: {e}",
                "recommendation": "Verify the hostname is correct",
            }
        )

    # Reverse lookup for IPs
    reverse_results = []
    for ip in records.get("resolved_ips", []):
        try:
            hostname = socket.gethostbyaddr(ip)
            reverse_results.append({"ip": ip, "hostname": hostname[0]})
        except socket.herror:
            reverse_results.append({"ip": ip, "hostname": None})
            findings.append(
                {
                    "severity": "low",
                    "finding": f"No reverse DNS (PTR) record for {ip}",
                    "recommendation": "Configure reverse DNS for better email deliverability and auditing",
                }
            )
    records["reverse_dns"] = reverse_results

    # Use dig/nslookup via subprocess for detailed record types
    for rtype in record_types:
        try:
            proc = await asyncio.create_subprocess_exec(
                "dig",
                "+short",
                target,
                rtype,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            results = [line.strip() for line in stdout.decode().strip().split("\n") if line.strip()]
            if results:
                records[rtype] = results
        except (TimeoutError, FileNotFoundError):
            # dig not available, skip detailed lookups
            break

    # Check for common issues
    txt_records = records.get("TXT", [])
    has_spf = any("v=spf1" in r for r in txt_records)
    has_dmarc = any("v=DMARC1" in r for r in txt_records)

    if not has_spf and txt_records:
        findings.append(
            {
                "severity": "medium",
                "finding": "No SPF record found",
                "recommendation": "Add an SPF TXT record to prevent email spoofing",
            }
        )
    if not has_dmarc and txt_records:
        findings.append(
            {
                "severity": "medium",
                "finding": "No DMARC record found",
                "recommendation": "Add a DMARC TXT record for email authentication policy",
            }
        )

    return {
        "status": "success",
        "target": target,
        "records": records,
        "findings": findings,
        "findings_count": len(findings),
    }


async def system_get_info(
    agent_name: str,
) -> dict[str, Any]:
    """Collect local system information for security assessment.

    Gathers OS version, hostname, uptime, network interfaces, listening
    ports, and other system details. No external network access required.

    Args:
        agent_name: Injected by framework for session isolation.

    Returns:
        Dict with system info including OS, network interfaces, and listening services.
    """
    info: dict[str, Any] = {}

    # Basic system info
    info["hostname"] = platform.node()
    info["os"] = platform.system()
    info["os_release"] = platform.release()
    info["os_version"] = platform.version()
    info["architecture"] = platform.machine()
    info["python_version"] = platform.python_version()

    # Network interfaces
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip",
            "-j",
            "addr",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0:
            try:
                info["interfaces"] = json.loads(stdout.decode())
            except json.JSONDecodeError:
                info["interfaces"] = stdout.decode().strip()
    except (TimeoutError, FileNotFoundError):
        # Fallback: try ifconfig
        try:
            proc = await asyncio.create_subprocess_exec(
                "ifconfig",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            info["interfaces_raw"] = stdout.decode().strip()[:3000]
        except (TimeoutError, FileNotFoundError):
            info["interfaces"] = "unable to enumerate"

    # Listening services
    try:
        proc = await asyncio.create_subprocess_exec(
            "ss",
            "-tlnp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        if proc.returncode == 0:
            info["listening_services"] = stdout.decode().strip()[:5000]
    except (TimeoutError, FileNotFoundError):
        try:
            proc = await asyncio.create_subprocess_exec(
                "netstat",
                "-tlnp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            info["listening_services"] = stdout.decode().strip()[:5000]
        except (TimeoutError, FileNotFoundError):
            info["listening_services"] = "unable to enumerate"

    # Uptime
    try:
        proc = await asyncio.create_subprocess_exec(
            "uptime",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        info["uptime"] = stdout.decode().strip()
    except (TimeoutError, FileNotFoundError):
        pass

    return {"status": "success", **info}


async def system_check_ssh_config(
    agent_name: str,
    config_path: str = "/etc/ssh/sshd_config",
) -> dict[str, Any]:
    """Audit SSH server configuration for security issues.

    Checks for common SSH misconfigurations including root login, password
    authentication, weak key exchange algorithms, and protocol version.

    Args:
        agent_name: Injected by framework for session isolation.
        config_path: Path to sshd_config (default: /etc/ssh/sshd_config).

    Returns:
        Dict with parsed config values and security findings.
    """
    # Validate config_path to prevent arbitrary file read
    _ALLOWED_SSH_CONFIG_DIR = "/etc/ssh/"
    resolved = os.path.realpath(config_path)
    if not resolved.startswith(_ALLOWED_SSH_CONFIG_DIR):
        return {
            "status": "error",
            "message": f"config_path must be under {_ALLOWED_SSH_CONFIG_DIR}, got {config_path!r}",
        }

    findings: list[dict[str, str]] = []
    config: dict[str, str] = {}

    try:
        content = await asyncio.to_thread(_read_text_file, resolved)
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                config[parts[0]] = parts[1]
    except FileNotFoundError:
        return {"status": "error", "message": f"Config file not found: {resolved}"}
    except PermissionError:
        return {"status": "error", "message": f"Permission denied reading {resolved}"}

    # Security checks
    permit_root_raw = config.get("PermitRootLogin")
    if permit_root_raw is not None:
        permit_root = permit_root_raw.lower()
        if permit_root == "yes":
            findings.append(
                {
                    "severity": "critical",
                    "finding": f"PermitRootLogin is {permit_root!r}",
                    "recommendation": "Set PermitRootLogin to 'no' and use sudo instead",
                }
            )
        elif permit_root in ("without-password", "prohibit-password"):
            findings.append(
                {
                    "severity": "low",
                    "finding": f"PermitRootLogin is {permit_root!r} (key-based root login allowed)",
                    "recommendation": "Consider setting PermitRootLogin to 'no' and use sudo instead",
                }
            )

    password_auth = config.get("PasswordAuthentication", "yes").lower()
    if password_auth == "yes":  # nosec B105  # pragma: allowlist secret
        findings.append(
            {
                "severity": "high",
                "finding": "Password authentication is enabled",
                "recommendation": "Disable PasswordAuthentication and use SSH keys",
            }
        )

    x11_forwarding = config.get("X11Forwarding", "no").lower()
    if x11_forwarding == "yes":
        findings.append(
            {
                "severity": "low",
                "finding": "X11 forwarding is enabled",
                "recommendation": "Disable X11Forwarding unless needed",
            }
        )

    max_auth_tries = config.get("MaxAuthTries", "6")
    try:
        if int(max_auth_tries) > 3:
            findings.append(
                {
                    "severity": "medium",
                    "finding": f"MaxAuthTries is {max_auth_tries} (default 6)",
                    "recommendation": "Set MaxAuthTries to 3 to limit brute-force attempts",
                }
            )
    except ValueError:
        pass

    permit_empty = config.get("PermitEmptyPasswords", "no").lower()
    if permit_empty == "yes":
        findings.append(
            {
                "severity": "critical",
                "finding": "Empty passwords are permitted",
                "recommendation": "Set PermitEmptyPasswords to 'no'",
            }
        )

    if "Protocol" in config and config["Protocol"] != "2":
        findings.append(
            {
                "severity": "critical",
                "finding": f"SSH protocol version {config['Protocol']} is enabled",
                "recommendation": "Use Protocol 2 only",
            }
        )

    return {
        "status": "success",
        "config_path": config_path,
        "config": config,
        "findings": findings,
        "findings_count": len(findings),
    }


async def system_check_file_permissions(
    agent_name: str,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Check permissions on sensitive files and directories.

    Identifies world-readable/writable sensitive files like SSH keys,
    shadow files, and environment files.

    Args:
        agent_name: Injected by framework for session isolation.
        paths: List of file paths to check (default: common sensitive paths).

    Returns:
        Dict with per-file permission info and security findings.
    """
    if paths is None:
        paths = list(_SENSITIVE_PATHS)
    else:
        # Validate caller-supplied paths against the sensitive paths allowlist
        allowed_prefixes = ("/etc/", "~/.ssh/", "~/.env")
        validated = []
        for p in paths:
            resolved = os.path.realpath(os.path.expanduser(p))
            expanded_prefixes = [
                os.path.realpath(os.path.expanduser(pfx)) for pfx in allowed_prefixes
            ]
            if any(resolved.startswith(ep) for ep in expanded_prefixes):
                validated.append(p)
        paths = validated

    findings: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []

    for path in paths:
        expanded = os.path.expanduser(path)
        try:
            stat = os.stat(expanded)
            mode = stat.st_mode
            mode_str = oct(mode)[-3:]
            entry: dict[str, Any] = {
                "path": expanded,
                "exists": True,
                "permissions": mode_str,
                "owner_uid": stat.st_uid,
                "group_gid": stat.st_gid,
            }

            # Check for world-readable
            if mode & 0o004:
                severity = (
                    "critical"
                    if "shadow" in path or "private" in path or "id_" in path
                    else "medium"
                )
                findings.append(
                    {
                        "severity": severity,
                        "finding": f"{expanded} is world-readable (mode {mode_str})",
                        "recommendation": f"chmod o-r {expanded}",
                    }
                )

            # Check for world-writable
            if mode & 0o002:
                findings.append(
                    {
                        "severity": "critical",
                        "finding": f"{expanded} is world-writable (mode {mode_str})",
                        "recommendation": f"chmod o-w {expanded}",
                    }
                )

            # SSH keys should be 600
            if ("id_rsa" in path or "id_ed25519" in path) and mode_str != "600":
                findings.append(
                    {
                        "severity": "high",
                        "finding": f"SSH private key {expanded} has loose permissions (mode {mode_str})",
                        "recommendation": f"chmod 600 {expanded}",
                    }
                )

            results.append(entry)

        except FileNotFoundError:
            results.append({"path": expanded, "exists": False})
        except PermissionError:
            results.append({"path": expanded, "exists": True, "readable": False})

    return {
        "status": "success",
        "files": results,
        "findings": findings,
        "findings_count": len(findings),
    }


async def system_check_firewall(
    agent_name: str,
) -> dict[str, Any]:
    """Check firewall configuration and identify overly permissive rules.

    Reads iptables, nftables, or ufw rules and flags potential issues
    like ACCEPT ALL on INPUT, wide-open port ranges, or disabled firewalls.

    Args:
        agent_name: Injected by framework for session isolation.

    Returns:
        Dict with firewall rules and security findings.
    """
    findings: list[dict[str, str]] = []
    rules: dict[str, Any] = {}

    # Try ufw first
    try:
        proc = await asyncio.create_subprocess_exec(
            "ufw",
            "status",
            "verbose",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = stdout.decode().strip()
        if output:
            rules["ufw"] = output[:5000]
            if "inactive" in output.lower():
                findings.append(
                    {
                        "severity": "high",
                        "finding": "UFW firewall is inactive",
                        "recommendation": "Enable the firewall: sudo ufw enable",
                    }
                )
    except (TimeoutError, FileNotFoundError):
        pass

    # Try iptables
    try:
        proc = await asyncio.create_subprocess_exec(
            "iptables",
            "-L",
            "-n",
            "--line-numbers",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = stdout.decode().strip()
        if output:
            rules["iptables"] = output[:5000]
            # Check for overly permissive rules
            if "ACCEPT     all" in output and "0.0.0.0/0" in output:
                findings.append(
                    {
                        "severity": "medium",
                        "finding": "iptables has ACCEPT ALL rule for 0.0.0.0/0",
                        "recommendation": "Review and restrict firewall rules to specific ports/sources",
                    }
                )
    except (TimeoutError, FileNotFoundError):
        pass

    # Try nftables
    try:
        proc = await asyncio.create_subprocess_exec(
            "nft",
            "list",
            "ruleset",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = stdout.decode().strip()
        if output:
            rules["nftables"] = output[:5000]
    except (TimeoutError, FileNotFoundError):
        pass

    if not rules:
        findings.append(
            {
                "severity": "high",
                "finding": "No firewall tool found (ufw, iptables, nftables)",
                "recommendation": "Install and configure a firewall",
            }
        )

    return {
        "status": "success",
        "rules": rules,
        "findings": findings,
        "findings_count": len(findings),
    }


async def network_check_default_credentials(
    agent_name: str,
    host: str,
    services: list[str] | None = None,
) -> dict[str, Any]:
    """Check for default/common credentials on discovered services.

    Tests well-known default credentials against services like SSH, HTTP
    admin panels, and SNMP community strings. This is for defensive
    auditing of your own infrastructure.

    Args:
        agent_name: Injected by framework for session isolation.
        host: Target hostname or IP address.
        services: Services to check (default: auto-detect from open ports).
            Supported: 'ssh', 'http', 'snmp'.

    Returns:
        Dict with per-service results (credentials are redacted in output).
    """
    await _check_host_allowed(host)

    results: list[dict[str, Any]] = []

    # If no services specified, auto-detect based on open ports
    if not services:
        scan = await network_scan_ports(agent_name, host, "22,80,161,443,8080")
        open_ports = {r["port"] for r in scan.get("open_ports", [])}
        services = []
        if 22 in open_ports:
            services.append("ssh")
        if open_ports & {80, 443, 8080}:
            services.append("http")
        if 161 in open_ports:
            services.append("snmp")

    for service in services:
        creds = _DEFAULT_CREDENTIALS.get(service, [])
        service_result: dict[str, Any] = {
            "service": service,
            "credentials_tested": len(creds),
            "vulnerable": False,
            "details": [],
        }

        if service == "ssh":
            for cred in creds:
                # Test SSH connection using asyncio subprocess
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "sshpass",
                        "-p",
                        cred["password"],
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        "-o",
                        "ConnectTimeout=5",
                        "-o",
                        "BatchMode=no",
                        f"{cred['username']}@{host}",
                        "echo",
                        "auth_success",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                    if "auth_success" in stdout.decode():
                        service_result["vulnerable"] = True
                        service_result["details"].append(
                            {
                                "username": cred["username"],
                                "password": "[REDACTED - default credential]",
                                "result": "LOGIN SUCCESSFUL - VULNERABLE",
                            }
                        )
                    else:
                        service_result["details"].append(
                            {
                                "username": cred["username"],
                                "password": "[REDACTED]",
                                "result": "login failed (good)",
                            }
                        )
                except (TimeoutError, FileNotFoundError):
                    service_result["details"].append(
                        {
                            "note": "sshpass not installed - cannot test SSH credentials",
                        }
                    )
                    break

        elif service == "snmp":
            for cred in creds:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "snmpwalk",
                        "-v2c",
                        "-c",
                        cred["community"],
                        host,
                        "system",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                    if proc.returncode == 0 and stdout.decode().strip():
                        service_result["vulnerable"] = True
                        service_result["details"].append(
                            {
                                "community_string": "[REDACTED - default community]",
                                "result": "ACCESSIBLE - VULNERABLE",
                            }
                        )
                    else:
                        service_result["details"].append(
                            {
                                "community_string": "[REDACTED]",
                                "result": "not accessible (good)",
                            }
                        )
                except (TimeoutError, FileNotFoundError):
                    service_result["details"].append(
                        {
                            "note": "snmpwalk not installed - cannot test SNMP community strings",
                        }
                    )
                    break

        elif service == "http":
            # Check for common admin panel paths with default creds
            import httpx

            admin_paths = ["/admin", "/login", "/admin/login", "/manager/html"]
            for path in admin_paths:
                for cred in creds:
                    try:
                        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                            url = f"http://{host}{path}"
                            resp = await client.post(
                                url,
                                data={"username": cred["username"], "password": cred["password"]},
                            )
                            # Heuristic: if we get 200 and no "invalid" in response, might be vulnerable
                            body = resp.text.lower()
                            if (
                                resp.status_code == 200
                                and "invalid" not in body
                                and "error" not in body
                                and "failed" not in body
                            ):
                                service_result["details"].append(
                                    {
                                        "path": path,
                                        "username": cred["username"],
                                        "password": "[REDACTED - default credential]",
                                        "result": "POSSIBLE LOGIN - NEEDS MANUAL VERIFICATION",
                                        "status_code": resp.status_code,
                                    }
                                )
                    except Exception:  # nosec B110 - intentionally ignoring HTTP probe errors
                        pass

        results.append(service_result)

    vulnerable_services = [r["service"] for r in results if r.get("vulnerable")]
    return {
        "status": "success",
        "host": host,
        "services_checked": len(results),
        "vulnerable_services": vulnerable_services,
        "results": results,
    }


async def network_generate_report(
    agent_name: str,
    host: str | None = None,
    subnet: str | None = None,
    include_scans: list[str] | None = None,
) -> dict[str, Any]:
    """Run a comprehensive security assessment and generate a report.

    Orchestrates multiple scans against a host or subnet and compiles
    findings into a prioritized report with remediation recommendations.

    Args:
        agent_name: Injected by framework for session isolation.
        host: Target host to assess (mutually exclusive with subnet).
        subnet: Target subnet to assess (mutually exclusive with host).
        include_scans: Scans to include. Default: all applicable.
            Options: 'ports', 'tls', 'banners', 'dns', 'ssh_config',
            'file_permissions', 'firewall', 'default_creds'.

    Returns:
        Dict with aggregated findings sorted by severity and remediation steps.
    """
    if not host and not subnet:
        return {"status": "error", "message": "Provide either host or subnet"}

    all_findings: list[dict[str, Any]] = []
    scan_results: dict[str, Any] = {}

    if include_scans is None:
        include_scans = [
            "ports",
            "tls",
            "banners",
            "dns",
            "ssh_config",
            "file_permissions",
            "firewall",
        ]
        if host:
            include_scans.append("default_creds")

    # Host-level scans
    target_host = host
    if subnet and not host:
        # Discover hosts first
        discovery = await network_discover_hosts(agent_name, subnet)
        scan_results["discovery"] = discovery
        all_findings.extend({"source": "discovery", **f} for f in discovery.get("findings", []))
        # Use first discovered host for detailed scans (user should run per-host)
        hosts = discovery.get("hosts", [])
        if hosts:
            target_host = hosts[0]["ip"]

    if target_host:
        if "ports" in include_scans:
            result = await network_scan_ports(agent_name, target_host, "common", grab_banners=True)
            scan_results["port_scan"] = result

        if "tls" in include_scans:
            result = await network_check_tls(agent_name, target_host)
            scan_results["tls"] = result
            all_findings.extend({"source": "tls", **f} for f in result.get("findings", []))

        if "dns" in include_scans:
            result = await network_check_dns(agent_name, target_host)
            scan_results["dns"] = result
            all_findings.extend({"source": "dns", **f} for f in result.get("findings", []))

        if "default_creds" in include_scans:
            result = await network_check_default_credentials(agent_name, target_host)
            scan_results["default_credentials"] = result
            for svc in result.get("results", []):
                if svc.get("vulnerable"):
                    all_findings.append(
                        {
                            "source": "default_credentials",
                            "severity": "critical",
                            "finding": f"Default credentials found on {svc['service']}",
                            "recommendation": f"Change default credentials for {svc['service']} immediately",
                        }
                    )

    # Local system scans (always applicable)
    if "ssh_config" in include_scans:
        result = await system_check_ssh_config(agent_name)
        scan_results["ssh_config"] = result
        all_findings.extend({"source": "ssh_config", **f} for f in result.get("findings", []))

    if "file_permissions" in include_scans:
        result = await system_check_file_permissions(agent_name)
        scan_results["file_permissions"] = result
        all_findings.extend({"source": "file_permissions", **f} for f in result.get("findings", []))

    if "firewall" in include_scans:
        result = await system_check_firewall(agent_name)
        scan_results["firewall"] = result
        all_findings.extend({"source": "firewall", **f} for f in result.get("findings", []))

    # Sort findings by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity", "info"), 5))

    severity_counts = {}
    for f in all_findings:
        sev = f.get("severity", "info")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    return {
        "status": "success",
        "target": host or subnet,
        "scans_performed": list(scan_results.keys()),
        "total_findings": len(all_findings),
        "severity_counts": severity_counts,
        "findings": all_findings,
        "scan_details": scan_results,
    }


# ---------------------------------------------------------------------------
# Tool schemas for MCP server auto-registration
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "network_discover_hosts",
        "description": (
            "Discover live hosts on a local subnet using TCP probes on common "
            "ports (80, 443, 22, 445). Returns alive hosts with responding ports "
            "and hostnames. Requires SYSADMIN_ALLOWED_SUBNETS env var."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subnet": {
                    "type": "string",
                    "description": "CIDR notation subnet (e.g. '192.168.1.0/24')",
                },
                "timeout": {
                    "type": "number",
                    "default": 1.0,
                    "description": "Per-host probe timeout in seconds",
                },
            },
            "required": ["subnet"],
        },
        "handler": network_discover_hosts,
    },
    {
        "name": "network_scan_ports",
        "description": (
            "Scan TCP ports on a target host. Supports common ports, ranges "
            "(e.g. '1-1024'), or comma-separated lists. Optionally grabs service "
            "banners from open ports. Requires SYSADMIN_ALLOWED_SUBNETS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target hostname or IP address",
                },
                "ports": {
                    "type": "string",
                    "default": "common",
                    "description": "Port spec: 'common', range '1-1024', or list '22,80,443'",
                },
                "timeout": {
                    "type": "number",
                    "default": 2.0,
                    "description": "Per-port connection timeout in seconds",
                },
                "grab_banners": {
                    "type": "boolean",
                    "default": False,
                    "description": "Attempt to read service banners from open ports",
                },
            },
            "required": ["host"],
        },
        "handler": network_scan_ports,
    },
    {
        "name": "network_check_tls",
        "description": (
            "Inspect TLS/SSL configuration of a service. Checks certificate "
            "validity, expiration, protocol version, cipher suites, and trust "
            "chain. Flags weak protocols (TLS 1.0/1.1), expired certs, and "
            "untrusted issuers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target hostname or IP address",
                },
                "port": {
                    "type": "integer",
                    "default": 443,
                    "description": "Port to connect on (default 443)",
                },
                "timeout": {
                    "type": "number",
                    "default": 10.0,
                    "description": "Connection timeout in seconds",
                },
            },
            "required": ["host"],
        },
        "handler": network_check_tls,
    },
    {
        "name": "network_grab_banners",
        "description": (
            "Connect to open ports and retrieve service banners. Banners often "
            "reveal software versions and misconfigurations. Automatically detects "
            "common services (SSH, HTTP, SMTP, FTP, MySQL, Redis, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target hostname or IP address",
                },
                "ports": {
                    "type": "string",
                    "default": "common",
                    "description": "Port spec: 'common', range '1-100', or list '22,80,443'",
                },
                "timeout": {
                    "type": "number",
                    "default": 3.0,
                    "description": "Per-port timeout in seconds",
                },
            },
            "required": ["host"],
        },
        "handler": network_grab_banners,
    },
    {
        "name": "network_check_dns",
        "description": (
            "Perform DNS lookups and check for common misconfigurations. Queries "
            "multiple record types (A, AAAA, MX, NS, TXT, SOA), checks reverse "
            "DNS, and flags missing SPF/DMARC records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Hostname or IP to query",
                },
                "record_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "DNS record types to query (default: A, AAAA, MX, NS, TXT, SOA)",
                },
            },
            "required": ["target"],
        },
        "handler": network_check_dns,
    },
    {
        "name": "system_get_info",
        "description": (
            "Collect local system information for security assessment. Gathers "
            "OS version, hostname, network interfaces, listening ports/services, "
            "and uptime. No external network access required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": system_get_info,
    },
    {
        "name": "system_check_ssh_config",
        "description": (
            "Audit SSH server configuration for security issues. Checks for root "
            "login, password authentication, empty passwords, X11 forwarding, "
            "protocol version, and MaxAuthTries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "config_path": {
                    "type": "string",
                    "default": "/etc/ssh/sshd_config",
                    "description": "Path to sshd_config file",
                },
            },
        },
        "handler": system_check_ssh_config,
    },
    {
        "name": "system_check_file_permissions",
        "description": (
            "Check permissions on sensitive files and directories. Identifies "
            "world-readable/writable sensitive files like SSH keys, /etc/shadow, "
            "and .env files. Flags SSH keys with loose permissions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to check (default: common sensitive paths)",
                },
            },
        },
        "handler": system_check_file_permissions,
    },
    {
        "name": "system_check_firewall",
        "description": (
            "Check firewall configuration and identify issues. Reads ufw, "
            "iptables, or nftables rules and flags disabled firewalls or "
            "overly permissive ACCEPT ALL rules."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
        "handler": system_check_firewall,
    },
    {
        "name": "network_check_default_credentials",
        "description": (
            "Check for default/common credentials on discovered services. Tests "
            "well-known defaults against SSH, HTTP admin panels, and SNMP. "
            "For defensive auditing of your own infrastructure. Credentials are "
            "redacted in output. Requires SYSADMIN_ALLOWED_SUBNETS."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target hostname or IP address",
                },
                "services": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["ssh", "http", "snmp"],
                    },
                    "description": "Services to check (default: auto-detect from open ports)",
                },
            },
            "required": ["host"],
        },
        "handler": network_check_default_credentials,
    },
    {
        "name": "network_generate_report",
        "description": (
            "Run a comprehensive security assessment and generate a prioritized "
            "report. Orchestrates port scans, TLS checks, banner grabs, DNS "
            "analysis, SSH config audit, file permission checks, firewall review, "
            "and default credential tests. Returns findings sorted by severity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "Target host (mutually exclusive with subnet)",
                },
                "subnet": {
                    "type": "string",
                    "description": "Target subnet in CIDR (mutually exclusive with host)",
                },
                "include_scans": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "ports",
                            "tls",
                            "banners",
                            "dns",
                            "ssh_config",
                            "file_permissions",
                            "firewall",
                            "default_creds",
                        ],
                    },
                    "description": "Scans to include (default: all applicable)",
                },
            },
        },
        "handler": network_generate_report,
    },
]
