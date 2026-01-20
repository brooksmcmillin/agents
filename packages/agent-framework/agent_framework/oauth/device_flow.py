"""OAuth 2.0 Device Authorization Grant (RFC 8628).

This module implements the Device Authorization Grant for OAuth 2.0,
which allows devices with limited input capabilities to obtain user
authorization without requiring a browser on the device.
"""

import asyncio
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from .oauth_base import OAuthHandlerBase
from .oauth_config import OAuthConfig
from .oauth_tokens import TokenSet

logger = logging.getLogger(__name__)


@dataclass
class DeviceAuthorizationInfo:
    """Information about a pending device authorization request.

    This is passed to the authorization callback so external systems
    (like Slack) can notify users about pending authorizations.
    """

    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    device_code: str  # The secret device code (don't expose to users)

    @property
    def expires_minutes(self) -> int:
        """Get expiration time in minutes."""
        return self.expires_in // 60


# Type alias for the authorization callback
DeviceAuthorizationCallback = Callable[[DeviceAuthorizationInfo], Awaitable[None] | None]


# RFC 8628 grant type URN
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class DeviceFlowError(Exception):
    """Base exception for device flow errors."""

    def __init__(self, error: str, error_description: str | None = None):
        self.error = error
        self.error_description = error_description
        message = f"{error}: {error_description}" if error_description else error
        super().__init__(message)


class DeviceFlowExpiredError(DeviceFlowError):
    """Device code has expired."""

    pass


class DeviceFlowDeniedError(DeviceFlowError):
    """User denied the authorization request."""

    pass


class DeviceFlowHandler(OAuthHandlerBase):
    """Handles OAuth 2.0 Device Authorization Grant (RFC 8628).

    This flow is designed for devices that:
    - Have limited input capabilities
    - Cannot easily open a browser
    - Need to run headless (e.g., in a container or SSH session)

    The flow works by:
    1. Requesting a device code from the authorization server
    2. Displaying a URL and user code for the user to enter in their browser
    3. Polling the token endpoint until the user completes authorization

    Example with callback for Slack notification:
        async def notify_slack(info: DeviceAuthorizationInfo):
            await slack_client.chat_postMessage(
                channel="#auth",
                text=f"🔐 Authorization required!\\n"
                     f"Visit: {info.verification_uri_complete or info.verification_uri}\\n"
                     f"Code: {info.user_code}\\n"
                     f"Expires in {info.expires_minutes} minutes"
            )

        handler = DeviceFlowHandler(
            oauth_config,
            authorization_callback=notify_slack
        )
    """

    def __init__(
        self,
        oauth_config: OAuthConfig,
        scopes: str | None = None,
        authorization_callback: DeviceAuthorizationCallback | None = None,
    ):
        """Initialize device flow handler.

        Args:
            oauth_config: OAuth configuration from discovery
            scopes: Space-separated scopes to request (default: use server's default)
            authorization_callback: Optional async callback invoked when device authorization
                is required. Receives DeviceAuthorizationInfo with the user code and URLs.
                Use this to notify users via Slack, email, etc.
        """
        super().__init__(oauth_config, scopes)
        self.authorization_callback = authorization_callback

    async def register_client(self) -> tuple[str, str | None]:
        """Register a dynamic OAuth client with device_code grant support.

        Returns:
            Tuple of (client_id, client_secret)
            client_secret will be None for public clients

        Raises:
            ValueError: If registration fails or endpoint not available
        """
        if not self.oauth_config.registration_endpoint:
            raise ValueError("Server does not support dynamic client registration")

        logger.info("Registering OAuth client for device flow...")

        # Determine if we should register as a public client
        is_public = self.oauth_config.supports_public_clients()

        registration_data = {
            "grant_types": ["urn:ietf:params:oauth:grant-type:device_code", "refresh_token"],
            "response_types": [],  # Device flow doesn't use response_type
            "token_endpoint_auth_method": "none" if is_public else "client_secret_post",
        }

        logger.debug(f"Registration endpoint: {self.oauth_config.registration_endpoint}")
        logger.debug(f"Registration data: {registration_data}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_config.registration_endpoint,
                    json=registration_data,
                )
                logger.debug(f"Registration response status: {response.status_code}")
                logger.debug(f"Registration response body: {response.text}")
                response.raise_for_status()
                client_data = response.json()

                client_id = client_data["client_id"]
                client_secret = client_data.get("client_secret")

                self.client_id = client_id
                self.client_secret = client_secret

                logger.info(f"Registered client: {client_id} (public: {is_public})")
                logger.debug(f"Client secret present: {client_secret is not None}")
                return client_id, client_secret

            except httpx.HTTPError as e:
                logger.error(f"Registration failed: {e}")
                if isinstance(e, httpx.HTTPStatusError):
                    logger.error(f"Response body: {e.response.text}")
                raise ValueError(f"Failed to register OAuth client: {e}") from e

    async def request_device_code(self) -> dict:
        """Request a device code from the authorization server.

        Returns:
            Device authorization response containing:
            - device_code: Secret code for polling
            - user_code: Code for user to enter
            - verification_uri: URL for user to visit
            - verification_uri_complete: URL with code pre-filled (optional)
            - expires_in: Seconds until codes expire
            - interval: Minimum polling interval in seconds

        Raises:
            ValueError: If the request fails
        """
        if not self.oauth_config.device_authorization_endpoint:
            raise ValueError("Server does not support device authorization")

        if not self.client_id:
            await self.register_client()

        request_data = {
            "client_id": self.client_id,
        }

        if self.scopes:
            request_data["scope"] = self.scopes

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.oauth_config.device_authorization_endpoint,
                    data=request_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                try:
                    error_data = e.response.json()
                    error = error_data.get("error", "unknown_error")
                    error_description = error_data.get("error_description")
                    raise DeviceFlowError(error, error_description) from e
                except (ValueError, KeyError):
                    raise ValueError(f"Failed to request device code: {e}") from e

    async def poll_for_token(
        self,
        device_code: str,
        interval: int = 5,
        expires_in: int = 1800,
    ) -> TokenSet:
        """Poll the token endpoint until user authorizes or code expires.

        Args:
            device_code: Device code from request_device_code()
            interval: Initial polling interval in seconds
            expires_in: Seconds until device code expires

        Returns:
            TokenSet with access token and optional refresh token

        Raises:
            DeviceFlowExpiredError: If the device code expires
            DeviceFlowDeniedError: If the user denies the request
            DeviceFlowError: For other OAuth errors
        """
        if not self.client_id:
            raise ValueError("Client not registered")

        token_data = {
            "grant_type": DEVICE_CODE_GRANT_TYPE,
            "device_code": device_code,
            "client_id": self.client_id,
        }

        if self.client_secret:
            token_data["client_secret"] = self.client_secret

        logger.debug(f"Token endpoint: {self.oauth_config.token_endpoint}")
        logger.debug(f"Polling with client_id: {self.client_id}")
        logger.debug(
            f"Token request data (without device_code): grant_type={token_data['grant_type']}, client_id={token_data['client_id']}, has_secret={self.client_secret is not None}"
        )

        start_time = time.time()
        current_interval = interval

        async with httpx.AsyncClient() as client:
            while True:
                # Check if we've exceeded the expiration time
                elapsed = time.time() - start_time
                if elapsed >= expires_in:
                    raise DeviceFlowExpiredError(
                        "expired_token",
                        "Device code has expired before user completed authorization",
                    )

                try:
                    response = await client.post(
                        self.oauth_config.token_endpoint,
                        data=token_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )

                    # Success - we got a token
                    if response.status_code == 200:
                        token_response = response.json()
                        logger.info("✅ Device authorization successful")
                        # Include client credentials in TokenSet for future refresh
                        return TokenSet.from_oauth_response(
                            token_response,
                            client_id=self.client_id,
                            client_secret=self.client_secret,
                        )

                    # Handle error responses
                    error_data = response.json()
                    error = error_data.get("error", "unknown_error")
                    error_description = error_data.get("error_description")
                    logger.debug(
                        f"Token poll response: status={response.status_code}, error={error}, description={error_description}"
                    )

                    if error == "authorization_pending":
                        # User hasn't authorized yet, keep polling
                        logger.debug(f"Authorization pending, waiting {current_interval}s...")
                        await asyncio.sleep(current_interval)
                        continue

                    elif error == "slow_down":
                        # Server wants us to slow down, increase interval
                        current_interval += 5
                        logger.debug(f"Slowing down, new interval: {current_interval}s")
                        await asyncio.sleep(current_interval)
                        continue

                    elif error == "expired_token":
                        raise DeviceFlowExpiredError(error, error_description)

                    elif error == "access_denied":
                        raise DeviceFlowDeniedError(error, error_description)

                    else:
                        # Other error
                        raise DeviceFlowError(error, error_description)

                except httpx.HTTPError as e:
                    # Network error, wait and retry
                    logger.warning(f"Network error during polling: {e}")
                    await asyncio.sleep(current_interval)
                    continue

    async def authorize(self) -> TokenSet:
        """Run the complete device authorization flow.

        This will:
        1. Register a dynamic OAuth client (if needed)
        2. Request a device code
        3. Display authorization instructions to the user
        4. Poll until user completes authorization

        Returns:
            TokenSet with access token and optional refresh token

        Raises:
            DeviceFlowError: If authorization fails
        """
        # Register client if not already registered
        if not self.client_id:
            await self.register_client()

        # Request device code
        logger.info("Requesting device code...")
        device_response = await self.request_device_code()

        device_code = device_response["device_code"]
        user_code = device_response["user_code"]
        verification_uri = device_response["verification_uri"]
        verification_uri_complete = device_response.get("verification_uri_complete")
        expires_in = device_response.get("expires_in", 1800)
        interval = device_response.get("interval", 5)

        # Create authorization info for callbacks
        auth_info = DeviceAuthorizationInfo(
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            expires_in=expires_in,
            device_code=device_code,
        )

        # Display authorization instructions (to stderr/console)
        self._display_authorization_instructions(
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            expires_in=expires_in,
        )

        # Invoke callback if provided (e.g., for Slack notification)
        if self.authorization_callback:
            logger.debug("Invoking device authorization callback...")
            try:
                result = self.authorization_callback(auth_info)
                # Handle both sync and async callbacks
                if asyncio.iscoroutine(result):
                    await result
                logger.debug("Device authorization callback completed")
            except Exception as e:
                logger.warning(f"Device authorization callback failed: {e}")
                # Don't fail the flow if callback fails

        # Poll for token
        logger.info("⏳ Waiting for user authorization...")
        token_set = await self.poll_for_token(
            device_code=device_code,
            interval=interval,
            expires_in=expires_in,
        )

        return token_set

    def _display_authorization_instructions(
        self,
        user_code: str,
        verification_uri: str,
        verification_uri_complete: str | None,
        expires_in: int,
    ) -> None:
        """Display authorization instructions to the user.

        Args:
            user_code: Code for user to enter
            verification_uri: URL for user to visit
            verification_uri_complete: URL with code pre-filled (optional)
            expires_in: Seconds until codes expire
        """
        expires_minutes = expires_in // 60

        print("\n" + "=" * 60, file=sys.stderr)
        print("🔐 DEVICE AUTHORIZATION REQUIRED", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(file=sys.stderr)
        print("To authorize this device, please:", file=sys.stderr)
        print(file=sys.stderr)

        if verification_uri_complete:
            print(f"  1. Visit: {verification_uri_complete}", file=sys.stderr)
            print(file=sys.stderr)
            print("  OR", file=sys.stderr)
            print(file=sys.stderr)
            print(f"  1. Visit: {verification_uri}", file=sys.stderr)
            print(f"  2. Enter code: {user_code}", file=sys.stderr)
        else:
            print(f"  1. Visit: {verification_uri}", file=sys.stderr)
            print(f"  2. Enter code: {user_code}", file=sys.stderr)

        print(file=sys.stderr)
        print(f"This code expires in {expires_minutes} minutes.", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        print(file=sys.stderr)
