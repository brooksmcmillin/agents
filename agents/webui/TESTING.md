## Web UI Testing Guide

Comprehensive testing setup for the Agents Web UI, covering backend API tests, frontend unit tests, and integration tests.

## Test Structure

```
agents/
├── api/
│   └── test_server.py          # Backend API tests (pytest)
└── webui/
    └── frontend/
        ├── vitest.config.ts     # Vitest configuration
        └── src/
            ├── test/
            │   └── setup.ts     # Test setup and mocks
            ├── api/
            │   └── client.test.ts           # API client tests
            ├── components/
            │   ├── Button.test.tsx          # Button component tests
            │   └── Message.test.tsx         # Message component tests
            └── utils/
                └── formatters.test.ts       # Utility function tests
```

## Backend Tests (Python + pytest)

### Setup

Backend tests are already set up with the existing pytest configuration. No additional installation needed.

### Running Backend Tests

```bash
# From project root

# Run all API tests
pytest agents/api/test_server.py -v

# Run specific test class
pytest agents/api/test_server.py::TestConversationEndpoints -v

# Run specific test
pytest agents/api/test_server.py::TestConversationEndpoints::test_create_conversation -v

# Run with coverage
pytest agents/api/test_server.py --cov=agents.api --cov-report=html

# Run integration tests (requires database)
export DATABASE_URL=postgresql://user:password@localhost:5432/agents_test
pytest agents/api/test_server.py::test_conversation_persistence_workflow -v
```

### Backend Test Coverage

**Endpoints Tested:**
- ✅ Health check (`/health`)
- ✅ List agents (`/agents`)
- ✅ List conversations (`/conversations`)
- ✅ Create conversation (`POST /conversations`)
- ✅ Get conversation (`/conversations/{id}`)
- ✅ Update conversation (`PATCH /conversations/{id}`)
- ✅ Delete conversation (`DELETE /conversations/{id}`)
- ✅ Send message (`POST /conversations/{id}/message`)
- ✅ CORS configuration
- ✅ Static file serving (SPA catch-all)

**Features Tested:**
- Database connection handling
- Error responses (404, 500, 503)
- Request validation
- Response structure
- Conversation persistence workflow

## Frontend Tests (Vitest + React Testing Library)

### Setup

Install testing dependencies:

```bash
cd agents/webui/frontend
npm install
```

This installs:
- `vitest` - Fast unit test runner (built on Vite)
- `@testing-library/react` - React testing utilities
- `@testing-library/user-event` - User interaction simulation
- `@testing-library/jest-dom` - Custom matchers for DOM
- `jsdom` - Browser environment simulation
- `@vitest/ui` - Interactive test UI

### Running Frontend Tests

```bash
cd agents/webui/frontend

# Run all tests (watch mode)
npm test

# Run tests once
npm test -- --run

# Run tests with UI
npm run test:ui

# Run tests with coverage
npm run test:coverage

# Run specific test file
npm test -- src/api/client.test.ts

# Run tests matching a pattern
npm test -- --grep "Button"
```

### Frontend Test Coverage

**Components Tested:**
- ✅ `Button` - All variants, sizes, disabled state, click handlers
- ✅ `Message` - User/assistant messages, content blocks, token display

**Utilities Tested:**
- ✅ `formatRelativeTime` - Time formatting (just now, minutes, hours, days)
- ✅ `formatTimestamp` - Time display
- ✅ `formatTokenCount` - Token count formatting (raw, k notation)
- ✅ `formatDate` - Date formatting

**API Client Tested:**
- ✅ `listAgents` - Fetch agents list
- ✅ `listConversations` - Fetch conversations
- ✅ `createConversation` - Create new conversation
- ✅ `sendMessage` - Send message to conversation
- ✅ `deleteConversation` - Delete conversation
- ✅ Error handling - HTTP errors, network failures

## Test Organization

### Backend Tests (`test_server.py`)

Tests are organized into classes by feature area:

```python
class TestHealthEndpoint:
    # Health check tests

class TestAgentEndpoints:
    # Agent listing tests

class TestConversationEndpoints:
    # Conversation CRUD tests

class TestCORSConfiguration:
    # CORS middleware tests

class TestStaticFileServing:
    # SPA serving tests

class TestMessageSending:
    # Message processing tests
```

### Frontend Tests

Tests follow naming convention: `ComponentName.test.tsx` or `filename.test.ts`

Each test file includes:
- `describe` blocks for grouping related tests
- `it` or `test` for individual test cases
- Arrange-Act-Assert pattern

## Mocking Strategy

### Backend Mocks

```python
# Mock conversation store
@pytest.fixture
def mock_conversation_store():
    with patch("agents.api.server._conversation_store") as mock:
        mock.list_conversations = AsyncMock(return_value=[...])
        yield mock

# Mock agent creation
@patch("agents.api.server._create_agent")
def test_send_message(mock_create_agent):
    mock_agent = MagicMock()
    mock_agent.process_message = AsyncMock(return_value="Response")
```

### Frontend Mocks

```typescript
// Mock fetch API
beforeEach(() => {
  global.fetch = vi.fn();
});

// Mock localStorage (done in test/setup.ts)
// Mock matchMedia (done in test/setup.ts)

// Mock component props
const mockMessage: MessageType = {
  role: 'user',
  content: 'Test',
};
```

## Coverage Reports

### Backend Coverage

```bash
# Generate HTML coverage report
pytest agents/api/test_server.py --cov=agents.api --cov-report=html

# Open report
open htmlcov/index.html
```

### Frontend Coverage

```bash
cd agents/webui/frontend

# Generate coverage report
npm run test:coverage

# Open report
open coverage/index.html
```

**Coverage Goals:**
- Backend: >80% line coverage
- Frontend: >70% line coverage (UI components are harder to test comprehensively)

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Install dependencies
        run: uv sync
      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
        run: uv run pytest agents/api/test_server.py -v --cov

  frontend-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - name: Install dependencies
        working-directory: agents/webui/frontend
        run: npm ci
      - name: Run tests
        working-directory: agents/webui/frontend
        run: npm test -- --run
      - name: Generate coverage
        working-directory: agents/webui/frontend
        run: npm run test:coverage
```

## Writing New Tests

### Backend Test Template

```python
def test_new_endpoint(client, mock_conversation_store):
    """Test description."""
    # Arrange
    mock_data = {...}
    mock_conversation_store.method = AsyncMock(return_value=mock_data)

    # Act
    response = client.get("/endpoint")

    # Assert
    assert response.status_code == 200
    assert response.json()["key"] == "value"
```

### Frontend Component Test Template

```typescript
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Component } from './Component';

describe('Component', () => {
  it('should render correctly', () => {
    // Arrange
    const props = { ... };

    // Act
    render(<Component {...props} />);

    // Assert
    expect(screen.getByText('Expected Text')).toBeInTheDocument();
  });
});
```

### API Client Test Template

```typescript
describe('apiClient.method', () => {
  it('should make correct API call', async () => {
    // Arrange
    const mockResponse = { ... };
    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    // Act
    const result = await apiClient.method(params);

    // Assert
    expect(global.fetch).toHaveBeenCalledWith(
      '/endpoint',
      expect.objectContaining({ method: 'POST' })
    );
    expect(result).toEqual(expectedData);
  });
});
```

## Common Testing Patterns

### Testing User Interactions

```typescript
import userEvent from '@testing-library/user-event';

it('handles button click', async () => {
  const user = userEvent.setup();
  const handleClick = vi.fn();

  render(<Button onClick={handleClick}>Click</Button>);

  await user.click(screen.getByRole('button'));
  expect(handleClick).toHaveBeenCalled();
});
```

### Testing Async State Updates

```typescript
it('loads data on mount', async () => {
  render(<Component />);

  // Wait for loading to finish
  await waitFor(() => {
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
  });

  expect(screen.getByText('Data loaded')).toBeInTheDocument();
});
```

### Testing Error Handling

```typescript
it('displays error message on API failure', async () => {
  (global.fetch as any).mockRejectedValueOnce(new Error('Network error'));

  render(<Component />);

  await waitFor(() => {
    expect(screen.getByText(/error/i)).toBeInTheDocument();
  });
});
```

## Debugging Tests

### Backend

```bash
# Run with verbose output
pytest agents/api/test_server.py -vv

# Run with print statements visible
pytest agents/api/test_server.py -s

# Run with pdb on failure
pytest agents/api/test_server.py --pdb

# Run last failed tests only
pytest agents/api/test_server.py --lf
```

### Frontend

```bash
# Run with UI for interactive debugging
npm run test:ui

# Run in watch mode for specific file
npm test -- src/components/Button.test.tsx --watch

# Show console.log output
npm test -- --reporter=verbose
```

## Performance Benchmarks

**Backend Tests:**
- Full suite: < 2 seconds
- Individual test: < 100ms

**Frontend Tests:**
- Full suite: < 5 seconds
- Individual test: < 50ms

## Troubleshooting

### "Cannot find module" errors (Frontend)

```bash
cd agents/webui/frontend
rm -rf node_modules package-lock.json
npm install
```

### "Connection refused" errors (Backend)

Make sure DATABASE_URL is not set or points to a test database:

```bash
unset DATABASE_URL
# or
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test_db
```

### Tests pass locally but fail in CI

- Check Node.js and Python versions match
- Ensure all dependencies are installed
- Check for timezone issues in date tests
- Verify database is running in CI environment

## Best Practices

1. **Test Behavior, Not Implementation**
   - Focus on what the user sees/does
   - Don't test internal state or private methods

2. **Keep Tests Independent**
   - Each test should run in isolation
   - Use beforeEach/afterEach for setup/cleanup

3. **Use Meaningful Assertions**
   - Prefer `toBeInTheDocument()` over `toBeTruthy()`
   - Use specific matchers for clarity

4. **Mock External Dependencies**
   - Mock API calls, database, localStorage
   - Don't let tests depend on external services

5. **Test Edge Cases**
   - Empty states, null values, errors
   - Loading states, disabled states

6. **Maintain Test Speed**
   - Keep tests fast (< 100ms each)
   - Use shallow rendering when appropriate
   - Mock heavy computations

## Future Test Additions

**High Priority:**
- [ ] E2E tests with Playwright
- [ ] Store/state management tests (Zustand)
- [ ] Integration tests for full workflows
- [ ] Accessibility tests (axe-core)

**Medium Priority:**
- [ ] Visual regression tests (Percy/Chromatic)
- [ ] Performance tests (Lighthouse CI)
- [ ] Security tests (SQL injection, XSS)

**Low Priority:**
- [ ] Mutation testing (Stryker)
- [ ] Contract testing (Pact)
- [ ] Load testing (k6)

## Resources

- [Vitest Documentation](https://vitest.dev/)
- [React Testing Library](https://testing-library.com/react)
- [pytest Documentation](https://docs.pytest.org/)
- [Testing Best Practices](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)
