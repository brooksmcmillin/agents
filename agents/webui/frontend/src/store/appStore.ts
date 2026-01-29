import { create } from 'zustand';
import type { AgentInfo } from '@/api/types';

export type AppView = 'chat' | 'claude-code';

interface AppState {
  darkMode: boolean;
  currentView: AppView;
  agents: AgentInfo[];
  isLoadingAgents: boolean;
  toggleDarkMode: () => void;
  setCurrentView: (view: AppView) => void;
  setAgents: (agents: AgentInfo[]) => void;
  setIsLoadingAgents: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  darkMode: localStorage.getItem('darkMode') === 'true',
  currentView: 'chat',
  agents: [],
  isLoadingAgents: false,

  toggleDarkMode: () =>
    set((state) => {
      const newDarkMode = !state.darkMode;
      localStorage.setItem('darkMode', String(newDarkMode));
      return { darkMode: newDarkMode };
    }),

  setCurrentView: (view) => set({ currentView: view }),

  setAgents: (agents) => set({ agents }),
  setIsLoadingAgents: (loading) => set({ isLoadingAgents: loading }),
}));
