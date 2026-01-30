# Backend Dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    nodejs \
    npm \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for Claude Code (it refuses --dangerously-skip-permissions as root)
RUN useradd -m -s /bin/bash claude

# Install Claude Code CLI for the claude user
RUN su - claude -c "curl -fsSL https://claude.ai/install.sh | bash"

# Add GitHub host key to known_hosts for both root and claude user
RUN mkdir -p /root/.ssh ~/.ssh && ssh-keyscan github.com >> /root/.ssh/known_hosts
RUN mkdir -p /home/claude/.ssh && ssh-keyscan github.com >> /home/claude/.ssh/known_hosts \
    && chown -R claude:claude /home/claude/.ssh

# Copy dependency files
COPY pyproject.toml uv.lock ./
COPY packages/agent-framework ./packages/agent-framework

# Install Python dependencies using uv
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs memories .data

# Create workspaces directory with claude user ownership
RUN mkdir -p /workspaces && chown claude:claude /workspaces

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the application
CMD ["uv", "run", "python", "-m", "agents.api"]
