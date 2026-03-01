import { useEffect } from 'react';
import { AppLayout } from './components/AppLayout';
import { LoginPage } from './components/LoginPage';
import { useDarkMode } from './hooks/useDarkMode';
import { useConversationStore } from './store/conversationStore';
import { useAuthStore } from './store/authStore';

function App() {
  useDarkMode(); // Initialize dark mode
  const { error, clearError } = useConversationStore();
  const { isAuthenticated } = useAuthStore();

  // Show error toast if there's an error
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => {
        clearError();
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [error, clearError]);

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <>
      <AppLayout />

      {/* Error Toast */}
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
              ✕
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export default App;
