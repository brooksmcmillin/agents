import { useState, KeyboardEvent } from 'react';
import { PaperAirplaneIcon } from '@heroicons/react/24/solid';
import { Button } from './Button';

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = 'Type your message...',
}: ChatInputProps) {
  const [message, setMessage] = useState('');

  const handleSend = () => {
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage('');
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-4">
      <div className="max-w-4xl mx-auto flex gap-2">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={3}
          className="
            flex-1 resize-none rounded-lg border-gray-300 shadow-sm
            focus:border-primary-500 focus:ring-primary-500
            dark:bg-gray-700 dark:border-gray-600 dark:text-white
            dark:placeholder-gray-400
            disabled:opacity-50 disabled:cursor-not-allowed
          "
        />
        <Button
          onClick={handleSend}
          disabled={!message.trim() || disabled}
          className="self-end"
          title="Send message (Enter)"
        >
          <PaperAirplaneIcon className="h-5 w-5" />
        </Button>
      </div>
      <p className="max-w-4xl mx-auto mt-2 text-xs text-gray-500 dark:text-gray-400">
        Press Enter to send, Shift+Enter for new line
      </p>
    </div>
  );
}
