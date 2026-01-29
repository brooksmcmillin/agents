#!/bin/bash
# Local CI simulation - runs the same checks as GitHub Actions
# Usage: .github/workflows/test-local.sh

set -e  # Exit on error

echo "🔍 Running local CI checks..."
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Track failures
FAILED=0

# Backend Tests
print_step "Running backend tests (pytest)..."
if uv run pytest agents/api/test_server.py -v --cov=agents.api --cov-report=term; then
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

# Frontend Tests
print_step "Running frontend tests (vitest)..."
cd agents/webui/frontend
if npm test -- --run; then
    print_success "Frontend tests passed"
else
    print_error "Frontend tests failed"
    FAILED=1
fi
cd ../../..
echo ""

# Frontend Linting
print_step "Running TypeScript linter (eslint)..."
cd agents/webui/frontend
if npm run lint; then
    print_success "ESLint passed"
else
    print_error "ESLint failed"
    FAILED=1
fi
cd ../../..
echo ""

# TypeScript Type Check
print_step "Running TypeScript type check..."
cd agents/webui/frontend
if npx tsc --noEmit; then
    print_success "TypeScript type check passed"
else
    print_error "TypeScript type check failed"
    FAILED=1
fi
cd ../../..
echo ""

# Frontend Build
print_step "Building frontend..."
cd agents/webui/frontend
if npm run build; then
    print_success "Frontend build succeeded"
else
    print_error "Frontend build failed"
    FAILED=1
fi
cd ../../..
echo ""

# Build verification
print_step "Verifying build output..."
if [ -f "agents/webui/dist/index.html" ] && [ -d "agents/webui/dist/assets" ]; then
    print_success "Build output verified"
else
    print_error "Build output missing"
    FAILED=1
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo "Ready to push to GitHub"
    exit 0
else
    echo -e "${RED}❌ Some checks failed${NC}"
    echo "Fix the errors above before pushing"
    exit 1
fi
