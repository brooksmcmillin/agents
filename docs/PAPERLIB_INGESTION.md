# Paperlib RAG Ingestion

This document describes the automated system for ingesting PDF papers from `~/paperlib` into the RAG knowledge base.

## Overview

Papers added to `~/paperlib` are automatically:
1. Extracted (PDF to markdown text)
2. Chunked (to fit embedding model token limits)
3. Embedded (using OpenAI's text-embedding-3-small)
4. Stored in PostgreSQL with pgvector for semantic search

## Components

### Ingestion Script

**Location:** `scripts/paperlib/ingest_paper.py`

A Python script that handles PDF ingestion with automatic chunking.

**Commands:**

```bash
# Ingest a single paper
uv run python scripts/paperlib/ingest_paper.py /path/to/paper.pdf

# Seed all papers in a directory (skip already ingested)
uv run python scripts/paperlib/ingest_paper.py --seed ~/paperlib

# Sync new papers only (used by systemd watcher)
uv run python scripts/paperlib/ingest_paper.py --sync ~/paperlib

# List all ingested papers
uv run python scripts/paperlib/ingest_paper.py --list

# Force re-ingestion (ignore duplicates)
uv run python scripts/paperlib/ingest_paper.py --seed ~/paperlib --force
```

### systemd Units

Two user-level systemd units provide automatic ingestion:

**Path Unit:** `~/.config/systemd/user/paperlib-watcher.path`
- Watches `~/paperlib` for file changes
- Triggers with 5-second debounce to handle batch operations

**Service Unit:** `~/.config/systemd/user/paperlib-watcher.service`
- Runs `--sync` to ingest only new papers
- Loads environment from `.env` file
- Logs to journald

## Setup

### Prerequisites

- PostgreSQL with pgvector extension
- `DATABASE_URL` or `RAG_DATABASE_URL` environment variable
- `OPENAI_API_KEY` environment variable

### Enable the Watcher

```bash
# Reload systemd and enable the watcher
systemctl --user daemon-reload
systemctl --user enable --now paperlib-watcher.path

# Check status
systemctl --user status paperlib-watcher.path
```

### Initial Seeding

If you have existing papers in `~/paperlib`:

```bash
uv run python scripts/paperlib/ingest_paper.py --seed ~/paperlib
```

## How It Works

### Document Chunking

Papers are split into chunks to fit within the embedding model's 8192 token limit:

- **Max chunk size:** 16,000 characters (~4,000 tokens)
- **Chunk overlap:** 500 characters for context continuity
- **Split strategy:** Paragraph boundaries first, then sentences for long paragraphs

### Metadata

Each chunk is stored with metadata:

```json
{
  "category": "research_paper",
  "title": "Paper Title (extracted from filename)",
  "paper_id": "unique-hash-of-file-path",
  "chunk_index": 0,
  "total_chunks": 4,
  "source": "/home/user/paperlib/paper.pdf",
  "filename": "paper.pdf",
  "source_dir": "paperlib"
}
```

### Deduplication

Papers are tracked by a stable ID generated from their file path. Re-running `--seed` or `--sync` will skip already-ingested papers unless `--force` is used.

### Title Extraction

Titles are extracted from filenames with automatic cleanup:
- Underscores replaced with spaces
- Hash suffixes removed (e.g., `_697ae3f3d26fd11e88443271`)
- `_main` suffix removed

Example: `Design_Patterns_for_Securing_LLM_697ae391d26fd11e8844326c_main.pdf` → `Design Patterns for Securing LLM`

## Monitoring

### View Watcher Logs

```bash
# Follow logs in real-time
journalctl --user -u paperlib-watcher.service -f

# View recent logs
journalctl --user -u paperlib-watcher.service --since "1 hour ago"
```

### Check Ingestion Status

```bash
uv run python scripts/paperlib/ingest_paper.py --list
```

### Watcher Status

```bash
systemctl --user status paperlib-watcher.path
systemctl --user status paperlib-watcher.service
```

## Troubleshooting

### Paper fails to extract

Some PDFs (scanned documents, image-only PDFs) have no extractable text. Solutions:
- Run OCR on the PDF: `ocrmypdf input.pdf output.pdf`
- Skip the file (it will be reported in logs but won't block other papers)

### Watcher not triggering

```bash
# Check if watcher is active
systemctl --user status paperlib-watcher.path

# Restart the watcher
systemctl --user restart paperlib-watcher.path

# Check for errors
journalctl --user -u paperlib-watcher.path
```

### Environment variables not loaded

The service loads from `~/build/agents/.env`. Ensure this file contains:
- `DATABASE_URL` or `RAG_DATABASE_URL`
- `OPENAI_API_KEY`

## Searching Ingested Papers

Use the RAG tools via MCP or directly:

```python
from agent_framework.tools.rag import search_documents

# Search for papers about prompt injection
results = await search_documents(
    query="techniques for defending against prompt injection attacks",
    top_k=5,
    min_score=0.3,
    metadata_filter={"category": "research_paper"}
)
```

The agents (chatbot, security_researcher, etc.) can search these papers automatically using the `search_documents` MCP tool.
