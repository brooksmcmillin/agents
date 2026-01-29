#!/bin/bash
# Start the web UI in development mode
# Requires two terminals or use with tmux/screen

set -e

echo "Starting Agents Web UI in development mode..."
echo ""
echo "This requires TWO terminals:"
echo ""
echo "Terminal 1 (Backend):"
echo "  cd $(pwd)/../.."
echo "  uv run python -m agents.api"
echo ""
echo "Terminal 2 (Frontend):"
echo "  cd $(pwd)/frontend"
echo "  npm run dev"
echo ""
echo "Then visit: http://localhost:5173"
echo ""
echo "Note: Make sure DATABASE_URL is set for persistent conversations"
echo ""

# Detect if we're in a terminal multiplexer
if command -v tmux &> /dev/null; then
    read -p "Start in tmux? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cd ../..
        tmux new-session -d -s agents-webui "uv run python -m agents.api"
        tmux split-window -h "cd agents/webui/frontend && npm run dev"
        tmux attach -t agents-webui
    fi
fi
