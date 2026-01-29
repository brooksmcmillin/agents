# Agents Web UI

Modern React web interface for the multi-agent system with persistent conversation support.

## Features

- **Multiple Agents** - Choose from 5 specialized agents (chatbot, PR, tasks, security, business)
- **Persistent Conversations** - Database-backed conversations that survive server restarts
- **Conversation Management** - Create, rename, delete, and switch between conversations
- **Real-time Chat** - Send messages and view responses with role-based message bubbles
- **Token Tracking** - View per-message and cumulative token usage
- **Dark Mode** - Toggle between light and dark themes with localStorage persistence
- **Responsive Design** - Works on desktop, tablet, and mobile

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite
- **Styling**: Tailwind CSS 3 with typography and forms plugins
- **State Management**: Zustand
- **UI Components**: Headless UI (accessible, unstyled components)
- **Icons**: Heroicons
- **Backend**: FastAPI (REST API)

## Prerequisites

- Node.js 18+ and npm
- Python 3.11+ with `uv`
- PostgreSQL database (for persistent conversations)

## Setup

### 1. Install Frontend Dependencies

```bash
cd agents/webui/frontend
npm install
```

### 2. Configure Environment

Copy `.env.example` to `.env` (optional - defaults work for local development):

```bash
cp .env.example .env
```

### 3. Configure Backend

Set up PostgreSQL and configure the connection:

```bash
# In project root
export DATABASE_URL=postgresql://user:password@localhost:5432/agents
```

## Development

Run the backend and frontend in separate terminals:

### Terminal 1: Backend API

```bash
# From project root
uv run python -m agents.api
# Runs on http://localhost:8080
```

### Terminal 2: Frontend Dev Server

```bash
# From agents/webui/frontend
npm run dev
# Runs on http://localhost:5173
# API calls automatically proxied to :8080
```

Visit http://localhost:5173 to use the web UI.

## Production Build

### 1. Build the Frontend

```bash
cd agents/webui/frontend
npm run build
# Output: agents/webui/dist/
```

### 2. Start the Server

The API server automatically serves the built web UI:

```bash
# From project root
uv run python -m agents.api
```

Visit http://localhost:8080 to access both the API and web UI.

## Project Structure

```
agents/webui/
├── frontend/           # React app source
│   ├── src/
│   │   ├── api/       # API client and types
│   │   ├── components/ # React components
│   │   ├── hooks/     # Custom hooks
│   │   ├── store/     # Zustand state management
│   │   ├── utils/     # Utilities and constants
│   │   ├── App.tsx    # Root component
│   │   ├── main.tsx   # Entry point
│   │   └── index.css  # Global styles
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
└── dist/              # Production build (gitignored)
    ├── index.html
    └── assets/
```

## Usage

### Creating a Conversation

1. Click "New Conversation" button
2. Select an agent (chatbot, PR, tasks, security, or business)
3. Optionally provide a title
4. Click "Create"

### Sending Messages

1. Select a conversation from the sidebar
2. Type your message in the input field
3. Press Enter or click the send button
4. View the agent's response with token counts

### Managing Conversations

- **Rename**: Click the menu (⋮) next to a conversation and select "Rename"
- **Delete**: Click the menu (⋮) next to a conversation and select "Delete"
- **Switch**: Click on any conversation in the sidebar to view it

### Dark Mode

Click the sun/moon icon in the header to toggle dark mode. Your preference is saved in localStorage.

## API Integration

The web UI uses the FastAPI backend's conversation endpoints:

- `GET /conversations` - List all conversations
- `POST /conversations` - Create new conversation
- `GET /conversations/{id}` - Get conversation with messages
- `POST /conversations/{id}/message` - Send message
- `PATCH /conversations/{id}` - Update title/metadata
- `DELETE /conversations/{id}` - Delete conversation

See `src/api/client.ts` for the full API client implementation.

## Development Tips

### Hot Reload

The Vite dev server provides instant hot reload for React components and styles. Changes appear immediately without losing state.

### Proxy Configuration

In development, API calls are proxied from :5173 to :8080 via Vite's proxy configuration. This avoids CORS issues. See `vite.config.ts` for details.

### Type Safety

TypeScript types in `src/api/types.ts` mirror the Pydantic models in the backend, ensuring type safety across the stack.

## Troubleshooting

### "Conversation persistence not configured" error

The backend requires a PostgreSQL database. Set the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/agents
```

### Frontend can't connect to backend

1. Verify the backend is running on port 8080
2. Check the console for CORS errors
3. Ensure `VITE_API_BASE_URL` is not set (or set correctly)

### Build fails

1. Delete `node_modules` and reinstall: `rm -rf node_modules && npm install`
2. Clear the build cache: `rm -rf dist`
3. Check for TypeScript errors: `npm run build`

### Web UI not served in production

1. Verify the build exists: `ls agents/webui/dist/`
2. Check server logs for "Serving Web UI" message
3. Rebuild: `cd agents/webui/frontend && npm run build`

## Contributing

When adding new features:

1. Add TypeScript types to `src/api/types.ts`
2. Update the API client in `src/api/client.ts`
3. Create components in `src/components/`
4. Use Zustand stores for global state
5. Follow existing patterns for error handling and loading states

## License

Same as parent project.
