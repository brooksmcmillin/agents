import { create } from 'zustand';
import { apiClient } from '@/api/client';
import type {
  ClaudeCodeWorkspace,
  ClaudeCodeSession,
  ClaudeCodeEvent,
  ClaudeCodePermissionRequest,
  ClaudeCodeSessionState,
} from '@/api/types';

interface OutputLine {
  id: number;
  text: string;
  timestamp: Date;
  type: 'output' | 'error' | 'system';
}

interface ClaudeCodeState {
  // Workspaces
  workspaces: ClaudeCodeWorkspace[];
  isLoadingWorkspaces: boolean;
  selectedWorkspace: string | null;

  // Active session
  activeSession: ClaudeCodeSession | null;
  sessionState: ClaudeCodeSessionState | null;
  isConnecting: boolean;

  // Terminal output
  outputLines: OutputLine[];
  outputLineCounter: number;

  // Permission handling
  pendingPermission: ClaudeCodePermissionRequest | null;

  // WebSocket
  ws: WebSocket | null;

  // Error handling
  error: string | null;

  // Actions
  loadWorkspaces: () => Promise<void>;
  createWorkspace: (name: string, gitUrl?: string) => Promise<void>;
  deleteWorkspace: (name: string, force?: boolean) => Promise<void>;
  selectWorkspace: (name: string | null) => void;

  startSession: (workspace: string, initialPrompt?: string) => Promise<void>;
  endSession: () => Promise<void>;
  connectWebSocket: (sessionId: string) => void;
  disconnectWebSocket: () => void;

  sendInput: (text: string) => void;
  respondToPermission: (approved: boolean) => void;
  resizeTerminal: (rows: number, cols: number) => void;

  clearOutput: () => void;
  clearError: () => void;
}

export const useClaudeCodeStore = create<ClaudeCodeState>((set, get) => ({
  // Initial state
  workspaces: [],
  isLoadingWorkspaces: false,
  selectedWorkspace: null,

  activeSession: null,
  sessionState: null,
  isConnecting: false,

  outputLines: [],
  outputLineCounter: 0,

  pendingPermission: null,

  ws: null,

  error: null,

  // Workspace actions
  loadWorkspaces: async () => {
    set({ isLoadingWorkspaces: true, error: null });
    try {
      const workspaces = await apiClient.listClaudeCodeWorkspaces();
      set({ workspaces, isLoadingWorkspaces: false });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to load workspaces',
        isLoadingWorkspaces: false,
      });
    }
  },

  createWorkspace: async (name: string, gitUrl?: string) => {
    try {
      const workspace = await apiClient.createClaudeCodeWorkspace({ name, git_url: gitUrl });
      set((state) => ({
        workspaces: [...state.workspaces, workspace],
        selectedWorkspace: workspace.name,
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to create workspace' });
      throw err;
    }
  },

  deleteWorkspace: async (name: string, force = false) => {
    try {
      await apiClient.deleteClaudeCodeWorkspace(name, force);
      set((state) => ({
        workspaces: state.workspaces.filter((w) => w.name !== name),
        selectedWorkspace: state.selectedWorkspace === name ? null : state.selectedWorkspace,
      }));
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Failed to delete workspace' });
      throw err;
    }
  },

  selectWorkspace: (name: string | null) => {
    set({ selectedWorkspace: name });
  },

  // Session actions
  startSession: async (workspace: string, initialPrompt?: string) => {
    const { endSession } = get();

    // End any existing session first
    await endSession();

    set({ isConnecting: true, error: null, outputLines: [], outputLineCounter: 0 });

    try {
      const session = await apiClient.createClaudeCodeSession({
        workspace,
        initial_prompt: initialPrompt,
      });

      set({
        activeSession: session,
        sessionState: session.state,
        isConnecting: false,
      });

      // Connect WebSocket
      get().connectWebSocket(session.session_id);

      // Add system message
      const { outputLineCounter } = get();
      set({
        outputLines: [
          {
            id: outputLineCounter,
            text: `Connected to Claude Code in workspace: ${workspace}`,
            timestamp: new Date(),
            type: 'system',
          },
        ],
        outputLineCounter: outputLineCounter + 1,
      });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'Failed to start session',
        isConnecting: false,
      });
      throw err;
    }
  },

  endSession: async () => {
    const { activeSession, disconnectWebSocket } = get();

    disconnectWebSocket();

    if (activeSession) {
      try {
        await apiClient.deleteClaudeCodeSession(activeSession.session_id);
      } catch {
        // Ignore errors when ending session
      }
    }

    set({
      activeSession: null,
      sessionState: null,
      pendingPermission: null,
    });
  },

  connectWebSocket: (sessionId: string) => {
    const { disconnectWebSocket } = get();
    disconnectWebSocket();

    const wsUrl = apiClient.getClaudeCodeWebSocketUrl(sessionId);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (event) => {
      try {
        const data: ClaudeCodeEvent = JSON.parse(event.data);
        const { outputLineCounter, outputLines } = get();

        switch (data.type) {
          case 'output': {
            const text = typeof data.data === 'string' ? data.data : JSON.stringify(data.data);
            set({
              outputLines: [
                ...outputLines,
                {
                  id: outputLineCounter,
                  text,
                  timestamp: new Date(data.timestamp),
                  type: 'output',
                },
              ],
              outputLineCounter: outputLineCounter + 1,
            });
            break;
          }

          case 'permission_request': {
            const permission = data.data as ClaudeCodePermissionRequest;
            set({
              pendingPermission: permission,
              sessionState: 'waiting_permission',
            });
            break;
          }

          case 'state_change': {
            const stateData = data.data as { state: string };
            set({ sessionState: stateData.state as ClaudeCodeSessionState });
            break;
          }

          case 'error': {
            const errorText = typeof data.data === 'string' ? data.data : JSON.stringify(data.data);
            set({
              outputLines: [
                ...outputLines,
                {
                  id: outputLineCounter,
                  text: `Error: ${errorText}`,
                  timestamp: new Date(data.timestamp),
                  type: 'error',
                },
              ],
              outputLineCounter: outputLineCounter + 1,
              sessionState: 'error',
            });
            break;
          }

          case 'completed': {
            const completedData = data.data as { exit_code: number };
            set({
              outputLines: [
                ...outputLines,
                {
                  id: outputLineCounter,
                  text: `Session completed with exit code: ${completedData.exit_code}`,
                  timestamp: new Date(data.timestamp),
                  type: 'system',
                },
              ],
              outputLineCounter: outputLineCounter + 1,
              sessionState: 'completed',
            });
            break;
          }
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      set({ error: 'WebSocket connection error' });
    };

    ws.onclose = (event) => {
      console.log('WebSocket closed:', event.code, event.reason);
      set({ ws: null });

      // If session is still active and not terminated, show message
      const { activeSession, sessionState } = get();
      if (activeSession && sessionState !== 'completed' && sessionState !== 'terminated') {
        const { outputLineCounter, outputLines } = get();
        set({
          outputLines: [
            ...outputLines,
            {
              id: outputLineCounter,
              text: 'WebSocket disconnected',
              timestamp: new Date(),
              type: 'system',
            },
          ],
          outputLineCounter: outputLineCounter + 1,
        });
      }
    };

    set({ ws });
  },

  disconnectWebSocket: () => {
    const { ws } = get();
    if (ws) {
      ws.close();
      set({ ws: null });
    }
  },

  sendInput: (text: string) => {
    const { ws } = get();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'input', text }));
    }
  },

  respondToPermission: (approved: boolean) => {
    const { ws } = get();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'permission', approved }));
      set({ pendingPermission: null });
    }
  },

  resizeTerminal: (rows: number, cols: number) => {
    const { ws } = get();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'resize', rows, cols }));
    }
  },

  clearOutput: () => {
    set({ outputLines: [], outputLineCounter: 0 });
  },

  clearError: () => {
    set({ error: null });
  },
}));
