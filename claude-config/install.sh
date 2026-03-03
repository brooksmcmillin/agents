#!/usr/bin/env bash
# Install custom Claude Code agents and commands to ~/.claude
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${HOME}/.claude"

install_dir() {
    local src="$1"
    local dest="$2"

    if [[ ! -d "$src" ]]; then
        return
    fi

    mkdir -p "$dest"

    local count=0
    for file in "$src"/*.md; do
        [[ -f "$file" ]] || continue
        local name
        name="$(basename "$file")"

        if [[ -f "$dest/$name" ]] && diff -q "$file" "$dest/$name" > /dev/null 2>&1; then
            continue
        fi

        cp "$file" "$dest/$name"
        echo "  $name"
        ((++count))
    done

    if [[ $count -eq 0 ]]; then
        echo "  (all up to date)"
    fi
}

echo "Installing Claude Code config to ${CLAUDE_DIR}"
echo ""

echo "Agents:"
install_dir "$SCRIPT_DIR/agents" "$CLAUDE_DIR/agents"
echo ""

echo "Commands:"
install_dir "$SCRIPT_DIR/commands" "$CLAUDE_DIR/commands"
echo ""

echo "Done."
