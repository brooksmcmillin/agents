import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ChatView } from './ChatView';
import { ClaudeCodeView } from './claude-code';
import { useAppStore } from '@/store/appStore';

export function AppLayout() {
  const { currentView } = useAppStore();

  return (
    <div className="h-screen flex flex-col bg-gray-50 dark:bg-gray-900">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        {currentView === 'chat' ? (
          <>
            <Sidebar />
            <ChatView />
          </>
        ) : (
          <main className="flex-1 overflow-hidden bg-white dark:bg-gray-800">
            <ClaudeCodeView />
          </main>
        )}
      </div>
    </div>
  );
}
