import { create } from 'zustand';
import type { Conversation, Message } from '@/api/types';
import { apiClient } from '@/api/client';

interface ConversationState {
  conversations: Conversation[];
  currentConversationId: string | null;
  currentMessages: Message[];
  isLoadingConversations: boolean;
  isLoadingMessages: boolean;
  isSendingMessage: boolean;
  error: string | null;

  // Actions
  loadConversations: () => Promise<void>;
  loadConversation: (id: string) => Promise<void>;
  createConversation: (agentName: string, title?: string) => Promise<string>;
  sendMessage: (message: string) => Promise<void>;
  updateConversationTitle: (id: string, title: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  setCurrentConversation: (id: string | null) => void;
  clearError: () => void;
}

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [],
  currentConversationId: null,
  currentMessages: [],
  isLoadingConversations: false,
  isLoadingMessages: false,
  isSendingMessage: false,
  error: null,

  loadConversations: async () => {
    set({ isLoadingConversations: true, error: null });
    try {
      const conversations = await apiClient.listConversations();
      set({ conversations, isLoadingConversations: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to load conversations',
        isLoadingConversations: false,
      });
    }
  },

  loadConversation: async (id: string) => {
    set({ isLoadingMessages: true, error: null });
    try {
      const conversation = await apiClient.getConversation(id);
      set({
        currentConversationId: id,
        currentMessages: conversation.messages,
        isLoadingMessages: false,
      });

      // Update the conversation in the list
      set((state) => ({
        conversations: state.conversations.map((c) =>
          c.id === id ? conversation : c
        ),
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to load conversation',
        isLoadingMessages: false,
      });
    }
  },

  createConversation: async (agentName: string, title?: string) => {
    set({ error: null });
    try {
      const conversation = await apiClient.createConversation({
        agent: agentName,
        title,
      });

      set((state) => ({
        conversations: [conversation, ...state.conversations],
        currentConversationId: conversation.id,
        currentMessages: [],
      }));

      return conversation.id;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to create conversation';
      set({ error: errorMessage });
      throw new Error(errorMessage);
    }
  },

  sendMessage: async (message: string) => {
    const { currentConversationId } = get();
    if (!currentConversationId) {
      set({ error: 'No conversation selected' });
      return;
    }

    set({ isSendingMessage: true, error: null });

    // Optimistic update
    const userMessage: Message = {
      role: 'user',
      content: message,
      timestamp: new Date().toISOString(),
    };

    set((state) => ({
      currentMessages: [...state.currentMessages, userMessage],
    }));

    try {
      const response = await apiClient.sendMessage(currentConversationId, {
        message,
      });

      // Replace optimistic message with server response
      set((state) => ({
        currentMessages: [
          ...state.currentMessages.slice(0, -1),
          response.message,
          response.response,
        ],
        isSendingMessage: false,
      }));

      // Reload conversation list to update metadata
      await get().loadConversations();
    } catch (error) {
      // Remove optimistic message on error
      set((state) => ({
        currentMessages: state.currentMessages.slice(0, -1),
        error: error instanceof Error ? error.message : 'Failed to send message',
        isSendingMessage: false,
      }));
    }
  },

  updateConversationTitle: async (id: string, title: string) => {
    set({ error: null });
    try {
      const updated = await apiClient.updateConversation(id, { title });
      set((state) => ({
        conversations: state.conversations.map((c) =>
          c.id === id ? updated : c
        ),
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to update conversation',
      });
    }
  },

  deleteConversation: async (id: string) => {
    set({ error: null });
    try {
      await apiClient.deleteConversation(id);
      set((state) => ({
        conversations: state.conversations.filter((c) => c.id !== id),
        currentConversationId:
          state.currentConversationId === id ? null : state.currentConversationId,
        currentMessages: state.currentConversationId === id ? [] : state.currentMessages,
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to delete conversation',
      });
    }
  },

  setCurrentConversation: (id: string | null) => {
    set({ currentConversationId: id });
    if (id) {
      get().loadConversation(id);
    } else {
      set({ currentMessages: [] });
    }
  },

  clearError: () => set({ error: null }),
}));
