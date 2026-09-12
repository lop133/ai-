"""Run MCP JSON-RPC calls (from .mcp/requests.jsonl) against .mcp/endpoint.

Used because the agent sandbox has no direct egress to the MCP host; this runs
on a GitHub Actions runner which does.
"""
import json
import sys
import urllib.error
import urllib.request

ENDPOINT = open(".mcp/endpoint").read().strip()
REQS = [json.loads(line) for line in open(".mcp/requests.jsonl") if line.strip()]

session = None
for req in REQS:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": req["id"],
            "method": req["method"],
            "params": req.get("params", {}),
        }
    ).encode()
    http_req = urllib.request.Request(ENDPOINT, data=payload, method="POST")
    http_req.add_header("Content-Type", "application/json")
    http_req.add_header("Accept", "application/json, text/event-stream")
    http_req.add_header("MCP-Protocol-Version", "2025-06-18")
    if session:
        http_req.add_header("Mcp-Session-Id", session)
    print("=== request %s: %s" % (req["id"], req["method"]), flush=True)
    try:
        with urllib.request.urlopen(http_req, timeout=90) as resp:
            body = resp.read().decode("utf-8", "replace")
            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if sid:
                session = sid
            print("--- HTTP %s session=%s" % (resp.status, session), flush=True)
            print(body, flush=True)
    except urllib.error.HTTPError as exc:
        print("--- HTTP %s" % exc.code, flush=True)
        print(dict(exc.headers), flush=True)
        print(exc.read().decode("utf-8", "replace"), flush=True)
    except Exception as exc:  # noqa: BLE001
        print("--- EXC %r" % (exc,), flush=True)
