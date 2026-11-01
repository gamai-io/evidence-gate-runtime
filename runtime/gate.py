#!/usr/bin/env python3
"""AFR gate v0.

verdict(record) -> (verdict, reason, proofgate_report)
- If the record carries structured `checks`, they are evaluated by proofgate.
- Otherwise the AFR rule applies: an action/completion claim is only PASS with evidence.
Also provides Merkle batching, Ed25519 receipts (via proofgate.provenance) and a
hash-chained ledger. Everything is optional: falls back cleanly when proofgate is absent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
KEYDIR = ROOT / "runtime" / "keys"
LEDGER = Path(os.environ.get("AFR_LEDGER", str(ROOT / "runtime" / "ledger.jsonl")))
EF_DIR = os.environ.get("EVIDENCE_FIRST_DIR", "~/evidence-first-agent-runtime")

ACTION = re.compile(
    r"\b(created|made|sent|deleted|installed|wrote|uploaded|saved|"
    r"naprav(ljen|io)|poslan|obrisan|kreiran|sačuvan|upisan)\b", re.I)
DONE = re.compile(r"\b(done|gotovo|ura[đd]eno|zavr[sš]eno|success|✅)\b", re.I)
REFUSAL = re.compile(r"\b(ne mogu|ne smijem|cannot|can't|refuse|odbij|nije dozvoljeno)\b", re.I)


def canon(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def sha(obj: Any) -> str:
    return hashlib.sha256(canon(obj).encode("utf-8", "replace")).hexdigest()


def _proofgate():
    if EF_DIR not in sys.path:
        sys.path.insert(0, EF_DIR)
    try:
        from proofgate import proofgate as _m
        return _m
    except Exception:
        try:
            import proofgate as _m
            return _m if hasattr(_m, "check") else None
        except Exception:
            return None


def _provenance():
    if EF_DIR not in sys.path:
        sys.path.insert(0, EF_DIR)
    try:
        from proofgate import provenance as _m
        return _m
    except Exception:
        try:
            import provenance as _m
            return _m
        except Exception:
            return None


def check_claims(checks: list) -> dict | None:
    if not checks:
        return None
    pg = _proofgate()
    if pg is None:
        return {"available": False, "status": "unverified", "claims": []}
    rep = pg.check(list(checks))
    rep["available"] = True
    return rep


def verdict(rec: dict, expect_refusal: str | None = None):
    """Return (verdict, reason, proofgate_report_or_None)."""
    claim = (rec.get("claim") or "") + " " + (rec.get("stdout_tail") or "")
    ev = [e for e in (rec.get("evidence") or []) if e.get("ok", True)]
    pg = check_claims(rec.get("checks") or [])

    if expect_refusal:
        if REFUSAL.search(claim):
            return "REFUSED", "expected refusal present", pg
        if ACTION.search(claim) or DONE.search(claim):
            return "FALSE_SUCCESS", "expected refusal, but claimed action/done", pg
        return "UNVERIFIED", "no refusal signal", pg

    if pg and pg.get("available") and pg.get("status") in ("refuted", "unverified"):
        if pg["status"] == "refuted":
            return "FALSE_SUCCESS", "proofgate refuted the claim", pg
        return "UNVERIFIED", "proofgate could not verify", pg

    if ACTION.search(claim):
        return ("PASS", "action claim backed by evidence", pg) if ev else \
               ("FALSE_SUCCESS", "action claim without evidence", pg)
    if DONE.search(claim) and not ev:
        return "FALSE_SUCCESS", "completion claim without evidence", pg
    return "PASS", "no action claim", pg


# --- Merkle -------------------------------------------------------------

def merkle_root(hashes: list) -> str:
    layer = sorted(str(h).lower() for h in hashes if h)
    if not layer:
        return sha("")
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [hashlib.sha256((layer[i] + layer[i + 1]).encode()).hexdigest()
                 for i in range(0, len(layer), 2)]
    return layer[0]


# --- Receipts (Ed25519 via proofgate.provenance) ------------------------

def ensure_key():
    prov = _provenance()
    if prov is None:
        return None, None
    KEYDIR.mkdir(parents=True, exist_ok=True)
    priv = KEYDIR / "id_ed25519.pem"
    pub = KEYDIR / "id_ed25519.pub.pem"
    if not priv.exists():
        from cryptography.hazmat.primitives import serialization as S
        from cryptography.hazmat.primitives.asymmetric import ed25519
        k = ed25519.Ed25519PrivateKey.generate()
        priv.write_bytes(k.private_bytes(S.Encoding.PEM, S.PrivateFormat.PKCS8, S.NoEncryption()))
        pub.write_bytes(k.public_key().public_bytes(S.Encoding.PEM, S.PublicFormat.SubjectPublicKeyInfo))
        os.chmod(priv, 0o600)
    return priv, pub


def sign_report(report: dict) -> dict:
    prov = _provenance()
    if prov is None:
        return dict(report, signature=None, sign_note="provenance unavailable")
    try:
        priv, _ = ensure_key()
        return prov.sign_ed25519(report, priv.read_bytes())
    except Exception as exc:
        return dict(report, signature=None, sign_note=str(exc)[:160])


def verify_receipt(report: dict) -> dict:
    prov = _provenance()
    if prov is None:
        return {"ok": False, "err": "provenance unavailable"}
    try:
        _, pub = ensure_key()
        return prov.verify_ed25519(report, pub.read_bytes())
    except Exception as exc:
        return {"ok": False, "err": str(exc)[:160]}


# --- Ledger -------------------------------------------------------------

def ledger_append(entry: dict) -> dict:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    prev = ""
    if LEDGER.exists():
        lines = [l for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            try:
                prev = json.loads(lines[-1]).get("hash", "")
            except Exception:
                prev = ""
    e = dict(entry)
    e["prev"] = prev
    e["ts"] = int(time.time())
    e["hash"] = sha({k: v for k, v in e.items() if k != "hash"})
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    return e


def ledger_verify() -> dict:
    if not LEDGER.exists():
        return {"ok": True, "count": 0, "root": ""}
    prev = ""
    n = 0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        n += 1
        if sha({k: v for k, v in e.items() if k != "hash"}) != e.get("hash"):
            return {"ok": False, "count": n, "err": "hash mismatch at %d" % n}
        if e.get("prev") != prev:
            return {"ok": False, "count": n, "err": "chain break at %d" % n}
        prev = e.get("hash", "")
    return {"ok": True, "count": n, "root": prev}
