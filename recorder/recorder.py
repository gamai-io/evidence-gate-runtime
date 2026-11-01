#!/usr/bin/env python3
"""AFR recorder: wrap a command, emit a content-addressed JSONL trace.

Usage:
  recorder.py wrap --trace out.jsonl [--task TEXT] [--claim TEXT] [--watch DIR] -- <cmd...>
  recorder.py note --trace out.jsonl --task ... --claim ... --evidence-json '[...]'
"""
import argparse, datetime, hashlib, json, os, subprocess, sys, time, uuid


def sha(b):
    return hashlib.sha256(b).hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan(d):
    out = {}
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
                with open(p, "rb") as fh:
                    out[p] = {"sha256": sha(fh.read()), "size": st.st_size, "mtime": st.st_mtime}
            except OSError:
                pass
    return out


def emit(path, rec):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return rec


def wrap(a):
    before = scan(a.watch) if a.watch else {}
    t0 = time.time()
    p = subprocess.run(a.cmd, capture_output=True)
    elapsed = round((time.time() - t0) * 1000, 1)
    after = scan(a.watch) if a.watch else {}

    evidence = []
    for path, meta in after.items():
        if before.get(path) != meta:
            evidence.append({"kind": "file", "path": path, **meta})

    rec = {
        "schema": "afr/v0",
        "run_id": a.run_id,
        "task_id": str(uuid.uuid4()),
        "node": os.uname().nodename,
        "model": a.model or "",
        "started_at": now(),
        "ended_at": now(),
        "elapsed_ms": elapsed,
        "task": a.task or "",
        "claim": a.claim or "",
        "command": a.cmd,
        "exit_code": p.returncode,
        "stdout_sha256": sha(p.stdout),
        "stderr_sha256": sha(p.stderr),
        "stdout_chars": len(p.stdout),
        "stderr_chars": len(p.stderr),
        "stdout_tail": p.stdout.decode("utf-8", "replace")[-2000:],
        "evidence": evidence,
        "meta": {"replay_of": a.replay_of, "tags": a.tag},
    }
    emit(a.trace, rec)
    sys.stderr.write(p.stderr.decode("utf-8", "replace"))
    sys.stdout.write(p.stdout.decode("utf-8", "replace"))
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)

    w = sub.add_parser("wrap")
    w.add_argument("--trace", required=True)
    w.add_argument("--task", default="")
    w.add_argument("--claim", default="")
    w.add_argument("--model", default="")
    w.add_argument("--watch", default="")
    w.add_argument("--run-id", default=str(uuid.uuid4()))
    w.add_argument("--tag", action="append", default=[])
    w.add_argument("--replay-of", default=None)
    w.add_argument("cmd", nargs=argparse.REMAINDER)

    n = sub.add_parser("note")
    n.add_argument("--trace", required=True)
    n.add_argument("--task", required=True)
    n.add_argument("--claim", default="")
    n.add_argument("--evidence-json", default="[]")
    n.add_argument("--run-id", default=str(uuid.uuid4()))

    a = ap.parse_args()
    if a.mode == "wrap":
        cmd = a.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        if not cmd:
            ap.error("no command after --")
        a.cmd = cmd
        sys.exit(wrap(a))

    emit(a.trace, {
        "schema": "afr/v0", "run_id": a.run_id, "task_id": str(uuid.uuid4()),
        "node": os.uname().nodename, "started_at": now(), "ended_at": now(),
        "task": a.task, "claim": a.claim, "exit_code": 0,
        "stdout_sha256": "", "evidence": json.loads(a.evidence_json),
        "meta": {"tags": ["note"]},
    })
    print("ok")


if __name__ == "__main__":
    main()
