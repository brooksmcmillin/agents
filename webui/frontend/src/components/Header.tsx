import { SunIcon, MoonIcon, ChatBubbleLeftRightIcon, CommandLineIcon } from '@heroicons/react/24/outline';
import { useDarkMode } from '@/hooks/useDarkMode';
import { useAppStore, type AppView } from '@/store/appStore';

interface NavTabProps {
  view: AppView;
  label: string;
  icon: React.ReactNode;
  isActive: boolean;
  onClick: () => void;
}

function NavTab({ label, icon, isActive, onClick }: NavTabProps) {
  return (
    <button
      onClick={onClick}
      className={`
        flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors
        ${isActive
          ? 'bg-primary-100 text-primary-700 dark:bg-primary-900 dark:text-primary-300'
          : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700'
        }
      `}
    >
      {icon}
      {label}
    </button>
  );
}

export function Header() {
  const { darkMode, toggleDarkMode } = useDarkMode();
  const { currentView, setCurrentView } = useAppStore();

  return (
    <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
              <span className="text-white font-bold text-lg">A</span>
            </div>
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">
              Agents
            </h1>
          </div>

          {/* Navigation tabs */}
          <nav className="flex items-center gap-1">
            <NavTab
              view="chat"
              label="Chat"
              icon={<ChatBubbleLeftRightIcon className="h-4 w-4" />}
              isActive={currentView === 'chat'}
              onClick={() => setCurrentView('chat')}
            />
            <NavTab
              view="claude-code"
              label="Claude Code"
              icon={<CommandLineIcon className="h-4 w-4" />}
              isActive={currentView === 'claude-code'}
              onClick={() => setCurrentView('claude-code')}
            />
          </nav>
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
