import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';

export interface TerminalHandle {
  write: (data: string) => void;
  writeln: (data: string) => void;
  clear: () => void;
  focus: () => void;
}

interface TerminalOutputProps {
  className?: string;
  onData?: (data: string) => void;
  onResize?: (cols: number, rows: number) => void;
}

export const TerminalOutput = forwardRef<TerminalHandle, TerminalOutputProps>(
  ({ className = '', onData, onResize }, ref) => {
    const containerRef = useRef<HTMLDivElement>(null);
    const terminalRef = useRef<Terminal | null>(null);
    const fitAddonRef = useRef<FitAddon | null>(null);

    useImperativeHandle(ref, () => ({
      write: (data: string) => {
        terminalRef.current?.write(data);
      },
      writeln: (data: string) => {
        terminalRef.current?.writeln(data);
      },
      clear: () => {
        terminalRef.current?.clear();
      },
      focus: () => {
        terminalRef.current?.focus();
      },
    }));

    useEffect(() => {
      if (!containerRef.current) return;

      // Create terminal with dark theme
      const terminal = new Terminal({
        cursorBlink: false,
        cursorStyle: 'block',
        fontSize: 14,
        fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
        theme: {
          background: '#111827', // gray-900
          foreground: '#f3f4f6', // gray-100
          cursor: '#f3f4f6',
          cursorAccent: '#111827',
          selectionBackground: '#374151', // gray-700
          black: '#1f2937',
          red: '#f87171',
          green: '#4ade80',
          yellow: '#facc15',
          blue: '#60a5fa',
          magenta: '#c084fc',
          cyan: '#22d3ee',
          white: '#f3f4f6',
          brightBlack: '#4b5563',
          brightRed: '#fca5a5',
          brightGreen: '#86efac',
          brightYellow: '#fde047',
          brightBlue: '#93c5fd',
          brightMagenta: '#d8b4fe',
          brightCyan: '#67e8f9',
          brightWhite: '#ffffff',
        },
        allowProposedApi: true,
        scrollback: 10000,
        convertEol: true,
      });

      // Add fit addon for auto-sizing
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      fitAddonRef.current = fitAddon;

      // Add web links addon for clickable URLs
      const webLinksAddon = new WebLinksAddon();
      terminal.loadAddon(webLinksAddon);

      // Open terminal in container
      terminal.open(containerRef.current);

      // Fit to container
      fitAddon.fit();

      // Handle user input
      if (onData) {
        terminal.onData(onData);
      }

      // Handle resize
      if (onResize) {
        terminal.onResize(({ cols, rows }) => {
          onResize(cols, rows);
        });
      }

      terminalRef.current = terminal;

      // Handle window resize
      const handleResize = () => {
        fitAddon.fit();
      };
      window.addEventListener('resize', handleResize);

      // Create ResizeObserver for container size changes
      const resizeObserver = new ResizeObserver(() => {
        fitAddon.fit();
      });
      resizeObserver.observe(containerRef.current);

      return () => {
        window.removeEventListener('resize', handleResize);
        resizeObserver.disconnect();
        terminal.dispose();
        terminalRef.current = null;
        fitAddonRef.current = null;
      };
    }, [onData, onResize]);

    return (
      <div
        ref={containerRef}
        className={`rounded-lg overflow-hidden ${className}`}
        style={{ backgroundColor: '#111827' }}
      />
    );
  }
);

TerminalOutput.displayName = 'TerminalOutput';
