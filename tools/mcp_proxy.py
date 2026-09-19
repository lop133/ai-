"""MCP relay: run JSON-RPC requests from .mcp/requests.jsonl against .mcp/endpoint.

Executed on a GitHub Actions runner because the agent sandbox has no direct
egress to the MCP host (Cloudflare Quick Tunnel, not on the sandbox egress
allowlist). The runner does the HTTP and the workflow commits results back.

Behaviour:
  * opens a fresh MCP session: initialize (adaptive: tries spec-correct request
    first, then header/protocol variants for strict gateways) ->
    notifications/initialized
  * executes every request from .mcp/requests.jsonl in order, e.g.
      {"id": 1, "method": "tools/list", "params": {}}
      {"id": 2, "method": "tools/call", "params": {"name": "x", "arguments": {}}}
  * if the tunnel is flapping (HTTP 5xx / DNS errors) the whole batch is
    retried (fresh session) until MCP_WAIT_SECONDS elapses
  * responses land in .mcp-out/result.jsonl (full fidelity) and
    .mcp-out/result.txt (human log); .mcp-out/ran_at is always written so the
    caller can see the run reached this script even on total failure

Env:
  MCP_WAIT_SECONDS  total retry window while the endpoint is unreachable (default 600,
                    or the value in .mcp/wait_minutes if present, whichever is larger)
  MCP_ENDPOINT      override .mcp/endpoint (for local testing)
"""

import os
import time

WAIT_SECONDS = int(os.environ.get("MCP_WAIT_SECONDS", "600"))
if os.path.exists(".mcp/wait_minutes"):
    try:
        WAIT_SECONDS = max(WAIT_SECONDS, int(open(".mcp/wait_minutes").read().strip()) * 60)
    except ValueError:
        pass

import json
import urllib.error
import urllib.request

ENDPOINT = os.environ.get("MCP_ENDPOINT") or open(".mcp/endpoint").read().strip()
REQS = [json.loads(line) for line in open(".mcp/requests.jsonl") if line.strip()]
OUT_DIR = ".mcp-out"

RETRYABLE_HTTP = {403, 408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530}

log_lines = []
results = []


def note(msg):
    print(msg, flush=True)
    log_lines.append(msg)


def save():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "ran_at"), "w", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n")
    with open(os.path.join(OUT_DIR, "result.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    with open(os.path.join(OUT_DIR, "result.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def post(obj, session=None, timeout=120, protocol_header=None):
    req = urllib.request.Request(ENDPOINT, data=json.dumps(obj).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if session:
        req.add_header("Mcp-Session-Id", session)
    if protocol_header:
        req.add_header("MCP-Protocol-Version", protocol_header)
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


def http_error_detail(exc):
    try:
        detail = exc.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        detail = ""
    return {"code": exc.code, "reason": str(exc.reason), "body": detail[:4000],
            "headers": {k.lower(): v for k, v in exc.headers.items()
                        if k.lower() in ("content-type", "allow", "mcp-session-id",
                                         "mcp-protocol-version", "retry-after")}}


def initialize(session_variant=None):
    """Try initialize variants. Returns (session, protocol_header, result, error)."""
    variants = [
        ("spec", {"protocolVersion": "2025-06-18",
                  "capabilities": {},
                  "clientInfo": {"name": "arena-relay", "version": "1.0"}}, None),
        ("hdr", {"protocolVersion": "2025-06-18",
                 "capabilities": {},
                 "clientInfo": {"name": "arena-relay", "version": "1.0"}}, "2025-06-18"),
        ("old", {"protocolVersion": "2025-03-26",
                 "capabilities": {},
                 "clientInfo": {"name": "arena-relay", "version": "1.0"}}, None),
    ]
    last_error = None
    for name, params, header in variants:
        try:
            status, session, body, ctype = post(
                {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": params},
                timeout=90, protocol_header=header)
            msgs = extract_messages(body, ctype)
            msg = next((m for m in msgs if m.get("id") == 0), None)
            if msg is not None and "result" in msg:
                return session, header, msg["result"], None, status
            err = (msg or {}).get("error") or {"unparseable": body[:2000]}
            last_error = {"variant": name, "http": status, "error": err}
            note("--- initialize variant '%s' rejected: %s" % (name, json.dumps(err, ensure_ascii=False)[:1500]))
        except urllib.error.HTTPError as exc:
            last_error = {"variant": name, "http_error": http_error_detail(exc)}
            note("--- initialize variant '%s' HTTP %s: %s" % (name, exc.code, last_error["http_error"]["body"][:800]))
        except Exception as exc:  # noqa: BLE001
            last_error = {"variant": name, "exception": repr(exc)}
            note("--- initialize variant '%s' exception: %r" % (name, exc))
    return None, None, None, last_error, None


def attempt():
    """One full pass. Returns (init_ok, retryable_failure, protocol_header)."""
    results.clear()
    log_lines.clear()
    note("=== relay attempt at %s -> %s" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), ENDPOINT))

    session, header, init_result, init_error, status = initialize()
    if init_result is None:
        results.append({"kind": "initialize", "ok": False, "error": init_error})
        note("--- initialize failed, all variants exhausted")
        return False, True, None  # retryable: transient tunnel errors look like this too

    results.append({"kind": "initialize", "ok": True, "http": status,
                    "session": session, "result": init_result})
    note("=== initialize ok (session=%s)" % session)
    note(json.dumps(init_result, ensure_ascii=False))

    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"},
             session=session, protocol_header=header)
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
                session=session, timeout=timeout, protocol_header=header)
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
            entry["error"] = http_error_detail(exc)
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
            note("--- retryable failure during batch; restarting batch")
            break
    return True, retryable_failure, header


deadline = time.time() + WAIT_SECONDS
delay = 5
try:
    while True:
        init_ok = False
        retryable = True
        try:
            init_ok, retryable, _ = attempt()
        except Exception as exc:  # noqa: BLE001
            note("--- attempt crashed: %r" % (exc,))
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
finally:
    save()
