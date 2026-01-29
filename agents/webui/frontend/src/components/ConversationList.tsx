import { useEffect } from 'react';
import { useConversationStore } from '@/store/conversationStore';
import { ConversationListItem } from './ConversationListItem';
import { Spinner } from './Spinner';

export function ConversationList() {
  const {
    conversations,
    currentConversationId,
    isLoadingConversations,
    loadConversations,
    setCurrentConversation,
  } = useConversationStore();

  useEffect(() => {
    loadConversations();
  }, []);

  if (isLoadingConversations) {
    return (
      <div className="flex items-center justify-center py-8">
        <Spinner />
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-sm text-gray-500 dark:text-gray-400">
        No conversations yet. Create one to get started!
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {conversations.map((conversation) => (
        <ConversationListItem
          key={conversation.id}
          conversation={conversation}
          isActive={conversation.id === currentConversationId}
          onClick={() => setCurrentConversation(conversation.id)}
        />
      ))}
    </div>
  );
}
