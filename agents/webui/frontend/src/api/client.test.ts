import { describe, it, expect, beforeEach, vi } from 'vitest';
import { apiClient } from './client';

describe('ApiClient', () => {
  beforeEach(() => {
    // Reset fetch mock before each test
    global.fetch = vi.fn();
  });

  describe('listAgents', () => {
    it('should fetch and return agents list', async () => {
      const mockResponse = {
        agents: [
          { name: 'chatbot', description: 'General-purpose chatbot' },
          { name: 'pr', description: 'PR assistant' },
        ],
      };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const result = await apiClient.listAgents();

      expect(global.fetch).toHaveBeenCalledWith(
        '/agents',
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
        })
      );
      expect(result).toEqual(mockResponse.agents);
    });

    it('should handle API errors', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => ({ detail: 'Server error' }),
      });

      await expect(apiClient.listAgents()).rejects.toThrow('Server error');
    });
  });

  describe('listConversations', () => {
    it('should fetch and return conversations list', async () => {
      const mockResponse = {
        conversations: [
          {
            id: 'conv-1',
            agent: 'chatbot',
            title: 'Test Conversation',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            message_count: 5,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const result = await apiClient.listConversations();

      expect(result).toEqual(mockResponse.conversations);
      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('conv-1');
    });
  });

  describe('createConversation', () => {
    it('should create a new conversation', async () => {
      const mockConversation = {
        id: 'conv-new',
        agent: 'chatbot',
        title: 'New Chat',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
        message_count: 0,
      };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockConversation,
      });

      const result = await apiClient.createConversation({
        agent: 'chatbot',
        title: 'New Chat',
      });

      expect(global.fetch).toHaveBeenCalledWith(
        '/conversations',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ agent: 'chatbot', title: 'New Chat' }),
        })
      );
      expect(result).toEqual(mockConversation);
    });
  });

  describe('sendMessage', () => {
    it('should send a message and return response', async () => {
      const mockResponse = {
        conversation_id: 'conv-1',
        message: {
          role: 'user',
          content: 'Hello',
        },
        response: {
          role: 'assistant',
          content: 'Hi there!',
        },
      };

      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      });

      const result = await apiClient.sendMessage('conv-1', { message: 'Hello' });

      expect(global.fetch).toHaveBeenCalledWith(
        '/conversations/conv-1/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ message: 'Hello' }),
        })
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe('deleteConversation', () => {
    it('should delete a conversation', async () => {
      (global.fetch as any).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ status: 'deleted' }),
      });

      const result = await apiClient.deleteConversation('conv-1');

      expect(global.fetch).toHaveBeenCalledWith(
        '/conversations/conv-1',
        expect.objectContaining({
          method: 'DELETE',
        })
      );
      expect(result).toEqual({ status: 'deleted' });
    });
  });
});
