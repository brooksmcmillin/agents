import { create } from 'zustand';
import type { AgentInfo } from '@/api/types';

interface AppState {
  darkMode: boolean;
  agents: AgentInfo[];
  isLoadingAgents: boolean;
  toggleDarkMode: () => void;
  setAgents: (agents: AgentInfo[]) => void;
  setIsLoadingAgents: (loading: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  darkMode: localStorage.getItem('darkMode') === 'true',
  agents: [],
  isLoadingAgents: false,

  toggleDarkMode: () =>
    set((state) => {
      const newDarkMode = !state.darkMode;
      localStorage.setItem('darkMode', String(newDarkMode));
      return { darkMode: newDarkMode };
    }),

  setAgents: (agents) => set({ agents }),
  setIsLoadingAgents: (loading) => set({ isLoadingAgents: loading }),
}));
