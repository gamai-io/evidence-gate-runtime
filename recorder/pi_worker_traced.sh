#!/bin/bash
# AFR traced worker: pi/opencode binary worker with model fallback + JSONL trace per task.
# Usage: pi_worker_traced.sh <name> <provider> <model1> [model2...]
# Env: AFR_TRACE (default /data/traces/<name>.jsonl), AFR_BIN (default pi), AFR_TIMEOUT (15)
set -u
NAME="$1"; PROV="$2"; shift 2
MODELS=("$@")
D="/tmp/afr/$NAME"; mkdir -p "$D"; touch "$D/inbox" "$D/pos"
TRACE="${AFR_TRACE:-/data/traces/$NAME.jsonl}"; mkdir -p "$(dirname "$TRACE")"
BIN="${AFR_BIN:-pi}"; TMO="${AFR_TIMEOUT:-15}"
READY="{\"schema\":\"afr/v0\",\"node\":\"$(hostname)\",\"task\":\"READY\",\"claim\":\"\",\"model\":\"$PROV/${MODELS[0]}\",\"exit_code\":0,\"evidence\":[]}"
echo "$READY" >> "$TRACE"
trap 'echo "stopped $NAME" >> "$D/out"; exit 0' TERM INT

while true; do
  N=$(cat "$D/pos" 2>/dev/null); N=${N:-0}
  L=$(wc -l < "$D/inbox" 2>/dev/null); L=${L:-0}
  L=$(echo "$L" | tr -dc '0-9'); N=$(echo "$N" | tr -dc '0-9'); N=${N:-0}; L=${L:-0}
  while [ "$L" -gt "$N" ]; do
    N=$((N+1)); echo "$N" > "$D/pos"
    LINE=$(sed -n "${N}p" "$D/inbox"); [ -z "$LINE" ] && continue
    OK=0; T0=$(date +%s%3N)
    for M in "${MODELS[@]}"; do
      for try in 1 2; do
        OUT=$(printf '%s' "$LINE" | timeout "$TMO" "$BIN" --provider "$PROV" --model "$M" -p --no-session 2>&1)
        RC=$?
        if printf '%s' "$OUT" | grep -qiE "Invalid Tool|Connection error|not found|Insufficient|Upstream request failed|ECONNREFUSED|rate limit|429|50[23]"; then
          echo "--- ($M error, next)" >> "$D/out"; continue
        fi
        if [ -n "$OUT" ] && [ "${#OUT}" -gt 2 ]; then
          T1=$(date +%s%3N); MS=$((T1-T0))
          SHA=$(printf '%s' "$OUT" | sha256sum | awk '{print $1}')
          CLAIM=$(printf '%s' "$OUT" | grep -oiE '\b(gotovo|urađeno|napravljen|poslan|obrisan|created|sent|done)\b' | head -1)
          printf '{"schema":"afr/v0","run_id":"%s","task_id":"%s-%s","node":"%s","model":"%s/%s","elapsed_ms":%s,"task":%s,"claim":%s,"exit_code":%s,"stdout_sha256":"%s","stdout_tail":%s,"evidence":[],"meta":{"tags":["worker"]}}\n' \
            "$NAME" "$NAME" "$N" "$(hostname)" "$PROV" "$M" "$MS" \
            "$(printf '%s' "$LINE" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
            "$(printf '%s' "$CLAIM" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" \
            "$RC" "$SHA" \
            "$(printf '%s' "$OUT" | tail -c 1500 | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')" >> "$TRACE"
          echo "$OUT" >> "$D/out"; echo "--- DONE via $PROV/$M (try $try)" >> "$D/out"
          OK=1; break 2
        fi
        sleep 5
      done
    done
    [ "$OK" = "0" ] && echo "--- FAIL (all models dead)" >> "$D/out"
  done
  sleep 2
done
