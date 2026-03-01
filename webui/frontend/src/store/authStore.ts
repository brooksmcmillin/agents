import { create } from 'zustand';

const AUTH_STORAGE_KEY = 'agents_api_key';

interface AuthState {
  apiKey: string | null;
  isAuthenticated: boolean;
  login: (apiKey: string) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  apiKey: sessionStorage.getItem(AUTH_STORAGE_KEY),
  isAuthenticated: sessionStorage.getItem(AUTH_STORAGE_KEY) !== null,

  login: (apiKey: string) => {
    sessionStorage.setItem(AUTH_STORAGE_KEY, apiKey);
    set({ apiKey, isAuthenticated: true });
  },

  logout: () => {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
    set({ apiKey: null, isAuthenticated: false });
  },
}));

/**
 * Get the stored API key. Utility for non-React code (e.g., the API client).
 */
export function getStoredApiKey(): string | null {
  return sessionStorage.getItem(AUTH_STORAGE_KEY);
}
