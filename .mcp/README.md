# MCP relay (sandbox has no egress to the MCP host)

**Endpoint:** see `.mcp/endpoint` — Cloudflare Quick Tunnel → MCP Streamable HTTP
(POST-only JSON-RPC; the GET/SSE channel is disabled on quick tunnels).

The agent sandbox's network egress is allowlisted (GitHub/PyPI/npm only), which
blocks the tunnel host. All MCP traffic is therefore relayed through this repo's
GitHub Actions runners, which have unrestricted internet:

```
sandbox --git push--> GitHub --Actions runner--> MCP endpoint
   ^                                              |
   +------------git pull .mcp-out/ results--------+
```

## How to make an MCP call

```bash
tools/mcp_call.sh 'tools/list' '{}'
tools/mcp_call.sh 'tools/call' '{"name":"<tool>","arguments":{...}}'
```

The helper:
1. writes the batch to `.mcp/requests.jsonl` (one JSON-RPC request per line),
2. pushes to the arena branch → triggers `.github/workflows/mcp-relay.yml`,
3. the runner runs `tools/mcp_proxy.py`, which opens a fresh MCP session
   (initialize + notifications/initialized), executes the batch, retries while
   the tunnel is flapping (HTTP 5xx / DNS, up to `MCP_WAIT_SECONDS`), and
4. commits full-fidelity responses to `.mcp-out/result.jsonl` (+ human-readable
   `.mcp-out/result.txt`) back onto this branch,
5. the helper polls, pulls, and prints the results.

Round trip is typically 30–60 s. Keep calls sequential: a new request push while
a relay run is in flight is fine (queued by the `concurrency` group), but wait
for results before pushing more.

## Files

- `.mcp/endpoint` — current tunnel URL (hostname changes whenever the owner
  restarts `cloudflared`; the `/mcp/<token>` path token is stable)
- `.mcp/requests.jsonl` — pending request batch
- `.mcp-out/result.jsonl` / `result.txt` — latest responses
- `tools/mcp_proxy.py` — runner-side client
- `tools/mcp_call.sh` — sandbox-side helper
