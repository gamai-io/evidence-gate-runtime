#!/bin/bash
#SBATCH --job-name=afr-replay
#SBATCH --account=eurohpc-project
#SBATCH --partition=standard
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:40:00
#SBATCH --output=afr-replay-%j.out
#
# Replay AFR bench across N nodes. Each node runs the async agent probe against
# a vLLM endpoint (start one with deploy/slurm/vllm_serve or point to an existing job).
#
#   VLLM_URL=http://<node>:8000 sbatch replay.sbatch
#   RUNS=200 TASKS_PER_NODE=16 sbatch replay.sbatch

set -euo pipefail
: "${VLLM_URL:?set VLLM_URL=host:port}"
RUNS="${RUNS:-200}"
OUT="${OUT:-/project/eurohpc-project/afr/replay_${SLURM_JOB_ID}}"
mkdir -p "$OUT"

echo "job=$SLURM_JOB_ID nodes=$SLURM_JOB_NUM_NODES runs=$RUNS url=$VLLM_URL"

srun --ntasks="$SLURM_JOB_NUM_NODES" --ntasks-per-node=1 bash -c '
  set -e
  W=/tmp/afr-$SLURM_PROCID; rm -rf "$W"; mkdir -p "$W"; cd "$W"
  cp "$OLDPWD"/bench/agent_load.py . 2>/dev/null || true
  python3 agent_load.py --url "$VLLM_URL" --agents 200 --rounds '"$RUNS"' > out.json
  cp out.json "'"$OUT"'/node-$SLURM_PROCID.json"
'

python3 - "$OUT" <<'PY'
import glob, json, sys
d = sys.argv[1]
tot = {"total": 0, "passed": 0, "false_success": 0}
for p in glob.glob(d + "/node-*.json"):
    r = json.load(open(p))
    for k in tot:
        tot[k] += r.get(k, 0)
fsr = tot["false_success"] / max(1, tot["passed"] + tot["false_success"])
json.dump({"aggregate": tot, "false_success_rate": round(fsr, 4)}, open(d + "/summary.json", "w"), indent=2)
print(json.dumps({"aggregate": tot, "false_success_rate": round(fsr, 4)}))
PY
