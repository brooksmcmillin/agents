"""Demo script for PR Agent - shows basic usage without interactive mode."""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent.mcp_client import MCPClient


async def demo_mcp_tools():
    """
    Demonstrate MCP tools with mock data.

    This script shows how to:
    1. Connect to the MCP server
    2. Call individual tools
    3. Process results
    """
    print("\n" + "="*70)
    print("PR AGENT - MCP TOOLS DEMO")
    print("="*70)
    print("\nThis demo showcases the MCP tools with mock data.")
    print("In production, these would call real APIs with OAuth.\n")

    # Create MCP client
    client = MCPClient(server_script_path="mcp_server/server.py")

    try:
        # Connect to MCP server
        async with client.connect():
            print(f"✓ Connected to MCP server")
            print(f"✓ Available tools: {', '.join(client.get_available_tools())}\n")

            # Demo 1: Analyze Website
            print("="*70)
            print("DEMO 1: Analyzing a blog post for tone")
            print("="*70)

            result1 = await client.call_tool(
                "analyze_website",
                {
                    "url": "https://example.com/blog/my-post",
                    "analysis_type": "tone",
                }
            )

            print(f"\nPrimary Tone: {result1['results']['primary_tone']}")
            print(f"Formality Level: {result1['results']['formality_level']}")
            print(f"Reading Level: {result1['results']['reading_level']}")
            print(f"\nRecommendations:")
            for i, rec in enumerate(result1['recommendations'], 1):
                print(f"  {i}. {rec}")

            # Demo 2: Social Media Stats
            print("\n" + "="*70)
            print("DEMO 2: Getting Twitter stats for last 30 days")
            print("="*70)

            result2 = await client.call_tool(
                "get_social_media_stats",
                {
                    "platform": "twitter",
                    "timeframe": "30d",
                }
            )

            print(f"\nFollowers: {result2['account_metrics']['followers']:,}")
            print(f"Follower Growth: +{result2['account_metrics']['follower_growth']}")
            print(f"Tweets Posted: {result2['content_metrics']['tweets_posted']}")
            print(f"Total Impressions: {result2['content_metrics']['impressions']:,}")
            print(f"Engagement Rate: {result2['content_metrics']['engagement_rate']}%")
            print(f"\nTop Performing Tweets:")
            for tweet in result2['top_tweets'][:2]:
                print(f"  - {tweet['text'][:50]}...")
                print(f"    Impressions: {tweet['impressions']:,}, Engagement Rate: {tweet['engagement_rate']}%")

            # Demo 3: Content Suggestions
            print("\n" + "="*70)
            print("DEMO 3: Getting blog content suggestions")
            print("="*70)

            result3 = await client.call_tool(
                "suggest_content_topics",
                {
                    "content_type": "blog",
                    "count": 3,
                }
            )

            print(f"\nGenerated {len(result3['suggestions'])} content ideas:\n")
            for i, suggestion in enumerate(result3['suggestions'], 1):
                print(f"{i}. {suggestion['suggested_title']}")
                print(f"   Topic: {suggestion['topic']}")
                print(f"   Target: {suggestion['target_audience']}")
                print(f"   SEO Potential: {suggestion['seo_potential']}")
                print(f"   Reasoning: {suggestion['reasoning']}")
                print()

            # Summary
            print("="*70)
            print("DEMO COMPLETE")
            print("="*70)
            print("\nAll tools executed successfully with mock data!")
            print("\nNext steps:")
            print("1. Set up your ANTHROPIC_API_KEY in .env")
            print("2. Run 'python -m agent.main' for interactive mode")
            print("3. Integrate real APIs (Twitter, LinkedIn, web scraping)")
            print("4. Set up OAuth flow for social media access")
            print("\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def demo_full_agent():
    """
    Demonstrate the full agent with a simulated conversation.

    This requires ANTHROPIC_API_KEY to be set.
    """
    load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\n⚠️  ANTHROPIC_API_KEY not set. Skipping full agent demo.")
        print("   Set it in .env to try the full agent.\n")
        return

    from agent.main import PRAgent

    print("\n" + "="*70)
    print("PR AGENT - FULL AGENT DEMO")
    print("="*70)
    print("\nThis demo shows the agent analyzing content and providing recommendations.\n")

    try:
        # Create agent
        agent = PRAgent()

        # Simulate a conversation
        print("Simulated User: Analyze https://example.com/blog for SEO\n")

        response1 = await agent.process_message(
            "Analyze https://example.com/blog for SEO"
        )
        print(f"Agent: {response1}\n")

        print("\n" + "="*70)
        print("Agent successfully used MCP tools to analyze content!")
        print("="*70)
        print("\nRun 'python -m agent.main' for interactive mode.\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run all demos."""
    # Always run MCP tools demo
    await demo_mcp_tools()

    # Optionally run full agent demo if API key is set
    await demo_full_agent()


if __name__ == "__main__":
    print("\nStarting PR Agent Demo...")
    asyncio.run(main())
