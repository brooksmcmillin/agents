"""Generic tools for agents."""

# Collect all tool schemas from every tool module.  Each module exposes a
# ``TOOL_SCHEMAS`` list of dicts with ``name``, ``description``,
# ``input_schema``, and ``handler`` keys.  Importing them here gives server
# code a single ``ALL_TOOL_SCHEMAS`` to iterate instead of manually
# registering each tool inline.
from .browser_testing import TOOL_SCHEMAS as _browser_testing_schemas
from .browser_testing import (
    browser_accessibility_audit,
    browser_check_links,
    browser_console_errors,
    browser_crawl_site,
    browser_performance_audit,
    browser_screenshot,
)
from .claude_code import TOOL_SCHEMAS as _claude_code_schemas
from .claude_code import (
    create_claude_code_workspace,
    delete_claude_code_workspace,
    get_claude_code_workspace_status,
    list_claude_code_workspaces,
    run_claude_code,
)
from .content_suggestions import TOOL_SCHEMAS as _content_suggestions_schemas
from .content_suggestions import suggest_content_topics
from .fastmail import TOOL_SCHEMAS as _fastmail_schemas
from .fastmail import (
    delete_email,
    get_calendar_events,
    get_email,
    get_emails,
    list_calendars,
    list_mailboxes,
    move_email,
    search_emails,
    send_agent_report,
    send_email,
    update_email_flags,
)
from .filesystem import TOOL_SCHEMAS as _filesystem_schemas
from .filesystem import edit_file, glob_files, grep_files, list_directory, read_file, write_file
from .http_client import TOOL_SCHEMAS as _http_client_schemas
from .http_client import (
    http_check_rate_limit,
    http_clear_session,
    http_fuzz_parameter,
    http_inspect_headers,
    http_request,
    http_session_login,
    http_upload_file,
)
from .markdown_files import TOOL_SCHEMAS as _markdown_files_schemas
from .markdown_files import (
    delete_markdown_file,
    list_markdown_files,
    read_markdown_file,
    write_markdown_file,
)
from .memory import TOOL_SCHEMAS as _memory_schemas
from .memory import (
    AsyncFileMemoryAdapter,
    MemoryStoreProtocol,
    configure_memory_store,
    delete_memory,
    get_active_memory_store,
    get_memories,
    get_memory_backend,
    get_memory_stats,
    recall_memories,
    save_memory,
    search_memories,
)
from .network_admin import TOOL_SCHEMAS as _network_admin_schemas
from .network_admin import (
    network_check_default_credentials,
    network_check_dns,
    network_check_tls,
    network_discover_hosts,
    network_generate_report,
    network_grab_banners,
    network_scan_ports,
    system_check_file_permissions,
    system_check_firewall,
    system_check_ssh_config,
    system_get_info,
)
from .rag import TOOL_SCHEMAS as _rag_schemas
from .rag import (
    add_document,
    delete_document,
    get_document,
    get_rag_stats,
    list_documents,
    search_documents,
)
from .slack import TOOL_SCHEMAS as _slack_schemas
from .slack import send_slack_message
from .social_media import TOOL_SCHEMAS as _social_media_schemas
from .social_media import get_social_media_stats
from .twilio_sms import TOOL_SCHEMAS as _twilio_sms_schemas
from .twilio_sms import get_sms_status, send_sms_to_admin
from .twilio_sms_clarification import TOOL_SCHEMAS as _twilio_sms_clarification_schemas
from .twilio_sms_clarification import (
    get_sms_clarification_status,
    get_sms_phone_pool_status,
    send_sms_clarification,
)
from .web_analyzer import TOOL_SCHEMAS as _web_analyzer_schemas
from .web_analyzer import analyze_website
from .web_reader import TOOL_SCHEMAS as _web_reader_schemas
from .web_reader import fetch_web_content

ALL_TOOL_SCHEMAS: list[dict] = [
    *_web_reader_schemas,
    *_web_analyzer_schemas,
    *_browser_testing_schemas,
    *_memory_schemas,
    *_slack_schemas,
    *_twilio_sms_schemas,
    *_twilio_sms_clarification_schemas,
    *_social_media_schemas,
    *_content_suggestions_schemas,
    *_rag_schemas,
    *_fastmail_schemas,
    *_claude_code_schemas,
    *_markdown_files_schemas,
    *_http_client_schemas,
    *_filesystem_schemas,
    *_network_admin_schemas,
]

__all__ = [
    "ALL_TOOL_SCHEMAS",
    "AsyncFileMemoryAdapter",
    "MemoryStoreProtocol",
    "analyze_website",
    "configure_memory_store",
    "delete_memory",
    "fetch_web_content",
    "get_active_memory_store",
    "get_memories",
    "get_memory_backend",
    "get_memory_stats",
    "get_social_media_stats",
    "recall_memories",
    "save_memory",
    "search_memories",
    "send_slack_message",
    "send_sms_to_admin",
    "get_sms_status",
    # SMS Clarification tools
    "send_sms_clarification",
    "get_sms_clarification_status",
    "get_sms_phone_pool_status",
    "suggest_content_topics",
    # RAG tools
    "add_document",
    "search_documents",
    "get_document",
    "delete_document",
    "list_documents",
    "get_rag_stats",
    # FastMail tools - Email
    "list_mailboxes",
    "get_emails",
    "get_email",
    "search_emails",
    "send_email",
    "send_agent_report",
    "move_email",
    "update_email_flags",
    "delete_email",
    # FastMail tools - Calendar
    "list_calendars",
    "get_calendar_events",
    # Claude Code tools
    "run_claude_code",
    "list_claude_code_workspaces",
    "create_claude_code_workspace",
    "delete_claude_code_workspace",
    "get_claude_code_workspace_status",
    # Markdown file tools
    "list_markdown_files",
    "read_markdown_file",
    "write_markdown_file",
    "delete_markdown_file",
    # HTTP client tools
    "http_request",
    "http_session_login",
    "http_upload_file",
    "http_inspect_headers",
    "http_fuzz_parameter",
    "http_check_rate_limit",
    "http_clear_session",
    # Filesystem tools
    "read_file",
    "write_file",
    "edit_file",
    "list_directory",
    "glob_files",
    "grep_files",
    # Browser testing tools
    "browser_screenshot",
    "browser_accessibility_audit",
    "browser_performance_audit",
    "browser_console_errors",
    "browser_check_links",
    "browser_crawl_site",
    # Network admin tools
    "network_discover_hosts",
    "network_scan_ports",
    "network_check_tls",
    "network_grab_banners",
    "network_check_dns",
    "system_get_info",
    "system_check_ssh_config",
    "system_check_file_permissions",
    "system_check_firewall",
    "network_check_default_credentials",
    "network_generate_report",
]
