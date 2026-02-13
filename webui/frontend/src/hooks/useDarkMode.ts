import { useEffect } from 'react';
import { useAppStore } from '@/store/appStore';

export function useDarkMode() {
  const { darkMode, toggleDarkMode } = useAppStore();

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  return { darkMode, toggleDarkMode };
}
