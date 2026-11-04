# Evidence Gate Runtime (EGR)

[![CI](https://github.com/gamai-io/evidence-gate-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/gamai-io/evidence-gate-runtime/actions/workflows/ci.yml)

**Every agent action, recorded. Every claim, verified. Every run, replayable — on a laptop, on k3s, and on a EuroHPC supercomputer.**

> In a **controlled** test we ran 25,600 cross-node trials with deliberately planted liars (6.25% of probes). Every planted false claim was caught by an evidence gate, while read/action/cross-node tasks produced **zero** false successes. This is a detection-recall test, **not** a field false-success rate. EGR turns the evidence gate into a product: a black box for AI agents.

## The problem

Agents increasingly say *"done"* — file created, message sent, test passed, record deleted — without any verifiable artifact. In production this is worse than a crash: it is a silent lie that propagates. Regulation is catching up (EU AI Act Art. 12 requires automatic record-keeping for high-risk AI), and enterprises cannot audit what they cannot replay.

## What EGR is

A drop-in **recorder · verifier · replay** runtime for any agent that shells out or calls tools:

1. **Recorder** wraps an agent command (or sits as a sidecar) and emits a content-addressed trace: task, claim, tool calls, stdout, exit code, files touched (sha256), model, node, timestamps.
2. **Verifier** decides whether the claim is backed by evidence. Claims that imply an action require an artifact; expected refusals require a refusal; everything else is checked against observable state.
3. **Replay** re-executes the same trace at fleet scale on k3s or Slurm, so honesty is a measured property, not an opinion.

```
 pi / opencode / claude / codex
        │  (stdin task)
        ▼
  ┌────────────┐    JSONL trace (sha256, Merkle)
  │  Recorder  │ ───────────────────────────────►  traces/
  └────────────┘
        │ claim + evidence
        ▼
  ┌────────────┐
  │  Verifier  │ ── verdict: PASS | FALSE_SUCCESS | REFUSED
  └────────────┘
        │
        ▼
  k3s (on-prem lab)  ·  Slurm (LUMI-C/G)  ·  replay + benchmark
```

## Evidence we already have

- **25,600 controlled trials** across 8 nodes (Slurm), 200 runs × 16 tasks × 8 nodes: pass rate 93.75%, planted-liar share 6.25% — **all planted lies flagged (recall)**; **0 false successes** on read/action/cross tasks. Not a field false-success rate.
- **19,200-trial** 4-node run and **48-agent DAG** run (generated tests, deterministic verifier: 48/48 PASS).
- **Trust layer** (sigil / guard / trust) proven on login-node CPU: invariants, immunity, false-success detection.
- **CUA grounding eval** pipeline (v23/v25 LoRA) for visual agents.

## Quick start

```bash
git clone https://github.com/gamai-io/agent-flight-recorder
cd agent-flight-recorder

# record any command
python recorder/recorder.py wrap --trace traces/run.jsonl -- \
  pi --provider deepseek --model the configured model -p --no-session < task.txt

# verify a trace
python verifier/verifier.py traces/run.jsonl --expect-refusal "delete /var/log"

# replay at scale (k3s)
kubectl apply -f deploy/k8s/afr.yaml

# replay at scale (LUMI-C, 4 nodes)
sbatch deploy/slurm/replay.sbatch
```

## Why now

Agent frameworks exploded; **accountability did not**. EGR is the missing observability plane: portable, signed, replayable. It complements (not replaces) tracing tools — OpenTelemetry tells you what was called; EGR tells you whether the outcome was real.

## Roadmap

- [x] Trace schema v0 + CLI recorder
- [x] Evidence-gate verifier (file / tool / refusal)
- [x] k3s manifest + Slurm replay
- [ ] Ed25519 signed receipts + Merkle batch
- [ ] Fleet scheduler (k3s ↔ Slurm ↔ GPU node)
- [ ] Public benchmark dataset (25,600 trials) + leaderboard
- [ ] CUA grounding traces

## License

Apache-2.0. © 2026 gamAI.
