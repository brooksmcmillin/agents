"""Debug MCP handshake to see what's failing."""

import asyncio
import logging

import httpx
from agent_framework.oauth import TokenStorage
from mcp.client.streamable_http import streamablehttp_client

# Enable detailed HTTP logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()


class LoggingAuth(httpx.Auth):
    """Auth that logs all requests."""

    def __init__(self, token: str):
        self.token = token

    def auth_flow(self, request):
        logger.info("\n=== REQUEST ===")
        logger.info(f"Method: {request.method}")
        logger.info(f"URL: {request.url}")
        logger.info(f"Headers: {dict(request.headers)}")
        if request.content:
            logger.info(f"Body: {request.content[:500]}")

        request.headers["Authorization"] = f"Bearer {self.token}"

        response = yield request

        logger.info("\n=== RESPONSE ===")
        logger.info(f"Status: {response.status_code}")
        logger.info(f"Headers: {dict(response.headers)}")


async def main():
    storage = TokenStorage()
    token_set = storage.load_token("https://your-mcp-server.example.com/mcp/")

    if not token_set:
        print("No token found. Run the agent first to authenticate.")
        return

    print(f"Using token: {token_set.access_token[:30]}...")

    auth = LoggingAuth(token_set.access_token)

    try:
        print("\n🔌 Attempting MCP connection with logging...")
        async with streamablehttp_client(
            "https://your-mcp-server.example.com/mcp/", auth=auth, timeout=10
        ) as (read_stream, write_stream, get_session_id):
            print(f"\n✅ Connected! Session ID: {get_session_id()}")

            # Try to create a session and list tools
            from mcp import ClientSession

            print("\n📋 Creating MCP session...")
            session = ClientSession(read_stream, write_stream)

            async with session:
                print("📋 Initializing MCP session...")
                await session.initialize()

                print("📋 Listing tools...")
                result = await session.list_tools()
                print(f"✅ Got {len(result.tools)} tools!")
                for tool in result.tools:
                    print(f"  - {tool.name}")

    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
