"""Base MCP server implementation.

This module provides utilities for creating MCP servers with tool registration.
"""

import json
import logging
from collections.abc import Callable, Sequence
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import EmbeddedResource, ImageContent, TextContent, Tool

from agent_framework.tools import (
    add_document,
    delete_document,
    # FastMail tools
    delete_email,
    fetch_web_content,
    get_document,
    get_email,
    get_emails,
    get_memories,
    get_rag_stats,
    list_documents,
    list_mailboxes,
    move_email,
    save_memory,
    search_documents,
    search_emails,
    search_memories,
    send_email,
    send_slack_message,
    update_email_flags,
)

logger = logging.getLogger(__name__)


class MCPServerBase:
    """
    Base class for MCP servers with tool registration.

    This provides a clean interface for building MCP servers with automatic
    tool registration and error handling.
    """

    def __init__(self, name: str, setup_defaults: bool = True):
        """
        Initialize MCP server.

        Args:
            name: Server name
            setup_defaults: Whether or not to set up default tools
        """
        self.app = Server(name)
        self.tools: dict[str, dict[str, Any]] = {}
        self._tool_handlers: dict[str, Callable] = {}

        if setup_defaults:
            setup_default_tools(self)

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable,
    ):
        """
        Register a tool with the server.

        Args:
            name: Tool name
            description: Tool description
            input_schema: JSON schema for tool inputs
            handler: Async function to handle tool calls
        """
        self.tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
        }
        self._tool_handlers[name] = handler
        logger.info(f"Registered tool: {name}")

    def setup_handlers(self) -> None:
        """Set up MCP handlers for tool listing and calling."""

        @self.app.list_tools()
        async def list_tools() -> list[Tool]:
            """List available MCP tools."""
            logger.info("Listing available tools")
            return [
                Tool(
                    name=tool_info["name"],
                    description=tool_info["description"],
                    inputSchema=tool_info["input_schema"],
                )
                for tool_info in self.tools.values()
            ]

        @self.app.call_tool()
        async def call_tool(
            name: str, arguments: Any
        ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
            """Execute a tool with the given arguments."""
            logger.info(f"Calling tool: {name} with arguments: {arguments}")

            try:
                # Check if tool exists
                if name not in self._tool_handlers:
                    raise ValueError(f"Unknown tool: {name}")

                # Call the handler
                handler = self._tool_handlers[name]
                result = await handler(**arguments)

                # Return as TextContent with JSON
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, indent=2),
                    )
                ]

            except ValueError as e:
                logger.error(f"Validation error in {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "validation_error",
                                "message": str(e),
                                "tool": name,
                            }
                        ),
                    )
                ]

            except PermissionError as e:
                logger.error(f"Auth error in {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "authentication_required",
                                "message": str(e),
                                "tool": name,
                                "action_required": "Please complete OAuth authentication flow",
                            }
                        ),
                    )
                ]

            except Exception as e:
                logger.exception(f"Error executing tool {name}: {e}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {
                                "error": "execution_error",
                                "message": str(e),
                                "tool": name,
                            }
                        ),
                    )
                ]

    async def run(self) -> None:
        """Run the MCP server."""
        logger.info(f"Starting MCP Server: {self.app.name}")

        # Run the server using stdio transport
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server running on stdio")
            await self.app.run(
                read_stream,
                write_stream,
                self.app.create_initialization_options(),
            )


def create_mcp_server(name: str) -> MCPServerBase:
    """
    Create a new MCP server.

    This is a convenience function for creating servers.

    Args:
        name: Server name

    Returns:
        MCPServerBase instance

    Example:
        ```python
        server = create_mcp_server("my-agent")

        server.register_tool(
            name="my_tool",
            description="Does something useful",
            input_schema={
                "type": "object",
                "properties": {
                    "param": {"type": "string"}
                },
                "required": ["param"]
            },
            handler=my_tool_handler
        )

        server.setup_handlers()
        await server.run()
        ```
    """
    return MCPServerBase(name)


def setup_default_tools(server: MCPServerBase) -> None:
    server.register_tool(
        name="fetch_web_content",
        description=(
            "Fetch web content and convert to clean, LLM-readable markdown format. "
            "Extracts the main content from a webpage, removes navigation and ads, "
            "and returns it as markdown. Useful for reading articles, blog posts, "
            "documentation, or any web content you want to analyze or comment on."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must start with http:// or https://)",
                },
                "max_length": {
                    "type": "integer",
                    "minimum": 1000,
                    "maximum": 100000,
                    "default": 50000,
                    "description": "Maximum content length in characters (default: 50000)",
                },
            },
            "required": ["url"],
        },
        handler=fetch_web_content,
    )

    server.register_tool(
        name="save_memory",
        description=(
            "Save important information to persistent memory. Use this to remember "
            "user preferences, goals, insights from analyses, brand voice, and any "
            "other details that should be recalled in future conversations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Unique identifier (e.g., 'user_blog_url', 'brand_voice', 'twitter_goal')",
                },
                "value": {
                    "type": "string",
                    "description": "The information to remember",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category: 'user_preference', 'fact', 'goal', 'insight', etc.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags for organization (e.g., ['seo', 'twitter'])",
                },
                "importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "default": 5,
                    "description": "Importance level 1-10 (1=low, 5=medium, 10=critical)",
                },
            },
            "required": ["key", "value"],
        },
        handler=save_memory,
    )

    server.register_tool(
        name="get_memories",
        description=(
            "Retrieve stored memories from previous conversations. Returns memories "
            "sorted by importance. Use this at the start of conversations to recall "
            "context about the user."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g., 'user_preference', 'goal')",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (returns memories with any matching tag)",
                },
                "min_importance": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Only return memories with importance >= this value",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum number of memories to return",
                },
            },
            "required": [],
        },
        handler=get_memories,
    )

    server.register_tool(
        name="search_memories",
        description=(
            "Search for memories by keyword. Searches both keys and values. "
            "Useful when you don't know the exact memory key."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Maximum number of results",
                },
            },
            "required": ["query"],
        },
        handler=search_memories,
    )
    server.register_tool(
        name="send_slack_message",
        description=(
            "Send a message to Slack using an incoming webhook. "
            "Useful for posting content, notifications, and updates to Slack channels. "
            "The webhook URL can be provided or will use SLACK_WEBHOOK_URL from environment. "
            "Supports custom usernames, emoji icons, and channel overrides."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The message text to send (supports Slack markdown formatting)",
                },
                "webhook_url": {
                    "type": "string",
                    "description": "Optional Slack webhook URL. If not provided, uses SLACK_WEBHOOK_URL from environment",
                },
                "username": {
                    "type": "string",
                    "description": "Optional custom username for the message",
                },
                "icon_emoji": {
                    "type": "string",
                    "description": "Optional emoji icon (e.g., 'robot_face', 'tada', ':rocket:')",
                },
                "channel": {
                    "type": "string",
                    "description": "Optional channel override (e.g., '#general', '@username')",
                },
            },
            "required": ["text"],
        },
        handler=send_slack_message,
    )

    # RAG (Retrieval-Augmented Generation) Tools
    server.register_tool(
        name="add_document",
        description=(
            "Add a document to the RAG knowledge base for semantic search. "
            "Documents are converted to vector embeddings and stored in PostgreSQL. "
            "Supports direct text content OR automatic extraction from PDF files. "
            "Use this to build a searchable knowledge base from articles, docs, notes, etc."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The document text content to store (required if file_path not provided)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to a PDF file to extract text from. Auto-populates metadata with file info.",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata: source, title, author, category, etc.",
                    "additionalProperties": True,
                },
                "document_id": {
                    "type": "string",
                    "description": "Optional custom ID. Auto-generated if not provided. Updates existing doc if ID exists.",
                },
            },
            "required": [],
        },
        handler=add_document,
    )

    server.register_tool(
        name="search_documents",
        description=(
            "Search the RAG knowledge base using semantic similarity. "
            "Finds documents based on meaning, not just keywords. "
            "Returns the most relevant documents with similarity scores."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query - describe what you're looking for",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Maximum number of results (default: 5)",
                },
                "min_score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0,
                    "description": "Minimum similarity score 0-1 (0.7+ is highly related)",
                },
                "metadata_filter": {
                    "type": "object",
                    "description": 'Optional filter on metadata fields, e.g., {"category": "blog"}',
                    "additionalProperties": True,
                },
            },
            "required": ["query"],
        },
        handler=search_documents,
    )

    server.register_tool(
        name="get_document",
        description=(
            "Retrieve a specific document from the RAG knowledge base by its ID. "
            "Use when you know the exact document ID."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "The unique identifier of the document",
                },
            },
            "required": ["document_id"],
        },
        handler=get_document,
    )

    server.register_tool(
        name="delete_document",
        description=(
            "Delete a document from the RAG knowledge base. "
            "Use to remove outdated or incorrect documents."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "description": "The unique identifier of the document to delete",
                },
            },
            "required": ["document_id"],
        },
        handler=delete_document,
    )

    server.register_tool(
        name="list_documents",
        description=(
            "List documents in the RAG knowledge base. "
            "Browse stored documents with optional filtering and pagination."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum number of documents to return",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Number of documents to skip for pagination",
                },
                "metadata_filter": {
                    "type": "object",
                    "description": "Optional filter on metadata fields",
                    "additionalProperties": True,
                },
            },
            "required": [],
        },
        handler=list_documents,
    )

    server.register_tool(
        name="get_rag_stats",
        description=(
            "Get statistics and summary of the RAG knowledge base. "
            "Returns document count, categories breakdown, sources, and recent documents. "
            "Use this to understand what topics are covered before deciding to search."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=get_rag_stats,
    )

    # FastMail Email Tools
    server.register_tool(
        name="list_mailboxes",
        description=(
            "List all mailboxes (folders) in the FastMail account. "
            "Returns mailboxes with their roles (inbox, sent, drafts, trash, etc.), "
            "email counts, and unread counts. Use this first to understand the account "
            "structure before querying emails."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token. If not provided, uses FASTMAIL_API_TOKEN from environment.",
                },
            },
            "required": [],
        },
        handler=list_mailboxes,
    )

    server.register_tool(
        name="get_emails",
        description=(
            "Get emails from a FastMail mailbox with filtering and pagination. "
            "Retrieves email summaries (not full content) for listing. "
            "Specify mailbox by ID or role (inbox, sent, drafts, trash, archive, junk). "
            "Use get_email() to get full content of a specific email."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mailbox_id": {
                    "type": "string",
                    "description": "Specific mailbox ID to query. Takes precedence over mailbox_role.",
                },
                "mailbox_role": {
                    "type": "string",
                    "enum": ["inbox", "sent", "drafts", "trash", "junk", "archive"],
                    "description": "Mailbox role to query. Used if mailbox_id not provided.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                    "description": "Maximum number of emails to return (default: 20)",
                },
                "position": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "Starting position for pagination",
                },
                "sort_by": {
                    "type": "string",
                    "enum": ["receivedAt", "sentAt", "from", "subject"],
                    "default": "receivedAt",
                    "description": "Sort field (default: receivedAt)",
                },
                "sort_descending": {
                    "type": "boolean",
                    "default": True,
                    "description": "Sort in descending order (default: True, newest first)",
                },
                "filter_unread": {
                    "type": "boolean",
                    "description": "Filter to only unread (true) or read (false) emails",
                },
                "filter_flagged": {
                    "type": "boolean",
                    "description": "Filter to only flagged (true) or unflagged (false) emails",
                },
                "filter_from": {
                    "type": "string",
                    "description": "Filter by sender email address (partial match)",
                },
                "filter_subject": {
                    "type": "string",
                    "description": "Filter by subject (partial match)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": [],
        },
        handler=get_emails,
    )

    server.register_tool(
        name="get_email",
        description=(
            "Get the full content of a specific FastMail email. "
            "Retrieves complete email including body text/HTML, all headers, and metadata. "
            "Use this after finding an email with get_emails() or search_emails()."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The unique email ID to retrieve",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        handler=get_email,
    )

    server.register_tool(
        name="search_emails",
        description=(
            "Search FastMail emails using full-text search. "
            "Searches email content, subject, sender, and recipients. "
            "Returns matching emails with search snippets highlighting the matches."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text",
                },
                "mailbox_id": {
                    "type": "string",
                    "description": "Optional mailbox ID to limit search scope",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "Maximum number of results (default: 20)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["query"],
        },
        handler=search_emails,
    )

    server.register_tool(
        name="send_email",
        description=(
            "Send an email via FastMail. "
            "Creates and sends an email using JMAP EmailSubmission. "
            "Supports plain text or HTML body, CC/BCC recipients, and replying to existing emails."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body content (plain text or HTML)",
                },
                "cc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of CC recipients",
                },
                "bcc": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of BCC recipients",
                },
                "reply_to_email_id": {
                    "type": "string",
                    "description": "Optional email ID to reply to (sets In-Reply-To header)",
                },
                "is_html": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, body is treated as HTML (default: false for plain text)",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["to", "subject", "body"],
        },
        handler=send_email,
    )

    server.register_tool(
        name="move_email",
        description=(
            "Move a FastMail email to a different mailbox. "
            "Moves the email from its current mailbox(es) to the specified destination. "
            "Can specify destination by ID or role (inbox, archive, trash, etc.)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to move",
                },
                "to_mailbox_id": {
                    "type": "string",
                    "description": "Destination mailbox ID (takes precedence over role)",
                },
                "to_mailbox_role": {
                    "type": "string",
                    "enum": ["inbox", "archive", "trash", "junk", "drafts", "sent"],
                    "description": "Destination mailbox role",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        handler=move_email,
    )

    server.register_tool(
        name="update_email_flags",
        description=(
            "Update FastMail email flags (read/unread, flagged/unflagged). "
            "Modifies the read status and/or flagged status of an email."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to update",
                },
                "mark_read": {
                    "type": "boolean",
                    "description": "Set to true to mark as read, false for unread",
                },
                "mark_flagged": {
                    "type": "boolean",
                    "description": "Set to true to flag, false to unflag",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        handler=update_email_flags,
    )

    server.register_tool(
        name="delete_email",
        description=(
            "Delete a FastMail email (move to trash or permanently delete). "
            "By default, moves the email to trash. Set permanent=true to permanently "
            "delete the email (cannot be undone)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to delete",
                },
                "permanent": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, permanently delete. If false (default), move to trash.",
                },
                "api_token": {
                    "type": "string",
                    "description": "Optional FastMail API token",
                },
            },
            "required": ["email_id"],
        },
        handler=delete_email,
    )
