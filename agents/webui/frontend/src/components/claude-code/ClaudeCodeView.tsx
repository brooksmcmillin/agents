import { useEffect, useState, useRef, KeyboardEvent, useCallback } from 'react';
import {
  PlayIcon,
  StopIcon,
  ArrowPathIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import { useClaudeCodeStore } from '@/store/claudeCodeStore';
import { Button } from '@/components/Button';
import { WorkspaceSelector } from './WorkspaceSelector';
import { TerminalOutput, TerminalHandle } from './TerminalOutput';
import { PermissionDialog } from './PermissionDialog';

export function ClaudeCodeView() {
  const [inputValue, setInputValue] = useState('');
  const [initialPrompt, setInitialPrompt] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const terminalRef = useRef<TerminalHandle>(null);

  const {
    workspaces,
    isLoadingWorkspaces,
    selectedWorkspace,
    activeSession,
    sessionState,
    isConnecting,
    pendingPermission,
    error,
    loadWorkspaces,
    createWorkspace,
    deleteWorkspace,
    selectWorkspace,
    startSession,
    endSession,
    sendInput,
    respondToPermission,
    resizeTerminal,
    clearError,
    setTerminalWriter,
  } = useClaudeCodeStore();

  // Load workspaces on mount
  useEffect(() => {
    loadWorkspaces();
  }, [loadWorkspaces]);

  // Register terminal writer when terminal is ready
  useEffect(() => {
    if (terminalRef.current) {
      setTerminalWriter({
        write: (data: string) => terminalRef.current?.write(data),
        writeln: (data: string) => terminalRef.current?.writeln(data),
        clear: () => terminalRef.current?.clear(),
      });
    }
    return () => {
      setTerminalWriter(null);
    };
  }, [setTerminalWriter]);

  // Focus input when session starts
  useEffect(() => {
    if (activeSession && inputRef.current) {
      inputRef.current.focus();
    }
  }, [activeSession]);

  const handleStart = async () => {
    if (!selectedWorkspace) return;
    terminalRef.current?.clear();
    await startSession(selectedWorkspace, initialPrompt || undefined);
    setInitialPrompt('');
  };

  const handleStop = async () => {
    await endSession();
  };

  const handleSendInput = () => {
    if (!inputValue.trim() || !activeSession) return;
    sendInput(inputValue);
    setInputValue('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendInput();
    }
  };

  const handleClear = () => {
    terminalRef.current?.clear();
  };

  // Handle terminal resize
  const handleTerminalResize = useCallback((cols: number, rows: number) => {
    resizeTerminal(rows, cols);
  }, [resizeTerminal]);

  const isSessionActive = activeSession && sessionState !== 'completed' && sessionState !== 'terminated' && sessionState !== 'error';

  const getStatusBadge = () => {
    if (!sessionState) return null;

    const statusColors: Record<string, string> = {
      starting: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
      running: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
      waiting_permission: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
      waiting_input: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      completed: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
      error: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
      terminated: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200',
    };

    return (
      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${statusColors[sessionState] || statusColors.running}`}>
        {sessionState.replace('_', ' ')}
      </span>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            Claude Code
          </h2>
          {getStatusBadge()}
        </div>

        {/* Workspace selector and controls */}
        <div className="space-y-3">
          <WorkspaceSelector
            workspaces={workspaces}
            selectedWorkspace={selectedWorkspace}
            onSelect={selectWorkspace}
            onCreateWorkspace={createWorkspace}
            onDeleteWorkspace={deleteWorkspace}
            disabled={isSessionActive || isLoadingWorkspaces}
          />

          {!activeSession && (
            <div className="flex gap-2">
              <input
                type="text"
                value={initialPrompt}
                onChange={(e) => setInitialPrompt(e.target.value)}
                placeholder="Initial prompt (optional)..."
                className="flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-sm focus:border-primary-500 focus:ring-primary-500"
                disabled={!selectedWorkspace || isConnecting}
              />
              <Button
                onClick={handleStart}
                disabled={!selectedWorkspace || isConnecting}
              >
                {isConnecting ? (
                  <>
                    <ArrowPathIcon className="h-4 w-4 mr-2 animate-spin" />
                    Connecting...
                  </>
                ) : (
                  <>
                    <PlayIcon className="h-4 w-4 mr-2" />
                    Start
                  </>
                )}
              </Button>
            </div>
          )}

          {activeSession && (
            <div className="flex justify-between items-center">
              <span className="text-sm text-gray-500 dark:text-gray-400">
                Workspace: <span className="font-medium text-gray-700 dark:text-gray-300">{activeSession.workspace}</span>
              </span>
              <div className="flex gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleClear}
                  title="Clear output"
                >
                  <TrashIcon className="h-4 w-4" />
                </Button>
                <Button
                  variant="danger"
                  size="sm"
                  onClick={handleStop}
                >
                  <StopIcon className="h-4 w-4 mr-1" />
                  Stop
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Terminal output */}
      <div className="flex-1 overflow-hidden p-4">
        <TerminalOutput
          ref={terminalRef}
          className="h-full"
          onResize={handleTerminalResize}
        />
      </div>

      {/* Input area */}
      {isSessionActive && (
        <div className="flex-shrink-0 p-4 border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message..."
              className="flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-sm focus:border-primary-500 focus:ring-primary-500 font-mono"
              disabled={sessionState === 'waiting_permission'}
            />
            <Button
              onClick={handleSendInput}
              disabled={!inputValue.trim() || sessionState === 'waiting_permission'}
            >
              Send
            </Button>
          </div>
          {sessionState === 'waiting_permission' && (
            <p className="text-xs text-orange-500 mt-1">
              Please respond to the permission request above
            </p>
          )}
        </div>
      )}

      {/* Permission dialog */}
      <PermissionDialog
        permission={pendingPermission}
        onApprove={() => respondToPermission(true)}
        onDeny={() => respondToPermission(false)}
      />

      {/* Error toast */}
      {error && (
        <div className="fixed bottom-4 right-4 z-50 max-w-md">
          <div className="bg-red-500 text-white px-4 py-3 rounded-lg shadow-lg flex items-start gap-3">
            <div className="flex-1">
              <p className="font-medium">Error</p>
              <p className="text-sm mt-1">{error}</p>
            </div>
            <button
              onClick={clearError}
              className="text-white hover:text-gray-200"
            >
              X
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
