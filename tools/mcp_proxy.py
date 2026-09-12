"""Run MCP JSON-RPC calls (from .mcp/requests.jsonl) against .mcp/endpoint.

This runs inside GitHub Actions (Ubuntu runner) because the agent sandbox has no
direct egress to the MCP host. Results land in the job log and in .mcp-out/result.txt,
which the workflow commits back to the arena branch.

Env:
  MCP_WAIT_SECONDS  how long to keep retrying while the endpoint is unreachable (default 300)
"""
import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = open(".mcp/endpoint").read().strip()
REQS = [json.loads(line) for line in open(".mcp/requests.jsonl") if line.strip()]
WAIT_SECONDS = int(os.environ.get("MCP_WAIT_SECONDS", "300"))

OUT_DIR = ".mcp-out"
_fh = None


def emit(text):
    text = text if len(text) < 4000 else text[:4000] + "...[truncated]"
    print(text, flush=True)
    global _fh
    if _fh is None:
        os.makedirs(OUT_DIR, exist_ok=True)
        _fh = open(os.path.join(OUT_DIR, "result.txt"), "w", encoding="utf-8")
    _fh.write(text + "\n")
    _fh.flush()


def post(obj, session=None, timeout=90):
    http_req = urllib.request.Request(
        ENDPOINT, data=json.dumps(obj).encode(), method="POST"
    )
    http_req.add_header("Content-Type", "application/json")
    http_req.add_header("Accept", "application/json, text/event-stream")
    http_req.add_header("MCP-Protocol-Version", "2025-06-18")
    if session:
        http_req.add_header("Mcp-Session-Id", session)
    resp = urllib.request.urlopen(http_req, timeout=timeout)
    sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
    return resp.status, sid, resp.read().decode("utf-8", "replace")


def rpc(req, session=None):
    return post(
        {
            "jsonrpc": "2.0",
            "id": req["id"],
            "method": req["method"],
            "params": req.get("params", {}),
        },
        session=session,
    )


session = None
first = REQS[0]
deadline = time.time() + WAIT_SECONDS
delay = 5
attempt = 0
while True:
    attempt += 1
    try:
        status, session, body = rpc(first)
        emit("=== endpoint reachable on attempt %d (%s)" % (attempt, first["method"]))
        emit("--- HTTP %s session=%s" % (status, session))
        emit(body)
        break
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        emit("--- attempt %d: HTTP %s" % (attempt, exc.code))
        emit(detail[:600])
        if exc.code not in (403, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 530):
            break
    except Exception as exc:  # noqa: BLE001
        emit("--- attempt %d: %r" % (attempt, exc))
    left = deadline - time.time()
    if left <= 0:
        emit("=== gave up waiting after %d s" % WAIT_SECONDS)
        break
    time.sleep(min(delay, left))
    delay = min(delay * 2, 30)

for req in REQS[1:]:
    emit("=== request %s: %s" % (req["id"], req["method"]))
    try:
        status, session, body = rpc(req, session=session)
        emit("--- HTTP %s session=%s" % (status, session))
        emit(body)
    except urllib.error.HTTPError as exc:
        emit("--- HTTP %s" % exc.code)
        emit(str(dict(exc.headers)))
        emit(exc.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        emit("--- EXC %r" % (exc,))
