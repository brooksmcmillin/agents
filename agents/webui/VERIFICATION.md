# Web UI Verification Checklist

Use this checklist to verify the Web UI implementation is working correctly.

## Prerequisites Check

```bash
# Check Node.js version (should be 18+)
node --version

# Check npm is installed
npm --version

# Check uv is installed
uv --version

# Check PostgreSQL is accessible
psql --version
```

## Installation Verification

```bash
# 1. Navigate to frontend directory
cd agents/webui/frontend

# 2. Verify package.json exists
ls -l package.json

# 3. Install dependencies (should complete without errors)
npm install

# 4. Verify node_modules was created
ls -ld node_modules

# 5. Build for production (should complete successfully)
npm run build

# 6. Verify dist directory was created
ls -ld ../dist
```

## Backend Verification

```bash
# 1. Navigate to project root
cd ../../..

# 2. Set database URL (replace with your credentials)
export DATABASE_URL=postgresql://user:password@localhost:5432/agents

# 3. Start the API server
uv run python -m agents.api

# Expected output:
# - "Conversation persistence enabled (PostgreSQL)"
# - "Serving Web UI static assets from..."
# - "Agent REST API started"
# - Server listening on http://0.0.0.0:8080
```

## Frontend Development Mode Verification

```bash
# In a separate terminal:
cd agents/webui/frontend

# Start dev server
npm run dev

# Expected output:
# - VITE v5.x.x ready
# - Local: http://localhost:5173
# - press h to show help
```

## Functional Testing

### 1. Access the Web UI

**Production Mode:**
- [ ] Navigate to http://localhost:8080
- [ ] Page loads without errors
- [ ] No console errors in browser DevTools

**Development Mode:**
- [ ] Navigate to http://localhost:5173
- [ ] Page loads with hot reload enabled
- [ ] Changes to source files trigger instant updates

### 2. Create a Conversation

- [ ] Click "New Conversation" button
- [ ] Dialog opens showing 5 agent options
- [ ] Select "Chatbot" agent
- [ ] Optionally enter a title
- [ ] Click "Create" button
- [ ] New conversation appears in sidebar
- [ ] Chat view updates to show selected conversation

### 3. Send a Message

- [ ] Type "Hello!" in the input field
- [ ] Press Enter or click send button
- [ ] Message appears immediately (optimistic update)
- [ ] Loading indicator shows while waiting
- [ ] Assistant response appears with token count
- [ ] Conversation list updates with new timestamp

### 4. Conversation Management

**Switch Conversations:**
- [ ] Create a second conversation with different agent
- [ ] Click on first conversation in sidebar
- [ ] Chat view switches to show first conversation's messages
- [ ] Click on second conversation
- [ ] Chat view switches to show second conversation's messages

**Rename Conversation:**
- [ ] Click menu icon (⋮) next to conversation
- [ ] Select "Rename"
- [ ] Dialog opens with current title
- [ ] Enter new title
- [ ] Click "Save"
- [ ] Sidebar updates to show new title

**Delete Conversation:**
- [ ] Click menu icon (⋮) next to conversation
- [ ] Select "Delete"
- [ ] Confirmation dialog appears
- [ ] Click "Delete"
- [ ] Conversation removed from sidebar
- [ ] If currently selected, view shows "No conversation selected"

### 5. Dark Mode

- [ ] Click sun/moon icon in header
- [ ] Theme switches between light and dark
- [ ] Refresh page
- [ ] Theme preference persists

### 6. Token Tracking

- [ ] Send a message
- [ ] View token count badge on messages
- [ ] Verify counts are displayed (e.g., "1.2k")
- [ ] Hover over badge to see full count

### 7. UI Features

**Empty States:**
- [ ] With no conversations: "No conversations yet" message
- [ ] With conversation but no messages: "No messages yet" message

**Loading States:**
- [ ] Spinner shows while loading conversations
- [ ] Spinner shows while sending message
- [ ] Button disabled during operations

**Error Handling:**
- [ ] Stop backend server
- [ ] Try sending message
- [ ] Error toast appears with message
- [ ] Error auto-dismisses after 5 seconds
- [ ] Can manually dismiss by clicking X

**Auto-Scroll:**
- [ ] Create conversation with multiple messages
- [ ] New message automatically scrolls into view
- [ ] Manual scroll up works
- [ ] Sending new message scrolls to bottom

**Keyboard Shortcuts:**
- [ ] Enter sends message
- [ ] Shift+Enter creates new line
- [ ] ESC closes dialogs

### 8. Responsive Design

- [ ] Resize browser window to mobile width
- [ ] UI adapts to smaller screen
- [ ] All features remain accessible
- [ ] No horizontal scrolling

### 9. API Integration

```bash
# Check API endpoints work correctly:

# List conversations
curl http://localhost:8080/conversations

# Get conversation
curl http://localhost:8080/conversations/{id}

# Send message
curl -X POST http://localhost:8080/conversations/{id}/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Test from API"}'
```

### 10. Persistence

- [ ] Create conversation and send messages
- [ ] Stop API server (Ctrl+C)
- [ ] Restart API server
- [ ] Reload web UI
- [ ] Conversation and messages still present

## Common Issues

### "Conversation persistence not configured"
**Solution:** Set `DATABASE_URL` environment variable
```bash
export DATABASE_URL=postgresql://user:password@localhost:5432/agents
```

### CORS errors in browser console
**Solution:**
- Verify backend is running on port 8080
- Check CORS middleware is configured in `agents/api/server.py`
- In dev mode, use `http://localhost:5173` (not :8080)

### "Web UI not built" error
**Solution:** Build the frontend
```bash
cd agents/webui/frontend
npm run build
```

### TypeScript compilation errors
**Solution:**
```bash
cd agents/webui/frontend
rm -rf node_modules package-lock.json
npm install
```

### Port already in use
**Solution:**
```bash
# Find and kill process using port 8080
lsof -ti:8080 | xargs kill -9

# Or use different port
uvicorn agents.api.server:app --port 8081
```

### Database connection errors
**Solution:**
- Verify PostgreSQL is running
- Check credentials in DATABASE_URL
- Create database if it doesn't exist:
  ```bash
  createdb agents
  ```

## Performance Benchmarks

Expected metrics for production build:

- [ ] Initial page load: < 1s (local network)
- [ ] JavaScript size: ~221 KB (70 KB gzipped)
- [ ] CSS size: ~26 KB (5 KB gzipped)
- [ ] Message send latency: < 500ms (excluding agent processing)
- [ ] Conversation switch: < 100ms

## Success Criteria

All of the following should be true:

- ✅ Frontend builds without TypeScript errors
- ✅ Backend serves static files in production
- ✅ Can create and delete conversations
- ✅ Can send messages and receive responses
- ✅ Token counts display correctly
- ✅ Dark mode toggles and persists
- ✅ Conversations persist across server restarts
- ✅ No console errors in browser DevTools
- ✅ Responsive design works on mobile
- ✅ All 5 agents are selectable

## Next Steps After Verification

If all checks pass:
1. Commit the changes to git
2. Deploy to production environment
3. Set up monitoring and analytics
4. Gather user feedback
5. Plan Phase 2 features (streaming, search, etc.)

If checks fail:
1. Review error messages in browser DevTools
2. Check server logs for errors
3. Verify all prerequisites are met
4. Consult TROUBLESHOOTING section in README.md
5. Open an issue on GitHub with details

## Additional Resources

- Full documentation: [README.md](README.md)
- Implementation details: [IMPLEMENTATION.md](IMPLEMENTATION.md)
- Project guide: [../../CLAUDE.md](../../CLAUDE.md)
- API documentation: http://localhost:8080/docs (when server running)
