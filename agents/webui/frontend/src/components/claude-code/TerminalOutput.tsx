import { useEffect, useRef } from 'react';

interface OutputLine {
  id: number;
  text: string;
  timestamp: Date;
  type: 'output' | 'error' | 'system';
}

interface TerminalOutputProps {
  lines: OutputLine[];
  className?: string;
}

// Simple ANSI escape code stripper for display
function stripAnsi(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]|\x1b\].*?\x07/g, '');
}

export function TerminalOutput({ lines, className = '' }: TerminalOutputProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (containerRef.current && shouldAutoScroll.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines]);

  // Detect if user scrolled up (disable auto-scroll)
  const handleScroll = () => {
    if (containerRef.current) {
      const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
      // If scrolled within 50px of bottom, enable auto-scroll
      shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 50;
    }
  };

  const getLineClass = (type: OutputLine['type']) => {
    switch (type) {
      case 'error':
        return 'text-red-400';
      case 'system':
        return 'text-blue-400 italic';
      default:
        return 'text-gray-100';
    }
  };

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className={`
        bg-gray-900 text-gray-100 font-mono text-sm
        overflow-y-auto overflow-x-auto
        p-4 rounded-lg
        ${className}
      `}
    >
      {lines.length === 0 ? (
        <div className="text-gray-500 italic">
          Waiting for output...
        </div>
      ) : (
        lines.map((line) => (
          <div
            key={line.id}
            className={`whitespace-pre-wrap break-words ${getLineClass(line.type)}`}
          >
            {stripAnsi(line.text)}
          </div>
        ))
      )}
    </div>
  );
}
