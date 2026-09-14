# Copilot Studio Custom MCP Connector

To connect Microsoft Copilot Studio to Chitin's MCP endpoint:

1. In Copilot Studio, add a Custom MCP Connector.
2. Configure with:
   - **URL:** `http://localhost:18790/mcp`
   - **Transport:** Streamable HTTP
   - **Auth header:** `Authorization: Bearer YOUR_CHITIN_API_KEY`
   - **Session:** `Mcp-Session-Id` (server-assigned, auto-managed by the MCP client)
3. The connector will discover available tools via `tools/list` automatically.

Replace `YOUR_CHITIN_API_KEY` with the key from Chitin Desktop > Settings > Inbound MCP.
