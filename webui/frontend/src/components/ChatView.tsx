import { useConversationStore } from '@/store/conversationStore';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { AGENT_NAMES, AGENT_COLORS } from '@/utils/constants';
import type { AgentName } from '@/utils/constants';

export function ChatView() {
  const {
    currentConversationId,
    currentMessages,
    conversations,
    isLoadingMessages,
    isSendingMessage,
    sendMessage,
  } = useConversationStore();

  const currentConversation = conversations.find(
    (c) => c.id === currentConversationId
  );

  if (!currentConversationId || !currentConversation) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <div className="text-center text-gray-500 dark:text-gray-400">
          <p className="text-lg font-medium mb-2">No conversation selected</p>
          <p className="text-sm">Select a conversation or create a new one to start chatting</p>
        </div>
      </div>
    );
  }

  const agentName = currentConversation.agent as AgentName;
  const agentDisplayName = AGENT_NAMES[agentName] || currentConversation.agent;
  const agentColor = AGENT_COLORS[agentName] || 'bg-gray-500';

  return (
    <div className="flex-1 flex flex-col bg-white dark:bg-gray-900">
      {/* Header */}
      <div className="border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-6 py-4">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full ${agentColor} flex items-center justify-center text-white font-semibold`}>
              {agentDisplayName.charAt(0)}
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
                {currentConversation.title || 'New Conversation'}
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                {agentDisplayName}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Messages */}
      <MessageList messages={currentMessages} isLoading={isLoadingMessages} />

      {/* Input */}
      <ChatInput
        onSend={sendMessage}
        disabled={isSendingMessage}
        placeholder={`Message ${agentDisplayName}...`}
      />
    </div>
  );
}
