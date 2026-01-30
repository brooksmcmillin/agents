"""Lakera Guard integration for prompt injection and security threat detection.

This module provides integration with the Lakera Guard API to screen
LLM interactions for security threats including:
- Prompt injection attacks
- Jailbreak attempts
- Content policy violations
- Malicious content

The integration is optional - if LAKERA_API_KEY is not set, security
checks are skipped silently.

For more information, see: https://docs.lakera.ai/docs/api/guard
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Lakera Guard API configuration
LAKERA_API_URL = "https://api.lakera.ai/v2/guard"
LAKERA_API_KEY_ENV = "LAKERA_API_KEY"  # pragma: allowlist secret
LAKERA_PROJECT_ID_ENV = "LAKERA_PROJECT_ID"
DEFAULT_TIMEOUT = 10.0  # seconds


class ThreatCategory(Enum):
    """Categories of security threats detected by Lakera Guard."""

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    CONTENT_MODERATION = "content_moderation"
    PII = "pii"
    UNKNOWN = "unknown"


class SecurityCheckError(Exception):
    """Raised when a security check fails due to API or network errors."""

    pass


@dataclass
class LakeraSecurityResult:
    """Result of a Lakera Guard security check.

    Attributes:
        flagged: Whether any security threats were detected
        categories: List of threat categories detected (if any)
        details: Raw response details from Lakera API
        skipped: Whether the check was skipped (e.g., no API key configured)
    """

    flagged: bool = False
    categories: list[ThreatCategory] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False

    @property
    def is_safe(self) -> bool:
        """Return True if content is safe (not flagged and check wasn't skipped)."""
        return not self.flagged and not self.skipped


class LakeraGuard:
    """Client for Lakera Guard API security checks.

    This client screens LLM inputs and outputs for security threats.
    If LAKERA_API_KEY environment variable is not set, all checks
    are skipped (fail-open behavior).

    Usage:
        guard = LakeraGuard()

        # Check user input before sending to LLM
        result = await guard.check_input("user message here")
        if result.flagged:
            raise SecurityError("Potential prompt injection detected")

        # Check LLM output before returning to user
        result = await guard.check_output("assistant response here")
        if result.flagged:
            # Handle content policy violation
            pass

    Attributes:
        enabled: Whether Lakera Guard is enabled (API key is configured)
    """

    def __init__(
        self,
        api_key: str | None = None,
        project_id: str | None = None,
        api_url: str = LAKERA_API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        fail_open: bool = True,
    ):
        """Initialize Lakera Guard client.

        Args:
            api_key: Lakera API key. If None, reads from LAKERA_API_KEY env var.
            project_id: Lakera project ID for tracking. If None, reads from
                       LAKERA_PROJECT_ID env var.
            api_url: Lakera Guard API URL (default: production endpoint).
            timeout: Request timeout in seconds.
            fail_open: If True, allow content through when API errors occur.
                      If False, raise SecurityCheckError on API failures.
        """
        self._api_key = api_key or os.environ.get(LAKERA_API_KEY_ENV)
        self._project_id = project_id or os.environ.get(LAKERA_PROJECT_ID_ENV)
        self._api_url = api_url
        self._timeout = timeout
        self._fail_open = fail_open
        self._client: httpx.AsyncClient | None = None

        if self._api_key:
            logger.info("Lakera Guard initialized with API key")
        else:
            logger.info(f"Lakera Guard disabled: {LAKERA_API_KEY_ENV} environment variable not set")

    @property
    def enabled(self) -> bool:
        """Return True if Lakera Guard is enabled (API key is configured)."""
        return self._api_key is not None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _make_request(self, messages: list[dict[str, str]]) -> LakeraSecurityResult:
        """Make a request to the Lakera Guard API.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.

        Returns:
            LakeraSecurityResult with the check results.

        Raises:
            SecurityCheckError: If fail_open is False and an API error occurs.
        """
        if not self.enabled:
            logger.debug("Lakera Guard check skipped: not enabled")
            return LakeraSecurityResult(skipped=True)

        try:
            client = await self._get_client()
            payload: dict[str, Any] = {"messages": messages}
            if self._project_id:
                payload["project_id"] = self._project_id
            response = await client.post(
                self._api_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code != 200:
                error_msg = f"Lakera API returned status {response.status_code}: {response.text}"
                logger.warning(error_msg)
                if self._fail_open:
                    return LakeraSecurityResult(skipped=True)
                raise SecurityCheckError(error_msg)

            result = response.json()
            flagged = result.get("flagged", False)

            # Parse threat categories from the response
            categories = []
            if flagged and "categories" in result:
                for category_name in result["categories"]:
                    try:
                        categories.append(ThreatCategory(category_name))
                    except ValueError:
                        categories.append(ThreatCategory.UNKNOWN)

            logger.debug(f"Lakera Guard result: flagged={flagged}, categories={categories}")

            return LakeraSecurityResult(
                flagged=flagged,
                categories=categories,
                details=result,
            )

        except httpx.TimeoutException as e:
            error_msg = f"Lakera API request timed out: {e}"
            logger.warning(error_msg)
            if self._fail_open:
                return LakeraSecurityResult(skipped=True)
            raise SecurityCheckError(error_msg) from e

        except httpx.HTTPError as e:
            error_msg = f"Lakera API request failed: {e}"
            logger.warning(error_msg)
            if self._fail_open:
                return LakeraSecurityResult(skipped=True)
            raise SecurityCheckError(error_msg) from e

    async def check_input(self, content: str, role: str = "user") -> LakeraSecurityResult:
        """Check user input for security threats before sending to LLM.

        This should be called before passing user messages to the LLM
        to detect prompt injection, jailbreak attempts, and other attacks.

        Args:
            content: The user input text to check.
            role: The message role (default: "user").

        Returns:
            LakeraSecurityResult indicating if threats were detected.
        """
        return await self._make_request([{"role": role, "content": content}])

    async def check_output(self, content: str, role: str = "assistant") -> LakeraSecurityResult:
        """Check LLM output for security threats before returning to user.

        This should be called before returning LLM responses to users
        to detect content policy violations, PII leakage, etc.

        Args:
            content: The LLM output text to check.
            role: The message role (default: "assistant").

        Returns:
            LakeraSecurityResult indicating if threats were detected.
        """
        return await self._make_request([{"role": role, "content": content}])

    async def check_conversation(self, messages: list[dict[str, str]]) -> LakeraSecurityResult:
        """Check a full conversation for security threats.

        This allows checking the full context of a conversation,
        which can help detect multi-turn prompt injection attacks.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                     Example: [{"role": "user", "content": "hello"},
                              {"role": "assistant", "content": "Hi!"}]

        Returns:
            LakeraSecurityResult indicating if threats were detected.
        """
        return await self._make_request(messages)

    async def check_tool_input(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> LakeraSecurityResult:
        """Check tool arguments for security threats.

        This can help detect injection attacks embedded in tool arguments,
        such as malicious URLs or commands.

        Args:
            tool_name: Name of the tool being called.
            arguments: Tool arguments as a dictionary.

        Returns:
            LakeraSecurityResult indicating if threats were detected.
        """
        # Serialize tool call as a message for checking
        tool_content = f"Tool: {tool_name}\nArguments: {arguments}"
        return await self._make_request([{"role": "user", "content": tool_content}])

    async def __aenter__(self) -> "LakeraGuard":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - closes the HTTP client."""
        await self.close()
