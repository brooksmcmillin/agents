"""Test MCP connection and capture error details."""

import asyncio
import httpx
from shared.oauth_tokens import TokenStorage

async def main():
    storage = TokenStorage()
    token_set = storage.load_token('https://mcp.brooksmcmillin.com/mcp/')

    if not token_set:
        print("No token found. Run the agent first to authenticate.")
        return

    print(f"✅ Found token: {token_set.access_token[:30]}...")

    # Test with proper MCP headers
    headers = {
        "Authorization": f"Bearer {token_set.access_token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }

    # MCP initialize message
    init_message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }

    async with httpx.AsyncClient() as client:
        print("\n📤 Sending initialize request...")
        response = await client.post(
            'https://mcp.brooksmcmillin.com/mcp/',
            headers=headers,
            json=init_message,
            timeout=10.0
        )

        print(f"\n📥 Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        print(f"\nResponse body:")
        print(response.text)

if __name__ == "__main__":
    asyncio.run(main())
