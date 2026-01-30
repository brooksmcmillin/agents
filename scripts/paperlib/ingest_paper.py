#!/usr/bin/env python3
"""Paper ingestion script for RAG knowledge base.

This script ingests PDF papers into the RAG system with automatic chunking
to handle large documents that exceed embedding model token limits.

It can:
1. Ingest a single paper (for systemd trigger)
2. Seed all papers in a directory (--seed flag)
3. Process new papers in a directory (--sync flag)

Usage:
    # Ingest a single paper
    uv run python scripts/paperlib/ingest_paper.py /path/to/paper.pdf

    # Seed all papers in a directory
    uv run python scripts/paperlib/ingest_paper.py --seed ~/paperlib

    # Sync new papers (skip already ingested)
    uv run python scripts/paperlib/ingest_paper.py --sync ~/paperlib

    # List ingested papers
    uv run python scripts/paperlib/ingest_paper.py --list

Environment variables required:
    DATABASE_URL or RAG_DATABASE_URL: PostgreSQL connection string
    OPENAI_API_KEY: For generating embeddings
"""

import argparse
import asyncio
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure we're in the project root (required for agent_framework imports)
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

import pymupdf4llm  # noqa: E402
from agent_framework.tools.rag import (  # noqa: E402
    add_document,
    get_rag_stats,
    list_documents,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Category for all papers from paperlib
PAPER_CATEGORY = "research_paper"

# Chunking parameters
# text-embedding-3-small has 8192 token limit
# ~4 chars per token on average, so ~20000 chars max
# Use 16000 to leave headroom
MAX_CHUNK_CHARS = 16000
CHUNK_OVERLAP_CHARS = 500  # Overlap between chunks for context continuity


def extract_text_from_pdf(file_path: Path) -> str:
    """Extract text from PDF as markdown."""
    result = pymupdf4llm.to_markdown(str(file_path))

    if isinstance(result, list):
        markdown_text = "\n\n".join(
            page.get("text", "") if isinstance(page, dict) else str(page) for page in result
        )
    else:
        markdown_text = result

    if not markdown_text or not markdown_text.strip():
        raise ValueError(f"No extractable text found in PDF: {file_path}")

    return markdown_text


def chunk_text(
    text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS
) -> list[str]:
    """Split text into overlapping chunks at paragraph boundaries.

    Args:
        text: The text to chunk
        max_chars: Maximum characters per chunk
        overlap: Characters to overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []

    # Split into paragraphs (double newlines)
    paragraphs = re.split(r"\n\n+", text)

    current_chunk: list[str] = []
    current_length = 0

    for para in paragraphs:
        para_len = len(para)

        # If single paragraph exceeds max, split it by sentences
        if para_len > max_chars:
            # First, save any accumulated content
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_length = 0

            # Split long paragraph by sentences
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sentence in sentences:
                if current_length + len(sentence) > max_chars and current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    # Start new chunk with overlap from previous
                    overlap_text = current_chunk[-1] if current_chunk else ""
                    current_chunk = (
                        [overlap_text[-overlap:]] if len(overlap_text) > overlap else [overlap_text]
                    )
                    current_length = len(current_chunk[0]) if current_chunk else 0

                current_chunk.append(sentence)
                current_length += len(sentence) + 2  # +2 for spacing

        elif current_length + para_len + 2 > max_chars:
            # Save current chunk
            chunks.append("\n\n".join(current_chunk))

            # Start new chunk with overlap
            # Take last paragraph(s) that fit within overlap limit
            overlap_paras: list[str] = []
            overlap_len = 0
            for prev_para in reversed(current_chunk):
                if overlap_len + len(prev_para) <= overlap:
                    overlap_paras.insert(0, prev_para)
                    overlap_len += len(prev_para)
                else:
                    break

            current_chunk = overlap_paras + [para]
            current_length = sum(len(p) for p in current_chunk) + len(current_chunk) * 2

        else:
            current_chunk.append(para)
            current_length += para_len + 2

    # Don't forget the last chunk
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def extract_title_from_filename(filename: str) -> str:
    """Extract human-readable title from PDF filename.

    Handles format: "Title_With_Underscores_697ae3f3d26fd11e88443271_main.pdf"
    """
    name = Path(filename).stem
    if name.endswith("_main"):
        name = name[:-5]
    # Remove hash if present (24 hex chars)
    parts = name.rsplit("_", 1)
    if len(parts) == 2 and len(parts[1]) == 24 and all(c in "0123456789abcdef" for c in parts[1]):
        name = parts[0]
    return name.replace("_", " ")


def generate_paper_id(file_path: Path) -> str:
    """Generate a stable ID for a paper based on its path."""
    return hashlib.sha256(str(file_path.resolve()).encode()).hexdigest()[:16]


async def get_ingested_paper_ids() -> set[str]:
    """Get set of already-ingested paper IDs (not chunk IDs)."""
    paper_ids: set[str] = set()
    offset = 0
    limit = 100

    while True:
        result = await list_documents(limit=limit, offset=offset)

        if result["status"] != "success":
            logger.warning(f"Failed to list documents: {result.get('message')}")
            break

        docs = result.get("documents", [])
        if not docs:
            break

        for doc in docs:
            meta = doc.get("metadata", {})
            if meta.get("category") == PAPER_CATEGORY:
                paper_id = meta.get("paper_id")
                if paper_id:
                    paper_ids.add(paper_id)

        offset += limit

    return paper_ids


async def ingest_paper(file_path: Path, force: bool = False) -> bool:
    """Ingest a single paper into the RAG store with chunking.

    Args:
        file_path: Path to the PDF file
        force: If True, re-ingest even if already exists

    Returns:
        True if successfully ingested, False otherwise
    """
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return False

    if file_path.suffix.lower() != ".pdf":
        logger.warning(f"Skipping non-PDF file: {file_path}")
        return False

    paper_id = generate_paper_id(file_path)

    # Check if already ingested
    if not force:
        ingested = await get_ingested_paper_ids()
        if paper_id in ingested:
            logger.info(f"Already ingested, skipping: {file_path.name}")
            return True

    logger.info(f"Ingesting: {file_path.name}")

    # Extract text
    try:
        text = extract_text_from_pdf(file_path)
    except Exception as e:
        logger.error(f"  ✗ Failed to extract text: {e}")
        return False

    # Extract title
    title = extract_title_from_filename(file_path.name)

    # Chunk the text
    chunks = chunk_text(text)
    logger.info(f"  Split into {len(chunks)} chunks")

    # Ingest each chunk
    success_count = 0
    for i, chunk in enumerate(chunks):
        chunk_id = f"{paper_id}-{i:03d}"

        result = await add_document(
            content=chunk,
            document_id=chunk_id,
            metadata={
                "category": PAPER_CATEGORY,
                "title": title,
                "paper_id": paper_id,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source": str(file_path.resolve()),
                "filename": file_path.name,
                "source_dir": "paperlib",
            },
        )

        if result["status"] == "success":
            success_count += 1
        else:
            logger.error(f"  ✗ Chunk {i} failed: {result.get('message')}")

    if success_count == len(chunks):
        logger.info(f"  ✓ Ingested {len(chunks)} chunks ({len(text):,} chars total)")
        return True
    else:
        logger.error(f"  ✗ Only {success_count}/{len(chunks)} chunks succeeded")
        return False


async def seed_directory(directory: Path, force: bool = False) -> tuple[int, int]:
    """Seed all papers in a directory.

    Args:
        directory: Directory containing PDF files
        force: If True, re-ingest all papers

    Returns:
        Tuple of (successful count, failed count)
    """
    if not directory.exists():
        logger.error(f"Directory not found: {directory}")
        return 0, 0

    pdf_files = sorted(directory.glob("*.pdf"))
    if not pdf_files:
        logger.info(f"No PDF files found in {directory}")
        return 0, 0

    logger.info(f"Found {len(pdf_files)} PDF files in {directory}")

    # Get already ingested if not forcing
    ingested: set[str] = set()
    if not force:
        ingested = await get_ingested_paper_ids()
        logger.info(f"Already ingested: {len(ingested)} papers")

    success = 0
    failed = 0

    for pdf_file in pdf_files:
        paper_id = generate_paper_id(pdf_file)

        # Skip if already ingested
        if not force and paper_id in ingested:
            logger.info(f"Skipping (already ingested): {pdf_file.name}")
            success += 1
            continue

        if await ingest_paper(pdf_file, force=True):
            success += 1
        else:
            failed += 1

    return success, failed


async def sync_directory(directory: Path) -> tuple[int, int, int]:
    """Sync new papers in a directory (skip already ingested).

    Args:
        directory: Directory containing PDF files

    Returns:
        Tuple of (new count, skipped count, failed count)
    """
    if not directory.exists():
        logger.error(f"Directory not found: {directory}")
        return 0, 0, 0

    pdf_files = sorted(directory.glob("*.pdf"))
    if not pdf_files:
        logger.info(f"No PDF files found in {directory}")
        return 0, 0, 0

    ingested = await get_ingested_paper_ids()
    logger.info(f"Checking {len(pdf_files)} PDFs against {len(ingested)} ingested papers")

    new = 0
    skipped = 0
    failed = 0

    for pdf_file in pdf_files:
        paper_id = generate_paper_id(pdf_file)

        if paper_id in ingested:
            skipped += 1
            continue

        logger.info(f"New paper found: {pdf_file.name}")
        if await ingest_paper(pdf_file, force=True):
            new += 1
        else:
            failed += 1

    return new, skipped, failed


async def list_ingested() -> None:
    """List all ingested papers."""
    result = await get_rag_stats()

    if result["status"] != "success":
        logger.error(f"Failed to get stats: {result.get('message')}")
        return

    stats = result.get("stats", {})
    print("\nRAG Knowledge Base Statistics:")
    print(f"  Total documents (chunks): {stats.get('total_documents', 0)}")

    # Collect unique papers
    papers: dict[str, dict] = {}
    offset = 0
    limit = 100

    while True:
        result = await list_documents(limit=limit, offset=offset)

        if result["status"] != "success":
            break

        docs = result.get("documents", [])
        if not docs:
            break

        for doc in docs:
            meta = doc.get("metadata", {})
            if meta.get("category") == PAPER_CATEGORY:
                paper_id = meta.get("paper_id", "unknown")
                if paper_id not in papers:
                    papers[paper_id] = {
                        "title": meta.get("title", "Unknown"),
                        "filename": meta.get("filename", "unknown"),
                        "total_chunks": meta.get("total_chunks", 1),
                        "chunks_found": 0,
                    }
                papers[paper_id]["chunks_found"] += 1

        offset += limit

    print(f"\nIngested research papers ({len(papers)} papers):")
    for i, (_paper_id, info) in enumerate(papers.items(), 1):
        print(f"  {i}. {info['title']}")
        print(f"     File: {info['filename']}")
        print(f"     Chunks: {info['chunks_found']}/{info['total_chunks']}")

    print(f"\nTotal papers: {len(papers)}")


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest papers into RAG knowledge base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Path to PDF file or directory",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed all papers in directory (skip already ingested)",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync new papers only (for systemd trigger)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-ingestion of all papers",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all ingested papers",
    )

    args = parser.parse_args()

    if args.list:
        await list_ingested()
        return 0

    if not args.path:
        parser.print_help()
        return 1

    path = args.path.expanduser().resolve()

    if args.seed:
        if not path.is_dir():
            logger.error(f"--seed requires a directory, got: {path}")
            return 1
        success, failed = await seed_directory(path, force=args.force)
        logger.info(f"Seeding complete: {success} successful, {failed} failed")
        return 0 if failed == 0 else 1

    elif args.sync:
        if not path.is_dir():
            logger.error(f"--sync requires a directory, got: {path}")
            return 1
        new, skipped, failed = await sync_directory(path)
        logger.info(f"Sync complete: {new} new, {skipped} skipped, {failed} failed")
        return 0 if failed == 0 else 1

    else:
        # Single file ingestion
        if not path.is_file():
            logger.error(f"File not found: {path}")
            return 1
        success = await ingest_paper(path, force=args.force)
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
