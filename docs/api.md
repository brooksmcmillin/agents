# REST API Server

The project includes a FastAPI REST server that exposes agents via HTTP endpoints.

```bash
uv run python -m api
# Runs on http://localhost:8080
# API docs at http://localhost:8080/docs
```

## API Endpoints

**Stateless (single-turn):**
```
POST /agents/{agent_name}/message  {"message": "..."}
```

**Stateful Sessions (in-memory):**
```
POST   /sessions              {"agent": "chatbot"}
POST   /sessions/{id}/message {"message": "..."}
GET    /sessions/{id}
DELETE /sessions/{id}
```

**Persistent Conversations (database-backed):**
Requires `DATABASE_URL` environment variable pointing to PostgreSQL.
```
GET    /conversations                    # List conversations
POST   /conversations                    # Create new
GET    /conversations/{id}               # Get with messages
POST   /conversations/{id}/message       # Send message
PATCH  /conversations/{id}               # Update title/metadata
DELETE /conversations/{id}               # Delete
POST   /conversations/{id}/clear         # Clear messages
GET    /conversations/{id}/export        # Export as JSON
GET    /conversations/{id}/messages      # Paginated messages
GET    /conversations/stats              # Storage statistics
```

## Conversation Persistence

To enable persistent conversations that survive server restarts:

1. Set up PostgreSQL database
2. Add to `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/agents
   ```
3. Tables are created automatically on first startup

## Database Schema

```sql
-- Created automatically by DatabaseConversationStore.initialize()

CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    agent_name VARCHAR(100) NOT NULL,
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE conversation_messages (
    id SERIAL PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_number INTEGER NOT NULL,
    role VARCHAR(20) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    token_count INTEGER,
    UNIQUE(conversation_id, turn_number)
);

-- Indexes for efficient queries
CREATE INDEX idx_conversations_agent_name ON conversations(agent_name);
CREATE INDEX idx_conversations_updated_at ON conversations(updated_at DESC);
CREATE INDEX idx_messages_conversation_id ON conversation_messages(conversation_id);
CREATE INDEX idx_messages_turn ON conversation_messages(conversation_id, turn_number);
```

**Migration Notes:**
If you prefer Alembic migrations, create a migration with the above schema. The auto-creation uses `IF NOT EXISTS` so it's safe to run alongside migrations.
