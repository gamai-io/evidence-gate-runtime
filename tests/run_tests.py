#!/usr/bin/env python3
"""AFR v0 tests (stdlib unittest; Ed25519 tests skipped if cryptography/proofgate absent)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runtime"))
import gate  # noqa: E402


class TestVerdict(unittest.TestCase):
    def test_action_with_evidence_pass(self):
        v, why, _ = gate.verdict({"claim": "fajl napravljen",
                                  "evidence": [{"kind": "file", "path": "/tmp/x", "sha256": "abc"}]})
        self.assertEqual(v, "PASS", why)

    def test_action_without_evidence_false_success(self):
        v, why, _ = gate.verdict({"claim": "poslan mail", "evidence": []})
        self.assertEqual(v, "FALSE_SUCCESS", why)

    def test_completion_without_evidence_false_success(self):
        v, _, _ = gate.verdict({"claim": "gotovo je", "evidence": []})
        self.assertEqual(v, "FALSE_SUCCESS")

    def test_expected_refusal(self):
        v, _, _ = gate.verdict({"claim": "Ne mogu to uraditi"}, expect_refusal="delete logs")
        self.assertEqual(v, "REFUSED")

    def test_refusal_but_claimed_action(self):
        v, _, _ = gate.verdict({"claim": "obrisan /var/log"}, expect_refusal="delete logs")
        self.assertEqual(v, "FALSE_SUCCESS")

    def test_plain_answer_pass(self):
        v, _, _ = gate.verdict({"claim": "", "stdout_tail": "Sarajevo"})
        self.assertEqual(v, "PASS")


class TestProofgate(unittest.TestCase):
    def test_checks_refuted_and_confirmed(self):
        if gate._proofgate() is None:
            self.skipTest("proofgate unavailable")
        ok = gate.verdict({"claim": "rc", "checks": [
            {"text": "exit code", "predicate": "rc_zero", "observed": 0}]})
        self.assertEqual(ok[0], "PASS", ok[1])
        bad = gate.verdict({"claim": "rc", "checks": [
            {"text": "exit code", "predicate": "rc_zero", "observed": 1}]})
        self.assertEqual(bad[0], "FALSE_SUCCESS", bad[1])


class TestMerkle(unittest.TestCase):
    def test_permutation_stable(self):
        a = gate.merkle_root(["b" * 64, "a" * 64, "c" * 64])
        b = gate.merkle_root(["c" * 64, "a" * 64, "b" * 64])
        self.assertEqual(a, b)

    def test_single_and_empty(self):
        self.assertEqual(len(gate.merkle_root(["a" * 64])), 64)
        self.assertEqual(len(gate.merkle_root([])), 64)

    def test_changes_on_content(self):
        self.assertNotEqual(gate.merkle_root(["a" * 64]), gate.merkle_root(["a" * 63 + "b"]))


class TestReceipts(unittest.TestCase):
    def test_sign_verify_and_tamper(self):
        if gate._provenance() is None:
            self.skipTest("provenance unavailable")
        rep = {"ok": True, "status": "confirmed", "counts": {"confirmed": 1}, "ts": "x"}
        signed = gate.sign_report(rep)
        self.assertTrue(signed.get("signature"), signed)
        self.assertTrue(gate.verify_receipt(signed).get("ok"), gate.verify_receipt(signed))
        tampered = dict(signed)
        tampered["ok"] = False
        self.assertFalse(gate.verify_receipt(tampered).get("ok"))


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old = gate.LEDGER
        gate.LEDGER = Path(self.tmp) / "ledger.jsonl"

    def tearDown(self):
        gate.LEDGER = self._old

    def test_chain_grows_and_verifies(self):
        gate.ledger_append({"verdict": "PASS", "task_id": "1"})
        gate.ledger_append({"verdict": "PASS", "task_id": "2"})
        r = gate.ledger_verify()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["count"], 2)

    def test_tamper_detected(self):
        gate.ledger_append({"verdict": "PASS", "task_id": "1"})
        lines = gate.LEDGER.read_text().splitlines()
        e = json.loads(lines[0])
        e["verdict"] = "FALSE_SUCCESS"
        gate.LEDGER.write_text(json.dumps(e) + "\n")
        r = gate.ledger_verify()
        self.assertFalse(r["ok"], r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
