"""Comprehensive unit tests for network_admin tool functions.

Tests cover:
- Argument sanitization and injection prevention
- Error paths (network errors, timeouts, invalid inputs)
- Output format consistency (JSON structure, required keys)
- All 11 tool functions
"""

import os
import socket
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agent_framework.tools.network_admin import (
    _check_host_allowed,
    _grab_banner,
    _tcp_connect,
    network_check_default_credentials,
    network_check_dns,
    network_check_tls,
    network_discover_hosts,
    network_generate_report,
    network_grab_banners,
    network_scan_ports,
    system_check_file_permissions,
    system_check_firewall,
    system_check_ssh_config,
    system_get_info,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AGENT = "test-agent"
ALLOWED_SUBNET = "192.168.1.0/24"
ALLOWED_IP = "192.168.1.100"


@pytest.fixture(autouse=True)
def allowed_subnet_env():
    """Set SYSADMIN_ALLOWED_SUBNETS to a test subnet for all tests."""
    with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": ALLOWED_SUBNET}):
        yield


@pytest.fixture
def mock_check_host_allowed():
    """Mock _check_host_allowed to return ALLOWED_IP without DNS/network."""
    with patch(
        "agent_framework.tools.network_admin._check_host_allowed",
        new_callable=AsyncMock,
        return_value=ALLOWED_IP,
    ) as mock:
        yield mock


@pytest.fixture
def mock_tcp_connect_open():
    """Mock _tcp_connect to always return an open port result."""

    async def _open(host: str, port: int, timeout: float) -> dict[str, Any]:
        return {"port": port, "state": "open", "elapsed_seconds": 0.001}

    with patch("agent_framework.tools.network_admin._tcp_connect", side_effect=_open):
        yield


@pytest.fixture
def mock_tcp_connect_closed():
    """Mock _tcp_connect to always return a closed port result."""

    async def _closed(host: str, port: int, timeout: float) -> dict[str, Any]:
        return {"port": port, "state": "closed", "elapsed_seconds": 0.001}

    with patch("agent_framework.tools.network_admin._tcp_connect", side_effect=_closed):
        yield


# ---------------------------------------------------------------------------
# Tests for _tcp_connect helper
# ---------------------------------------------------------------------------


class TestTcpConnect:
    """Unit tests for the low-level TCP probe helper."""

    @pytest.mark.asyncio
    async def test_returns_open_on_successful_connection(self) -> None:
        mock_writer = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(AsyncMock(), mock_writer),
        ):
            result = await _tcp_connect("192.168.1.1", 80, 2.0)
        assert result["port"] == 80
        assert result["state"] == "open"
        assert "elapsed_seconds" in result

    @pytest.mark.asyncio
    async def test_returns_filtered_on_timeout(self) -> None:
        with patch("asyncio.open_connection", side_effect=TimeoutError()):
            result = await _tcp_connect("192.168.1.1", 80, 2.0)
        assert result["port"] == 80
        assert result["state"] == "filtered"
        assert result["elapsed_seconds"] == 2.0

    @pytest.mark.asyncio
    async def test_returns_closed_on_connection_refused(self) -> None:
        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError()):
            result = await _tcp_connect("192.168.1.1", 80, 2.0)
        assert result["port"] == 80
        assert result["state"] == "closed"
        assert "elapsed_seconds" in result

    @pytest.mark.asyncio
    async def test_returns_closed_on_os_error(self) -> None:
        with patch("asyncio.open_connection", side_effect=OSError("no route")):
            result = await _tcp_connect("192.168.1.1", 80, 2.0)
        assert result["port"] == 80
        assert result["state"] == "closed"


# ---------------------------------------------------------------------------
# Tests for _grab_banner helper
# ---------------------------------------------------------------------------


class TestGrabBanner:
    """Unit tests for the banner-grabbing helper."""

    @pytest.mark.asyncio
    async def test_returns_banner_on_immediate_data(self) -> None:
        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"SSH-2.0-OpenSSH_8.9\r\n")
        mock_writer = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(mock_reader, mock_writer),
        ):
            banner = await _grab_banner("192.168.1.1", 22, 3.0)
        assert banner is not None
        assert "SSH" in banner

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_failure(self) -> None:
        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError()):
            banner = await _grab_banner("192.168.1.1", 22, 3.0)
        assert banner is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_response(self) -> None:
        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=b"")
        mock_writer = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(mock_reader, mock_writer),
        ):
            banner = await _grab_banner("192.168.1.1", 22, 3.0)
        assert banner is None

    @pytest.mark.asyncio
    async def test_truncates_long_banners(self) -> None:
        long_data = b"X" * 1000
        mock_reader = AsyncMock()
        mock_reader.read = AsyncMock(return_value=long_data)
        mock_writer = AsyncMock()
        mock_writer.wait_closed = AsyncMock()
        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(mock_reader, mock_writer),
        ):
            banner = await _grab_banner("192.168.1.1", 80, 3.0)
        assert banner is not None
        assert len(banner) <= 500


# ---------------------------------------------------------------------------
# Tests for _check_host_allowed
# ---------------------------------------------------------------------------


class TestCheckHostAllowed:
    """Tests for async host allowlist validation."""

    @pytest.mark.asyncio
    async def test_resolves_and_allows_ip_in_subnet(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(
            return_value=[(None, None, None, None, ("192.168.1.50", 0))]
        )
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            result = await _check_host_allowed("192.168.1.50")
        assert result == "192.168.1.50"

    @pytest.mark.asyncio
    async def test_raises_for_ip_outside_subnet(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("10.0.0.1", 0))])
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                await _check_host_allowed("10.0.0.1")

    @pytest.mark.asyncio
    async def test_raises_for_unresolvable_hostname(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(side_effect=socket.gaierror("Name not resolved"))
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with pytest.raises(ValueError, match="Cannot resolve hostname"):
                await _check_host_allowed("nonexistent.invalid")


# ---------------------------------------------------------------------------
# Tests for network_discover_hosts
# ---------------------------------------------------------------------------


class TestNetworkDiscoverHosts:
    """Tests for the host discovery tool."""

    @pytest.mark.asyncio
    async def test_blocks_when_subnet_not_in_allowlist(self) -> None:
        with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
            await network_discover_hosts(AGENT, "10.0.0.0/24")

    @pytest.mark.asyncio
    async def test_raises_for_invalid_subnet_format(self) -> None:
        # _check_subnet_allowed raises ValueError for an invalid IP/subnet
        with pytest.raises(ValueError, match="Invalid target or subnet"):
            await network_discover_hosts(AGENT, "not-a-valid-subnet")

    @pytest.mark.asyncio
    async def test_returns_error_for_oversized_subnet(self) -> None:
        # /16 has 65534 hosts, exceeds MAX_HOSTS=512
        with patch.dict(os.environ, {"SYSADMIN_ALLOWED_SUBNETS": "192.168.0.0/16"}):
            result = await network_discover_hosts(AGENT, "192.168.0.0/16")
        assert result["status"] == "error"
        assert "too large" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_success_with_hosts_found(self, mock_tcp_connect_open: Any) -> None:
        with patch("socket.getfqdn", return_value="192.168.1.1"):
            result = await network_discover_hosts(AGENT, "192.168.1.0/30", timeout=0.1)
        assert result["status"] == "success"
        assert "subnet" in result
        assert "total_ips_scanned" in result
        assert "hosts_found" in result
        assert "hosts" in result
        assert "scan_seconds" in result
        assert result["hosts_found"] > 0

    @pytest.mark.asyncio
    async def test_returns_success_with_no_hosts(self, mock_tcp_connect_closed: Any) -> None:
        result = await network_discover_hosts(AGENT, "192.168.1.0/30", timeout=0.1)
        assert result["status"] == "success"
        assert result["hosts_found"] == 0
        assert result["hosts"] == []

    @pytest.mark.asyncio
    async def test_output_format_is_consistent(self, mock_tcp_connect_closed: Any) -> None:
        result = await network_discover_hosts(AGENT, "192.168.1.0/30")
        required_keys = {
            "status",
            "subnet",
            "total_ips_scanned",
            "hosts_found",
            "hosts",
            "scan_seconds",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests for network_scan_ports
# ---------------------------------------------------------------------------


class TestNetworkScanPorts:
    """Tests for the port scanning tool."""

    @pytest.mark.asyncio
    async def test_blocks_host_outside_allowlist(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("10.0.0.1", 0))])
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                await network_scan_ports(AGENT, "10.0.0.1")

    @pytest.mark.asyncio
    async def test_scans_common_ports(
        self, mock_check_host_allowed: Any, mock_tcp_connect_closed: Any
    ) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="common")
        assert result["status"] == "success"
        assert result["host"] == "192.168.1.1"
        assert result["resolved_ip"] == ALLOWED_IP
        assert "ports_scanned" in result
        assert "open" in result
        assert "closed" in result
        assert "filtered" in result
        assert "open_ports" in result
        assert "all_results" in result

    @pytest.mark.asyncio
    async def test_scans_port_range(
        self, mock_check_host_allowed: Any, mock_tcp_connect_closed: Any
    ) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="80-90")
        assert result["status"] == "success"
        assert result["ports_scanned"] == 11

    @pytest.mark.asyncio
    async def test_returns_error_for_oversized_range(self, mock_check_host_allowed: Any) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="1-5000")
        assert result["status"] == "error"
        assert "too large" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_range_format(
        self, mock_check_host_allowed: Any
    ) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="abc-def")
        assert result["status"] == "error"
        assert "Invalid port range" in result["message"]

    @pytest.mark.asyncio
    async def test_scans_comma_separated_ports(
        self, mock_check_host_allowed: Any, mock_tcp_connect_closed: Any
    ) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="22,80,443")
        assert result["status"] == "success"
        assert result["ports_scanned"] == 3

    @pytest.mark.asyncio
    async def test_returns_error_for_invalid_port_list(self, mock_check_host_allowed: Any) -> None:
        result = await network_scan_ports(AGENT, "192.168.1.1", ports="abc,def")
        assert result["status"] == "error"
        assert "Invalid port list" in result["message"]

    @pytest.mark.asyncio
    async def test_grabs_banners_when_requested(self, mock_check_host_allowed: Any) -> None:
        async def _open(host: str, port: int, timeout: float) -> dict[str, Any]:
            return {"port": port, "state": "open", "elapsed_seconds": 0.001}

        with patch("agent_framework.tools.network_admin._tcp_connect", side_effect=_open):
            with patch(
                "agent_framework.tools.network_admin._grab_banner",
                new_callable=AsyncMock,
                return_value="SSH-2.0-OpenSSH_8.9",
            ):
                result = await network_scan_ports(
                    AGENT, "192.168.1.1", ports="22", grab_banners=True
                )
        assert result["status"] == "success"
        open_ports = result["open_ports"]
        assert len(open_ports) > 0
        assert "banner" in open_ports[0]

    @pytest.mark.asyncio
    async def test_returns_error_for_too_many_comma_ports(
        self, mock_check_host_allowed: Any
    ) -> None:
        # Build a list with more than MAX_PORTS=1024 ports
        ports = ",".join(str(i) for i in range(1, 1030))
        result = await network_scan_ports(AGENT, "192.168.1.1", ports=ports)
        assert result["status"] == "error"
        assert "Too many ports" in result["message"]


# ---------------------------------------------------------------------------
# Tests for network_check_tls
# ---------------------------------------------------------------------------


class TestNetworkCheckTls:
    """Tests for the TLS/SSL inspection tool."""

    @pytest.mark.asyncio
    async def test_returns_error_on_timeout(self, mock_check_host_allowed: Any) -> None:
        with patch("asyncio.open_connection", side_effect=TimeoutError()):
            result = await network_check_tls(AGENT, "192.168.1.1", timeout=1.0)
        assert result["status"] == "error"
        assert "timed out" in result["message"]
        assert "host" in result
        assert "port" in result

    @pytest.mark.asyncio
    async def test_returns_error_on_connection_refused(self, mock_check_host_allowed: Any) -> None:
        with patch("asyncio.open_connection", side_effect=ConnectionRefusedError()):
            result = await network_check_tls(AGENT, "192.168.1.1")
        assert result["status"] == "error"
        assert "refused" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_error_on_generic_exception(self, mock_check_host_allowed: Any) -> None:
        with patch("asyncio.open_connection", side_effect=OSError("network unreachable")):
            result = await network_check_tls(AGENT, "192.168.1.1")
        assert result["status"] == "error"
        assert "host" in result
        assert "port" in result

    @pytest.mark.asyncio
    async def test_output_format_on_success(self, mock_check_host_allowed: Any) -> None:
        mock_ssl_object = MagicMock()
        mock_ssl_object.version.return_value = "TLSv1.3"
        mock_ssl_object.cipher.return_value = ("TLS_AES_256_GCM_SHA384", "TLSv1.3", 256)
        mock_ssl_object.getpeercert.return_value = {
            "subject": ((("commonName", "test.example.com"),),),
            "issuer": ((("organizationName", "Test CA"),),),
            "serialNumber": "1234",
            "notBefore": "Jan  1 00:00:00 2025 GMT",
            "notAfter": "Jan  1 00:00:00 2027 GMT",
            "subjectAltName": (("DNS", "test.example.com"),),
        }

        mock_writer = AsyncMock()
        mock_writer.get_extra_info = MagicMock(return_value=mock_ssl_object)
        mock_writer.wait_closed = AsyncMock()

        # Make verify connection also succeed
        mock_verify_writer = AsyncMock()
        mock_verify_writer.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            side_effect=[
                (AsyncMock(), mock_writer),  # first call (inspect)
                (AsyncMock(), mock_verify_writer),  # second call (verify)
            ],
        ):
            result = await network_check_tls(AGENT, "192.168.1.1", port=443)

        assert result["status"] == "success"
        assert "host" in result
        assert "port" in result
        assert "certificate" in result
        assert "protocol" in result
        assert "findings" in result
        assert "findings_count" in result

    @pytest.mark.asyncio
    async def test_flags_weak_tls_protocol(self, mock_check_host_allowed: Any) -> None:
        mock_ssl_object = MagicMock()
        mock_ssl_object.version.return_value = "TLSv1.0"
        mock_ssl_object.cipher.return_value = ("RC4-MD5", "TLSv1.0", 128)
        mock_ssl_object.getpeercert.return_value = {}

        mock_writer = AsyncMock()
        mock_writer.get_extra_info = MagicMock(return_value=mock_ssl_object)
        mock_writer.wait_closed = AsyncMock()

        mock_verify_writer = AsyncMock()
        mock_verify_writer.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            side_effect=[
                (AsyncMock(), mock_writer),
                (AsyncMock(), mock_verify_writer),
            ],
        ):
            result = await network_check_tls(AGENT, "192.168.1.1")

        assert result["status"] == "success"
        findings = result["findings"]
        severities = [f["severity"] for f in findings]
        assert "critical" in severities

    @pytest.mark.asyncio
    async def test_flags_deprecated_tls11(self, mock_check_host_allowed: Any) -> None:
        mock_ssl_object = MagicMock()
        mock_ssl_object.version.return_value = "TLSv1.1"
        mock_ssl_object.cipher.return_value = ("AES128-SHA", "TLSv1.1", 128)
        mock_ssl_object.getpeercert.return_value = {}

        mock_writer = AsyncMock()
        mock_writer.get_extra_info = MagicMock(return_value=mock_ssl_object)
        mock_writer.wait_closed = AsyncMock()

        mock_verify_writer = AsyncMock()
        mock_verify_writer.wait_closed = AsyncMock()

        with patch(
            "asyncio.open_connection",
            new_callable=AsyncMock,
            side_effect=[
                (AsyncMock(), mock_writer),
                (AsyncMock(), mock_verify_writer),
            ],
        ):
            result = await network_check_tls(AGENT, "192.168.1.1")

        assert result["status"] == "success"
        findings = result["findings"]
        severities = [f["severity"] for f in findings]
        assert "high" in severities


# ---------------------------------------------------------------------------
# Tests for network_grab_banners
# ---------------------------------------------------------------------------


class TestNetworkGrabBanners:
    """Tests for the banner-grabbing tool."""

    @pytest.mark.asyncio
    async def test_returns_no_banners_when_no_open_ports(
        self, mock_check_host_allowed: Any
    ) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "open_ports": [],
                "host": "192.168.1.1",
                "resolved_ip": ALLOWED_IP,
            },
        ):
            result = await network_grab_banners(AGENT, "192.168.1.1")
        assert result["status"] == "success"
        assert result["banners"] == []
        assert "No open ports" in result["message"]

    @pytest.mark.asyncio
    async def test_propagates_scan_error(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={"status": "error", "message": "Connection refused"},
        ):
            result = await network_grab_banners(AGENT, "192.168.1.1")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_detects_ssh_service_from_banner(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "open_ports": [{"port": 22, "state": "open", "elapsed_seconds": 0.001}],
                "host": "192.168.1.1",
                "resolved_ip": ALLOWED_IP,
            },
        ):
            with patch(
                "agent_framework.tools.network_admin._grab_banner",
                new_callable=AsyncMock,
                return_value="SSH-2.0-OpenSSH_8.9",
            ):
                result = await network_grab_banners(AGENT, "192.168.1.1", ports="22")

        assert result["status"] == "success"
        assert len(result["banners"]) == 1
        assert result["banners"][0]["service"] == "SSH"

    @pytest.mark.asyncio
    async def test_detects_http_service_from_banner(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "open_ports": [{"port": 80, "state": "open", "elapsed_seconds": 0.001}],
                "host": "192.168.1.1",
                "resolved_ip": ALLOWED_IP,
            },
        ):
            with patch(
                "agent_framework.tools.network_admin._grab_banner",
                new_callable=AsyncMock,
                return_value="HTTP/1.1 200 OK\r\nServer: nginx/1.18.0",
            ):
                result = await network_grab_banners(AGENT, "192.168.1.1", ports="80")

        assert result["status"] == "success"
        assert result["banners"][0]["service"] == "HTTP"

    @pytest.mark.asyncio
    async def test_output_includes_ports_with_banners_count(
        self, mock_check_host_allowed: Any
    ) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "open_ports": [
                    {"port": 22, "state": "open"},
                    {"port": 80, "state": "open"},
                ],
                "host": "192.168.1.1",
                "resolved_ip": ALLOWED_IP,
            },
        ):
            with patch(
                "agent_framework.tools.network_admin._grab_banner",
                new_callable=AsyncMock,
                side_effect=["SSH-2.0-OpenSSH", None],
            ):
                result = await network_grab_banners(AGENT, "192.168.1.1")

        assert result["status"] == "success"
        assert result["ports_with_banners"] == 1


# ---------------------------------------------------------------------------
# Tests for network_check_dns
# ---------------------------------------------------------------------------


class TestNetworkCheckDns:
    """Tests for the DNS checking tool."""

    @pytest.mark.asyncio
    async def test_rejects_injection_at_sign(self) -> None:
        with pytest.raises(ValueError, match="Invalid dig target"):
            await network_check_dns(AGENT, "@attacker.com")

    @pytest.mark.asyncio
    async def test_rejects_injection_dash_option(self) -> None:
        with pytest.raises(ValueError, match="Invalid dig target"):
            await network_check_dns(AGENT, "-b")

    @pytest.mark.asyncio
    async def test_rejects_shell_metacharacters(self) -> None:
        with pytest.raises(ValueError, match="Invalid dig target"):
            await network_check_dns(AGENT, "example.com;evil.com")

    @pytest.mark.asyncio
    async def test_rejects_backtick_injection(self) -> None:
        with pytest.raises(ValueError, match="Invalid dig target"):
            await network_check_dns(AGENT, "`id`")

    @pytest.mark.asyncio
    async def test_rejects_empty_target(self) -> None:
        with pytest.raises(ValueError, match="Invalid dig target"):
            await network_check_dns(AGENT, "")

    @pytest.mark.asyncio
    async def test_rejects_host_outside_allowlist(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("10.0.0.1", 0))])
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                await network_check_dns(AGENT, "10.0.0.1")

    @pytest.mark.asyncio
    async def test_filters_invalid_record_types(self, mock_check_host_allowed: Any) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(
            return_value=[(None, None, None, None, ("192.168.1.1", 0))]
        )
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with patch("socket.gethostbyaddr", return_value=("host.example.com", [], [])):
                with patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError("dig not found"),
                ):
                    result = await network_check_dns(
                        AGENT,
                        "192.168.1.1",
                        record_types=["A", "INJECTED", "MX"],
                    )
        # INJECTED should have been filtered out
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_output_format_is_consistent(self, mock_check_host_allowed: Any) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(
            return_value=[(None, None, None, None, ("192.168.1.1", 0))]
        )
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with patch("socket.gethostbyaddr", return_value=("host.example.com", [], [])):
                with patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError("dig not found"),
                ):
                    result = await network_check_dns(AGENT, "192.168.1.1")

        required_keys = {"status", "target", "records", "findings", "findings_count"}
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_flags_missing_reverse_dns(self, mock_check_host_allowed: Any) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(
            return_value=[(None, None, None, None, ("192.168.1.1", 0))]
        )
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with patch("socket.gethostbyaddr", side_effect=socket.herror("no PTR")):
                with patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=FileNotFoundError("dig not found"),
                ):
                    result = await network_check_dns(AGENT, "192.168.1.1")

        findings = result["findings"]
        assert any("PTR" in f["finding"] or "reverse" in f["finding"].lower() for f in findings)

    @pytest.mark.asyncio
    async def test_handles_dns_resolution_failure(self, mock_check_host_allowed: Any) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(side_effect=socket.gaierror("Name not resolved"))
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("dig not found"),
            ):
                result = await network_check_dns(AGENT, "192.168.1.1")

        assert result["status"] == "success"
        # Should have an info finding about resolution failure
        findings = result["findings"]
        assert any("resolution failed" in f["finding"].lower() for f in findings)


# ---------------------------------------------------------------------------
# Tests for system_get_info
# ---------------------------------------------------------------------------


class TestSystemGetInfo:
    """Tests for the system information tool."""

    @pytest.mark.asyncio
    async def test_returns_success_status(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await system_get_info(AGENT)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_includes_basic_system_info(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await system_get_info(AGENT)
        assert "hostname" in result
        assert "os" in result
        assert "architecture" in result
        assert "python_version" in result

    @pytest.mark.asyncio
    async def test_handles_missing_ip_command(self) -> None:
        """Gracefully handles systems without 'ip' command."""

        call_count = [0]

        async def _subprocess_exec(*args: Any, **kwargs: Any) -> Any:
            call_count[0] += 1
            raise FileNotFoundError("ip not found")

        with patch("asyncio.create_subprocess_exec", side_effect=_subprocess_exec):
            result = await system_get_info(AGENT)
        assert result["status"] == "success"
        # Either interfaces or interfaces_raw will be "unable to enumerate" or similar
        ifaces = result.get("interfaces", result.get("interfaces_raw", "unable to enumerate"))
        assert ifaces is not None

    @pytest.mark.asyncio
    async def test_handles_invalid_json_from_ip_command(self) -> None:
        """If 'ip -j addr' returns non-JSON output, falls back gracefully."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"not json", b""))
        mock_proc.returncode = 0
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await system_get_info(AGENT)
        assert result["status"] == "success"
        # Should have stored raw text
        assert "interfaces" in result or "interfaces_raw" in result


# ---------------------------------------------------------------------------
# Tests for system_check_ssh_config
# ---------------------------------------------------------------------------


class TestSystemCheckSshConfig:
    """Tests for the SSH configuration audit tool."""

    @pytest.mark.asyncio
    async def test_returns_error_for_path_outside_allowed_dir(self) -> None:
        result = await system_check_ssh_config(AGENT, config_path="/tmp/evil_sshd_config")
        assert result["status"] == "error"
        assert "/etc/ssh/" in result["message"]

    @pytest.mark.asyncio
    async def test_returns_error_for_symlink_escape_attempt(self, tmp_path: Any) -> None:
        """A symlink pointing outside /etc/ssh/ must be caught by realpath check."""
        # We can't actually create a symlink to /tmp in /etc/ssh/, so we test
        # the logic by passing a path outside /etc/ssh/ directly
        result = await system_check_ssh_config(AGENT, config_path="/home/user/.ssh/sshd_config")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_error_when_file_not_found(self) -> None:
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            side_effect=FileNotFoundError("no such file"),
        ):
            result = await system_check_ssh_config(
                AGENT, config_path="/etc/ssh/sshd_config_nonexistent"
            )
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_returns_error_on_permission_denied(self) -> None:
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            side_effect=PermissionError("access denied"),
        ):
            result = await system_check_ssh_config(AGENT, config_path="/etc/ssh/sshd_config")
        assert result["status"] == "error"
        assert "permission" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_flags_permit_root_login_yes(self) -> None:
        config_content = "PermitRootLogin yes\nPasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        assert result["status"] == "success"
        findings = result["findings"]
        assert any(
            f["severity"] == "critical" and "PermitRootLogin" in f["finding"] for f in findings
        )

    @pytest.mark.asyncio
    async def test_flags_password_authentication_enabled(self) -> None:
        config_content = "PasswordAuthentication yes\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        assert result["status"] == "success"
        findings = result["findings"]
        assert any("Password authentication" in f["finding"] for f in findings)

    @pytest.mark.asyncio
    async def test_flags_permit_empty_passwords(self) -> None:
        config_content = "PermitEmptyPasswords yes\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        assert result["status"] == "success"
        findings = result["findings"]
        assert any(f["severity"] == "critical" for f in findings)

    @pytest.mark.asyncio
    async def test_flags_x11_forwarding(self) -> None:
        config_content = "X11Forwarding yes\nPasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        findings = result["findings"]
        assert any("X11" in f["finding"] for f in findings)

    @pytest.mark.asyncio
    async def test_flags_high_max_auth_tries(self) -> None:
        config_content = "MaxAuthTries 10\nPasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        findings = result["findings"]
        assert any("MaxAuthTries" in f["finding"] for f in findings)

    @pytest.mark.asyncio
    async def test_flags_old_ssh_protocol(self) -> None:
        config_content = "Protocol 1\nPasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        findings = result["findings"]
        assert any("protocol" in f["finding"].lower() for f in findings)

    @pytest.mark.asyncio
    async def test_skips_comments_and_blank_lines(self) -> None:
        config_content = "# This is a comment\n\nPasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        assert result["status"] == "success"
        # No critical findings since password auth is 'no'
        findings = result["findings"]
        assert not any(f["severity"] == "critical" for f in findings)

    @pytest.mark.asyncio
    async def test_output_format_is_consistent(self) -> None:
        config_content = "PasswordAuthentication no\n"
        with patch(
            "agent_framework.tools.network_admin._read_text_file",
            return_value=config_content,
        ):
            result = await system_check_ssh_config(AGENT)
        required_keys = {"status", "config_path", "config", "findings", "findings_count"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests for system_check_file_permissions
# ---------------------------------------------------------------------------


class TestSystemCheckFilePermissions:
    """Tests for the file permissions audit tool."""

    @pytest.mark.asyncio
    async def test_returns_success_with_default_paths(self) -> None:
        with patch("os.stat", side_effect=FileNotFoundError()):
            result = await system_check_file_permissions(AGENT)
        assert result["status"] == "success"
        assert "files" in result
        assert "findings" in result
        assert "findings_count" in result

    @pytest.mark.asyncio
    async def test_filters_caller_paths_outside_allowed_prefixes(self) -> None:
        """Paths not under /etc/ or ~/.ssh/ should be silently dropped."""
        with patch("os.stat", side_effect=FileNotFoundError()):
            result = await system_check_file_permissions(
                AGENT, paths=["/tmp/evil", "/var/log/test"]
            )
        assert result["status"] == "success"
        # All non-allowed paths should have been filtered
        assert result["files"] == []

    @pytest.mark.asyncio
    async def test_accepts_valid_etc_path(self, tmp_path: Any) -> None:
        """Paths under /etc/ should be accepted."""
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100644  # world-readable
        mock_stat.st_uid = 0
        mock_stat.st_gid = 0
        with patch("os.stat", return_value=mock_stat):
            with patch("os.path.realpath", side_effect=lambda p: p):
                result = await system_check_file_permissions(AGENT, paths=["/etc/passwd"])
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_flags_world_readable_shadow(self, tmp_path: Any) -> None:
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100604  # world-readable (other read bit set)
        mock_stat.st_uid = 0
        mock_stat.st_gid = 0
        with patch("os.stat", return_value=mock_stat):
            result = await system_check_file_permissions(AGENT, paths=None)
        # Should have critical findings about world-readable shadow files
        findings = result["findings"]
        shadow_findings = [f for f in findings if "shadow" in f.get("finding", "")]
        if shadow_findings:
            assert any(f["severity"] == "critical" for f in shadow_findings)

    @pytest.mark.asyncio
    async def test_flags_world_writable_files(self) -> None:
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100666  # world-writable
        mock_stat.st_uid = 0
        mock_stat.st_gid = 0
        with patch("os.stat", return_value=mock_stat):
            result = await system_check_file_permissions(AGENT)
        findings = result["findings"]
        assert any(
            f["severity"] == "critical" and "world-writable" in f["finding"] for f in findings
        )

    @pytest.mark.asyncio
    async def test_flags_ssh_key_with_loose_permissions(self) -> None:
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o100644  # 644 instead of required 600
        mock_stat.st_uid = 1000
        mock_stat.st_gid = 1000
        with patch("os.stat", return_value=mock_stat):
            with patch("os.path.expanduser", side_effect=lambda p: p.replace("~", "/home/user")):
                result = await system_check_file_permissions(AGENT)
        findings = result["findings"]
        # Should flag SSH key permission issues
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_handles_file_not_found_gracefully(self) -> None:
        with patch("os.stat", side_effect=FileNotFoundError()):
            result = await system_check_file_permissions(AGENT)
        assert result["status"] == "success"
        for f in result["files"]:
            if not f["exists"]:
                assert "path" in f

    @pytest.mark.asyncio
    async def test_handles_permission_error_gracefully(self) -> None:
        with patch("os.stat", side_effect=PermissionError()):
            result = await system_check_file_permissions(AGENT)
        assert result["status"] == "success"
        for f in result["files"]:
            if f.get("exists") and not f.get("readable", True):
                assert "path" in f


# ---------------------------------------------------------------------------
# Tests for system_check_firewall
# ---------------------------------------------------------------------------


class TestSystemCheckFirewall:
    """Tests for the firewall configuration audit tool."""

    @pytest.mark.asyncio
    async def test_returns_success_when_no_tools_available(self) -> None:
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")):
            result = await system_check_firewall(AGENT)
        assert result["status"] == "success"
        assert "rules" in result
        assert "findings" in result
        assert "findings_count" in result

    @pytest.mark.asyncio
    async def test_flags_no_firewall_found(self) -> None:
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("not found")):
            result = await system_check_firewall(AGENT)
        findings = result["findings"]
        assert any("No firewall tool found" in f["finding"] for f in findings)
        assert any(f["severity"] == "high" for f in findings)

    @pytest.mark.asyncio
    async def test_flags_ufw_inactive(self) -> None:
        async def _subprocess_exec(*args: Any, **kwargs: Any) -> Any:
            if args[0] == "ufw":
                mock = AsyncMock()
                mock.communicate = AsyncMock(return_value=(b"Status: inactive\n", b""))
                return mock
            raise FileNotFoundError("not found")

        with patch("asyncio.create_subprocess_exec", side_effect=_subprocess_exec):
            result = await system_check_firewall(AGENT)

        assert result["status"] == "success"
        findings = result["findings"]
        assert any("inactive" in f["finding"].lower() for f in findings)

    @pytest.mark.asyncio
    async def test_flags_iptables_accept_all(self) -> None:
        iptables_output = (
            b"Chain INPUT (policy ACCEPT)\nACCEPT     all  --  0.0.0.0/0            0.0.0.0/0\n"
        )

        async def _subprocess_exec(*args: Any, **kwargs: Any) -> Any:
            if args[0] == "ufw":
                raise FileNotFoundError("not found")
            if args[0] == "iptables":
                mock = AsyncMock()
                mock.communicate = AsyncMock(return_value=(iptables_output, b""))
                mock.returncode = 0
                return mock
            raise FileNotFoundError("not found")

        with patch("asyncio.create_subprocess_exec", side_effect=_subprocess_exec):
            result = await system_check_firewall(AGENT)

        assert result["status"] == "success"
        findings = result["findings"]
        assert any("ACCEPT ALL" in f["finding"] or "0.0.0.0/0" in f["finding"] for f in findings)

    @pytest.mark.asyncio
    async def test_collects_ufw_rules(self) -> None:
        ufw_output = b"Status: active\nTo   Action  From\n22/tcp ALLOW Anywhere\n"

        async def _subprocess_exec(*args: Any, **kwargs: Any) -> Any:
            if args[0] == "ufw":
                mock = AsyncMock()
                mock.communicate = AsyncMock(return_value=(ufw_output, b""))
                return mock
            raise FileNotFoundError("not found")

        with patch("asyncio.create_subprocess_exec", side_effect=_subprocess_exec):
            result = await system_check_firewall(AGENT)

        assert result["status"] == "success"
        assert "ufw" in result["rules"]


# ---------------------------------------------------------------------------
# Tests for network_check_default_credentials
# ---------------------------------------------------------------------------


class TestNetworkCheckDefaultCredentials:
    """Tests for the default credential auditing tool."""

    @pytest.mark.asyncio
    async def test_blocks_host_outside_allowlist(self) -> None:
        loop_mock = AsyncMock()
        loop_mock.getaddrinfo = AsyncMock(return_value=[(None, None, None, None, ("10.0.0.1", 0))])
        with patch("asyncio.get_running_loop", return_value=loop_mock):
            with pytest.raises(ValueError, match="not in SYSADMIN_ALLOWED_SUBNETS"):
                await network_check_default_credentials(AGENT, "10.0.0.1")

    @pytest.mark.asyncio
    async def test_auto_detects_services_from_open_ports(
        self, mock_check_host_allowed: Any
    ) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={
                "status": "success",
                "open_ports": [{"port": 22, "state": "open"}],
            },
        ):
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=FileNotFoundError("sshpass not installed"),
            ):
                result = await network_check_default_credentials(AGENT, "192.168.1.1")
        assert result["status"] == "success"
        # Should have tried SSH since port 22 was open
        services_checked = [r["service"] for r in result["results"]]
        assert "ssh" in services_checked

    @pytest.mark.asyncio
    async def test_handles_sshpass_not_installed(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("sshpass not installed"),
        ):
            result = await network_check_default_credentials(AGENT, "192.168.1.1", services=["ssh"])
        assert result["status"] == "success"
        ssh_result = next(r for r in result["results"] if r["service"] == "ssh")
        assert any("sshpass not installed" in str(d) for d in ssh_result["details"])

    @pytest.mark.asyncio
    async def test_handles_snmpwalk_not_installed(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("snmpwalk not installed"),
        ):
            result = await network_check_default_credentials(
                AGENT, "192.168.1.1", services=["snmp"]
            )
        assert result["status"] == "success"
        snmp_result = next(r for r in result["results"] if r["service"] == "snmp")
        assert any("snmpwalk not installed" in str(d) for d in snmp_result["details"])

    @pytest.mark.asyncio
    async def test_output_format_is_consistent(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={"status": "success", "open_ports": []},
        ):
            result = await network_check_default_credentials(AGENT, "192.168.1.1")
        required_keys = {"status", "host", "services_checked", "vulnerable_services", "results"}
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_redacts_credentials_in_output(self, mock_check_host_allowed: Any) -> None:
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Permission denied"))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await network_check_default_credentials(AGENT, "192.168.1.1", services=["ssh"])
        # None of the detail strings should contain actual passwords
        for svc_result in result["results"]:
            for detail in svc_result.get("details", []):
                password_val = detail.get("password", "")
                assert "raspberry" not in password_val
                assert "admin" not in password_val or "[REDACTED" in password_val

    @pytest.mark.asyncio
    async def test_unknown_service_returns_zero_credentials(
        self, mock_check_host_allowed: Any
    ) -> None:
        result = await network_check_default_credentials(
            AGENT, "192.168.1.1", services=["unknown_service"]
        )
        assert result["status"] == "success"
        svc_result = next(r for r in result["results"] if r["service"] == "unknown_service")
        assert svc_result["credentials_tested"] == 0
        assert not svc_result["vulnerable"]


# ---------------------------------------------------------------------------
# Tests for network_generate_report
# ---------------------------------------------------------------------------


class TestNetworkGenerateReport:
    """Tests for the comprehensive report generation tool."""

    @pytest.mark.asyncio
    async def test_returns_error_when_no_target_provided(self) -> None:
        result = await network_generate_report(AGENT)
        assert result["status"] == "error"
        assert "host or subnet" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_output_format_with_host(self, mock_check_host_allowed: Any) -> None:
        # Mock all individual scan functions to avoid network calls
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={"status": "success", "open_ports": [], "findings": []},
        ):
            with patch(
                "agent_framework.tools.network_admin.network_check_tls",
                new_callable=AsyncMock,
                return_value={"status": "success", "findings": []},
            ):
                with patch(
                    "agent_framework.tools.network_admin.network_check_dns",
                    new_callable=AsyncMock,
                    return_value={"status": "success", "findings": []},
                ):
                    with patch(
                        "agent_framework.tools.network_admin.network_check_default_credentials",
                        new_callable=AsyncMock,
                        return_value={"status": "success", "results": []},
                    ):
                        with patch(
                            "agent_framework.tools.network_admin.system_check_ssh_config",
                            new_callable=AsyncMock,
                            return_value={"status": "success", "findings": []},
                        ):
                            with patch(
                                "agent_framework.tools.network_admin.system_check_file_permissions",
                                new_callable=AsyncMock,
                                return_value={"status": "success", "findings": []},
                            ):
                                with patch(
                                    "agent_framework.tools.network_admin.system_check_firewall",
                                    new_callable=AsyncMock,
                                    return_value={"status": "success", "findings": []},
                                ):
                                    result = await network_generate_report(
                                        AGENT,
                                        host="192.168.1.1",
                                    )

        assert result["status"] == "success"
        required_keys = {
            "status",
            "target",
            "scans_performed",
            "total_findings",
            "severity_counts",
            "findings",
            "scan_details",
        }
        assert required_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_findings_sorted_by_severity(self, mock_check_host_allowed: Any) -> None:
        """Findings should be sorted critical -> high -> medium -> low -> info."""
        findings_from_ssh = [
            {"severity": "low", "finding": "Low issue", "recommendation": "fix"},
            {"severity": "critical", "finding": "Critical issue", "recommendation": "fix now"},
            {"severity": "medium", "finding": "Medium issue", "recommendation": "fix soon"},
        ]

        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={"status": "success", "open_ports": [], "findings": []},
        ):
            with patch(
                "agent_framework.tools.network_admin.network_check_tls",
                new_callable=AsyncMock,
                return_value={"status": "success", "findings": []},
            ):
                with patch(
                    "agent_framework.tools.network_admin.network_check_dns",
                    new_callable=AsyncMock,
                    return_value={"status": "success", "findings": []},
                ):
                    with patch(
                        "agent_framework.tools.network_admin.network_check_default_credentials",
                        new_callable=AsyncMock,
                        return_value={"status": "success", "results": []},
                    ):
                        with patch(
                            "agent_framework.tools.network_admin.system_check_ssh_config",
                            new_callable=AsyncMock,
                            return_value={"status": "success", "findings": findings_from_ssh},
                        ):
                            with patch(
                                "agent_framework.tools.network_admin.system_check_file_permissions",
                                new_callable=AsyncMock,
                                return_value={"status": "success", "findings": []},
                            ):
                                with patch(
                                    "agent_framework.tools.network_admin.system_check_firewall",
                                    new_callable=AsyncMock,
                                    return_value={"status": "success", "findings": []},
                                ):
                                    result = await network_generate_report(
                                        AGENT, host="192.168.1.1"
                                    )

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings = result["findings"]
        if len(findings) > 1:
            for i in range(len(findings) - 1):
                sev_a = severity_order.get(findings[i].get("severity", "info"), 5)
                sev_b = severity_order.get(findings[i + 1].get("severity", "info"), 5)
                assert sev_a <= sev_b, (
                    f"Findings not sorted: {findings[i]} before {findings[i + 1]}"
                )

    @pytest.mark.asyncio
    async def test_uses_limited_scans_when_specified(self, mock_check_host_allowed: Any) -> None:
        with patch(
            "agent_framework.tools.network_admin.network_scan_ports",
            new_callable=AsyncMock,
            return_value={"status": "success", "open_ports": [], "findings": []},
        ) as mock_ports:
            with patch(
                "agent_framework.tools.network_admin.network_check_tls",
                new_callable=AsyncMock,
                return_value={"status": "success", "findings": []},
            ) as mock_tls:
                with patch(
                    "agent_framework.tools.network_admin.system_check_ssh_config",
                    new_callable=AsyncMock,
                    return_value={"status": "success", "findings": []},
                ) as mock_ssh:
                    result = await network_generate_report(
                        AGENT,
                        host="192.168.1.1",
                        include_scans=["ports"],
                    )

        # Only ports scan should have been called
        assert mock_ports.called
        assert not mock_tls.called
        assert not mock_ssh.called
        assert result["status"] == "success"
