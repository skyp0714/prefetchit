#!/usr/bin/env python3

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DERIVER = ROOT / "tools" / "derive_prefetch_plan.py"


class DerivePrefetchPlanTest(unittest.TestCase):
    def test_same_cacheline_filter_is_opt_in_and_audited(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            source = tmp / "full.json"
            filtered = tmp / "filtered.json"
            unfiltered = tmp / "unfiltered.json"
            source.write_text(
                json.dumps(
                    {
                        "schema": "prefetchit.plan.v1",
                        "prefetch": {"byte_offsets": [0]},
                        "options": {},
                        "stats": {},
                        "injections": [
                            {
                                "target_rank": 1,
                                "site_rank": 1,
                                "new_covered_samples": 17,
                                "site": {
                                    "addr": "0x1034",
                                    "cacheline64": "0x1000",
                                    "lbr_depth": 4,
                                    "branch_type": "CALL",
                                },
                                "target": {
                                    "addr": "0x1038",
                                    "cacheline64": "0x1000",
                                },
                            },
                            {
                                "target_rank": 2,
                                "site_rank": 1,
                                "new_covered_samples": 11,
                                "samples": 13,
                                "site": {
                                    "addr": "0x2010",
                                    "cacheline64": "0x2000",
                                    "lbr_depth": 5,
                                    "branch_type": "COND",
                                },
                                "target": {
                                    "addr": "0x3040",
                                    "cacheline64": "0x3040",
                                },
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            common = [
                "python3",
                str(DERIVER),
                "--input",
                str(source),
                "--label",
                "fixture",
            ]
            subprocess.run(
                common + ["--output", str(unfiltered)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                common
                + [
                    "--output",
                    str(filtered),
                    "--exclude-site-target-same-cacheline",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            all_rows = json.loads(unfiltered.read_text(encoding="utf-8"))
            kept = json.loads(filtered.read_text(encoding="utf-8"))
            self.assertEqual(all_rows["stats"]["selected_injections"], 2)
            self.assertFalse(
                all_rows["options"]["exclude_site_target_same_cacheline"]
            )
            self.assertEqual(kept["stats"]["selected_injections"], 1)
            self.assertEqual(
                kept["stats"]["same_cacheline_injections_filtered"], 1
            )
            self.assertEqual(
                kept["stats"]["same_cacheline_new_covered_samples_filtered"], 17
            )
            self.assertEqual(kept["stats"]["selected_new_covered_samples"], 11)
            self.assertEqual(kept["stats"]["selected_site_samples"], 13)
            self.assertTrue(kept["options"]["exclude_site_target_same_cacheline"])
            self.assertEqual(kept["injections"][0]["target"]["addr"], "0x3040")

    def test_site_budget_is_applied_after_depth_filter(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            source = tmp / "full.json"
            output = tmp / "derived.json"
            source.write_text(
                json.dumps(
                    {
                        "schema": "prefetchit.plan.v1",
                        "prefetch": {"byte_offsets": [0]},
                        "options": {},
                        "stats": {},
                        "injections": [
                            {
                                "target_rank": 1,
                                "site_rank": 1,
                                "new_covered_samples": 20,
                                "samples": 20,
                                "site": {
                                    "addr": "0x1000",
                                    "lbr_depth": 1,
                                    "branch_type": "COND",
                                },
                                "target": {"addr": "0x4000"},
                            },
                            {
                                "target_rank": 1,
                                "site_rank": 2,
                                "new_covered_samples": 0,
                                "samples": 15,
                                "site": {
                                    "addr": "0x2000",
                                    "lbr_depth": 8,
                                    "branch_type": "CALL",
                                },
                                "target": {"addr": "0x4000"},
                            },
                            {
                                "target_rank": 1,
                                "site_rank": 3,
                                "new_covered_samples": 0,
                                "samples": 10,
                                "site": {
                                    "addr": "0x3000",
                                    "lbr_depth": 9,
                                    "branch_type": "RET",
                                },
                                "target": {"addr": "0x4000"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    str(DERIVER),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--label",
                    "after-filter",
                    "--depth-min",
                    "4",
                    "--sites-per-target-after-filter",
                    "1",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            plan = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(plan["stats"]["selected_injections"], 1)
            self.assertEqual(plan["injections"][0]["site_rank"], 2)
            self.assertEqual(
                plan["options"]["derive_sites_per_target_after_filter"], 1
            )


if __name__ == "__main__":
    unittest.main()
