import { formatTimestamp } from '@/utils/formatters';
import { TokenBadge } from './TokenBadge';
import type { Message as MessageType, ContentBlock } from '@/api/types';

interface MessageProps {
  message: MessageType;
}

function renderContent(content: string | ContentBlock[]): string {
  if (typeof content === 'string') {
    return content;
  }

  // Extract text from content blocks
  return content
    .map((block) => {
      if (block.type === 'text' && block.text) {
        return block.text;
      }
      if (block.type === 'tool_use') {
        return `[Using tool: ${block.name}]`;
      }
      if (block.type === 'tool_result') {
        if (block.is_error) {
          return `[Tool error: ${typeof block.content === 'string' ? block.content : 'Unknown error'}]`;
        }
        return ''; // Don't show successful tool results in chat
      }
      return '';
    })
    .filter(Boolean)
    .join('\n\n');
}

export function Message({ message }: MessageProps) {
  const isUser = message.role === 'user';
  const content = renderContent(message.content);

  if (!content.trim()) {
    return null; // Don't render empty messages
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`
          max-w-[80%] rounded-lg px-4 py-2
          ${
            isUser
              ? 'bg-primary-600 text-white'
              : 'bg-gray-200 text-gray-900 dark:bg-gray-700 dark:text-gray-100'
          }
        `}
      >
        <div className="whitespace-pre-wrap break-words">{content}</div>
        <div className="flex items-center gap-2 mt-2 text-xs opacity-70">
          {message.timestamp && (
            <span>{formatTimestamp(message.timestamp)}</span>
          )}
          {message.token_count && <TokenBadge count={message.token_count} />}
        </div>
      </div>
    </div>
  );
}
