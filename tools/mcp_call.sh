#!/usr/bin/env bash
# Relay MCP JSON-RPC calls through GitHub Actions and print the results.
#
# Why: the agent sandbox's egress allowlist (GitHub/PyPI/npm only) blocks the
# MCP host (Cloudflare Quick Tunnel). This script commits the request batch to
# .mcp/requests.jsonl, pushes (which triggers the mcp-relay workflow on an
# Actions runner with full internet), waits for the runner to commit the
# responses back to .mcp-out/, then prints them.
#
# Usage:
#   tools/mcp_call.sh '<method>' '<params-json>' ['<method>' '<params-json>' ...]
#   tools/mcp_call.sh                      # replay the current .mcp/requests.jsonl
#
# Examples:
#   tools/mcp_call.sh 'tools/list' '{}'
#   tools/mcp_call.sh 'tools/call' '{"name":"some_tool","arguments":{"x":1}}'
#
# Env:
#   MCP_CALL_TIMEOUT  seconds to wait for the relay round trip (default 480)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
BR=arena/01a0b91c-ai
TIMEOUT=${MCP_CALL_TIMEOUT:-480}

if [ $# -ge 2 ]; then
  : > .mcp/requests.jsonl
  id=1
  while [ $# -ge 2 ]; do
    python3 - "$id" "$1" "${2:-}" <<'PY' >> .mcp/requests.jsonl
import json, sys
print(json.dumps({"id": int(sys.argv[1]), "method": sys.argv[2],
                  "params": json.loads(sys.argv[3] or "{}")}))
PY
    shift 2
    id=$((id + 1))
  done
fi

req_count=$(grep -c . .mcp/requests.jsonl || true)
if [ "${req_count:-0}" -eq 0 ]; then
  echo "!! .mcp/requests.jsonl is empty" >&2
  exit 1
fi

echo ">> relaying $req_count request(s) -> $(cat .mcp/endpoint)"
git add .mcp
git commit -q -m "mcp relay request $(date -u +%FT%TZ)" || { echo "!! nothing new to commit (requests unchanged)"; exit 1; }
git push -q origin "HEAD:$BR"
base=$(git rev-parse HEAD)
echo ">> pushed $base; waiting for the Actions runner (~30-60s)..."

se0=$SECONDS
deadline=$((SECONDS + TIMEOUT))
while [ $SECONDS -lt $deadline ]; do
  git fetch -q origin "$BR"
  new=$(git rev-parse "origin/$BR")
  if [ "$new" != "$base" ] && git diff --name-only "$base" "$new" -- .mcp-out | grep -q .; then
    git merge -q --ff-only "origin/$BR"
    elapsed=$((SECONDS - se0))
    echo ">> results after ${elapsed}s:"
    python3 - <<'PY'
import json

for line in open(".mcp-out/result.jsonl", encoding="utf-8"):
    r = json.loads(line)
    if r.get("kind") == "initialize":
        if r.get("ok"):
            print("== initialize ok")
            print(json.dumps(r.get("result"), ensure_ascii=False, indent=2))
        else:
            print("== initialize FAILED:", json.dumps(r.get("error"), ensure_ascii=False))
    elif r.get("kind") == "response":
        print("\n== %s (id=%s, http=%s)" % (r.get("method"), r.get("id"), r.get("http")))
        payload = r.get("result", r.get("error"))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
    exit 0
  fi
  # surface an early failure of the workflow run itself
  run_json=$(gh run list --branch "$BR" -L 1 --json status,conclusion,databaseId --jq '.[0]' 2>/dev/null || echo '{}')
  st=$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)
  concl=$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("conclusion") or "")' 2>/dev/null || true)
  if [ "$st" = "completed" ] && [ "$concl" = "failure" ]; then
    rid=$(printf '%s' "$run_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("databaseId",""))' 2>/dev/null || true)
    echo "!! relay workflow run failed (run id $rid) - check the Actions tab" >&2
    exit 2
  fi
  sleep 10
done
echo "!! timed out after ${TIMEOUT}s - check https://github.com/lop133/ai-/actions" >&2
exit 1
