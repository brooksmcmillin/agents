import { SunIcon, MoonIcon } from '@heroicons/react/24/outline';
import { useDarkMode } from '@/hooks/useDarkMode';

export function Header() {
  const { darkMode, toggleDarkMode } = useDarkMode();

  return (
    <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
            <span className="text-white font-bold text-lg">A</span>
          </div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Agents
          </h1>
        </div>
        <button
          onClick={toggleDarkMode}
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          aria-label="Toggle dark mode"
        >
          {darkMode ? (
            <SunIcon className="h-5 w-5 text-gray-600 dark:text-gray-400" />
          ) : (
            <MoonIcon className="h-5 w-5 text-gray-600 dark:text-gray-400" />
          )}
        </button>
      </div>
    </header>
  );
}
