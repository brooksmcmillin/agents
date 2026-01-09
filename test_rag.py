#!/usr/bin/env python3
"""Quick test script for RAG functionality."""

import asyncio

from dotenv import load_dotenv

from agent_framework.tools.rag import (
    search_documents,
    get_rag_stats,
)

load_dotenv()


async def main():
    print("=== RAG Test ===\n")

    # Get stats (what agents would use to decide if RAG is useful)
    print("1. Knowledge base summary...")
    stats = await get_rag_stats()
    if stats["status"] == "success":
        s = stats["stats"]
        print(f"   Total documents: {s['total_documents']}")
        print(f"   Categories: {s.get('categories', {})}")
        print(f"   Sources: {s.get('sources', {})}")
        print("   Recent documents:")
        for doc in s.get("recent_documents", [])[:3]:
            print(f"     - {doc['title'][:60]}...")
    print()

    # Search test
    print("2. Searching for 'AI agent security'...")
    results = await search_documents(
        query="AI agent security testing red team",
        top_k=3,
    )
    print(f"   Found {results['count']} results:")
    for r in results.get("results", []):
        print(f"   - [{r['score']:.3f}] {r['id']}: {r['content'][:100]}...")
    print()

    # Optional: Add a test document
    # print("3. Adding test document...")
    # result = await add_document(
    #     content="This is a test document about machine learning and neural networks.",
    #     metadata={"source": "test", "category": "ml"}
    # )
    # print(f"   {result['status']}: {result.get('message', '')}")


if __name__ == "__main__":
    asyncio.run(main())
