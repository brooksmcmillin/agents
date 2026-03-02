"""Tests for X-Correlation-ID header validation middleware.

Covers:
- Valid correlation IDs are echoed back unchanged
- Missing header generates a fresh UUID
- Malicious/malformed headers are rejected (UUID generated instead)
- Boundary cases: empty string, too long, special characters
"""

import os
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def client() -> TestClient:
    """Create a test client with auth disabled."""
    from api.server import app

    with patch.dict(os.environ, {"DISABLE_AUTH": "true", "ENV": "development"}):
        with TestClient(app) as c:
            yield c


class TestCorrelationIdValidation:
    """Test that X-Correlation-ID is validated before echoing."""

    def test_valid_uuid_echoed(self, client: TestClient) -> None:
        """A valid UUID correlation ID should be echoed back unchanged."""
        cid = "550e8400-e29b-41d4-a716-446655440000"
        resp = client.get("/health", headers={"X-Correlation-ID": cid})
        assert resp.headers["X-Correlation-ID"] == cid

    def test_valid_alphanumeric_echoed(self, client: TestClient) -> None:
        """A short alphanumeric ID should be accepted."""
        cid = "abc-123-def"
        resp = client.get("/health", headers={"X-Correlation-ID": cid})
        assert resp.headers["X-Correlation-ID"] == cid

    def test_missing_header_generates_uuid(self, client: TestClient) -> None:
        """No header should produce a fresh UUID."""
        resp = client.get("/health")
        assert UUID_RE.match(resp.headers["X-Correlation-ID"])

    def test_empty_header_generates_uuid(self, client: TestClient) -> None:
        """An empty string should be rejected and a UUID generated."""
        resp = client.get("/health", headers={"X-Correlation-ID": ""})
        assert UUID_RE.match(resp.headers["X-Correlation-ID"])

    def test_too_long_rejected(self, client: TestClient) -> None:
        """A value longer than 64 chars should be rejected."""
        cid = "a" * 65
        resp = client.get("/health", headers={"X-Correlation-ID": cid})
        assert UUID_RE.match(resp.headers["X-Correlation-ID"])

    def test_max_length_accepted(self, client: TestClient) -> None:
        """Exactly 64 chars should be accepted."""
        cid = "a" * 64
        resp = client.get("/health", headers={"X-Correlation-ID": cid})
        assert resp.headers["X-Correlation-ID"] == cid

    @pytest.mark.parametrize(
        "bad_id",
        [
            "id\r\nX-Injected: evil",  # CRLF injection
            "id\nX-Injected: evil",  # LF injection
            "<script>alert(1)</script>",  # XSS attempt
            "id with spaces",  # spaces
            "id;drop table",  # semicolons
            "../../etc/passwd",  # path traversal chars
            "id\x00null",  # null byte
        ],
        ids=[
            "crlf_injection",
            "lf_injection",
            "xss",
            "spaces",
            "semicolons",
            "path_traversal",
            "null_byte",
        ],
    )
    def test_malicious_values_rejected(self, client: TestClient, bad_id: str) -> None:
        """Malicious header values should be rejected; a UUID is generated."""
        resp = client.get("/health", headers={"X-Correlation-ID": bad_id})
        assert UUID_RE.match(resp.headers["X-Correlation-ID"])
        assert resp.headers["X-Correlation-ID"] != bad_id
