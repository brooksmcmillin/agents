import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ChatView } from './ChatView';

export function AppLayout() {
  return (
    <div className="h-screen flex flex-col bg-gray-50 dark:bg-gray-900">
      <Header />
      <div className="flex-1 flex overflow-hidden">
        <Sidebar />
        <ChatView />
      </div>
    </div>
  );
}
