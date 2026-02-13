export interface AgentInfo {
  name: string;
  description: string;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string | ContentBlock[];
  timestamp?: string;
  token_count?: number | null;
}

export interface ContentBlock {
  type: 'text' | 'tool_use' | 'tool_result';
  text?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
  content?: string | unknown[];
  is_error?: boolean;
}

export interface Conversation {
  id: string;
  agent: string; // Backend returns "agent" not "agent_name"
  title: string | null;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
  message_count?: number;
  total_tokens?: number;
}

export interface ConversationWithMessages extends Conversation {
  messages: Message[];
}

export interface CreateConversationRequest {
  agent: string; // Backend expects "agent" not "agent_name"
  title?: string;
  metadata?: Record<string, unknown>;
}

export interface SendMessageRequest {
  message: string;
}

export interface SendMessageResponse {
  conversation_id: string;
  message: Message;
  response: Message;
}

export interface UpdateConversationRequest {
  title?: string;
  metadata?: Record<string, unknown>;
}

export interface ConversationStats {
  total_conversations: number;
  total_messages: number;
  total_tokens: number;
  by_agent: Record<string, {
    conversation_count: number;
    message_count: number;
    token_count: number;
  }>;
}

export interface ApiError {
  detail: string;
}

// ---------------------------------------------------------------------------
// Claude Code types
// ---------------------------------------------------------------------------

export interface ClaudeCodeWorkspace {
  name: string;
  path: string;
  is_git_repo: boolean;
  size_mb: number;
  file_count: number;
  current_branch: string | null;
}

export interface ClaudeCodeSession {
  session_id: string;
  workspace: string;
  state: ClaudeCodeSessionState;
  created_at: string;
  last_activity: string;
}

export type ClaudeCodeSessionState =
  | 'starting'
  | 'running'
  | 'waiting_permission'
  | 'waiting_input'
  | 'completed'
  | 'error'
  | 'terminated';

export interface ClaudeCodePermissionRequest {
  id: string;
  tool_type: string;
  description: string;
  command: string | null;
  file_path: string | null;
}

export interface ClaudeCodeEvent {
  type: ClaudeCodeEventType;
  data: string | ClaudeCodePermissionRequest | { state: string } | { exit_code: number };
  timestamp: string;
}

export type ClaudeCodeEventType =
  | 'output'
  | 'permission_request'
  | 'question'
  | 'state_change'
  | 'error'
  | 'completed';

export interface CreateClaudeCodeSessionRequest {
  workspace: string;
  initial_prompt?: string;
}

export interface CreateClaudeCodeWorkspaceRequest {
  name: string;
  git_url?: string;
}
