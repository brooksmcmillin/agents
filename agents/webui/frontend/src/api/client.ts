import { API_BASE_URL } from '@/utils/constants';
import type {
  AgentInfo,
  Conversation,
  ConversationWithMessages,
  CreateConversationRequest,
  SendMessageRequest,
  SendMessageResponse,
  UpdateConversationRequest,
  ConversationStats,
  ApiError,
} from './types';

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string = API_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async request<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
      try {
        const errorData: ApiError = await response.json();
        errorMessage = errorData.detail || errorMessage;
      } catch {
        // Ignore JSON parse errors
      }
      throw new Error(errorMessage);
    }

    return response.json();
  }

  // Agent endpoints
  async listAgents(): Promise<AgentInfo[]> {
    const response = await this.request<{ agents: AgentInfo[] }>('/agents');
    return response.agents;
  }

  // Conversation endpoints
  async listConversations(): Promise<Conversation[]> {
    const response = await this.request<{
      conversations: Conversation[];
      total: number;
      limit: number;
      offset: number;
    }>('/conversations');
    return response.conversations;
  }

  async createConversation(
    data: CreateConversationRequest
  ): Promise<Conversation> {
    return this.request<Conversation>('/conversations', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getConversation(id: string): Promise<ConversationWithMessages> {
    return this.request<ConversationWithMessages>(`/conversations/${id}`);
  }

  async sendMessage(
    conversationId: string,
    data: SendMessageRequest
  ): Promise<SendMessageResponse> {
    return this.request<SendMessageResponse>(
      `/conversations/${conversationId}/message`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  }

  async updateConversation(
    id: string,
    data: UpdateConversationRequest
  ): Promise<Conversation> {
    return this.request<Conversation>(`/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteConversation(id: string): Promise<{ status: string }> {
    return this.request<{ status: string }>(`/conversations/${id}`, {
      method: 'DELETE',
    });
  }

  async getConversationStats(): Promise<ConversationStats> {
    return this.request<ConversationStats>('/conversations/stats');
  }
}

export const apiClient = new ApiClient();
