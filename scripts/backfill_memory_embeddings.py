"""Backfill embeddings for existing memories that have embedding IS NULL.

Usage:
    uv run python scripts/backfill_memory_embeddings.py             # process all
    uv run python scripts/backfill_memory_embeddings.py --dry-run   # preview only
    uv run python scripts/backfill_memory_embeddings.py --batch-size 50
"""

import argparse
import asyncio
import logging
import os
import sys

import asyncpg

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_framework.storage.embedding import EmbeddingClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def backfill(
    database_url: str,
    openai_api_key: str,
    batch_size: int = 100,
    dry_run: bool = False,
) -> None:
    """Generate embeddings for memories where embedding IS NULL."""
    client = EmbeddingClient(api_key=openai_api_key)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)

    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM memories WHERE embedding IS NULL")
        logger.info(f"Found {total} memories without embeddings")

        if dry_run:
            sample = await conn.fetch(
                "SELECT agent_name, key, LEFT(value, 80) AS preview "
                "FROM memories WHERE embedding IS NULL LIMIT 10"
            )
            for row in sample:
                logger.info(f"  [{row['agent_name']}] {row['key']}: {row['preview']}...")
            logger.info("Dry run complete — no changes made")
            await pool.close()
            return

    processed = 0
    while processed < total:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT agent_name, key, value FROM memories "
                "WHERE embedding IS NULL "
                "ORDER BY agent_name, key "
                "LIMIT $1 OFFSET $2",
                batch_size,
                processed,
            )

        if not rows:
            break

        for row in rows:
            text = f"{row['key']}: {row['value']}"
            try:
                vec = await client.get_embedding(text)
                vec_str = EmbeddingClient.embedding_to_pgvector(vec)
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE memories SET embedding = $1::vector "
                        "WHERE agent_name = $2 AND key = $3",
                        vec_str,
                        row["agent_name"],
                        row["key"],
                    )
                processed += 1
                if processed % 10 == 0:
                    logger.info(f"Processed {processed}/{total}")
            except Exception as e:
                logger.error(f"Failed to embed [{row['agent_name']}] {row['key']}: {e}")
                processed += 1

    logger.info(f"Backfill complete: {processed} memories processed")
    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill memory embeddings")
    parser.add_argument("--batch-size", type=int, default=100, help="Batch size")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--database-url", help="Override DATABASE_URL env var")
    args = parser.parse_args()

    database_url = (
        args.database_url or os.environ.get("MEMORY_DATABASE_URL") or os.environ.get("DATABASE_URL")
    )
    if not database_url:
        logger.error("Set MEMORY_DATABASE_URL or DATABASE_URL environment variable")
        sys.exit(1)

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("Set OPENAI_API_KEY environment variable")
        sys.exit(1)

    asyncio.run(
        backfill(
            database_url=database_url,
            openai_api_key=openai_api_key,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
