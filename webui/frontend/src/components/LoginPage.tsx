import { useState, type FormEvent } from 'react';
import { useAuthStore } from '@/store/authStore';

export function LoginPage() {
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuthStore();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = apiKey.trim();
    if (!trimmed) {
      setError('API key is required');
      return;
    }

    setIsLoading(true);
    setError('');

    try {
      // Validate the key by making a test request to /health
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await fetch(`${baseUrl}/agents`, {
        headers: { Authorization: `Bearer ${trimmed}` },
      });

      if (response.status === 401) {
        setError('Invalid API key');
        return;
      }

      if (!response.ok) {
        setError(`Server error: ${response.status}`);
        return;
      }

      login(trimmed);
    } catch {
      setError('Cannot connect to API server');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4">
      <div className="w-full max-w-sm">
        <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-lg p-8">
          <div className="flex items-center justify-center mb-6">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
              <span className="text-white font-bold text-2xl">A</span>
            </div>
          </div>

          <h1 className="text-xl font-bold text-center text-gray-900 dark:text-white mb-2">
            Agents
          </h1>
          <p className="text-sm text-center text-gray-500 dark:text-gray-400 mb-6">
            Enter your API key to continue
          </p>

          <form onSubmit={handleSubmit}>
            <div className="mb-4">
              <label
                htmlFor="api-key"
                className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1"
              >
                API Key
              </label>
              <input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Enter your API key"
                autoFocus
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg
                  bg-white dark:bg-gray-700 text-gray-900 dark:text-white
                  placeholder-gray-400 dark:placeholder-gray-500
                  focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 dark:text-red-400 mb-4">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full py-2 px-4 rounded-lg font-medium text-white
                bg-primary-600 hover:bg-primary-700
                disabled:opacity-50 disabled:cursor-not-allowed
                transition-colors"
            >
              {isLoading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
