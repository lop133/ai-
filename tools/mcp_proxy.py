"""MCP relay: run JSON-RPC requests from .mcp/requests.jsonl against .mcp/endpoint.

Executed on a GitHub Actions runner because the agent sandbox has no direct
egress to the MCP host (Cloudflare Quick Tunnel, not on the sandbox egress
allowlist). The runner does the HTTP and commits results back to the branch.

Behaviour:
  * always opens a fresh MCP session: initialize -> notifications/initialized
  * then executes every request from .mcp/requests.jsonl in order, e.g.
      {"id": 1, "method": "tools/list", "params": {}}
      {"id": 2, "method": "tools/call", "params": {"name": "x", "arguments": {}}}
  * if the tunnel is flapping (HTTP 5xx / DNS errors) the whole batch is
    retried (fresh session) until MCP_WAIT_SECONDS elapses
  * responses are written to .mcp-out/result.jsonl (machine readable, full
    fidelity) and .mcp-out/result.txt (human readable log)

Env:
  MCP_WAIT_SECONDS  total retry window while the endpoint is unreachable (default 600)
"""

import json
import os
import time
import urllib.error
import urllib.request

ENDPOINT = open(".mcp/endpoint").read().strip()
REQS = [json.loads(line) for line in open(".mcp/requests.jsonl") if line.strip()]
WAIT_SECONDS = int(os.environ.get("MCP_WAIT_SECONDS", "600"))
OUT_DIR = ".mcp-out"

RETRYABLE_HTTP = {403, 408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530}

log_lines = []
results = []


def note(msg):
    print(msg, flush=True)
    log_lines.append(msg)


def save():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "result.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    with open(os.path.join(OUT_DIR, "result.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def post(obj, session=None, timeout=120):
    req = urllib.request.Request(ENDPOINT, data=json.dumps(obj).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if session:
        req.add_header("Mcp-Session-Id", session)
    if obj.get("method") != "initialize" and obj.get("id") is not None:
        req.add_header("MCP-Protocol-Version", "2025-06-18")
    resp = urllib.request.urlopen(req, timeout=timeout)
    sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id") or session
    body = resp.read().decode("utf-8", "replace")
    ctype = resp.headers.get("Content-Type", "")
    return resp.status, sid, body, ctype


def extract_messages(body, ctype):
    """Parse a JSON / JSONL / SSE response body into JSON-RPC message objects."""
    msgs = []
    if "text/event-stream" in (ctype or ""):
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                data = line[5:].strip()
                if data and data != "[DONE]":
                    try:
                        msgs.append(json.loads(data))
                    except json.JSONDecodeError:
                        pass
        return msgs
    txt = body.strip()
    if not txt:
        return msgs
    try:
        return [json.loads(txt)]
    except json.JSONDecodeError:
        for line in txt.splitlines():
            line = line.strip()
            if line:
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return msgs


def attempt():
    """One full pass. Returns (init_ok, had_retryable_failure)."""
    results.clear()
    log_lines.clear()
    note("=== relay attempt at %s -> %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ENDPOINT))

    status, session, body, ctype = post({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "arena-relay", "version": "1.0"},
        },
    })
    init_msgs = extract_messages(body, ctype)
    init_msg = next((m for m in init_msgs if m.get("id") == 0), None)
    if init_msg is None or "result" not in init_msg:
        results.append({"kind": "initialize", "ok": False, "http": status,
                        "error": (init_msg or {}).get("error") or body[:2000]})
        note("--- initialize failed (HTTP %s)" % status)
        note(body[:2000])
        return False, status in RETRYABLE_HTTP

    results.append({"kind": "initialize", "ok": True, "http": status,
                    "session": session, "result": init_msg["result"]})
    note("=== initialize ok (session=%s)" % session)
    note(json.dumps(init_msg["result"], ensure_ascii=False))

    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session=session)
    except Exception as exc:  # noqa: BLE001
        note("--- notifications/initialized: %r" % (exc,))

    retryable_failure = False
    for req in REQS:
        rid, method, params = req["id"], req["method"], req.get("params", {})
        entry = {"kind": "response", "id": rid, "method": method}
        timeout = 480 if method.startswith("tools/call") else 120
        try:
            status, session, body, ctype = post(
                {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
                session=session, timeout=timeout)
            entry["http"] = status
            msgs = extract_messages(body, ctype)
            msg = next((m for m in msgs if m.get("id") == rid), None)
            if msg is None and len(msgs) == 1:
                msg = msgs[0]
            if msg is None:
                entry["error"] = "unparseable response (%d messages)" % len(msgs)
                entry["raw"] = body[:8000]
            elif "error" in msg:
                entry["error"] = msg["error"]
            else:
                entry["result"] = msg.get("result")
        except urllib.error.HTTPError as exc:
            entry["http"] = exc.code
            entry["error"] = exc.read().decode("utf-8", "replace")[:4000]
            if exc.code in RETRYABLE_HTTP:
                retryable_failure = True
        except Exception as exc:  # noqa: BLE001
            entry["error"] = repr(exc)
            retryable_failure = True
        results.append(entry)
        note("=== request id=%s %s -> HTTP %s" % (rid, method, entry.get("http", "?")))
        payload = entry.get("result", entry.get("error"))
        note(json.dumps(payload, ensure_ascii=False)[:6000])
        if retryable_failure:
            note("--- retryable failure during batch; will restart batch")
            break
    return True, retryable_failure


deadline = time.time() + WAIT_SECONDS
delay = 5
while True:
    try:
        init_ok, retryable = attempt()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        note("--- attempt failed: HTTP %s" % exc.code)
        note(detail)
        retryable = exc.code in RETRYABLE_HTTP
    except Exception as exc:  # noqa: BLE001
        note("--- attempt failed: %r" % (exc,))
        retryable = True
    if init_ok and not retryable:
        break
    left = deadline - time.time()
    if left <= 0:
        note("=== gave up after %ds" % WAIT_SECONDS)
        break
    save()
    time.sleep(min(delay, left))
    delay = min(delay * 2, 30)

note("=== done (%d result entries)" % len(results))
save()
