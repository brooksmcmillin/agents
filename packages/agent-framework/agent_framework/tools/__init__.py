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

__all__ = [
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
