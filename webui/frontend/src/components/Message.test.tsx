import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Message } from './Message';
import type { Message as MessageType } from '@/api/types';

describe('Message Component', () => {
  it('renders user message correctly', () => {
    const message: MessageType = {
      role: 'user',
      content: 'Hello, how are you?',
      timestamp: '2024-01-01T12:00:00Z',
      token_count: 10,
    };

    render(<Message message={message} />);

    expect(screen.getByText('Hello, how are you?')).toBeInTheDocument();
    expect(screen.getByText('10')).toBeInTheDocument();
  });

  it('renders assistant message correctly', () => {
    const message: MessageType = {
      role: 'assistant',
      content: "I'm doing well, thank you!",
      timestamp: '2024-01-01T12:00:01Z',
      token_count: 15,
    };

    render(<Message message={message} />);

    expect(screen.getByText("I'm doing well, thank you!")).toBeInTheDocument();
    expect(screen.getByText('15')).toBeInTheDocument();
  });

  it('handles content blocks with text', () => {
    const message: MessageType = {
      role: 'assistant',
      content: [
        { type: 'text', text: 'First paragraph' },
        { type: 'text', text: 'Second paragraph' },
      ],
    };

    render(<Message message={message} />);

    expect(screen.getByText(/First paragraph/)).toBeInTheDocument();
    expect(screen.getByText(/Second paragraph/)).toBeInTheDocument();
  });

  it('shows tool use indicator', () => {
    const message: MessageType = {
      role: 'assistant',
      content: [
        { type: 'tool_use', name: 'search_documents', id: 'tool-1' },
      ],
    };

    render(<Message message={message} />);

    expect(screen.getByText('[Using tool: search_documents]')).toBeInTheDocument();
  });

  it('does not render empty messages', () => {
    const message: MessageType = {
      role: 'assistant',
      content: '',
    };

    const { container } = render(<Message message={message} />);

    expect(container.firstChild).toBeNull();
  });

  it('renders without token count when not provided', () => {
    const message: MessageType = {
      role: 'user',
      content: 'Test message',
    };

    render(<Message message={message} />);

    expect(screen.getByText('Test message')).toBeInTheDocument();
    expect(screen.queryByTitle(/tokens/)).not.toBeInTheDocument();
  });
});
