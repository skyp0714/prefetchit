#!/usr/bin/env python3
"""Focused tests for LBR target and coverage semantics."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/prefetchit_trace_to_plan.py"
SPEC = importlib.util.spec_from_file_location("prefetchit_trace_to_plan_tested", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
P2P = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = P2P
SPEC.loader.exec_module(P2P)


def symbol(addr: int, size: int, name: str):
    return P2P.Symbol(addr=addr, size=size, typ="T", raw=name, demangled=f"{name}()")


class TraceToPlanTest(unittest.TestCase):
    def setUp(self):
        self.symbols = P2P.SymbolIndex(
            [
                symbol(0x1000, 0x100, "target_hot"),
                symbol(0x2000, 0x100, "newest_site"),
                symbol(0x3000, 0x100, "older_site"),
                symbol(0x4000, 0x100, "target_cold"),
            ]
        )

    def test_newest_lbr_to_is_target_and_from_entries_are_sites(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lbr_symbolic_dump.txt"
            path.write_text(
                "deadbeef "
                "newest_site+0x8/target_hot+0x40/P/-/-/0/IND_CALL/0 "
                "older_site+0x4/newest_site+0x8/P/-/-/0/COND/0\n",
                encoding="utf-8",
            )
            rows = list(
                P2P.iter_trace_samples(
                    path,
                    None,
                    self.symbols,
                    depth=8,
                    target_ip_source="lbr-to",
                )
            )

            self.assertEqual(len(rows), 1)
            _, target_addr, target_branch_type, candidates = rows[0]
            self.assertEqual(target_addr, 0x1040)
            self.assertEqual(target_branch_type, "IND_CALL")
            self.assertEqual(
                candidates,
                [(0x2008, "IND_CALL", 1), (0x3004, "COND", 2)],
            )

            trace = P2P.TraceInput(Path(tmp), path, None)
            stats, targets = P2P.audit_lbr0_targets([trace], self.symbols)
            self.assertEqual(stats["samples_with_lbr"], 1)
            self.assertEqual(stats["unique_symbolic_targets"], 1)
            self.assertEqual(stats["binary_resolved_samples"], 1)
            self.assertEqual(targets[0]["raw_lbr0_to"], "target_hot+0x40")
            self.assertEqual(targets[0]["cacheline64"], "0x1040")

    def test_coverage_selection_is_not_limited_by_top_k(self):
        counts = Counter({0x1040: 7, 0x1080: 2, 0x4040: 1})
        locs = {
            0x1040: P2P.SourceLoc("target_hot()", "/tmp/hot.cc", 10),
            0x1080: P2P.SourceLoc("target_hot()", "/tmp/hot.cc", 20),
            0x4040: P2P.SourceLoc("target_cold()", "/tmp/cold.cc", 30),
        }
        selected, _ = P2P.choose_top_targets(
            counts,
            locs,
            self.symbols,
            top_k=1,
            target_coverage_pct=80.0,
            allow_unresolved=False,
        )
        self.assertEqual(len(selected), 2)
        self.assertEqual(sum(count for _, count in selected), 9)


if __name__ == "__main__":
    unittest.main()
