"""Generic tools for agents."""

from .content_suggestions import suggest_content_topics
from .fastmail import (
    delete_email,
    get_email,
    get_emails,
    list_mailboxes,
    move_email,
    search_emails,
    send_email,
    update_email_flags,
)
from .memory import (
    configure_memory_store,
    delete_memory,
    get_memories,
    get_memory_stats,
    save_memory,
    search_memories,
)
from .rag import (
    add_document,
    delete_document,
    get_document,
    get_rag_stats,
    list_documents,
    search_documents,
)
from .slack import send_slack_message
from .social_media import get_social_media_stats
from .web_analyzer import analyze_website
from .web_reader import fetch_web_content

# Collect all tool schemas from every tool module.  Each module exposes a
# ``TOOL_SCHEMAS`` list of dicts with ``name``, ``description``,
# ``input_schema``, and ``handler`` keys.  Importing them here gives server
# code a single ``ALL_TOOL_SCHEMAS`` to iterate instead of manually
# registering each tool inline.
from .content_suggestions import TOOL_SCHEMAS as _content_suggestions_schemas
from .fastmail import TOOL_SCHEMAS as _fastmail_schemas
from .memory import TOOL_SCHEMAS as _memory_schemas
from .rag import TOOL_SCHEMAS as _rag_schemas
from .slack import TOOL_SCHEMAS as _slack_schemas
from .social_media import TOOL_SCHEMAS as _social_media_schemas
from .web_analyzer import TOOL_SCHEMAS as _web_analyzer_schemas
from .web_reader import TOOL_SCHEMAS as _web_reader_schemas

ALL_TOOL_SCHEMAS: list[dict] = [
    *_web_reader_schemas,
    *_web_analyzer_schemas,
    *_memory_schemas,
    *_slack_schemas,
    *_social_media_schemas,
    *_content_suggestions_schemas,
    *_rag_schemas,
    *_fastmail_schemas,
]

__all__ = [
    "ALL_TOOL_SCHEMAS",
    "analyze_website",
    "configure_memory_store",
    "delete_memory",
    "fetch_web_content",
    "get_memories",
    "get_memory_stats",
    "get_social_media_stats",
    "save_memory",
    "search_memories",
    "send_slack_message",
    "suggest_content_topics",
    # RAG tools
    "add_document",
    "search_documents",
    "get_document",
    "delete_document",
    "list_documents",
    "get_rag_stats",
    # FastMail tools
    "list_mailboxes",
    "get_emails",
    "get_email",
    "search_emails",
    "send_email",
    "move_email",
    "update_email_flags",
    "delete_email",
]
