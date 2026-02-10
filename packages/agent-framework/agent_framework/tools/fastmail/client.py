"""JMAP client for FastMail API interactions.

This module provides the JMAPClient class and related constants for
interacting with the FastMail JMAP API.
"""

import logging
from typing import Any

import httpx

from ...core.config import settings

logger = logging.getLogger(__name__)

# JMAP Constants
JMAP_SESSION_URL = "https://api.fastmail.com/jmap/session"
JMAP_CAPABILITIES = {
    "core": "urn:ietf:params:jmap:core",
    "mail": "urn:ietf:params:jmap:mail",
    "submission": "urn:ietf:params:jmap:submission",
}


class JMAPClient:
    """JMAP client for FastMail API interactions."""

    def __init__(self, api_token: str | None = None) -> None:
        """Initialize JMAP client.

        Args:
            api_token: FastMail API token. If not provided, uses FASTMAIL_API_TOKEN
                from environment.
        """
        self.api_token = api_token or settings.fastmail_api_token
        if not self.api_token:
            raise ValueError(
                "FastMail API token required. Set FASTMAIL_API_TOKEN environment variable "
                "or provide api_token parameter. Generate a token at: "
                "Settings -> Privacy & Security -> Integrations -> API tokens"
            )

        self._session: dict[str, Any] | None = None
        self._account_id: str | None = None
        self._api_url: str | None = None

    async def _ensure_session(self) -> None:
        """Ensure we have a valid JMAP session."""
        if self._session is not None:
            return

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                JMAP_SESSION_URL,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            self._session = response.json()

        # Extract primary account ID and API URL
        assert self._session is not None  # Guaranteed by line 52-53
        accounts = self._session.get("accounts", {})
        primary_accounts = self._session.get("primaryAccounts", {})

        # Get the primary mail account
        mail_account_id = primary_accounts.get(JMAP_CAPABILITIES["mail"])
        if mail_account_id:
            self._account_id = mail_account_id
        elif accounts:
            # Fallback to first account
            self._account_id = next(iter(accounts.keys()))

        self._api_url = self._session.get("apiUrl")

        if not self._account_id or not self._api_url:
            raise ValueError("Could not determine FastMail account or API URL from session")

        logger.info(f"JMAP session established for account: {self._account_id}")

    async def _call(self, method_calls: list[list[Any]]) -> dict[str, Any]:
        """Make a JMAP API call.

        Args:
            method_calls: List of JMAP method calls in format [[method, args, id], ...]

        Returns:
            JMAP response with methodResponses
        """
        await self._ensure_session()
        assert self._api_url is not None  # Guaranteed by _ensure_session

        request_body = {
            "using": list(JMAP_CAPABILITIES.values()),
            "methodCalls": method_calls,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            return response.json()

    @property
    def account_id(self) -> str:
        """Get the account ID (requires session to be established)."""
        if not self._account_id:
            raise ValueError("Session not established. Call a method first.")
        return self._account_id


def _get_client(api_token: str | None = None) -> JMAPClient:
    """Get a JMAP client instance."""
    return JMAPClient(api_token)
