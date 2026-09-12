# MCP connection

Endpoint: see `.mcp/endpoint` (Cloudflare Quick Tunnel -> MCP streamable HTTP).

The agent sandbox has no egress to that host, so calls are relayed through this
repo's GitHub Actions (`.github/workflows/mcp-probe.yml` -> `tools/mcp_proxy.py`):

1. put JSON-RPC requests in `.mcp/requests.jsonl`
2. push anything under `.mcp/` to `arena/01a094b2-ai`
3. the workflow waits for the tunnel to be up, runs the requests, and commits the
   raw responses to `.mcp-out/result.txt` on the same branch
