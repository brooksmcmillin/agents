import { formatRelativeTime } from '@/utils/formatters';
import { AGENT_NAMES, AGENT_COLORS } from '@/utils/constants';
import { ConversationMenu } from './ConversationMenu';
import type { Conversation } from '@/api/types';
import type { AgentName } from '@/utils/constants';

interface ConversationListItemProps {
  conversation: Conversation;
  isActive: boolean;
  onClick: () => void;
}

export function ConversationListItem({
  conversation,
  isActive,
  onClick,
}: ConversationListItemProps) {
  const agentName = conversation.agent as AgentName;
  const agentDisplayName = AGENT_NAMES[agentName] || conversation.agent;
  const agentColor = AGENT_COLORS[agentName] || 'bg-gray-500';

  return (
    <div
      className={`
        group relative px-3 py-3 rounded-lg cursor-pointer transition-colors
        ${
          isActive
            ? 'bg-primary-100 dark:bg-primary-900/30'
            : 'hover:bg-gray-100 dark:hover:bg-gray-800'
        }
      `}
      onClick={onClick}
    >
      <div className="flex items-start gap-3">
        <div
          className={`
            w-8 h-8 rounded-full ${agentColor}
            flex items-center justify-center text-white text-sm font-semibold flex-shrink-0
          `}
        >
          {agentDisplayName.charAt(0)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-medium text-gray-900 dark:text-white truncate">
              {conversation.title || 'New Conversation'}
            </h3>
            <div
              className="opacity-0 group-hover:opacity-100 transition-opacity"
              onClick={(e) => e.stopPropagation()}
            >
              <ConversationMenu
                conversationId={conversation.id}
                currentTitle={conversation.title}
              />
            </div>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 truncate">
            {agentDisplayName}
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
            {formatRelativeTime(conversation.updated_at)}
          </p>
        </div>
      </div>
    </div>
  );
}
