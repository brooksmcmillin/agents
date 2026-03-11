#!/bin/bash
# Local CI simulation - runs the same checks as GitHub Actions
# Usage: .github/workflows/test-local.sh

set -e  # Exit on error

echo "Running local CI checks..."
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}> $1${NC}"
}

print_success() {
    echo -e "${GREEN}  $1${NC}"
}

print_error() {
    echo -e "${RED}  $1${NC}"
}

# Track failures
FAILED=0

# Backend Tests
print_step "Running backend tests (pytest)..."
if uv run pytest api/test_server.py -v --cov=api --cov-report=term; then
    print_success "Backend tests passed"
else
    print_error "Backend tests failed"
    FAILED=1
fi
echo ""

# Python Linting
print_step "Running Python linter (ruff)..."
if uv run ruff check .; then
    print_success "Ruff check passed"
else
    print_error "Ruff check failed"
    FAILED=1
fi
echo ""

print_step "Running Python formatter check (ruff format)..."
if uv run ruff format --check .; then
    print_success "Ruff format check passed"
else
    print_error "Ruff format check failed - run 'uv run ruff format .' to fix"
    FAILED=1
fi
echo ""

# Summary
echo "---"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All checks passed${NC}"
    echo "Ready to push to GitHub"
    exit 0
else
    echo -e "${RED}Some checks failed${NC}"
    echo "Fix the errors above before pushing"
    exit 1
fi
