# Docker Deployment Guide

This guide explains how to run the agents webui using Docker and Docker Compose.

## Quick Start

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Anthropic API key
- Remote PostgreSQL database (for persistent conversations)

**Note:** If running locally without Docker, you'll need Node.js 20.19+ or 22.12+ for the frontend.

### Setup

1. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Configure required environment variables in `.env`:**
   ```bash
   # Required: Anthropic API key
   ANTHROPIC_API_KEY=your_key_here

   # Required: Remote PostgreSQL database URL
   DATABASE_URL=postgresql://user:password@your-db-host:5432/agents  # pragma: allowlist secret
   ```

3. **Start the services:**
   ```bash
   # Production mode
   docker-compose up -d

   # Or development mode (with hot reload)
   docker-compose -f docker-compose.dev.yml up
   ```

4. **Configure local DNS (optional but recommended):**
   ```bash
   # Add to /etc/hosts (Linux/Mac) or C:\Windows\System32\drivers\etc\hosts (Windows)
   127.0.0.1 agents.lan
   ```

5. **Access the web UI:**
   - Production: http://agents.lan:8080 (or http://localhost:8080)
   - Development: http://agents.lan:5173 (or http://localhost:5173)
   - Backend API: http://agents.lan:8080 (or http://localhost:8080)

## Architecture

The Docker setup includes two services:

### 1. Backend API (`backend`)
- **Build:** Custom Dockerfile with Python 3.12 + uv
- **Port:** 8080
- **Purpose:** FastAPI server with agent endpoints
- **Database:** Connects to remote PostgreSQL (configured via `DATABASE_URL`)
- **Features:**
  - Persistent conversations backed by PostgreSQL
  - All 34 MCP tools available
  - RESTful API for agents
  - Health checks

### 2. Frontend (`frontend`)
- **Build:** Multi-stage Node.js 18 + nginx
- **Port:** 80 (internal), proxied through nginx
- **Purpose:** React web UI
- **Features:**
  - Optimized production build
  - Static asset caching
  - API proxy to backend
  - SPA routing support

## Configuration Files

### `docker-compose.yml` (Production)
- Optimized for production deployment
- Built frontend served by nginx
- Backend with uvicorn
- Connects to remote PostgreSQL database

### `docker-compose.dev.yml` (Development)
- Hot reload for both frontend and backend
- Source code mounted as volumes
- Debug logging enabled
- Development servers (Vite + uvicorn --reload)
- Connects to remote PostgreSQL database

### `Dockerfile` (Backend)
- Based on `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
- Installs system dependencies (git, curl, build tools)
- Uses uv for Python dependency management
- Includes health check endpoint

### `agents/webui/frontend/Dockerfile` (Frontend)
- Multi-stage build for optimized image size
- Stage 1: Node.js for building React app
- Stage 2: nginx alpine for serving static files
- Includes nginx configuration for SPA routing

## Usage

### Production Deployment

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres

# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v
```

### Development Mode

```bash
# Start with hot reload
docker-compose -f docker-compose.dev.yml up

# Rebuild after dependency changes
docker-compose -f docker-compose.dev.yml up --build

# Stop
docker-compose -f docker-compose.dev.yml down
```

### Accessing Services

**Production:**
- Web UI: http://agents.lan:8080 (or http://localhost:8080)
- API Docs: http://agents.lan:8080/docs

**Development:**
- Frontend (Vite): http://agents.lan:5173 (or http://localhost:5173)
- Backend API: http://agents.lan:8080 (or http://localhost:8080)
- API Docs: http://agents.lan:8080/docs

**Note:** Add `127.0.0.1 agents.lan` to `/etc/hosts` to use the `agents.lan` hostname.

## Environment Variables

Configure via `.env` file:

### Required
```bash
# Anthropic API key
ANTHROPIC_API_KEY=your_key_here

# Remote PostgreSQL database URL
DATABASE_URL=postgresql://user:password@your-db-host:5432/agents  # pragma: allowlist secret
```

### Optional
```bash

# Memory backend
MEMORY_BACKEND=database  # or "file"

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR

# Remote MCP (for task_manager agent)
MCP_SERVER_URL=https://your-mcp-server.com/mcp
MCP_AUTH_TOKEN=your_token

# Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# GitHub integration
GITHUB_MCP_PAT=your_github_token
```

## Database Management

The application connects to a remote PostgreSQL database. Use your database provider's tools for management.

### View Database Stats (via API)
```bash
curl http://localhost:8080/conversations/stats
```

## Troubleshooting

### Backend won't start
1. Check API key is set: `docker-compose logs backend | grep ANTHROPIC`
2. Check database connection: `docker-compose logs backend | grep DATABASE`
3. Verify DATABASE_URL is correct in `.env`
4. Ensure remote PostgreSQL is accessible from the container

### Frontend build fails
1. Clear node_modules: `rm -rf agents/webui/frontend/node_modules`
2. Rebuild: `docker-compose build --no-cache frontend`

### Database connection errors
1. Verify DATABASE_URL format: `postgresql://user:password@host:port/dbname`  <!-- pragma: allowlist secret -->
2. Check remote database is accessible: `ping your-db-host`
3. Verify firewall rules allow connection from Docker container
4. Check database credentials are correct
5. Ensure database exists and schema is initialized
6. If using Cloudflare or CDN in front of database, add direct IP mapping:
   ```yaml
   # In docker-compose.yml under backend service:
   extra_hosts:
     - "your-db-host.com:1.2.3.4"
   ```

### Port already in use
```bash
# Check what's using port 8080
lsof -i :8080

# Or change port in docker-compose.yml
ports:
  - "8081:8080"  # External:Internal
```

### Hot reload not working (dev mode)
1. Ensure volumes are mounted correctly
2. Check file permissions: `ls -la`
3. Restart container: `docker-compose -f docker-compose.dev.yml restart backend`

### Out of disk space
```bash
# Clean up Docker resources
docker system prune -a

# Remove unused volumes
docker volume prune
```

## Production Considerations

### Security
1. **Use Docker secrets** for sensitive environment variables
2. **Enable SSL/TLS** with reverse proxy (nginx, caddy)
3. **Use encrypted database connections** - ensure DATABASE_URL uses SSL (`?sslmode=require`)
4. **Restrict network access** - use firewall rules to limit database access
5. **Set strong encryption key** for TOKEN_ENCRYPTION_KEY

### Performance
1. **Optimize database connection pool** - configure in your PostgreSQL provider
2. **Use connection pooling** (PgBouncer) if not provided by your database host
3. **Enable nginx caching** for static assets
4. **Add rate limiting** to API endpoints
5. **Monitor database performance** using your provider's tools

### Monitoring
1. Add health check endpoints
2. Integrate with monitoring tools (Prometheus, Grafana)
3. Configure log aggregation (ELK, Loki)
4. Set up alerts for service failures

### Scaling
1. **Run multiple backend containers:**
   ```bash
   docker-compose up -d --scale backend=3
   ```
2. **Add load balancer** (nginx, traefik)
3. **Use managed PostgreSQL** with automatic scaling (AWS RDS, Supabase, Neon)
4. **Deploy to orchestration platform** (Kubernetes, Docker Swarm)

## Development Tips

### Installing new Python dependencies
```bash
# Add to pyproject.toml locally
uv add package-name

# Rebuild container
docker-compose build backend
```

### Installing new npm packages
```bash
# Add to package.json locally
cd agents/webui/frontend
npm install package-name

# Rebuild container
docker-compose build frontend
```

### Debugging inside containers
```bash
# Backend shell
docker-compose exec backend bash

# Frontend shell (dev mode)
docker-compose exec frontend sh

# Database shell
docker-compose exec postgres psql -U agents
```

### Viewing live logs
```bash
# All services
docker-compose logs -f

# Backend only
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend
```

## Database Cleanup

### Remove Test Data

If you see conversations with names like `test_a40c160f_2`, these are leftover from test runs. Clean them up:

```bash
# Run the cleanup script
uv run python scripts/cleanup_test_conversations.py

# Or manually via SQL
psql "$DATABASE_URL" -c "DELETE FROM conversations WHERE title LIKE 'test_%';"
```

**Prevention:** Always use a separate test database when running tests:

```bash
# Create .env.test with a different database
cp .env.test.example .env.test
# Edit .env.test to use agents_test database

# Run tests against test database
DATABASE_URL=postgresql://user:pass@host:5432/agents_test pytest  # pragma: allowlist secret
```

## Clean Installation

To completely reset and start fresh:

```bash
# Stop and remove everything
docker-compose down -v

# Remove images
docker-compose rm -f
docker rmi agents-backend agents-frontend

# Rebuild from scratch
docker-compose build --no-cache
docker-compose up -d
```

## Additional Resources

- [Docker Documentation](https://docs.docker.com/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/docker/)
- [PostgreSQL Docker Hub](https://hub.docker.com/_/postgres)
- [nginx Docker Hub](https://hub.docker.com/_/nginx)
