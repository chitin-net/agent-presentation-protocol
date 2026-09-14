#!/bin/bash
# Register Chitin as an MCP tool server in Claude Code.
# Replace YOUR_CHITIN_API_KEY with the key from Chitin Desktop > Settings > Inbound MCP.

claude mcp add chitin \
  --transport http \
  --url http://localhost:18790/mcp \
  --header "Authorization: Bearer YOUR_CHITIN_API_KEY"
