import { useState, useEffect, KeyboardEvent } from 'react';
import { PaperAirplaneIcon, MicrophoneIcon } from '@heroicons/react/24/solid';
import { Button } from './Button';
import { useVoiceInput } from '@/hooks/useVoiceInput';

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

  const { isSupported, isListening, transcript, error, toggleListening } = useVoiceInput({
    onResult: (finalTranscript) => {
      setMessage((prev) => {
        const separator = prev.trim() ? ' ' : '';
        return prev.trim() + separator + finalTranscript;
      });
    },
  });

  // Update textarea with interim transcript while speaking
  useEffect(() => {
    if (isListening && transcript) {
      setMessage((prev) => {
        // Show interim text after any existing content
        const base = prev.replace(/\s*\[\.{3}\]$/, '').trim();
        const separator = base ? ' ' : '';
        return base + separator + transcript;
      });
    }
  }, [isListening, transcript]);

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
          placeholder={isListening ? 'Listening...' : placeholder}
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
        <div className="flex flex-col gap-2 self-end">
          {isSupported && (
            <Button
              onClick={toggleListening}
              disabled={disabled}
              variant={isListening ? 'danger' : 'ghost'}
              title={isListening ? 'Stop listening' : 'Voice input'}
              className={`relative min-w-[44px] min-h-[44px] ${isListening ? 'animate-pulse' : ''}`}
            >
              <MicrophoneIcon className="h-5 w-5" />
              {isListening && (
                <span className="absolute top-1 right-1 h-2.5 w-2.5 rounded-full bg-red-400 animate-ping" />
              )}
            </Button>
          )}
          <Button
            onClick={handleSend}
            disabled={!message.trim() || disabled}
            title="Send message (Enter)"
            className="min-w-[44px] min-h-[44px]"
          >
            <PaperAirplaneIcon className="h-5 w-5" />
          </Button>
        </div>
      </div>
      <div className="max-w-4xl mx-auto mt-2 flex items-center justify-between">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Press Enter to send, Shift+Enter for new line
        </p>
        {error && (
          <p className="text-xs text-red-500 dark:text-red-400">{error}</p>
        )}
      </div>
    </div>
  );
}
